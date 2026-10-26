#!/usr/bin/env python3
"""Run every stack regression in a fresh faulthandler child; retain failures."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('test_structure_depth', 'test_interpreter_stack_semantics',
           'test_interpreter_stack_depth')


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--child')
    args = parser.parse_args()
    sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
    if args.child:
        suite = unittest.defaultTestLoader.loadTestsFromName(args.child)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        report = {'case': args.child, 'tests_run': result.testsRun,
                  'failures': len(result.failures), 'errors': len(result.errors),
                  'skipped': result.skipped,
                  'passed': result.wasSuccessful() and result.testsRun == 1 and not result.skipped}
        save(args.out, report)
        return 0 if report['passed'] else 1
    args.out.mkdir(parents=True, exist_ok=True)
    cases = sorted(test.id() for module in MODULES
                   for test in flatten(unittest.defaultTestLoader.loadTestsFromName(module)))
    if not cases or len(cases) != len(set(cases)) or any('_FailedTest' in c for c in cases):
        raise RuntimeError('Missing, duplicate, or unloadable required stack cases')
    inputs = ['rulang/interpreter.py', 'tools/verify_interpreter_stack.py']
    inputs += ['tests/'+m+'.py' for m in MODULES]
    hashes = lambda: {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in inputs}
    report = {'python': sys.version, 'platform': platform.platform(),
              'head': os.environ.get('GITHUB_SHA'), 'inputs': hashes(),
              'planned': cases, 'attempts': [], 'passed': False}
    save(args.out/'report.json', report)
    for i, case in enumerate(cases):
        prefix = args.out/f'{i:03d}'
        detail = prefix.with_suffix('.json')
        # Never consume a prior child's receipt after a crash or startup error.
        detail.unlink(missing_ok=True)
        attempt = {'case': case, 'timeout_seconds': 120, 'returncode': None,
                   'timeout': False, 'passed': False}
        report['attempts'].append(attempt)
        save(args.out/'report.json', report)
        started = time.monotonic()
        stdout = stderr = b''
        try:
            completed = subprocess.run([sys.executable, '-X', 'faulthandler',
                str(Path(__file__).resolve()), '--child', case, '--out', str(detail.resolve())],
                cwd=ROOT, capture_output=True, timeout=120)
            stdout, stderr = completed.stdout, completed.stderr
            attempt['returncode'] = completed.returncode
            attempt['returncode_hex'] = hex(completed.returncode & 0xffffffff)
            if detail.exists():
                child = json.loads(detail.read_text(encoding='utf-8'))
                attempt['result'] = child
                attempt['passed'] = (completed.returncode == 0 and child.get('case') == case
                    and child.get('passed') is True and type(child.get('tests_run')) is int
                    and child['tests_run'] == 1 and type(child.get('failures')) is int
                    and child['failures'] == 0 and type(child.get('errors')) is int
                    and child['errors'] == 0 and child.get('skipped') == [])
        except subprocess.TimeoutExpired as error:
            attempt['timeout'] = True
            stdout, stderr = error.stdout or b'', error.stderr or b''
        except Exception as error:
            attempt['error'] = type(error).__name__+': '+str(error)
        finally:
            attempt['elapsed_seconds'] = time.monotonic()-started
            for suffix, data in (('stdout', stdout), ('stderr', stderr)):
                prefix.with_suffix('.'+suffix).write_bytes(data)
                attempt[suffix+'_sha256'] = hashlib.sha256(data).hexdigest()
            save(args.out/'report.json', report)
            print(case, 'PASS' if attempt['passed'] else 'FAIL', flush=True)
    try:
        report['inputs_after'] = hashes()
    except Exception as error:
        report['inputs_after'] = None
        report['input_error'] = type(error).__name__+': '+str(error)
    report['passed'] = (report['inputs'] == report['inputs_after'] and
                        len(report['attempts']) == len(cases) and
                        all(a['passed'] for a in report['attempts']))
    save(args.out/'report.json', report)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
