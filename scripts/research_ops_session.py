"""Import a selected Codex rollout window; retain counts/locators, never raw prompts."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re

from research_ops import sha, STAGES


def stamp(row):
    return datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))


def commands(payload):
    raw = payload.get('input', payload.get('arguments', ''))
    if isinstance(raw, dict):
        return [raw['cmd']] if 'cmd' in raw else []
    try:
        value = json.loads(raw)
        if isinstance(value, dict) and 'cmd' in value:
            return [value['cmd']]
    except (ValueError, TypeError):
        pass
    return [json.loads(s) for s in re.findall(r'\bcmd\s*:\s*("(?:\\.|[^"\\])*")', raw)]


def classify(name, text):
    s = text.lower()
    if name == 'js' or 'cua.' in s: return 'browser_qa'
    if re.search(r'git (?:push|add|commit|diff|check-attr|ls-remote)|write_stdin|git-remote-https', s): return 'git_closeout'
    if 'pytest' in s or 'node --test' in s: return 'tests'
    if 'apply_patch' in s: return 'implementation'
    if re.search(r'hashlib|sha256|consoledata|audit\.py|verify', s): return 'audit'
    if re.search(r'mj_step|run_phase|render_mechanism.py --', s): return 'experiment'
    if re.search(r'get-content|rg |get-childitem|git status|git branch|git log', s): return 'context'
    return 'reasoning'


def import_session(path, start, end=None):
    all_rows = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
    rows = all_rows[start:end]
    calls = []; file_reads = []; stages = Counter(); tools = Counter(); usage = Counter(); output_chars = 0
    reasoning_items = 0
    for ordinal, row in enumerate(rows, start):
        payload = row.get('payload', {})
        if row.get('type') == 'token_usage_record':
            usage.update({k: v for k, v in payload['usage'].items() if isinstance(v, int)})
        if row.get('type') != 'response_item': continue
        typ = payload.get('type')
        if typ == 'reasoning': reasoning_items += 1
        if typ in ('function_call_output', 'custom_tool_call_output'):
            out = payload.get('output', '')
            # Images/binary payloads must not inflate textual context estimates.
            if isinstance(out, str): output_chars += len(out)
            elif isinstance(out, list):
                output_chars += sum(len(c.get('text', '')) for c in out if c.get('type') in ('text', 'input_text'))
        if typ not in ('function_call', 'custom_tool_call'): continue
        name = payload.get('name', 'unknown'); tools[name] += 1
        raw = payload.get('input', payload.get('arguments', ''))
        cmd = commands(payload); stage = classify(name, str(raw)); stages[stage] += 1
        refs = []
        for command in cmd:
            for match in re.findall(r'Get-Content\s+(?:-LiteralPath\s+)?([^;|\r\n]+)', command, re.I):
                locator = re.split(r'\s+-', match.strip())[0].strip('"\' ')
                # Keep repo paths only; discard home/config/credentials and external history.
                locator = locator.replace('\\', '/')
                if ':' not in locator and not locator.startswith(('/', '$')):
                    refs.append(locator); file_reads.append(locator)
        calls.append({'ordinal': ordinal, 'at': row['timestamp'], 'tool': name, 'stage_inferred': stage,
                      'shell_commands': len(cmd), 'file_read_references': refs,
                      'nested_tool_calls': Counter(re.findall(r'tools\.([A-Za-z_][A-Za-z_0-9]*)\(', str(raw)))})
    reads = Counter(file_reads)
    return {'schema_version': 1, 'source_rollout_sha256': sha(path), 'source_filename': path.name,
            'window': {'start_ordinal_inclusive': start, 'end_ordinal_exclusive': end or len(all_rows),
                       'first_at': rows[0]['timestamp'], 'last_at': rows[-1]['timestamp'],
                       'elapsed_seconds': (stamp(rows[-1]) - stamp(rows[0])).total_seconds()},
            'outer_tool_calls': len(calls), 'tools': tools, 'nested_shell_commands': sum(c['shell_commands'] for c in calls),
            'get_content_references': len(file_reads), 'unique_get_content_paths': len(reads),
            'repeated_get_content_references': sum(n - 1 for n in reads.values()), 'file_read_counts': reads,
            'reasoning_items': reasoning_items, 'stage_tool_calls_inferred': {s: stages[s] for s in STAGES},
            'text_tool_output_chars': output_chars, 'recorded_token_usage': dict(usage) or None,
            'uncached_input_tokens': usage['input_tokens'] - usage['cached_input_tokens'] if 'input_tokens' in usage and 'cached_input_tokens' in usage else None,
            'calls': calls, 'limitations': ['Parent rollout only; child work/cost excluded.',
                'Reasoning items are observable segments, not proven repeated semantic decisions.',
                'Get-Content references are a lower bound: Python/open/rg/child reads excluded; original files-read count unavailable.',
                'Stage labels are heuristics, not measured phase time. Shell calls include batched commands.',
                'Cumulative input token counts include repeated cached context; not unique prompt size or billing.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('rollout', type=Path); p.add_argument('--start', type=int, required=True); p.add_argument('--end', type=int)
    p.add_argument('--output', type=Path, required=True); args = p.parse_args()
    if args.output.exists(): raise SystemExit('Refusing to replace existing imported evidence')
    result = import_session(args.rollout, args.start, args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('calls', 'file_read_counts', 'tools', 'limitations')}, indent=2))


if __name__ == '__main__': main()
