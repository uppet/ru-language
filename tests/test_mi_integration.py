"""Opt-in integration contracts frozen against main/wip ae1a994 (Ru 0.23.0)."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rulang.cli import build, make_parser
from rulang.compiler import Compiler
from rulang.frontend import RuError, parse
from rulang.js_compiler import JSCompiler


class MiIntegration(unittest.TestCase):
    def test_default_generated_outputs_match_pre_mi_baseline(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/mi-default-ae1a994.json').read_text(encoding='utf-8'))
        actual = [hashlib.sha256(cls(parse(source), '/fixed/example.ru').compile().encode()).hexdigest()
                  for source in fixture['sources'] for cls in (Compiler, JSCompiler)]
        self.assertEqual(actual, fixture['sha256'])

    def test_manifest_cannot_be_output_or_emit_c(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / 'main.ru'; entry.write_text('显 1.', encoding='utf-8')
            manifest = root / 'manifest.json'
            original = b'{"version":1,"functions":[]}'
            manifest.write_bytes(original)
            output = root / 'program'; output.write_bytes(b'previous binary')
            for destination in ('output', 'emit_c'):
                for alias in (manifest, root / '.' / 'manifest.json'):
                    with self.subTest(destination=destination, alias=str(alias)):
                        with patch('rulang.cli.subprocess.run') as invoked:
                            with self.assertRaises(RuError):
                                build(parse('显 1.'), entry, alias if destination == 'output' else output,
                                      emit_c=alias if destination == 'emit_c' else None,
                                      mi_manifest=manifest)
                            invoked.assert_not_called()
                        self.assertEqual(manifest.read_bytes(), original)
                        self.assertEqual(output.read_bytes(), b'previous binary')

    def test_non_c_manifest_is_rejected_before_tools(self):
        with patch('rulang.cli.subprocess.run') as invoked:
            with self.assertRaisesRegex(RuError, '仅支持 C'):
                build(parse('显 1.'), 'main.ru', 'program.js', target='js', mi_manifest='manifest.json')
            invoked.assert_not_called()

    def test_no_llvm_target_or_tool_requirement(self):
        parser = make_parser()
        options = {action.dest: action for action in parser._subparsers._group_actions[0].choices['build']._actions}
        self.assertEqual(tuple(options['target'].choices), ('c', 'js'))
        self.assertNotIn('llvm_clang', options)
        self.assertNotIn('emit_llvm', options)
        with self.assertRaises(RuError):
            Compiler(parse('显 1.'), mi_backend='llvm')
