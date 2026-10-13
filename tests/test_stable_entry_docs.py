"""Keep the stable entry and target distinction tied to installed packages."""
from pathlib import Path
import re
import unittest

import rulang
import rushu

ROOT = Path(__file__).resolve().parents[1]


class StableEntryDocsTests(unittest.TestCase):
    def test_current_entry_versions_match_packages(self):
        entry = (ROOT / 'docs/stable-entry.md').read_text(encoding='utf-8')
        self.assertIn(f'如 {rulang.__version__}、语言规范 {rulang.__version__}、如书 {rushu.__version__}', entry)
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn(f'· {rulang.__version__} 元初实现', readme)
        notebook = (ROOT / 'rushu/README.md').read_text(encoding='utf-8')
        self.assertIn(f'如书包版本：{rushu.__version__}', notebook)

    def test_update_commands_are_non_destructive(self):
        entry = (ROOT / 'docs/stable-entry.md').read_text(encoding='utf-8')
        commands = '\n'.join(re.findall(r'```sh\n(.*?)```', entry, re.S))
        self.assertIn('git status --short', commands)
        self.assertIn('git clone --branch main', commands)
        self.assertIn('git pull --ff-only origin main', commands)
        self.assertNotRegex(commands, r'git (?:reset|clean)|--force|git checkout -f')
        self.assertIn('没有自动保存', entry)

    def test_target_names_and_review_boundary(self):
        for document in ('docs/stable-entry.md', 'docs/prompt-export.md'):
            text = (ROOT / document).read_text(encoding='utf-8')
            for required in ('--target browser-js', 'Node.js', 'Python', '审阅'):
                self.assertIn(required, text)
        notebook = (ROOT / 'rushu/README.md').read_text(encoding='utf-8')
        self.assertIn('编译产物随即丢弃', notebook)
        self.assertIn('检查通过不保证运行正确或安全', notebook)

    def test_local_document_links_resolve(self):
        for document in ('README.md', 'docs/stable-entry.md', 'docs/getting-started.md',
                         'docs/prompt-export.md', 'docs/browser-js.md', 'docs/ruguan-guide.md',
                         'rushu/README.md'):
            path = ROOT / document
            for link in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
                target = link.split('#')[0]
                if not target or '://' in target:
                    continue
                with self.subTest(document=document, target=target):
                    self.assertTrue((path.parent / target).exists())
