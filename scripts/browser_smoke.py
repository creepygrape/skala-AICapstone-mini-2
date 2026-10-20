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
        await evaluate("document.querySelector('#query').value='리쿠가 마니또 뽑다가 자기 자신을 뽑은 장면'; document.querySelector('#query').dispatchEvent(new Event('input',{bubbles:true}));")
        await asyncio.sleep(.1)
        await evaluate("document.querySelector('form').requestSubmit()")
        await wait_for("document.querySelector('article a') !== null || document.querySelector('[role=alert]') !== null")
        assert not await evaluate("!!document.querySelector('[role=alert]')")
        href = await evaluate("document.querySelector('article a').href")
        assert href=='https://www.youtube.com/watch?v=1HJgbE66GI4&t=189s', href
        assert await evaluate("document.querySelector('article blockquote').textContent.includes('(RIKU chose RIKU)')")
        assert await evaluate("document.body.textContent.includes('화자 미확인')")
        assert await evaluate("document.body.textContent.includes('의미 일치는 아직 검증하지 않았어요')")
        screenshot = await command('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True})
        target=Path('/private/tmp/wish-finder-day1.png')
        target.write_bytes(base64.b64decode(screenshot['data']))
        print(json.dumps({'browser_smoke':'passed','first_result_url':href,'screenshot':str(target)},ensure_ascii=False))


if __name__=='__main__':
    asyncio.run(main())
