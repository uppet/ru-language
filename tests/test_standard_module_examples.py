"""Current examples use canonical import names; saved user books are not rewritten."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
OLD_IMPORT = re.compile(r'''外言\s*(['"])(?:如观|如竞|如:竞赛)\1''')


class StandardModuleExampleTests(unittest.TestCase):
    def test_current_repository_sources_use_canonical_imports(self):
        paths = []
        for directory in ('examples', 'rushu/examples', 'tests/fixtures'):
            paths.extend((ROOT / directory).rglob('*.ru'))
            paths.extend((ROOT / directory).rglob('*.rushu.json'))
        self.assertTrue(paths)
        seen = set()
        for path in paths:
            with self.subTest(path=str(path.relative_to(ROOT))):
                text = path.read_text(encoding='utf-8')
                if path.name.endswith('.rushu.json'):
                    book = json.loads(text)
                    text = '\n'.join(cell.get('source', '') for cell in book['cells']
                                     if cell['type'] == 'code')
                self.assertIsNone(OLD_IMPORT.search(text))
                seen.update(re.findall(r'''外言\s*['"](如:[^'"]+)['"]''', text))
        self.assertTrue({'如:观', '如:竞'}.issubset(seen))

    def test_current_guides_use_canonical_import_examples(self):
        for name in ('README.md', 'rulang/language-spec.md', 'rushu/README.md',
                     'docs/contest-library.md', 'docs/ruguan-guide.md'):
            with self.subTest(path=name):
                self.assertIsNone(OLD_IMPORT.search((ROOT / name).read_text(encoding='utf-8')))


if __name__ == '__main__':
    unittest.main()
