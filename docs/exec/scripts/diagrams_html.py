"""Render the two report figures from HTML/CSS with headless Chrome (2x). Output replaces the PIL versions."""
import base64, json, subprocess, tempfile, time
from pathlib import Path
import httpx
from websockets.asyncio.client import connect
import asyncio

OUT = Path(r'D:\skala\workspace\skala-AICapstone-mini-2\eval\private\submission\diagrams')
CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
SCR = Path(r'C:\Users\175072\AppData\Local\Temp\claude\D--skala-workspace-skala-AICapstone-mini-2\1cd96cc8-0d77-46c9-865c-725254297d26\scratchpad')

STYLE = """
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#fff;font-family:'Malgun Gothic','맑은 고딕',sans-serif;color:#1c2540}
  .canvas{position:relative;background:#fff}
  .box{position:absolute;border-radius:14px;border:2.5px solid;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:10px 12px}
  .box b{font-size:21px;line-height:1.25}
  .box span{font-size:15.5px;color:#4a5570;margin-top:6px;line-height:1.35}
  .blue{background:#e8f0ff;border-color:#4a78e0}
  .green{background:#e6f6ec;border-color:#2fa05f}
  .amber{background:#fff3dc;border-color:#e0951e}
  .gray{background:#f1f3f7;border-color:#8a93a8}
  .lab{position:absolute;font-size:14.5px;color:#4a5570;background:#fff;padding:1px 6px;white-space:nowrap}
  .pill{position:absolute;text-align:center;font-size:15px;font-weight:700;color:#1f7a45;background:#fff;border:2px solid #2fa05f;border-radius:999px;padding:5px 0}
  .legend{position:absolute;font-size:15px;color:#2b3550}
  .legend div{display:flex;align-items:center;margin-bottom:8px}
  .chip{width:20px;height:20px;border-radius:5px;border:2.5px solid;margin-right:10px}
  svg{position:absolute;left:0;top:0}
</style>
"""
MARK = """<defs>
<marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#566079"/></marker>
<marker id="r" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#d04b4b"/></marker>
<marker id="b" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#2f5fd0"/></marker>
</defs>"""

def box(x, y, w, h, cls, title, sub):
    return f'<div class="box {cls}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px"><b>{title}</b><span>{sub}</span></div>'

def lab(x, y, text):
    return f'<div class="lab" style="left:{x}px;top:{y}px">{text}</div>'

