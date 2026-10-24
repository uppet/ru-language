"""Physical control-character keys must survive source integration unchanged."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTROLS = (*range(1, 9), 11, 12, *range(14, 32))


def validate_escape_tables(source):
    # splitlines also treats VT/FF/record separators as line boundaries: it is
    # forbidden here because those characters are literal dictionary keys.
    physical_lines = source.split('\n')
    for prefix, width in (('LLVM转义 取 ', 2), ('C转义 取 ', 3)):
        rows = [line for line in physical_lines if line.startswith(prefix)]
        if len(rows) != 1:
            raise ValueError('escape table must occupy one physical line')
        for number in CONTROLS:
            digits = format(number, '02X') if width == 2 else format(number, '03o')
            expected = "'" + chr(number) + "':'" + '\\\\' + digits + "'"
            if rows[0].count(expected) != 1:
                raise ValueError('missing exact escape for ' + str(number))


class NativeIntegrationByteTests(unittest.TestCase):
    def test_control_escape_tables_preserve_literal_keys(self):
        validate_escape_tables((ROOT/'bootstrap/compiler.ru').read_text(encoding='utf-8'))

    def test_splitlines_rewrite_is_rejected(self):
        source = (ROOT/'bootstrap/compiler.ru').read_text(encoding='utf-8')
        corrupted = '\n'.join(source.splitlines()) + '\n'
        with self.assertRaises(ValueError):
            validate_escape_tables(corrupted)


if __name__ == '__main__':
    unittest.main()
