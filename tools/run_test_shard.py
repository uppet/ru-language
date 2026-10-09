#!/usr/bin/env python3
"""Run one deterministic, disjoint shard of the full unittest discovery suite."""
import argparse
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def select_tests(suite, shard, count):
    if count < 1 or not 0 <= shard < count:
        raise ValueError('shard must be in [0, count)')
    tests = sorted(flatten(suite), key=lambda test: test.id())
    ids = [test.id() for test in tests]
    if len(ids) != len(set(ids)):
        raise ValueError('discovered duplicate test identities')
    return tests, tests[shard::count]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shard', type=int, required=True)
    parser.add_argument('--count', type=int, required=True)
    parser.add_argument('--failfast', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    discovered = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    try:
        all_tests, selected = select_tests(discovered, args.shard, args.count)
    except ValueError as error:
        parser.error(str(error))
    digest = hashlib.sha256('\n'.join(test.id() for test in all_tests).encode()).hexdigest()
    print(f'Shard {args.shard + 1}/{args.count}: {len(selected)} of {len(all_tests)} tests; '
          f'collection SHA-256 {digest}', flush=True)
    if not selected:
        parser.error('empty shard')
    result = unittest.TextTestRunner(verbosity=2, failfast=args.failfast).run(unittest.TestSuite(selected))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
