"""Keep stable release claims distinct from the current development packages."""
from pathlib import Path
import re
import unittest

import rulang
import rushu
from rulang.frontend import parse, validate

ROOT = Path(__file__).resolve().parents[1]


class StableEntryDocsTests(unittest.TestCase):
    def test_current_entry_versions_match_packages(self):
        entry = (ROOT / 'docs/stable-entry.md').read_text(encoding='utf-8')
        changelog = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
        release_pattern = r'(\d+\.\d+\.\d+)／如书(?:保持)?\s*(\d+\.\d+\.\d+)'
        stable = re.findall(r'^# ' + release_pattern + r'（main 稳定版）$',
                            changelog, re.MULTILINE)
        self.assertEqual(len(stable), 1, 'exactly one release must identify current main')
        stable_ru, stable_rushu = stable[0]
        self.assertIn(f'如 {stable_ru}、语言规范 {stable_ru}、如书 {stable_rushu}', entry)
        # The newest entry follows this checkout; an older labeled main release
        # must not force candidate package versions back or silently age out its docs.
        current = re.match(r'^# ' + release_pattern + r'（', changelog)
        self.assertIsNotNone(current, 'the changelog starts with the current toolchain')
        self.assertEqual(current.groups(), (rulang.__version__, rushu.__version__))
        self.assertLessEqual(tuple(map(int, stable_ru.split('.'))),
                             tuple(map(int, rulang.__version__.split('.'))))
        if stable_ru != rulang.__version__:
            self.assertIn(
                f'本工作树为如／规范 {rulang.__version__}、如书 {rushu.__version__} 开发候选',
                entry)
            self.assertIn('尚未发布', entry)
            self.assertIn('不替代上面的稳定组合', entry)
            self.assertRegex(changelog.splitlines()[0], r'（开发候选，尚未发布）$')
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('[安装、版本与更新](docs/stable-entry.md)', readme)
        notebook = (ROOT / 'rushu/README.md').read_text(encoding='utf-8')
        self.assertIn(f'如书包版本：{rushu.__version__}', notebook)

    def test_readme_offers_a_progressive_learning_path(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        stages = ('## 第一步：在如书里试一试', '## 第二步：给程序一点本领',
                  '## 第三步：做一个自己的小作品', '## 用到时，再往下走')
        positions = [readme.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(readme.index('```ru'), positions[0])
        for link in ('docs/first-steps.md', 'docs/index.md', 'docs/language-guide.md',
                     'docs/command-line.md', 'docs/generation.md', 'docs/development.md',
                     'CHANGELOG.md', 'VALIDATION.md'):
            self.assertIn('](' + link + ')', readme)
        self.assertIn('不需要账号或 API key', readme)
        self.assertIn('语言原型', readme)
        self.assertIn('安全沙箱', readme)
        # Advanced contracts live in linked references, not hidden homepage blocks.
        for moved_detail in ('<details', '<!--', '--allow-native', 'max_output_tokens'):
            self.assertNotIn(moved_detail, readme)
        index = (ROOT / 'docs/index.md').read_text(encoding='utf-8')
        self.assertIn('](native-library.md)', index)

    def test_intro_examples_parse_without_execution(self):
        for document in ('README.md', 'docs/first-steps.md'):
            text = (ROOT / document).read_text(encoding='utf-8')
            examples = re.findall(r'^```ru[ \t]*\n(.*?)^```[ \t]*$', text,
                                  re.MULTILINE | re.DOTALL)
            self.assertGreaterEqual(len(examples), 2)
            for index, source in enumerate(examples, 1):
                with self.subTest(document=document, example=index):
                    validate(parse(source))

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
                         'rushu/README.md', 'docs/index.md', 'docs/first-steps.md',
                         'docs/language-guide.md', 'docs/command-line.md',
                         'docs/generation.md', 'docs/development.md'):
            path = ROOT / document
            for link in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
                target = link.split('#')[0]
                if not target or '://' in target:
                    continue
                with self.subTest(document=document, target=target):
                    self.assertTrue((path.parent / target).exists())
