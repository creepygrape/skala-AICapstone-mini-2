"""Run A/B (product search service) and C (real FinderAgent); never evaluate draft gold.

All relative CLI paths are project-root relative. Output stays in eval/private/.
--systems A,B,C adds the Agent. --control adds C-ko: the real Agent with the same raw
Korean starting query A/B use (Router intent kept, Router query replaced).
"""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from pydantic import ValidationError

from backend.app.agent.graph import FinderAgent
from backend.app.agent.model import build_model
from backend.app.agent.telemetry import TelemetryPublisher
from backend.app.mcp.client import connect
from backend.app.schemas import MetadataReply, SearchResponse
from backend.app.services.search import SearchFailure, call_tool, search_and_verify
from backend.app.services.video_catalog import Catalog, ROOT, resolve_manifest
from eval.agent_runner import RouteProbe, evaluate_agent_question
from eval.dataset import load_questions, validate_source_labels
from eval.metrics import answerability_metrics, scene_metrics, summarize
from eval.paths import private_output, project_path, write_private_json


async def evaluate_question(session, question, query, mode, metadata, *, condition, system):
    """One product-path execution, including failures in the measured record."""
    start = time.monotonic()
    request_id = str(uuid4())
    error = None
    try:
        execution = await search_and_verify(session, query, mode, metadata, request_id=request_id)
        response = execution.response
        calls, normalized, timing = execution.tool_calls, execution.query, execution.video_timing
    except (SearchFailure, ValidationError) as exc:
        failure = exc if isinstance(exc, SearchFailure) else SearchFailure('invalid_query')
        error = {'code':failure.code, 'fatal':failure.fatal}
        calls, normalized, timing = failure.tool_calls, None, {}
        response = SearchResponse(request_id=request_id, status='error', search_attempts=failure.search_attempts,
                                  results=[], warnings=['search_failed'])
    return {
        'id':question.id, 'condition':condition, 'system':system,
        'query':query, 'normalized_query':normalized, 'answerability':question.answerability,
        'request_id':response.request_id, 'status':response.status, 'warnings':response.warnings,
        'error':error, 'video_timing':timing,
        'latency_seconds':round(time.monotonic()-start,6), 'tool_calls':calls,
        'llm_calls':0, 'search_rounds':response.search_attempts,
        'metrics':scene_metrics(question,response.results),
        'answerability_metrics':answerability_metrics(question,response),
        'results':[{'video_id':x.video_id, 'cue_ids':x.cue_ids,
                    'start_seconds':x.start_seconds, 'speaker':x.speaker,
                    'speaker_status':x.speaker_status} for x in response.results],
    }


def verify_gold_approval(dataset, rows):
    """Private gold must match the recorded human approval byte-for-byte."""
    if not any(r.split=='gold' for r in rows) or not dataset.is_relative_to(ROOT/'eval/private'):
        return None
    approval_path = ROOT/'eval/private/gold-approval.json'
    approval = json.loads(approval_path.read_text(encoding='utf-8')) if approval_path.exists() else None
    if not approval or approval.get('approved_by')!='user':
        raise ValueError('Private gold has no recorded human approval')
    if approval['gold_sha256']!=hashlib.sha256(dataset.read_bytes()).hexdigest() or \
            set(approval['approved_ids'])!={r.id for r in rows if r.split=='gold'}:
        raise ValueError('Gold changed after human approval; re-review before evaluation')
    return {'approved_at':approval['approved_at'], 'approved_count':approval['approved_count'],
            'pending_excluded':approval.get('pending_ids',[])}


async def start_langsmith(enabled):
    """Optional LangSmith tracing for paid runs so token usage is visible there.

    Explicit flag only; refuses to run silently untraced when it is not configured.
    Uses a separate project so evaluation traces never mix with web traffic.
    """
    if not enabled:
        return None
    if os.getenv('WISH_LANGSMITH_ENABLED') != '1' or not os.getenv('LANGSMITH_API_KEY'):
        raise ValueError('--langsmith needs WISH_LANGSMITH_ENABLED=1 and LANGSMITH_API_KEY')
    os.environ.setdefault('LANGSMITH_PROJECT', 'wish-finder-eval')
    telemetry = await TelemetryPublisher().start()
    if not telemetry.enabled:
        raise ValueError('LangSmith client could not start; check LANGSMITH_API_KEY and network')
    return telemetry


MAX_LLM_CALLS_PER_QUESTION = 6  # route + 3 verify + 2 rewrite: the worst case of one Agent run


