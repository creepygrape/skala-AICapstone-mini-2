"""Drive an existing local Chrome CDP session without installing browser packages.

Start a separate headless Chrome with --remote-debugging-port=9223 first.
Requires the API on :8000 and Vite on :5173. Uses the actual local corpus.
"""

import asyncio
import base64
import json
from pathlib import Path
import time

import httpx
from websockets.asyncio.client import connect


async def main():
    pages = httpx.get('http://127.0.0.1:9223/json/list').json()
    page = next(p for p in pages if p['type'] == 'page')
    async with connect(page['webSocketDebuggerUrl'], max_size=8*1024*1024) as ws:
        sequence = 0

        async def command(method, params=None):
            nonlocal sequence
            sequence += 1
            message_id = sequence
            await ws.send(json.dumps({'id':message_id,'method':method,'params':params or {}}))
            while True:
                reply = json.loads(await ws.recv())
                if reply.get('id') == message_id:
                    if 'error' in reply:
                        raise RuntimeError(reply['error'])
                    return reply['result']

        async def evaluate(expression):
            reply = await command('Runtime.evaluate',{'expression':expression,'returnByValue':True})
            if reply.get('exceptionDetails'):
                raise RuntimeError(reply['exceptionDetails'])
            return reply['result'].get('value')

        async def wait_for(expression, seconds=65):
            deadline = time.monotonic()+seconds
            while time.monotonic() < deadline:
                value = await evaluate(expression)
                if value:
                    return value
                await asyncio.sleep(.2)
            raise TimeoutError(expression)

        await command('Page.enable')
        await command('Page.navigate',{'url':'http://127.0.0.1:5173/'})
        await wait_for("document.querySelector('#query') !== null",10)
        await evaluate("window.__wishResults=[]; const originalFetch=window.fetch; window.fetch=async (...args) => { const response=await originalFetch(...args); if(String(args[0]).includes('/search/stream')) response.clone().text().then(text => { for(const frame of text.split('\\n\\n')) if(frame.startsWith('event: result')) window.__wishResults.push(JSON.parse(frame.split('data: ')[1])); }).catch(() => {}); return response; }")
        await evaluate("window.__wishProgress=[]; new MutationObserver(() => { const n=document.querySelector('[role=status]'); if(n) window.__wishProgress.push(n.textContent) }).observe(document.body,{subtree:true,childList:true,characterData:true})")
        await evaluate("document.querySelector('#query').value='리쿠가 마니또 뽑다가 자기 자신을 뽑은 장면'; document.querySelector('#query').dispatchEvent(new Event('input',{bubbles:true}));")
        await asyncio.sleep(.1)
        await evaluate("document.querySelector('form').requestSubmit()")
        await wait_for("document.querySelector('article a') !== null || document.querySelector('[role=alert]') !== null")
        assert not await evaluate("!!document.querySelector('[role=alert]')")
        href = await evaluate("document.querySelector('article a').href")
        assert href=='https://www.youtube.com/watch?v=1HJgbE66GI4&t=189s', href
        assert await evaluate("document.querySelector('article blockquote').textContent.includes('(RIKU chose RIKU)')")
        assert await evaluate("document.body.textContent.includes('화자 미확인')")
        await wait_for("window.__wishResults.length === 1")
        result = await evaluate("window.__wishResults[0].results[0]")
        assert result['cue_ids'] == ['69'] and result['speaker'] is None, result
        progress=await evaluate("window.__wishProgress")
        assert any('질문 유형' in item for item in progress),progress
        assert any('검색 중' in item for item in progress),progress
        assert any('원문과 시점' in item for item in progress),progress

        await evaluate("document.querySelector('#query').value='료칸이 뭐냐고 물었던 사람은 누구야? 그 장면 찾아줘'; document.querySelector('#query').dispatchEvent(new Event('input',{bubbles:true})); document.querySelector('form').requestSubmit()")
        await wait_for("document.querySelector('article') !== null && !document.querySelector('button[type=submit]').disabled")
        assert await evaluate("document.body.textContent.includes('자막에는 화자 정보가 없어 발화자는 확인할 수 없습니다.')")
        assert await evaluate("document.querySelector('article').textContent.includes('화자 미확인')")
        await wait_for("window.__wishResults.length === 2")
        assert await evaluate("window.__wishResults[1].results.every(item => item.speaker === null)")


        await evaluate("document.querySelector('#query').value='리쿠가 마니또 뽑을 때 입은 옷 색깔은 뭐야?'; document.querySelector('#query').dispatchEvent(new Event('input',{bubbles:true})); document.querySelector('form').requestSubmit()")
        await wait_for("document.body.textContent.includes('자막으로 확인할 수 없는 요청이에요') && !document.querySelector('button[type=submit]').disabled")
        assert not await evaluate("!!document.querySelector('article')")
        # Cancel while the actual model is waiting, then prove the API is reusable.
        await evaluate("document.querySelector('#query').value='리쿠가 마니또 뽑다가 자기 자신을 뽑은 장면'; document.querySelector('#query').dispatchEvent(new Event('input',{bubbles:true})); document.querySelector('form').requestSubmit()")
        await wait_for("document.querySelector('[role=status]') !== null")
        await evaluate("document.querySelector('[role=status] button').click()")
        await wait_for("document.querySelector('[role=alert]')?.textContent.includes('취소') && !document.querySelector('button[type=submit]').disabled")
        await asyncio.sleep(.5)
        await evaluate("document.querySelector('form').requestSubmit()")
        await wait_for("!document.querySelector('button[type=submit]').disabled")
        assert not await evaluate("!!document.querySelector('[role=alert]')"), await evaluate("document.body.textContent")
        assert await evaluate("document.querySelector('article a')?.href") == href
        screenshot = await command('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True})
        target=Path('/private/tmp/wish-finder-day2-sse.png')
        target.write_bytes(base64.b64decode(screenshot['data']))
        print(json.dumps({'browser_smoke':'passed','scenarios':4,'first_result_url':href,
                          'progress':progress,'screenshot':str(target)},ensure_ascii=False))


if __name__=='__main__':
    asyncio.run(main())
