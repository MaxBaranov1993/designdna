"""Opt-in live four-case QA; existing tagged nodes only, no mocks or publication."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import time

from ui_source_sites_qa import OUT, ROOT, output


def run_case(site, provider):
    report = {'site': site, 'provider': provider, 'startedAt': time.time(), 'steps': []}
    def step(action, operation=None):
        started = time.time()
        command = [sys.executable, str(ROOT / 'app/ui_source_sites_qa.py'), action,
                   '--site', site, '--provider', provider]
        if operation:
            command += ['--operation', operation]
        label = operation or action
        log = OUT / f'{site}-{provider}-{label}-live.log'
        print(json.dumps({'site': site, 'provider': provider, 'step': label, 'status': 'running'}), flush=True)
        with log.open('w', encoding='utf-8') as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    encoding='utf-8', timeout=3700)
        item = {'step': label, 'exitCode': result.returncode, 'seconds': round(time.time()-started), 'log': str(log)}
        report['steps'].append(item)
        output(f'{site}-{provider}-case', report)
        print(json.dumps({'site': site, 'provider': provider, **item}), flush=True)
        return result.returncode == 0
    if not step('import'):
        return report
    source = json.loads((OUT / f'{site}-{provider}-source.json').read_text(encoding='utf-8'))
    report['sourcePipeline'] = source.get('pipelineStatus')
    if (source.get('pipelineStatus') or {}).get('import', {}).get('status') not in ('success', 'warning'):
        report['blocked'] = 'Source import did not complete; refusing to review an older DS'
        output(f'{site}-{provider}-case', report)
        return report
    if not step('build'):
        return report
    for operation in ('organize', 'style-review', 'master-review'):
        step('ai', operation)
    report['finishedAt'] = time.time()
    output(f'{site}-{provider}-case', report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-live', action='store_true')
    parser.add_argument('--round', type=int, choices=[1, 2], required=True)
    parser.add_argument('--site', choices=['slsbmb', 'rsale'], help='Retry only one existing pair')
    args = parser.parse_args()
    if not args.run_live:
        parser.error('Explicit --run-live required; calls authenticated subscription providers')
    OUT.mkdir(parents=True, exist_ok=True)
    pairs = [('slsbmb', 'claude'), ('rsale', 'codex')] if args.round == 1 else [('slsbmb', 'codex'), ('rsale', 'claude')]
    if args.site:
        pairs = [pair for pair in pairs if pair[0] == args.site]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pair: run_case(*pair), pairs))
    output(f'matrix-round-{args.round}', results)


if __name__ == '__main__':
    main()
