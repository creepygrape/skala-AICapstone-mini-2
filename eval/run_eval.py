"""Run A/B through one real MCP subprocess; do not execute draft gold labels.

Example: .venv/bin/python -m eval.run_eval --dataset eval/private/dev.jsonl
--rewrites eval/private/dev.rewrites.json --output eval/private/day1-baselines.json
Only A/B are implemented here. Final C requires the actual Day 2 Agent.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from statistics import mean
import time

from backend.app.mcp.client import connect
from backend.app.schemas import ContextReply, MetadataReply, SearchReply
from backend.app.services.evidence import verify_candidate
from backend.app.services.video_catalog import Catalog, ROOT, resolve_manifest
from eval.dataset import load_questions, validate_source_labels
from eval.metrics import scene_metrics


async def read_tool(session,name,args,schema):
    reply=await session.call_tool(name,args,read_timeout_seconds=30)
    if reply.is_error or reply.structured_content is None:
        raise RuntimeError(f'MCP evaluation tool failed: {name}')
    return schema.model_validate(reply.structured_content)


async def run(args):
    rows=load_questions(args.dataset)
    if any(r.split=='gold_draft' or (r.split=='gold' and r.label_status!='accepted') for r in rows):
        raise ValueError('Draft gold is reserved: review/freeze labels before evaluation')
    manifest=resolve_manifest(args.manifest)
    catalog=Catalog(manifest)
    validate_source_labels(rows,catalog)
    rewrites=None
    if args.rewrites:
        rewrite_data=json.loads(args.rewrites.read_text())
        items=rewrite_data['queries']
        if len(items)!=len(rows) or {x['id'] for x in items}!={r.id for r in rows}:
            raise ValueError('Frozen rewrite IDs must match dataset exactly once')
        rewrites={x['id']:x['query_en'] for x in items}
    conditions=['raw_ko']+(['frozen_model_en'] if rewrites else [])
    corpus=[{'video_id':v.video_id,'sha256':hashlib.sha256((ROOT/v.transcript_file).read_bytes()).hexdigest()}
            for v in catalog.videos.values()]
    started=time.monotonic()
    records=[]
    env={key:value for key,value in os.environ.items() if key.startswith('WISH_')}
    env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false',
               WISH_MANIFEST=str(manifest.resolve()),WISH_KEYWORD_ONLY='0')
    async with connect(env=env) as session:
        startup=time.monotonic()-started
        metadata={vid:await read_tool(session,'get_video_metadata',{'video_id':vid},MetadataReply)
                  for vid in catalog.videos}
        for condition in conditions:
            for system,mode in [('A','keyword'),('B','hybrid')]:
                for row in rows:
                    query=row.query if condition=='raw_ko' else rewrites[row.id]
                    begin=time.monotonic();calls=1
                    reply=await read_tool(session,'search_transcripts',{'query':query,'mode':mode,'top_k':3},SearchReply)
                    results=[]
                    for candidate in reply.candidates:
                        context=await read_tool(session,'get_scene_context',{
                            'video_id':candidate.chunk.video_id,'start_seconds':candidate.chunk.start_seconds,
                            'window_seconds':20},ContextReply)
                        calls+=1
                        results.append(verify_candidate(candidate,context,metadata[candidate.chunk.video_id]))
                    records.append({'id':row.id,'condition':condition,'system':system,'query':query,
                                    'latency_seconds':round(time.monotonic()-begin,6),
                                    'tool_calls':calls,'llm_calls':0,'search_rounds':1,
                                    'metrics':scene_metrics(row,results),
                                    'results':[{'video_id':x.video_id,'cue_ids':x.cue_ids,
                                                'start_seconds':x.start_seconds,'speaker':x.speaker}
                                               for x in results]})
    summaries=[]
    for condition in conditions:
        for system in ['A','B']:
            group=[x for x in records if x['condition']==condition and x['system']==system]
            scored=[x for x in group if x['metrics'] is not None]
            summaries.append({'condition':condition,'system':system,'scene_questions':len(scored),
                              'success_at_1_count':sum(x['metrics']['scene_success_at_1'] for x in scored),
                              'hit_at_3_count':sum(x['metrics']['hit_at_3'] for x in scored),
                              'mean_seconds':round(mean(x['latency_seconds'] for x in group),4),
                              'samples_per_question':1})
    output={'created_at':datetime.now(timezone.utc).isoformat(),'corpus':corpus,
            'dataset_sha256':hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
            'rewrite_sha256':hashlib.sha256(args.rewrites.read_bytes()).hexdigest() if args.rewrites else None,
            'mcp_startup_seconds':round(startup,3),'metric_policy':'Same video and floor(link time) in accepted interval ±10s',
            'semantic_verification':False,'systems_not_measured':['C'],
            'summary':summaries,'records':records}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'summary':summaries,'mcp_startup_seconds':output['mcp_startup_seconds'],
                      'output':str(args.output)},ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--rewrites',type=Path)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--output',type=Path,default=Path('eval/private/day1-baselines.json'))
    args=parser.parse_args()
    if args.manifest and not args.manifest.is_absolute():
        args.manifest=ROOT/args.manifest
    asyncio.run(run(args))


if __name__=='__main__':
    main()
