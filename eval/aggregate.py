"""Recompute report numbers from a private result file (no model, no search).

C counts as success only when status == 'found' (partial/ambiguous never do), even for
older artifacts whose `metrics` held raw candidate hits. A/B keep their search semantics.
"""

import argparse
import json
from pathlib import Path

from eval.paths import private_output


def aggregate(records):
    rows = {}
    for r in records:
        agent = r['system'].startswith('C')
        m = r.get('retrieval_metrics') if r.get('retrieval_metrics') is not None else r['metrics']
        row = rows.setdefault((r['condition'], r['system']), {
            'scene_questions':0, 'success_at_1':0, 'hit_at_3':0, 'raw_success_at_1':0, 'raw_hit_at_3':0,
            'confident_wrong':0, 'status':{}, 'tool_calls':0, 'llm_calls':0, 'fallback':0})
        row['status'][r['status']] = row['status'].get(r['status'], 0) + 1
        row['tool_calls'] += r.get('tool_calls', 0)
        row['llm_calls'] += r.get('llm_calls', 0)
        row['fallback'] += bool(r.get('fallback'))
        if m is None:
            continue
        counted = (not agent) or r['status'] == 'found'
        row['scene_questions'] += 1
        row['raw_success_at_1'] += m['scene_success_at_1']
        row['raw_hit_at_3'] += m['hit_at_3']
        row['success_at_1'] += bool(counted and m['scene_success_at_1'])
        row['hit_at_3'] += bool(counted and m['hit_at_3'])
        row['confident_wrong'] += bool(agent and r['status'] == 'found' and not m['scene_success_at_1'])
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    path = private_output(parser.parse_args().input)
    for (condition, system), row in aggregate(json.loads(path.read_text(encoding='utf-8'))['records']).items():
        print(condition, system, json.dumps(row, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