# ------------------------------------------------------------ figure 1: system structure (1410 x 790)
def fig1():
    W, H = 1410, 725
    bw, bh = 250, 108
    cx = [30, 380, 730, 1130]            # columns
    ry = [30, 215, 400, 585]             # rows
    parts = [box(cx[0], ry[0], bw, bh, 'blue', '웹 화면 (Vue)', '질문 입력 · 진행 단계 ·<br>결과 카드 · 영상 재생'),
             box(cx[1], ry[0], bw, bh, 'blue', 'API 서버 (FastAPI)', '서버 시작 때 한 번 준비<br>요청을 Agent에 전달'),
             box(cx[2], ry[0], bw, bh, 'green', 'Agent (LangGraph)', '분류 → 검색 → 검증<br>→ (재검색) → 결과 정리'),
             box(cx[3], ry[0], 250, bh, 'amber', 'LLM', '개발: Ollama<br>제출: OpenAI'),
             box(cx[2], ry[1], bw, bh, 'green', 'MCP 서버', '읽기 전용 도구 4개<br>(로컬 프로세스, stdio)'),
             box(cx[2], ry[2], bw, bh, 'green', 'Hybrid 검색기', '키워드(BM25) +<br>의미(bge-m3) 검색'),
             box(cx[2], ry[3], bw, bh, 'gray', '자막 데이터', 'cue 3,750개 · 청크 869개<br>(영상 3편)')]
    mid = ry[0] + bh / 2
    svg = [f'<svg width="{W}" height="{H}">{MARK}']
    # browser -> api (request) and api -> browser (progress, dashed)
    svg.append(f'<line x1="{cx[0]+bw}" y1="{mid-16}" x2="{cx[1]-4}" y2="{mid-16}" stroke="#566079" stroke-width="2.5" marker-end="url(#a)"/>')
    svg.append(f'<line x1="{cx[1]}" y1="{mid+22}" x2="{cx[0]+bw+4}" y2="{mid+22}" stroke="#2f5fd0" stroke-width="2.5" stroke-dasharray="7 5" marker-end="url(#b)"/>')
    # api -> agent
    svg.append(f'<line x1="{cx[1]+bw}" y1="{mid}" x2="{cx[2]-4}" y2="{mid}" stroke="#566079" stroke-width="2.5" marker-end="url(#a)"/>')
    # agent <-> llm
    svg.append(f'<line x1="{cx[2]+bw}" y1="{mid-16}" x2="{cx[3]-4}" y2="{mid-16}" stroke="#566079" stroke-width="2.5" marker-end="url(#a)"/>')
    svg.append(f'<line x1="{cx[3]}" y1="{mid+22}" x2="{cx[2]+bw+4}" y2="{mid+22}" stroke="#566079" stroke-width="2.5" marker-end="url(#a)"/>')
    # vertical chain
    xc = cx[2] + bw / 2
    for a, b in ((0, 1), (1, 2), (2, 3)):
        svg.append(f'<line x1="{xc}" y1="{ry[a]+bh}" x2="{xc}" y2="{ry[b]-4}" stroke="#566079" stroke-width="2.5" marker-end="url(#a)"/>')
    svg.append('</svg>')
    labels = [lab(cx[0] + bw + 18, mid - 46, '질문'), lab(cx[0] + bw + 6, mid + 32, '진행 단계'),
              lab(cx[1] + bw + 20, mid - 26, '호출'),
              lab(cx[2] + bw + 28, mid - 46, '판단 요청'), lab(cx[2] + bw + 28, mid + 30, '판단 결과'),
              lab(xc + 12, ry[0] + bh + 26, '도구 호출'), lab(xc + 12, ry[1] + bh + 26, '검색 요청'), lab(xc + 12, ry[2] + bh + 26, '조회')]
    legend = ('<div class="legend" style="left:30px;top:440px">'
              '<div><span class="chip" style="background:#e8f0ff;border-color:#4a78e0"></span>화면 · 서버</div>'
              '<div><span class="chip" style="background:#e6f6ec;border-color:#2fa05f"></span>코드로 동작</div>'
              '<div><span class="chip" style="background:#fff3dc;border-color:#e0951e"></span>LLM이 판단</div>'
              '<div><span class="chip" style="background:#f1f3f7;border-color:#8a93a8"></span>저장된 자료</div>'
              '<div style="margin-top:14px"><svg width="46" height="12" style="position:static"><line x1="0" y1="6" x2="40" y2="6" stroke="#2f5fd0" stroke-width="2.5" stroke-dasharray="7 5"/></svg>&nbsp;실시간 진행 전송(SSE)</div></div>')
    return W, H, f'<html><head><meta charset="utf-8">{STYLE}</head><body><div class="canvas" style="width:{W}px;height:{H}px">{"".join(parts)}{"".join(svg)}{"".join(labels)}{legend}</div></body></html>'

