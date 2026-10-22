"""Guard Windows CI against native-command exit-code masking (stdlib only)."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
# These steps can run under the default Windows PowerShell shell. Keeping one
# native process per step lets the Actions wrapper propagate its exit status.
COMMANDS = {'Check Windows C compiler': 'gcc --version', 'Check Windows Node.js': 'node --version', 'Run Windows regression shard': 'python tools/run_test_shard.py --shard ${{ matrix.shard }} --count 3 --failfast', 'Checked source and differential kernels': 'python experiments/mi_source/test_source.py', 'Real NativeMemory owner and failure cleanup': 'python experiments/mi_borrow/test_bridge.py', 'Historical kernel regression': 'python experiments/mi_kernel/test_kernel.py', 'UTF8 caller and synchronous native callback': 'python -m unittest discover -s tests -p test_mi_utf8_c.py -v', 'CLI protection and default output contract': 'python -m unittest discover -s tests -p test_mi_integration.py -v'}


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

    def test_required_steps_cannot_continue_on_error(self):
        for name in COMMANDS:
            with self.subTest(step=name):
                marker = '      - name: ' + name + '\n'
                unsafe = self.source.replace(marker, marker + '        continue-on-error: true\n', 1)
                with self.assertRaisesRegex(AssertionError, 'cannot hide'):
                    check_contract(unsafe)


if __name__ == '__main__':
    unittest.main()
