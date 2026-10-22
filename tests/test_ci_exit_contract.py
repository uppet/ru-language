"""Guard Windows CI against native-command exit-code masking (stdlib only)."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
# These steps can run under the default Windows PowerShell shell. Keeping one
# native process per step lets the Actions wrapper propagate its exit status.
COMMANDS = {
    'Check LLVM tools': 'python -c "from rulang.llvm_toolchain import LLVMToolchain; print(LLVMToolchain().version)"',
    'Test LLVM environment': 'python -m unittest discover -s tests -p test_toolchain_environment.py -v',
    'Test bootstrap verifier': 'python -m unittest discover -s tests -p test_bootstrap_verifier.py -v',
    'Test workspace preparation': 'python -m unittest discover -s tests -p test_prepare_workspace.py -v',
    'Test native LLVM AOT': 'python -m unittest discover -s tests -p test_llvm.py -v',
    'Verify Ru self-compilation': 'python tools/bootstrap.py verify',
    'Test AOT interpreter host': 'python -m unittest discover -s tests -p test_interpreter_host.py -v',
    'Test AOT notebook sessions': 'python -m unittest discover -s tests -p test_rushu_native.py -v',
    'Test direct LLVM Mi kernels': 'python -m unittest discover -s tests -p test_mi_llvm.py -v',
    'Test Mi UTF8 owner bridges': 'python -m unittest discover -s tests -p test_mi_utf8.py -v',
    'Check Windows C compiler': 'gcc --version',
    'Check Windows Node.js': 'node --version',
    'Run Windows regression shard': 'python tools/run_test_shard.py --shard ${{ matrix.shard }} --count 3 --failfast',
}

COMMANDS.update({'Checked source and differential kernels': 'python experiments/mi_source/test_source.py', 'Real NativeMemory owner and failure cleanup': 'python experiments/mi_borrow/test_bridge.py', 'Historical kernel regression': 'python experiments/mi_kernel/test_kernel.py', 'UTF8 caller and synchronous native callback': 'python -m unittest discover -s tests -p test_mi_utf8_c.py -v', 'CLI protection and default output contract': 'python -m unittest discover -s tests -p test_mi_integration.py -v'})

GIT_BASH_JOB = """  windows-git-bash-bootstrap:
    # Keep this second full bootstrap independent of the LLVM acceptance budget.
    runs-on: windows-latest
    timeout-minutes: 20
    env:
      PYTHONUTF8: "1"
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.10"
      - name: Bootstrap from Windows Git Bash with POSIX search paths
        shell: bash
        run: |
          export INCLUDE='C:/msys64/usr/include/:C:/msys64/include/:'
          export LIB='C:/msys64/usr/lib/:'
          export CPATH='/usr/include:/mingw64/include'
          unset PYTHONUTF8 PYTHONIOENCODING
          python tools/prepare_workspace.py --with-llvm
          python tools/bootstrap.py verify --directory bin/bootstrap/git-bash
          python tools/bootstrap.py build examples/hello.ru --compiler bin/bootstrap/git-bash/stage3.exe -o bin/hello-git-bash.exe
          ./bin/hello-git-bash.exe
          python tools/build_rushu_kernel.py --compiler bin/bootstrap/git-bash/stage3.exe -o bin/rushu/git-bash-kernel.exe
          ./bin/rushu/git-bash-kernel.exe examples/factorial.ru
