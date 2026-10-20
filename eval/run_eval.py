"""Run A/B through the product search service; never evaluate draft gold.

All relative CLI paths are project-root relative. Output stays in eval/private/.
Final C requires the actual Day 2 Agent and is not measured here.
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

from backend.app.mcp.client import connect
from backend.app.schemas import MetadataReply, SearchResponse
from backend.app.services.search import SearchFailure, call_tool, search_and_verify
from backend.app.services.video_catalog import Catalog, ROOT, resolve_manifest
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


async def run(args):
    dataset = project_path(args.dataset)
    rows = load_questions(dataset)
    if any(r.split=='gold_draft' or (r.split=='gold' and r.label_status!='accepted') for r in rows):
        raise ValueError('Draft gold is reserved: review/freeze labels before evaluation')
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
    conditions = ['raw_ko'] + (['frozen_model_en'] if rewrites else [])
    tasks = [{'question':row, 'query':row.query if condition=='raw_ko' else rewrites[row.id],
              'condition':condition, 'system':system, 'mode':mode}
             for condition in conditions for system,mode in [('A','keyword'),('B','hybrid')] for row in rows]
    corpus = [{'video_id':v.video_id,
               'sha256':hashlib.sha256((ROOT/v.transcript_file).read_bytes()).hexdigest()}
              for v in catalog.videos.values()]
    output = {
        'schema_version':2, 'created_at':datetime.now(timezone.utc).isoformat(), 'corpus':corpus,
        'dataset_sha256':hashlib.sha256(dataset.read_bytes()).hexdigest(),
        'rewrite_sha256':hashlib.sha256(rewrite_path.read_bytes()).hexdigest() if rewrite_path else None,
        'preprocessing':'SearchRequest: length validation then trim/nonblank validation',
        'metric_policy':'Same video and floor(link time) in accepted interval ±10s',
        'semantic_verification':False, 'systems_not_measured':['C'], 'mcp_startup_seconds':None,
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
    try:
        async with connect(env=env) as session:
            output['mcp_startup_seconds'] = round(time.monotonic()-started,3)
            metadata = {vid:await call_tool(session,'get_video_metadata',{'video_id':vid},MetadataReply)
                        for vid in catalog.videos}
            output['video_timing'] = {vid:'sampled' if v.timing_verified else 'unverified'
                                      for vid,v in metadata.items()}
            for task in tasks:
                record = await evaluate_question(session,task['question'],task['query'],task['mode'],metadata,
                                                  condition=task['condition'],system=task['system'])
                output['records'].append(record)
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
    parser.add_argument('--output',type=Path,default=Path('eval/private/day1-baselines.review2.json'))
    output = asyncio.run(run(parser.parse_args()))
    if not output['complete'] or any(r['status']=='error' for r in output['records']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
