"""Print one private Agent trace (WISH_AGENT_TRACE) as a readable round-by-round view.

Usage: .venv/bin/python scripts/show_trace.py [trace.json | trace_dir]
With a directory (default eval/private/traces), the newest trace is shown.
Traces contain subtitle text: keep them in Git-ignored eval/private/ or logs/.
"""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def mmss(seconds):
    seconds = int(seconds)
    return f'{seconds // 60}:{seconds % 60:02d}'


def pick(arg):
    path = Path(arg) if arg else ROOT / 'eval/private/traces'
    if path.is_dir():
        files = sorted(path.glob('*.json'))
        if not files:
            sys.exit(f'no traces in {path}')
        return files[-1]
    return path


def main():
    path = pick(sys.argv[1] if len(sys.argv) > 1 else None)
    data = json.loads(path.read_text(encoding='utf-8'))
    print(f"질문: {data['user_query']}")
    print(f"결과: {data['status']}  검색 {data['search_attempts']}회  LLM {data['llm_calls']}회  "
          f"tool {data['tool_calls']}회  {data['seconds']:.1f}s  error={data['error']}")
    for item in data['trace']:
        step = item['step']
        if step == 'router':
            print(f"\n[router] intent={item['intent']}  query={item['query']!r}")
        elif step == 'search':
            print(f"\n[search #{item['attempt'] + 1}] query={item['query']!r}")
            for c in item['candidates']:
                text = ' / '.join(c['text'].splitlines())[:110]
                print(f"  {c['rank']}. {c['video_id']} {mmss(c['start'])}-{mmss(c['end'])} "
                      f"score={c['score']}  {text}")
        elif step == 'context':
            print(f"[context] grounded={len(item['grounded'])} rejected={item['rejected']}")
        elif step == 'verification':
            for v in item['verdicts']:
                print(f"[verify] {v['verdict']:<10} {v['evidence_id']} {mmss(v['start'])}  {v['quote'][:90]!r}")
        elif step == 'replan':
            print(f"[replan] -> {item['proposed']!r}")
    print('\n최종 결과:')
    for r in data['results'] or [{'evidence_id': '(없음)', 'start': 0, 'quote': ''}]:
        print(f"  {r['evidence_id']} {mmss(r['start'])}  {r['quote'][:90]!r}")
    print(f"warnings: {', '.join(data['warnings'])}")
    print(f"\n({path})")


if __name__ == '__main__':
    main()
