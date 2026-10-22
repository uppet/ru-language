"""Freeze the reviewed isolated job contract with stdlib only, not a YAML parser.

This deliberately accepts only the tiny, single-line-run YAML form below.
Unknown controls/steps fail closed; ordinary workflows are outside this scope.
GitHub remains the actual workflow parser; these are portable policy negatives,
not proof of remote execution or new-stage3 LLVM14 acceptance.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/bootstrap-dense.yml'
EXPECTED_HEADER = "name: Bootstrap dense isolated core acceptance\non:\n  push:\n    branches: [feature/bootstrap-dense-20261022]\n  workflow_dispatch:\npermissions:\n  contents: read\nconcurrency:\n  group: ${{ github.workflow }}-${{ github.ref }}\n  cancel-in-progress: false\njobs:\n  dense-bootstrap-core:\n    runs-on: ${{ matrix.os }}\n    timeout-minutes: 75\n    strategy:\n      fail-fast: false\n      matrix:\n        os: [ubuntu-22.04, windows-latest]\n    defaults:\n      run:\n        working-directory: language\n    env:\n      PYTHONUTF8: '1'\n      CC: gcc\n      GIT_CONFIG_COUNT: '1'\n      GIT_CONFIG_KEY_0: core.autocrlf\n      GIT_CONFIG_VALUE_0: 'false'"

INIT_CODE = "import json,os; from pathlib import Path; p=Path('bin/bootstrap/dense-ci'); p.mkdir(parents=True,exist_ok=True); (p/'preflight-diagnostics.json').write_text(json.dumps({'scope':'diagnostics-only','head_sha':os.environ.get('GITHUB_SHA'),'run_id':os.environ.get('GITHUB_RUN_ID')})+'\\n',encoding='utf-8')"
UNIT_CODE = "import hashlib,json,subprocess,sys; from pathlib import Path; p=Path('bin/bootstrap/dense-ci'); p.mkdir(parents=True,exist_ok=True); r=subprocess.run([sys.executable,'-m','unittest','tests.test_bootstrap_native_host','tests.test_bootstrap_dense_host','tests.test_bootstrap_native_ci','tests.test_bootstrap_dense_ci','tests.test_bootstrap_dense_runtime_gate','tests.test_bootstrap_dense_fixture_portability','tests.test_bootstrap_dense_workflow','-v'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT); (p/'host-units.log').write_bytes(r.stdout); (p/'host-units-diagnostics.json').write_text(json.dumps({'scope':'diagnostics-only','returncode':r.returncode,'log_sha256':hashlib.sha256(r.stdout).hexdigest(),'argv':r.args})+'\\n',encoding='utf-8'); sys.stdout.buffer.write(r.stdout); sys.exit(r.returncode)"

EXPECTED_STEPS = [{'name': 'Exact immutable candidate checkout',
  'uses': 'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1',
  'with': {'ref': '${{ github.sha }}', 'path': 'language', 'persist-credentials': 'false'}},
 {'name': 'Python for bootstrap host and test orchestration',
  'uses': 'actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97',
  'with': {'python-version': '3.10'}},
 {'name': 'Initialize diagnostics before toolchain and unit gates',
  'run': 'python -c \"'+INIT_CODE+'\"'},
 {'name': 'Require dedicated branch and exact checked out commit',
  'run': 'python -c "import os,subprocess,sys; sys.exit(0 if '
         "os.environ['GITHUB_REF']=='refs/heads/feature/bootstrap-dense-20261022' and "
         "subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==os.environ['GITHUB_SHA'] "
         'else \'wrong dense branch/commit\')"'},
 {'name': 'Install Linux LLVM 14',
  'if': "runner.os == 'Linux'",
  'run': 'sudo apt-get update && sudo apt-get install --no-install-recommends -y clang-14 llvm-14'},
 {'name': 'Prepare pinned project-local Windows LLVM 14',
  'if': "runner.os == 'Windows'",
  'run': 'python tools/prepare_workspace.py --with-llvm'},
 {'name': 'Require independent C fixture compiler', 'run': 'gcc --version'},
 {'name': 'Require complete matching LLVM14 toolchain',
  'run': 'python -c "from tools.verify_bootstrap_dense_ci import toolchain_identity; '
         'print(toolchain_identity())"'},
 {'name': 'Host and fail-closed evidence checker unit contracts',
  'run': 'python -c \"'+UNIT_CODE+'\"'},
 {'name': 'Fresh stage1 stage2 stage3 and existing complete M4 suite',
  'run': 'python tools/bootstrap.py verify --directory bin/bootstrap/dense-ci'},
 {'name': 'Require 105 actual passes zero skips and all fixed points',
  'run': 'python tools/verify_bootstrap_native_ci.py report --directory bin/bootstrap/dense-ci'},
 {'name': 'Existing required stage3 native frontend regressions',
  'run': 'python tools/verify_bootstrap_native_ci.py frontend --directory bin/bootstrap/dense-ci'},
 {'name': 'Existing real Windows DLL callback GC owner regressions',
  'if': "runner.os == 'Windows'",
  'run': 'python tools/verify_bootstrap_native_ci.py windows --directory bin/bootstrap/dense-ci'},
 {'name': 'Required new-stage3 dense frontend 15 cases',
  'run': 'python tools/verify_bootstrap_dense_ci.py frontend --directory bin/bootstrap/dense-ci'},
 {'name': 'Required actual LLVM14 shared applications 6 cases',
  'run': 'python tools/verify_bootstrap_dense_ci.py runtime --directory bin/bootstrap/dense-ci'},
 {'name': 'Required real Windows combined native dense callback 2 cases',
  'if': "runner.os == 'Windows'",
  'run': 'python tools/verify_bootstrap_dense_ci.py windows --directory bin/bootstrap/dense-ci'},
 {'name': 'Require all per-case source tool and artifact identities',
  'run': 'python tools/verify_bootstrap_dense_ci.py report --directory bin/bootstrap/dense-ci'},
 {'name': 'Preserve all core identities and partial failed evidence',
  'if': 'always()',
  'uses': 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02',
  'with': {'name': 'bootstrap-dense-${{ matrix.os }}-${{ github.sha }}',
           'path': 'language/bin/bootstrap/dense-ci/',
           'if-no-files-found': 'error',
           'retention-days': '14'}}]


def validate_workflow(text):
    def require(ok, message):
        if not ok:
            raise ValueError(message)
    require(text.count('    steps:\n') == 1, 'one isolated job required')
    header, body = text.split('    steps:\n')
    header = '\n'.join(line.rstrip() for line in header.splitlines()
                       if line.strip() and not line.lstrip().startswith('#'))
    require(header == EXPECTED_HEADER, 'isolated trigger/matrix/budget/environment changed')
    require(body.startswith('      - name: '), 'all steps must be named')
    chunks = re.split(r'(?m)^      - name: ', body)[1:]
    steps = []
    for chunk in chunks:
        lines = chunk.splitlines()
        step = {'name': lines[0]}
        within = False
        for line in lines[1:]:
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            match = re.fullmatch(r'( {8}| {10})([a-z][a-z0-9-]*):(?: (.+))?', line)
            require(match is not None, 'unexpected control/indentation/multiline script')
            indent, key, value = match.groups()
            if value and value[:1] in ("'", '"') and value[-1:] == value[:1]:
                value = value[1:-1]
            if len(indent) == 8:
                require(key in ('if','run','uses','with') and key not in step,
                        'unknown or duplicate step control')
                within = key == 'with'
                if within:
                    require(value is None, 'with must be a mapping')
                    step[key] = {}
                else:
                    require(value is not None, 'empty step control')
                    step[key] = value.split(' #',1)[0] if key == 'uses' else value
            else:
                require(within and key not in step['with'] and value is not None,
                        'unexpected nested control')
                step['with'][key] = value
        steps.append(step)
    require(steps == EXPECTED_STEPS, 'required commands/actions/order/conditions/evidence changed')


class DenseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding='utf-8')

    def reject(self, old, new):
        self.assertIn(old, self.text)
        with self.assertRaises(ValueError):
            validate_workflow(self.text.replace(old,new,1))

    def test_unit_diagnostics_preserve_raw_bytes_and_child_exit(self):
        for code in (0, 3):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                payload = '诊断\r\n'.encode('utf-8')
                (root/'unittest.py').write_text(
                    'import sys; sys.stdout.buffer.write('+repr(payload)+'); sys.exit('+str(code)+')',
                    encoding='utf-8')
                result = subprocess.run([sys.executable, '-c', UNIT_CODE], cwd=root,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(result.stdout, payload)
                evidence = root/'bin/bootstrap/dense-ci'
                self.assertEqual((evidence/'host-units.log').read_bytes(), payload)
                report = json.loads((evidence/'host-units-diagnostics.json').read_bytes())
                self.assertEqual(report['scope'], 'diagnostics-only')
                self.assertEqual(report['returncode'], code)
                self.assertEqual(report['log_sha256'], hashlib.sha256(payload).hexdigest())
                self.assertEqual(report['argv'][0:3], [sys.executable, '-m', 'unittest'])

    def test_initial_diagnostics_exist_before_any_compiler(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            result = subprocess.run([sys.executable, '-c', INIT_CODE], cwd=root,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((root/'bin/bootstrap/dense-ci/preflight-diagnostics.json').read_bytes())
            self.assertEqual(report['scope'], 'diagnostics-only')
            self.assertNotIn('complete', report)

    def test_diagnostics_cannot_mask_exit_or_be_late(self):
        self.reject('sys.exit(r.returncode)', 'sys.exit(0)')
        self.reject('Initialize diagnostics before toolchain and unit gates', 'Initialize diagnostics after gates')

    def test_reviewed_core_workflow(self):
        validate_workflow(self.text)

    def test_workflow_and_policy_are_bound_in_every_dense_report(self):
        from tools.verify_bootstrap_dense_ci import evidence_inputs
        for kind in ('frontend','runtime','windows'):
            inputs = evidence_inputs(kind)
            self.assertIn('.github/workflows/bootstrap-dense.yml', inputs)
            self.assertIn('tests/test_bootstrap_dense_workflow.py', inputs)

    def test_missing_required_gate_rejected(self):
        self.reject('verify_bootstrap_dense_ci.py runtime', 'verify_bootstrap_dense_ci.py frontend')

    def test_development_adapter_rejected(self):
        self.reject('verify_bootstrap_dense_ci.py runtime --directory bin/bootstrap/dense-ci',
                    '-m unittest tests.test_bootstrap_dense_execution')

    def test_tolerated_failure_or_skipped_gate_rejected(self):
        self.reject('      - name: Required actual LLVM14 shared applications 6 cases',
                    "      - name: Required actual LLVM14 shared applications 6 cases\n        if: false")
        self.reject('        run: gcc --version',
                    '        continue-on-error: true\n        run: gcc --version')

    def test_trigger_matrix_budget_changes_rejected(self):
        self.reject('branches: [feature/bootstrap-dense-20261022]', 'branches: [wip]')
        self.reject('os: [ubuntu-22.04, windows-latest]', 'os: [ubuntu-22.04]')
        self.reject('timeout-minutes: 75', 'timeout-minutes: 15')

    def test_unpinned_or_external_checkout_rejected(self):
        self.reject('actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1',
                    'actions/checkout@main')
        self.reject('          path: language',
                    '          path: language\n          repository: other/editor')

    def test_failed_evidence_upload_cannot_be_omitted(self):
        self.reject('        if: always()', '        if: success()')
        self.reject('          if-no-files-found: error', '          if-no-files-found: ignore')

    def test_later_native_success_cannot_mask_failure(self):
        self.reject('        run: gcc --version', '        run: gcc --version; python -c "exit(0)"')

    def test_extra_job_rejected(self):
        with self.assertRaises(ValueError):
            validate_workflow(self.text+'\n  unrelated-job:\n    runs-on: ubuntu-latest\n')