"""


def check_git_bash_contract(source):
    """Pin the standalone Windows path-variant acceptance job, not just its name."""
    marker = "  windows-git-bash-bootstrap:\n"
    if source.count(marker) != 1:
        raise AssertionError("missing or duplicate Git Bash acceptance job")
    body = re.split(r"^  [a-zA-Z]", source.split(marker, 1)[1], maxsplit=1, flags=re.MULTILINE)[0]
    if marker + body != GIT_BASH_JOB:
        raise AssertionError("Git Bash acceptance setup, budget, shell and commands must be preserved")


def check_contract(source):
    """Deliberately narrow format check, not a general-purpose YAML parser."""
    for name, command in COMMANDS.items():
        marker = '      - name: ' + name + '\n'
        if source.count(marker) != 1:
            raise AssertionError('missing or duplicate isolated step: ' + name)
        body = source.split(marker, 1)[1]
        body = re.split(r'^      - |^  [a-zA-Z]', body, maxsplit=1, flags=re.MULTILINE)[0]
        run = re.search(r'^        run: (.+)$', body, re.MULTILINE)
        if not run or run.group(1) != command:
            raise AssertionError('native command must be isolated: ' + name)
        if 'continue-on-error:' in body or re.search(r'^        (if|shell):', body, re.MULTILINE):
            raise AssertionError('required step cannot hide or skip failure: ' + name)


class CIExitContractTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')

    def test_required_windows_commands_are_separate_failing_steps(self):
        check_contract(self.source)

    def test_failure_followed_by_success_is_rejected_for_every_required_step(self):
        # Negative control: reintroduce exactly the risky shape, including in
        # the Mi and AOT notebook steps. A later exit(0) must not pass the guard.
        for name, command in COMMANDS.items():
            with self.subTest(step=name):
                marker = '      - name: ' + name + '\n'
                before, after = self.source.split(marker, 1)
                after = after.replace('        run: ' + command,
                    '        run: |\n          python -c "raise SystemExit(23)"\n'
                    '          python -c "raise SystemExit(0)"', 1)
                with self.assertRaisesRegex(AssertionError, 'must be isolated'):
                    check_contract(before + marker + after)

    def test_only_wrapper_negative_control_tolerates_failure(self):
        settings = re.findall(r'^\s*continue-on-error:.*$', self.source, re.MULTILINE)
        self.assertEqual(settings, ['        continue-on-error: true'])
        wrapper, acceptance = self.source.split('  test:\n', 1)
        self.assertIn('id: expected_failure', wrapper)
        self.assertIn('steps.expected_failure.outcome', wrapper)
        self.assertIn('steps.expected_failure.conclusion', wrapper)
        self.assertIn('steps.later_success.outcome', wrapper)
        self.assertIn('steps.later_success.conclusion', wrapper)
        self.assertNotIn('continue-on-error:', acceptance)

    def test_git_bash_acceptance_is_independent_and_fail_fast(self):
        # Explicit shell: bash uses Actions' -e -o pipefail wrapper. Unlike
        # PowerShell, this multi-command step stops at the first failed process.
        check_git_bash_contract(self.source)

    def test_git_bash_acceptance_mutations_are_rejected(self):
        mutations = [
            self.source.replace(GIT_BASH_JOB, ''),
            self.source.replace(GIT_BASH_JOB, GIT_BASH_JOB + GIT_BASH_JOB),
        ]
        for old, new in [
            ('timeout-minutes: 20', 'timeout-minutes: 30'),
            ('runs-on: windows-latest', 'runs-on: ubuntu-22.04'),
            ('python-version: "3.10"', 'python-version: "3.14"'),
            ('shell: bash', 'shell: pwsh'),
            ('        run: |', '        continue-on-error: true\n        run: |'),
            ('    steps:', '    if: false\n    steps:'),
            ('        shell: bash', '        if: false\n        shell: bash'),
            ('export CPATH=', '# export CPATH='),
            ('unset PYTHONUTF8 PYTHONIOENCODING', 'echo keep encodings'),
        ]:
            mutations.append(self.source.replace(GIT_BASH_JOB, GIT_BASH_JOB.replace(old, new)))
        # Every actual native command is required, including the preparation,
        # stage3 example and notebook kernel executions after self-compilation.
        for line in GIT_BASH_JOB.splitlines(keepends=True):
            if line.startswith(('          python ', '          ./bin/')):
                mutations.append(self.source.replace(GIT_BASH_JOB, GIT_BASH_JOB.replace(line, '')))
        for index, unsafe in enumerate(mutations):
            with self.subTest(mutation=index):
                self.assertNotEqual(unsafe, self.source)
                with self.assertRaises(AssertionError):
                    check_git_bash_contract(unsafe)

    def test_required_steps_cannot_continue_on_error(self):
        for name in COMMANDS:
            with self.subTest(step=name):
                marker = '      - name: ' + name + '\n'
                unsafe = self.source.replace(marker, marker + '        continue-on-error: true\n', 1)
                with self.assertRaisesRegex(AssertionError, 'cannot hide'):
                    check_contract(unsafe)

class MiPrototypePublicationContractTests(unittest.TestCase):
    def test_full_integration_and_mainline_run_exact_generation_checks(self):
        source = (ROOT / '.github/workflows/mi-kernel-prototype.yml').read_text(encoding='utf-8')
        self.assertIn('branches: [mi-perf-prototype, bs, wip, main, "feature/bs-full-integration-*"]', source)
        self.assertIn('branches: [bs, wip, main]', source)
        for command in (
            'python experiments/mi_kernel/generate.py',
            'git diff --exit-code -- experiments/mi_kernel/generated',
            'python experiments/mi_kernel/generate.py --manifest experiments/mi_source/manifest.json --entry experiments/mi_source/caller.ru',
            'git diff --exit-code -- experiments/mi_source/generated',
            'python experiments/mi_kernel/verify_baseline.py',
        ):
            self.assertIn('        run: ' + command + '\n', source)
        self.assertNotIn('continue-on-error:', source)


if __name__ == '__main__':
    unittest.main()
