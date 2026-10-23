"""Portable workflow contract; never actual compiler or performance evidence."""
from pathlib import Path
import hashlib,re,unittest
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.github/workflows/bootstrap-native.yml'
WORKFLOW=ROOT/'.github/workflows/bootstrap-slot-reuse.yml'

def validate(text):
    base=BASE.read_text(encoding='utf-8')
    assert hashlib.sha256(BASE.read_bytes()).hexdigest()=='54e49702a83c285899f0772ba38c9646650a5362283b600322bd3b8b7f143cf2'
    assert 'branches: [feature/bootstrap-slot-reuse-20261023]' in text
    assert 'cancel-in-progress: false' in text and 'fail-fast: false' in text
    assert text.count('timeout-minutes: 45')==1 and text.count('timeout-minutes: 60')==1
    assert 'continue-on-error:' not in text
    assert 'libLLVM17' not in text and 'dev_codegen' not in text
    checkout='      - name: Require exact isolated experiment checkout\n        run: python tools/verify_bootstrap_slot_ci.py checkout --directory bin/bootstrap/gui-ci\n'
    gui=text.split('  bootstrap-editor-gui:\n',1)[1].replace(checkout,'')
    permissions='    permissions:\n      contents: read\n      actions: read\n'
    assert gui.startswith(permissions) and text.count('actions: read')==1
    gui=gui[len(permissions):]
    start=gui.index('      - name: Checkout immutable old strategy')
    end=gui.index('      - name: Same-runner C control')
    extra=gui[start:end]
    assert hashlib.sha256(extra.encode()).hexdigest()=='7b50fd8d378e9ed5c2e36533d7603e2b7565fa580e908a245f7fbbec4becc73c'
    gui=gui[:start]+gui[end:]
    start=gui.index('          $threeExit = ')
    end=gui.index('      - name: Preserve JSON and logs only')
    extra=gui[start:end]
    assert hashlib.sha256(extra.encode()).hexdigest()=='8b761a6f2f63238e72bfac2f94c43cc2a5f810b577f8ef3fe61d9a0386b04fa6'
    gui=gui[:start]+gui[end:]
    expected=base.split('  bootstrap-editor-gui:\n',1)[1].replace('name: bootstrap-editor-gui-evidence-${{ github.sha }}','name: bootstrap-slot-editor-gui-evidence-${{ github.sha }}')
    # Only the three reviewed editor pins differ from the byte-frozen native workflow.
    assert expected.count('5a900a037cd54f4f89c3658e246195bbf3d389d3') == 2
    assert gui.count('90c87d2da6bf6b4e8814f7551f8ad6161b25d483') == 2
    expected = expected.replace('5a900a037cd54f4f89c3658e246195bbf3d389d3', '90c87d2da6bf6b4e8814f7551f8ad6161b25d483')
    assert expected.count('06eefc5de1fb864cbb7676e5950acc23752d53c5') == 1
    assert gui.count('1cd4b863714a705789ed095dbf83089dcec31310') == 1
    control = (ROOT/'tools/diagnose_bootstrap_slot_control.py').read_text(encoding='utf-8')
    assert re.search(r"^APP = '([0-9a-f]{40})'$", control, re.M).group(1) == '90c87d2da6bf6b4e8814f7551f8ad6161b25d483'
    assert re.search(r"^APP_TREE = '([0-9a-f]{40})'$", control, re.M).group(1) == '1cd4b863714a705789ed095dbf83089dcec31310'
    expected = expected.replace('06eefc5de1fb864cbb7676e5950acc23752d53c5', '1cd4b863714a705789ed095dbf83089dcec31310')
    assert gui==expected, 'GUI source pins, three-way diagnostic, budgets or artifact policy changed'
    commands=[line.strip()[5:] for line in text.splitlines() if line.startswith('        run: ')]
    for command in [
        'python tools/bootstrap.py verify --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_native_ci.py report --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_native_ci.py frontend --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_native_ci.py windows --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_slot_ci.py units --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_slot_ci.py runtime --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_slot_ci.py windows --directory bin/bootstrap/native-ci',
        'python tools/verify_bootstrap_slot_ci.py report --directory bin/bootstrap/native-ci',
    ]:
        assert commands.count(command)==1,command
    for tail in ('runtime','windows','report'):
        pattern='run: python tools/verify_bootstrap_slot_ci.py '+tail+' --directory bin/bootstrap/native-ci'
        assert pattern in text and pattern+' ||' not in text
    assert text.index('Create persistent evidence')<text.index('Slot runner fail-closed')<text.index('Build stage1, stage2, stage3')
    assert text.index('Required LLVM14 two-frontends')<text.index('Required ordinary Win64')<text.index('Require all new and original native gates')
    assert text.count('if: always()')==2
    assert 'path: language/bin/bootstrap/native-ci/' in text
    assert text.count('if-no-files-found: error')==2

class SlotWorkflowTests(unittest.TestCase):
    def test_full_workflow_contract(self):validate(WORKFLOW.read_text(encoding='utf-8'))
    def test_ordinary_and_existing_native_workflows_unchanged(self):
        self.assertEqual(hashlib.sha256((ROOT/'.github/workflows/ci.yml').read_bytes()).hexdigest(),'f111e88fa147054af11ad1f023c39b58ef2df4591e630ba4399eb48717a7af31')
        self.assertEqual(hashlib.sha256(BASE.read_bytes()).hexdigest(),'54e49702a83c285899f0772ba38c9646650a5362283b600322bd3b8b7f143cf2')
    def test_mutation_guards(self):
        source=WORKFLOW.read_text(encoding='utf-8')
        for old,new in [('1cd4b863714a705789ed095dbf83089dcec31310','06eefc5de1fb864cbb7676e5950acc23752d53c5'),('timeout-minutes: 45','timeout-minutes: 90'),('cancel-in-progress: false','cancel-in-progress: true'),('if: always()','if: success()'),('runtime --directory','runtime-optional --directory'),('90c87d2da6bf6b4e8814f7551f8ad6161b25d483','main'),('90c87d2da6bf6b4e8814f7551f8ad6161b25d483','5a900a037cd54f4f89c3658e246195bbf3d389d3'),('test_bootstrap_native_host.py','test_missing.py'),('actions: read','actions: write'),('persist-credentials: false','persist-credentials: true'),('$threeExit = $LASTEXITCODE','$threeExit = 0'),('6e03236c4fecf5a5219eb28a3ba1c46bfeb36d65','main')]:
            with self.subTest(old=old),self.assertRaises(AssertionError):validate(source.replace(old,new))

if __name__=='__main__':unittest.main()
