#!/usr/bin/env python3
"""Verify a punctuation-only asset migration against an explicit local baseline.

Usage: python3 tools/verify_statement_style_assets.py --baseline /path/to/base
Neither tree is modified. Token source positions are intentionally excluded;
all node kinds, names, values, bodies and expression structure must stay equal.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.frontend import Node, Token, RuError, parse


def semantic(value):
    if isinstance(value, Node):
        return (value.kind, semantic(value.data))
    if isinstance(value, Token):
        return (value.kind, value.value)
    if isinstance(value, dict):
        return {key: semantic(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [semantic(item) for item in value]
    return value


def asset_label(path, root):
    """Serialize repository-relative asset identity consistently on every host."""
    return path.relative_to(root).as_posix()


def sources(root):
    for directory in ('examples', 'rushu/examples', 'rulang/stdlib', 'rulang/thirdparty'):
        for path in sorted((root / directory).rglob('*.ru')):
            yield asset_label(path, root), path.read_text(encoding='utf-8')
    docs = list((root / 'docs').rglob('*.md'))
    docs += [root / p for p in ('README.md', 'rulang/language-spec.md', 'emacs/README.md', 'rushu/README.md', 'examples/wish.md')]
    docs += list((root / 'rulang/thirdparty').rglob('*.md'))
    for path in sorted(docs):
        for index, match in enumerate(re.finditer(r'^```ru[^\n]*\n(.*?)^```\s*$', path.read_text(encoding='utf-8'), re.M | re.S)):
            yield f'{asset_label(path, root)}:fence:{index}', match[1]
    for path in sorted((root / 'rushu/examples').rglob('*.rushu.json')):
        for index, cell in enumerate(json.loads(path.read_text(encoding='utf-8'))['cells']):
            if cell['type'] == 'code':
                yield f'{asset_label(path, root)}:cell:{index}', cell['source']
    script = """
import {templates,createTemplateBook} from './rushu/static/templates.mjs';
console.log(JSON.stringify(templates.map(t=>[t.id,createTemplateBook(t.id)])));
"""
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=root,
                            text=True, encoding='utf-8', capture_output=True, check=True, timeout=15)
    for name, book in json.loads(result.stdout):
        for index, cell in enumerate(book['cells']):
            if cell['type'] == 'code':
                yield f'template:{name}:{index}', cell['source']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    args = parser.parse_args()
    before, after = dict(sources(args.baseline)), dict(sources(ROOT))
    if before.keys() != after.keys():
        raise AssertionError('Asset source inventory changed')
    checked, changed, preserved_invalid = 0, 0, 0
    for label, old in before.items():
        new = after[label]
        try:
            old_ast = parse(old)
        except RuError:
            if not label.startswith('docs/language-review-tracker.md:') or old != new:
                raise AssertionError(f'Unexpected or changed invalid source: {label}')
            preserved_invalid += 1
            continue
        if semantic(old_ast) != semantic(parse(new)):
            raise AssertionError(f'AST changed: {label}')
        checked += 1
        changed += old != new
    print(f'AST equivalent: {checked}; punctuation-normalized: {changed}; unchanged historical invalid examples: {preserved_invalid}')


if __name__ == '__main__':
    main()
