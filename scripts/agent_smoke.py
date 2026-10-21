"""Run actual local LLM + Hybrid + stdio Graph on non-gold demo questions.

Does not download models, call paid APIs or modify frozen evaluation labels.
Run after stopping other dense API processes to avoid loading bge-m3 twice.
"""

import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from backend.app.agent.graph import FinderAgent
from backend.app.agent.model import build_model
from backend.app.profile import load_profile
from backend.app.mcp.client import connect
from backend.app.schemas import MetadataReply
from backend.app.services.search import SearchFailure, call_tool
from backend.app.services.video_catalog import load_videos
from eval.paths import private_output, write_private_json


async def main():
    output=private_output('eval/private/day2-agent-smoke.json')
    if output.exists():
        raise ValueError('Smoke output already exists; preserve previous measurements')
    model=build_model(profile=load_profile())
    records=[]
    try:
        await model.ready()
        env={k:v for k,v in os.environ.items() if k.startswith('WISH_')}
        env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
        async with connect(env=env) as session:
            metadata={v.video_id:await call_tool(session,'get_video_metadata',
                         {'video_id':v.video_id},MetadataReply) for v in load_videos()}
            agent=FinderAgent(session,metadata,model)
            for name,query in [
                ('scene','리쿠가 마니또 뽑다가 자기 자신을 뽑은 장면'),
                ('speaker','료칸이 뭐냐고 물었던 사람은 누구야? 그 장면 찾아줘'),
                ('visual','리쿠가 마니또 뽑을 때 입은 옷 색깔은 뭐야?'),
            ]:
                try:
                    response,stats=await agent.run(query)
                    records.append({'case':name,'response':response.model_dump(),'stats':stats})
                    print(json.dumps({'case':name,'status':response.status,
                        'first_url':response.results[0].url if response.results else None,**stats},ensure_ascii=False),flush=True)
                except SearchFailure as exc:
                    records.append({'case':name,'error':exc.code,'tool_calls':exc.tool_calls})
                    print(json.dumps({'case':name,'error':exc.code}),flush=True)
                write_private_json(output,{'model':model.name,'records':records})
    finally:
        await model.close()


if __name__=='__main__':
    asyncio.run(main())
