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

    def test_required_steps_cannot_continue_on_error(self):
        for name in COMMANDS:
            with self.subTest(step=name):
                marker = '      - name: ' + name + '\n'
                unsafe = self.source.replace(marker, marker + '        continue-on-error: true\n', 1)
                with self.assertRaisesRegex(AssertionError, 'cannot hide'):
                    check_contract(unsafe)


if __name__ == '__main__':
    unittest.main()
