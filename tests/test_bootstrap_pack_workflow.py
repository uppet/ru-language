"""Rebuilt pack workflow contracts; no prior local/real-CI result is inherited."""
import ast
import hashlib
from pathlib import Path
import re
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import bootstrap_pack_artifact as loader

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT/'.github/workflows/bootstrap-argument-pack.yml'
BASE = ROOT/'.github/workflows/bootstrap-slot-address.yml'
OLD_HASHES = {
    'bootstrap-native.yml':'54e49702a83c285899f0772ba38c9646650a5362283b600322bd3b8b7f143cf2',
    'bootstrap-slot-address.yml':'5b0b23093dba17f1d620f2aa3d12ddb0b4ad620ccee7b844d8a7801e33e6b1f0',
    'bootstrap-slot-reuse.yml':'6d9d9ce7cd21cd4bfcf28cbf63fcb3bed7c8dfb3e2f679e7f82bab19cc40c307',
    'ci.yml':'f111e88fa147054af11ad1f023c39b58ef2df4591e630ba4399eb48717a7af31',
    'mi-kernel-prototype.yml':'243339bad95f1707276d0365551c1fc5eb7ef0a580ad732827b147d04f679c55',
}


def job(text, name):
    found = re.search(r'^  '+re.escape(name)+r':\n(.*?)(?=^  [a-z][a-z-]+:\n|\Z)', text, re.M | re.S)
    if not found:
        raise ValueError('required job missing: '+name)
    return found[1]


def python_snippet(text, step):
    section = text.split('      - name: '+step+'\n', 1)[1].split('      - name:', 1)[0]
    return textwrap.dedent(section.split("          @'\n", 1)[1].split("          '@ | python -", 1)[0])


def parent_code(text):
    return python_snippet(text, 'Prepare only the fixed compiler artifact parent with reparse guards')


def expected_gui():
    text = job(BASE.read_text(encoding='utf-8'), 'bootstrap-editor-gui')
    start = text.index('      - name: Checkout immutable old strategy source only for fourth diagnostic\n')
    end = text.index('      - name: Same-runner C control versus bootstrap fixture diagnostic only\n', start)
    text = text[:start]+text[end:]
    start = text.index('          $threeExit = $LASTEXITCODE\n')
    end = text.index('      - name: Preserve JSON and logs only, never runtime binaries or packages\n', start)
    text = text[:start]+'          if ($LASTEXITCODE) { exit $LASTEXITCODE }\n'+text[end:]
    return text.replace('tools/verify_bootstrap_slot_ci.py checkout', 'tools/verify_bootstrap_pack_ci.py checkout').replace(
        'name: bootstrap-slot-editor-gui-evidence-', 'name: bootstrap-pack-editor-gui-evidence-')


def validate(text):
    def require(ok, reason):
        if not ok:
            raise ValueError(reason)
    require('branches: [feature/bootstrap-argument-pack-20261023]' in text and
            'workflow_dispatch:' not in text and 'pull_request:' not in text, 'push-only exact branch required')
    names = re.findall(r'^  ([a-z][a-z-]+):$', text.split('jobs:\n', 1)[1], re.M)
    require(names == ['pack-bootstrap', 'bootstrap-editor-gui', 'pack-measurement'], 'exact job inventory')
    for forbidden in ('continue-on-error:', 'cancel-in-progress: true', 'contents: write', 'actions: write',
                      'persist-credentials: true', 'libLLVM17', 'dev_codegen', '--emit-c-via-gcc'):
        require(forbidden not in text, 'scope weakened: '+forbidden)
    require(all(re.fullmatch(r'[a-f0-9]{40}', value) for value in re.findall(r'uses: [^\s@]+@([^\s]+)', text)),
            'action SHA must remain pinned')
    for name, minutes in [('pack-bootstrap',45),('bootstrap-editor-gui',60),('pack-measurement',75)]:
        body = job(text, name)
        require(re.findall(r'timeout-minutes: (\d+)', body) == [str(minutes)], 'original job budget required')
    core = job(text, 'pack-bootstrap')
    required = [
        'python tools/verify_bootstrap_slot_ci.py units --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_pack_ci.py units --directory bin/bootstrap/native-ci',
        'python -m unittest discover -s tests -p test_bootstrap_native_host.py -v',
        'python -m unittest discover -s tests -p test_bootstrap_native_ci.py -v',
        'python tools/bootstrap.py verify --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_native_ci.py report --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_native_ci.py frontend --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_native_ci.py windows --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_slot_ci.py runtime --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_slot_ci.py windows --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_slot_ci.py report --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_pack_ci.py runtime --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_pack_ci.py windows --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_pack_ci.py report --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_native_ci.py editor --directory bin/bootstrap/native-ci --editor-root ../editor',
    ]
    require(all(core.count(command)==1 for command in required), 'required complete acceptance commands missing/duplicated')
    require([core.index(command) for command in required] == sorted(core.index(command) for command in required),
            'acceptance stage order changed')
    require('os: [ubuntu-22.04, windows-latest]' in core and 'fail-fast: false' in core, 'two real hosts required')
    full = core.split('      - name: Preserve native build identities and partial evidence\n',1)[1].split('      - name:',1)[0]
    require('if: always()' in full and 'path: language/bin/bootstrap/native-ci/' in full and
            'if-no-files-found: error' in full, 'original full partial-evidence artifact required')
    require('name: bootstrap-pack-windows-latest-${{ github.sha }}' in core and
            'path: ${{ runner.temp }}/bootstrap-pack-compiler-bundle/' in core, 'separate bounded compiler bundle required')
    preflight = python_snippet(text, 'Preflight bounded current compiler and pack evidence bundle')
    for token in ('loader.CURRENT_CORE','len(names) <= 512','loader.MAX_EXPANDED','loader.MAX_MEMBER',
                  'loader.extract_core(raw.getvalue(), current=True)','loader.validate_pack_bundle(files, identity)',
                  "path.open('xb')",'loader.no_links(source); loader.no_links(parent)',
                  "loader.read_fixed(source/name,loader.MAX_MEMBER)==data", "loader.read_fixed(output/name,loader.MAX_MEMBER)==data"):
        require(token in preflight, 'bundle safeguard missing: '+token)
    require(job(text,'bootstrap-editor-gui') == expected_gui(), 'existing GUI acceptance or three-route diagnostic changed')
    measure = job(text, 'pack-measurement')
    for token in ('needs: [pack-bootstrap, bootstrap-editor-gui]', 'actions: read',
                  'ref: 46c81ccfde815b8917be9107288b9a80b08758c9',
                  "'tree':'19c4199f3381bca19be01d5e703ef0b691ec7f8b'",
                  'EDITOR_COMMIT: 2cb3b8c81ba300745b244c51b50d5625430fbe4f',
                  'EDITOR_TREE: 5c63f94cd9e3816608cc95b834f91428bbeb3c49',
                  'from tools.bootstrap_pack_build import MEASUREMENT_INPUTS', 'names = MEASUREMENT_INPUTS',
                  'python tools/bootstrap_pack_artifact.py old --output',
                  'python tools/bootstrap_pack_artifact.py current --output',
                  'python tools/bootstrap_pack_build.py --config', 'python tools/measure_bootstrap_packs.py --prepared',
                  'strict 600 second aggregate watchdog', 'all eighteen fixed 60 second',
                  'if: always()', '**/*.json', '**/*.log'):
        require(token in measure, 'measurement contract missing: '+token)
    require(measure.count('GITHUB_TOKEN:')==1 and 'bootstrap.py verify' not in measure and
            '**/*.exe' not in measure, 'measurement scope widened')
    code = parent_code(text)
    for token in ("parent = Path.cwd() / 'bin' / 'bootstrap'", "output = parent / 'pack-current'",
                  'loader.no_links(ancestor)', 'loader.no_links(parent)',
                  'parent.mkdir(parents=True, exist_ok=True)', 'not output.exists() and not output.is_symlink()'):
        require(token in code, 'parent guard missing: '+token)
    require(text.index('Prepare only the fixed compiler artifact parent') < text.index('Download exact old46c'),
            'artifact parent prepared too late')