def llm_budget_exhausted(calls_so_far, cap):
    """True when one more Agent question could exceed the cap (cap=None: unlimited)."""
    return cap is not None and calls_so_far + MAX_LLM_CALLS_PER_QUESTION > cap


async def run(args):
    dataset = project_path(args.dataset)
    rows = load_questions(dataset)
    if any(r.split=='gold_draft' or (r.split=='gold' and r.label_status!='accepted') for r in rows):
        raise ValueError('Draft gold is reserved: review/freeze labels before evaluation')
    approval = verify_gold_approval(dataset, rows)
    systems = [x.strip() for x in (getattr(args,'systems',None) or 'A,B').split(',')]
    if not set(systems)<={'A','B','C'}:
        raise ValueError('systems must be a subset of A,B,C')
    control = bool(getattr(args,'control',False))
    if control and 'C' not in systems:
        raise ValueError('--control needs system C')
    use_agent = 'C' in systems
    max_llm_calls = getattr(args,'max_llm_calls',None)
    output_path = private_output(args.output)
    if output_path.exists():
        raise ValueError('Output already exists; choose a new path to preserve prior results')
    manifest = resolve_manifest(args.manifest)
    catalog = Catalog(manifest)
    validate_source_labels(rows,catalog)
    rewrite_path = project_path(args.rewrites) if args.rewrites else None
    rewrites = None
    if rewrite_path:
        rewrite_data = json.loads(rewrite_path.read_text())
        items = rewrite_data['queries']
        if len(items)!=len(rows) or {x['id'] for x in items}!={r.id for r in rows}:
            raise ValueError('Frozen rewrite IDs must match dataset exactly once')
        rewrites = {x['id']:x['query_en'] for x in items}
    modes = [(s_,m) for s_,m in [('A','keyword'),('B','hybrid')] if s_ in systems]
    conditions = ['raw_ko'] + (['frozen_model_en'] if rewrites else [])
    tasks = []
    if use_agent:  # Native C first: its Router queries become the identical A/B starting query.
        tasks += [{'kind':'agent','question':row,'condition':'router_en','system':'C','override':None}
                  for row in rows]
    tasks += [{'kind':'search','question':row, 'query':row.query if condition=='raw_ko' else rewrites[row.id],
               'condition':condition, 'system':system, 'mode':mode}
              for condition in conditions for system,mode in modes for row in rows]
    if control:
        tasks += [{'kind':'agent','question':row,'condition':'raw_ko','system':'C-ko','override':row.query}
                  for row in rows]
    if use_agent:
        tasks += [{'kind':'search','question':row,'query':None,'condition':'router_en','system':system,
                   'mode':mode} for system,mode in modes for row in rows]
    corpus = [{'video_id':v.video_id,
               'sha256':hashlib.sha256((ROOT/v.transcript_file).read_bytes()).hexdigest()}
              for v in catalog.videos.values()]
    output = {
        'schema_version':2, 'created_at':datetime.now(timezone.utc).isoformat(), 'corpus':corpus,
        'dataset_sha256':hashlib.sha256(dataset.read_bytes()).hexdigest(),
        'rewrite_sha256':hashlib.sha256(rewrite_path.read_bytes()).hexdigest() if rewrite_path else None,
        'preprocessing':{
            'A/B raw_ko':'SearchRequest only: length validation then trim/nonblank',
            'A/B frozen_model_en':'stored model-written English string, identical for A and B',
            'C router_en':'Agent Router (LLM) writes the English first query, then bounded replans; A/B router_en reuse that exact first query',
            'C-ko control':'real Agent, real Router intent, but first query replaced by the raw Korean text A/B raw_ko use; replans still LLM-written',
            'comparability':'A/B raw_ko vs C differ in preprocessing; use router_en and C-ko rows for like-for-like starting queries'},
        'gold_approval':approval, 'agent_model':None, 'llm_usage':None, 'langsmith_project':None, 'max_llm_calls':max_llm_calls,
        'metric_policy':'Same video and floor(link time) in accepted interval ±10s',
        'semantic_verification':use_agent, 'systems_not_measured':[x for x in 'ABC' if x not in systems], 'mcp_startup_seconds':None,
        'video_timing':{v.video_id:'sampled' if v.timing_verified else 'unverified' for v in catalog.videos.values()},
        'timing_scope':'Manifest flags mean sampled user checks, never exhaustive cue validation',
        'records':[], 'run_error':None,
    }

    def save():
        keys = {(r['condition'],r['system'],r['id']) for r in output['records']}
        output['not_run'] = [{'id':t['question'].id, 'condition':t['condition'], 'system':t['system'],
                              'reason':output['run_error'] or 'not_executed'} for t in tasks
                             if (t['condition'],t['system'],t['question'].id) not in keys]
        output['complete'] = not output['not_run'] and output['run_error'] is None
        output['summary'] = summarize(output['records'],tasks)
        write_private_json(output_path,output)

    save()  # Startup failures also leave an explicit incomplete artifact.
    env = {key:value for key,value in os.environ.items() if key.startswith('WISH_')}
    env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false',
               WISH_MANIFEST=str(manifest),WISH_KEYWORD_ONLY='0')
    started = time.monotonic()
    model = None
    # Configuration errors surface here, before any session or billing starts.
    telemetry = await start_langsmith(getattr(args,'langsmith',False))
    output['langsmith_project'] = os.getenv('LANGSMITH_PROJECT') if telemetry else None
    try:
        async with connect(env=env) as session:
            output['mcp_startup_seconds'] = round(time.monotonic()-started,3)
            metadata = {vid:await call_tool(session,'get_video_metadata',{'video_id':vid},MetadataReply)
                        for vid in catalog.videos}
            output['video_timing'] = {vid:'sampled' if v.timing_verified else 'unverified'
                                      for vid,v in metadata.items()}
            agent = probe = None
            if use_agent:
                model = build_model()
                await model.ready()
                output['agent_model'] = model.name
                probe = RouteProbe(model)
                agent = FinderAgent(session,metadata,probe,mode='hybrid',
                                    log_path=private_output('eval/private/agent-eval.jsonl'),
                                    telemetry=telemetry,
                                    trace_dir=private_output(os.environ['WISH_AGENT_TRACE'])
                                    if os.getenv('WISH_AGENT_TRACE') else None)
            router_queries = {}
            for task in tasks:
                if task['kind']=='agent':
                    if llm_budget_exhausted(getattr(model,'usage',{}).get('calls',0), max_llm_calls):
                        output['run_error'] = 'llm_budget_reached'  # stop before spending more
                        break
                    record = await evaluate_agent_question(agent,probe,task['question'],condition=task['condition'],
                                                           system=task['system'],override=task['override'])
                    if task['system']=='C' and record['router_first_query']:
                        router_queries[task['question'].id] = record['router_first_query']
                else:
                    query = task['query'] or router_queries.get(task['question'].id)
                    if query is None:
                        continue  # stays in not_run: Router produced no query for this question
                    record = await evaluate_question(session,task['question'],query,task['mode'],metadata,
                                                      condition=task['condition'],system=task['system'])
                output['records'].append(record)
                if model is not None:
                    output['llm_usage'] = dict(model.usage)
                if record['error'] and record['error']['fatal']:
                    output['run_error'] = record['error']['code']
                save()
                if output['run_error']:
                    break
    except asyncio.CancelledError:
        output['run_error'] = 'cancelled'
        raise
    except Exception as exc:
        # Session teardown may wrap errors in an ExceptionGroup; do not serialize
        # raw messages, source text, credentials or local peer traceback paths.
        output['run_error'] = exc.code if isinstance(exc,SearchFailure) else 'session_failure'
    finally:
        if model is not None:
            await model.close()
        if telemetry is not None:
            await telemetry.close()  # flushes queued traces
        save()
    print(json.dumps({'complete':output['complete'],'summary':output['summary'],
                      'mcp_startup_seconds':output['mcp_startup_seconds'],
                      'output':str(output_path)},ensure_ascii=False),flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--rewrites',type=Path)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--systems',default='A,B',help='comma list from A,B,C')
    parser.add_argument('--control',action='store_true',help='add C-ko same-starting-query control')
    parser.add_argument('--langsmith',action='store_true',
                        help='trace every Agent run in LangSmith (project wish-finder-eval) to see token usage; uploads questions and subtitle excerpts')
    parser.add_argument('--max-llm-calls',type=int,default=None,
                        help='stop before an Agent question that could exceed this many LLM calls (billing guard)')
    parser.add_argument('--output',type=Path,default=Path('eval/private/day1-baselines.review2.json'))
    output = asyncio.run(run(parser.parse_args()))
    if not output['complete'] or any(r['status']=='error' for r in output['records']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
