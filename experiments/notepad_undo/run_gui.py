"""Run the original notepad Markdown GUI gate against an isolated runtime copy."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

BASE = 'd964ea9f7e27065aa5bbcced8d6c7526a6224dd1'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--app-root', required=True, type=Path)
    ap.add_argument('--binary-dir', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    if sys.platform != 'win32': ap.error('actual Windows GUI execution required')
    app, binary, work = args.app_root.resolve(), args.binary_dir.resolve(), args.output.resolve()
    runner = app/'tools/windows_ci.py'
    original = subprocess.check_output(['git','-C',str(app),'show',BASE+':tools/windows_ci.py'])
    assert runner.read_bytes() == original, 'the original GUI gate must remain unchanged'
    work.mkdir(parents=True, exist_ok=False)
    fixtures, evidence, inputs = (work/name for name in ('fixtures', 'evidence', 'input'))
    for p in (fixtures, evidence, inputs): p.mkdir()
    sys.path.insert(0, str(app/'tools'))
    spec = importlib.util.spec_from_file_location('notepad_original_gate', runner)
    ci = importlib.util.module_from_spec(spec); spec.loader.exec_module(ci)
    hashes = {}
    for name in ci.portable.RUNTIME_NAMES:
        shutil.copyfile(binary/name, inputs/name)
        hashes[name] = hashlib.sha256((inputs/name).read_bytes()).hexdigest()
    started = time.monotonic()
    result = ci.run_gui_markdown(ci.Windows(), inputs, fixtures, evidence)
    result.update(process_wall_seconds=time.monotonic()-started, runtime_sha256=hashes,
                  original_gui_gate_sha256=hashlib.sha256(original).hexdigest(),
                  application_base=BASE,
                  full_product_acceptance=False)
    assert all(hashlib.sha256((inputs/n).read_bytes()).hexdigest() == h for n,h in hashes.items())
    (work/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed':result.get('passed'),'error':result.get('error'),
                     'cases':[{'kind':c['kind'],'stages':[{k:s.get(k) for k in ('operation','wall_ms','undo_commands')}
                                                       for s in c['stages']]}
                              for c in result.get('markdown_performance',{}).get('cases',[])]},
                     ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get('passed') else 1)


if __name__ == '__main__': main()