class PackWorkflowTests(unittest.TestCase):
    def test_final_workflow_contract(self):
        validate(WORKFLOW.read_text(encoding='utf-8'))

    def test_original_workflows_are_unchanged(self):
        for name, expected in OLD_HASHES.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((BASE.parent/name).read_bytes()).hexdigest(), expected)

    def test_budget_scope_and_gate_mutations_are_rejected(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        for old,new in [('timeout-minutes: 45','timeout-minutes: 90'),('timeout-minutes: 60','timeout-minutes: 90'),
                        ('timeout-minutes: 75','timeout-minutes: 90'),('actions: read','actions: write'),
                        ('needs: [pack-bootstrap, bootstrap-editor-gui]','needs: pack-bootstrap'),
                        ('if: always()','if: success()'),('persist-credentials: false','persist-credentials: true'),
                        ('verify_bootstrap_pack_ci.py runtime','verify_bootstrap_pack_ci.py units'),
                        ('46c81ccfde815b8917be9107288b9a80b08758c9','main'),
                        ('len(names) <= 512','len(names) <= 999'),('loader.validate_pack_bundle(files, identity)','pass'),
                        ('loader.no_links(ancestor)','pass'),('names = MEASUREMENT_INPUTS','names = []')]:
            with self.subTest(old=old), self.assertRaises(ValueError):
                validate(text.replace(old,new))

    def test_all_inline_python_parses(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        blocks = re.findall(r"          @'\n(.*?)          '@ \| python -", text, re.S)
        self.assertGreater(len(blocks), 5)
        for index, code in enumerate(blocks):
            with self.subTest(index=index): ast.parse(textwrap.dedent(code))

    def test_parent_creates_only_fixed_fresh_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with patch.object(Path,'cwd',return_value=root):
                exec(parent_code(WORKFLOW.read_text(encoding='utf-8')), {})
            self.assertTrue((root/'bin/bootstrap').is_dir())
            self.assertFalse((root/'bin/bootstrap/pack-current').exists())

    def test_parent_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); output = root/'bin/bootstrap/pack-current'; output.mkdir(parents=True)
            with patch.object(Path,'cwd',return_value=root), self.assertRaises(RuntimeError):
                exec(parent_code(WORKFLOW.read_text(encoding='utf-8')), {})

    def test_parent_refuses_reparse_ancestor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); (root/'bin').mkdir(); original = Path.lstat
            def lstat(path,*args,**kwargs):
                info = original(path,*args,**kwargs)
                return SimpleNamespace(st_mode=info.st_mode,st_file_attributes=0x400) if path==root/'bin' else info
            with patch.object(Path,'cwd',return_value=root), patch.object(Path,'lstat',lstat), self.assertRaises(RuntimeError):
                exec(parent_code(WORKFLOW.read_text(encoding='utf-8')), {})
            self.assertFalse((root/'bin/bootstrap').exists())


if __name__ == '__main__':
    unittest.main()