# ------------------------------------------------------------ figure 2: graph flow (1560 x 545)
def fig2():
    W, H = 1560, 590
    bw, bh, y = 220, 108, 165
    xs = [30, 350, 670, 990, 1310]
    items = [('amber', '① 분류 (Router)', '질문 종류를 판단하고<br>검색어를 작성한다'),
             ('green', '② 검색', '질문과 가까운<br>후보 청크를 찾는다'),
             ('green', '③ 원본 대조', '원본 cue를 다시 읽어<br>영상·시각을 확인한다'),
             ('amber', '④ 의미 판정', '질문과 자막 내용이<br>맞는지 판정한다'),
             ('blue', '⑤ 결과 정리', '결과 상태와<br>고정 문구를 정한다')]
    parts = [box(xs[i], y, bw, bh, c, t, s_) for i, (c, t, s_) in enumerate(items)]
    ry = 370
    parts.append(box(xs[3], ry, bw, 92, 'amber', '재검색 (Replan)', '검색어를 새로 작성한다<br>(최대 2번)'))
    for i, name in ((1, 'search_transcripts'), (2, 'get_scene_context')):
        parts.append(f'<div class="pill" style="left:{xs[i]+14}px;top:{y-44}px;width:{bw-28}px">MCP · {name}</div>')
    mid = y + bh / 2
    svg = [f'<svg width="{W}" height="{H}">{MARK}']
    for i in range(4):
        svg.append(f'<line x1="{xs[i]+bw}" y1="{mid}" x2="{xs[i+1]-4}" y2="{mid}" stroke="#566079" stroke-width="2.5" marker-end="url(#a)"/>')
    # shortcut over the top: 분류 -> 결과 정리 (unsupported / chat)
    svg.append(f'<path d="M {xs[0]+bw/2} {y} L {xs[0]+bw/2} 62 L {xs[4]+bw/2} 62 L {xs[4]+bw/2} {y-4}" fill="none" stroke="#d04b4b" stroke-width="2.5" stroke-dasharray="8 5" marker-end="url(#r)"/>')
    # 판정 -> 재검색 (down) and loop back to 검색
    svg.append(f'<line x1="{xs[3]+bw/2}" y1="{y+bh}" x2="{xs[3]+bw/2}" y2="{ry-4}" stroke="#566079" stroke-width="2.5" marker-end="url(#a)"/>')
    svg.append(f'<path d="M {xs[3]} {ry+46} L {xs[1]+bw/2} {ry+46} L {xs[1]+bw/2} {y+bh+4}" fill="none" stroke="#566079" stroke-width="2.5" marker-end="url(#a)"/>')
    svg.append('</svg>')
    labels = [lab(640, 36, '자막으로 알 수 없는 요청 · 일반 대화는 검색 없이 바로 종료'),
              lab(xs[3] + bw + 18, mid - 36, '후보 있음'),
              lab(xs[3] + bw/2 + 14, 296, '관련 후보 없음'),
              lab(520, ry + 16, '새 검색어로 ② 부터 다시 (처음 포함 최대 3라운드)')]
    legend = ('<div class="legend" style="left:30px;top:345px">'
              '<div><span class="chip" style="background:#fff3dc;border-color:#e0951e"></span>LLM이 판단</div>'
              '<div><span class="chip" style="background:#e6f6ec;border-color:#2fa05f"></span>코드로 동작</div>'
              '<div><span class="chip" style="background:#e8f0ff;border-color:#4a78e0"></span>결과 정리</div></div>')
    note = ('<div style="position:absolute;left:30px;top:492px;font-size:16px;color:#4a5570;line-height:1.7">'
            '그래프 밖에서 쓰는 MCP 도구: get_video_metadata(서버 시작 때 영상 정보 읽기), get_cue_neighbors(화면의 앞뒤 자막 조회)<br>'
            '제한: 재검색 최대 2번 · LLM 호출 20초 · 전체 60초 · 남은 시간 25초 미만이거나 같은 검색어·새 후보 없음이면 재검색하지 않는다</div>')
    return W, H, f'<html><head><meta charset="utf-8">{STYLE}</head><body><div class="canvas" style="width:{W}px;height:{H}px">{"".join(parts)}{"".join(svg)}{"".join(labels)}{legend}{note}</div></body></html>'


async def render(html_path, W, H, out_png):
    profile = tempfile.mkdtemp(prefix='wf-fig-')
    proc = subprocess.Popen([CHROME, '--headless=new', '--remote-debugging-port=9337', f'--user-data-dir={profile}',
                             '--no-first-run', 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                page = next(p for p in httpx.get('http://127.0.0.1:9337/json/list', timeout=1).json() if p['type'] == 'page'); break
            except Exception:
                time.sleep(.3)
        async with connect(page['webSocketDebuggerUrl'], max_size=64 * 1024 * 1024) as ws:
            seq = 0
            async def cmd(m, p=None):
                nonlocal seq
                seq += 1; i = seq
                await ws.send(json.dumps({'id': i, 'method': m, 'params': p or {}}))
                while True:
                    r = json.loads(await ws.recv())
                    if r.get('id') == i:
                        if 'error' in r: raise RuntimeError(r['error'])
                        return r['result']
            await cmd('Page.enable')
            await cmd('Emulation.setDeviceMetricsOverride', {'width': W, 'height': H, 'deviceScaleFactor': 2, 'mobile': False})
            await cmd('Page.navigate', {'url': html_path.as_uri()})
            await asyncio.sleep(1.2)
            shot = await cmd('Page.captureScreenshot', {'format': 'png', 'clip': {'x': 0, 'y': 0, 'width': W, 'height': H, 'scale': 1}})
            out_png.write_bytes(base64.b64decode(shot['data']))
            print('saved', out_png, W, H)
    finally:
        proc.terminate()


async def main():
    for name, fn, out in (('fig1', fig1, 'architecture.png'), ('fig2', fig2, 'langgraph_flow.png')):
        W, H, html = fn()
        path = SCR / f'{name}.html'
        path.write_text(html, encoding='utf-8')
        await render(path, W, H, OUT / out)

asyncio.run(main())
