"""Review evidence must identify Git paths without quoting or whitespace loss."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools.verify_bs_review import archived_files, source_identity, tracked_files
from tools import verify_bs_review as review
from tools import benchmark_bootstrap_syntax as benchmark


class CoreSuiteRegistrationTests(unittest.TestCase):
    def test_new_suites_use_verified_stage3_and_skips_fail_closed(self):
        for skipped in (False, True):
            with self.subTest(skipped=skipped), tempfile.TemporaryDirectory() as temporary:
                out = Path(temporary)
                stage = out/('stage3.exe' if os.name == 'nt' else 'stage3')
                stage.write_bytes(b'verified-stage3-fixture')
                parent = self
                class Probe(unittest.TestCase):
                    def runTest(self):
                        for name in ('RU_FRAME_TEST_COMPILER', 'RU_BINDING_TEST_COMPILER',
                                     'RU_SCALAR_TEST_COMPILER'):
                            parent.assertEqual(os.environ[name], str(stage.resolve()))
                        if skipped:
                            self.skipTest('deliberate missing toolchain')
                def load(names):
                    self.assertEqual(set(names), {
                        'test_llvm_bindings', 'test_llvm_frames', 'test_llvm_target_attributes',
                        'test_bs_review', 'test_c_bindings', 'test_llvm_lowering',
                        'test_scalar_lowering'})
                    self.assertEqual(len(names), len(set(names)))
                    return unittest.TestSuite([Probe()])
                with patch.object(review.unittest.defaultTestLoader, 'loadTestsFromNames', side_effect=load), \
                     patch.object(review, 'source_identity', return_value={}), \
                     patch.dict(os.environ), patch('builtins.print'):
                    if skipped:
                        with self.assertRaisesRegex(RuntimeError, 'without skips'):
                            review.core(out)
                    else:
                        review.core(out)
                report = json.loads((out/'new-suites.json').read_text())
                self.assertEqual(report['planned'], report['executed'])
                self.assertEqual(report['tests_run'], len(report['planned']))
                self.assertEqual(bool(report['skipped']), skipped)


class BenchmarkAdapterTests(unittest.TestCase):
    def test_splice_preserves_native_sections_and_literal_control_characters(self):
        # These are literal table entries, not source line delimiters.
        table = "表 取 '\x1c\x1d\x1e\x85\u2028\u2029'.\n"
        spans = (
            ('算 新号 全 前:', '算 读文 文件:'),
            ('算 检函 全 模块 函 保护 值域:', '算 检块 全 模块 体 函 循深 可声明 顶 保护 值域:'),
            ('算 描述符 全:', "    序 取 0. 类列 取 全['类']. 类指 取 []."),
            ('算 发全 全 三元 布局:', '算 元初 参数 为 句 阵:'),
        )
        def source(label):
            return table + ''.join(a+'\n'+label+'\n'+b+'\n原生保留\n' for a, b in spans) + 'LLVM接口 取 '+label+'\n'+table
        actual = benchmark.splice_frontend(source('old'), source('new'))
        self.assertEqual(actual, source('new'))
        self.assertEqual(actual.count(table), 2)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            benchmark.splice_frontend(source('old')+spans[0][0], source('new'))

    def test_standalone_measure_retains_timeout_and_finishes_all_pairs(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            benchmark.save(out/'inputs.json', {'files': {}})
            for arm in ('c-llvm', 'bootstrap'):
                (out/arm).mkdir()
                (out/arm/'program.exe').write_bytes(arm.encode())
            stdout = '\n'.join('PASS: case-'+str(i) for i in range(149))+'\nTOTAL PASS: 149\n'
            for size in (100000, 1000000):
                stdout += f'PERF_RU size={size} initial_ms=10 edit_ms=2 initial_read_bytes={size} edit_read_bytes=32768\n'
            stdout += 'RU_GUI_SYNC size=1000000 wall_ms=5 read_bytes=1000000 source_chars=636370\n'
            invoked = []
            def run(command, **kwargs):
                self.assertEqual(json.loads((out/'measurement/plan.json').read_text())['retries'], 0)
                invoked.append(Path(command[0]).parent.name)
                if len(invoked) == 1:
                    raise subprocess.TimeoutExpired(command, 180, output=b'partial', stderr=b'timeout')
                return subprocess.CompletedProcess(command, 0, stdout.encode(), b'')
            with patch.object(benchmark.subprocess, 'run', side_effect=run), patch('builtins.print'), \
                 self.assertRaisesRegex(RuntimeError, 'invalid samples retained'):
                benchmark.measure(SimpleNamespace(output=out))
            self.assertEqual(invoked, ['c-llvm', 'bootstrap', 'bootstrap', 'c-llvm']*3)
            evidence = out/'measurement'
            attempts = json.loads((evidence/'attempts.json').read_text())
            self.assertEqual(len(attempts), 12)
            self.assertTrue(attempts[0]['timeout'])
            self.assertEqual((evidence/'1-c-llvm.stdout').read_bytes(), b'partial')
            self.assertEqual((evidence/'1-c-llvm.stderr').read_bytes(), b'timeout')
            self.assertEqual(len(list(evidence.glob('*.stdout'))), 12)
            self.assertTrue(json.loads((evidence/'after.json').read_text())['verified'])


class GitFilenameTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git('init', '-q')

    def git(self, *arguments, input=None):
        return subprocess.check_output(
            ['git', '-C', str(self.root), *arguments], input=input)

    def tree(self, files):
        entries = []
        for name, content in files.items():
            blob = self.git('hash-object', '-w', '--stdin', input=content).strip()
            entries.append(b'100644 blob '+blob+b'\t'+name.encode('utf-8')+b'\0')
        return self.git('mktree', '-z', input=b''.join(entries)).decode('ascii').strip()

    def test_nul_paths_preserve_every_character_with_default_git_quoting(self):
        # mktree exercises real Git on Windows too, where several of these
        # legal Git names cannot be materialized as filesystem paths.
        names = ['中文.ru', 'with space.ru', ' leading.ru', 'trailing ',
                 'quote".ru', 'tab\t.ru', 'line\n.ru', 'back\\slash.ru']
        revision = self.tree({name: b'content' for name in names})
        self.git('config', 'core.quotepath', 'true')
        actual = tracked_files(self.root, revision)
        self.assertEqual(len(actual), len(names))
        self.assertEqual(set(actual), set(names))
        self.git('config', 'core.quotepath', 'false')
        self.assertEqual(tracked_files(self.root, revision), actual)

    def test_source_identity_reads_real_unicode_and_space_paths(self):
        files = {'中文.ru': '印「你好」。\n'.encode('utf-8'),
                 'with space.ru': b'one\n', ' leading.ru': b'two\n'}
        revision = self.tree(files)
        for name, content in files.items():
            (self.root/name).write_bytes(content)
        expected = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
        self.assertEqual(source_identity(self.root, revision), expected)
        (self.root/'中文.ru').write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'production source differs: 中文.ru'):
            source_identity(self.root, revision)

    def test_empty_tree_has_no_paths(self):
        self.assertEqual(tracked_files(self.root, self.tree({})), [])

    def test_explicit_git_crlf_checkout_preserves_actual_byte_hash(self):
        files = {'.gitattributes': b'*.cmd text eol=crlf\n', '中文.cmd': b'echo test\n'}
        revision = self.tree(files)
        (self.root/'.gitattributes').write_bytes(files['.gitattributes'])
        checked_out = b'echo test\r\n'
        self.assertEqual(archived_files(self.root, revision)['中文.cmd'], checked_out)
        (self.root/'中文.cmd').write_bytes(checked_out)
        identity = source_identity(self.root, revision)
        self.assertEqual(identity['中文.cmd'], hashlib.sha256(checked_out).hexdigest())
        (self.root/'中文.cmd').write_bytes(b'echo changed\r\n')
        with self.assertRaisesRegex(RuntimeError, 'production source differs'):
            source_identity(self.root, revision)


class MeasurementEvidenceTests(unittest.TestCase):
    def test_timeout_keeps_output_and_completes_the_predeclared_order_without_retries(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            comparison = out/'comparison'
            comparison.mkdir()
            review.save(comparison/'inputs.json', {'files': {}})
            review.save(out/'tool-lock.json', {'source_sha256': {}, 'tool_paths': {}})
            for arm in ('c-llvm', 'bootstrap'):
                (comparison/arm).mkdir()
                (comparison/arm/'program.exe').write_bytes(arm.encode())
            stdout = '\n'.join('PASS: case-'+str(i) for i in range(149))+'\nTOTAL PASS: 149\n'
            for size in (100000, 1000000):
                stdout += f'PERF_RU size={size} initial_ms=10 edit_ms=2 initial_read_bytes={size} edit_read_bytes=32768\n'
            stdout += 'RU_GUI_SYNC size=1000000 wall_ms=5 read_bytes=1000000 source_chars=636370\n'
            invoked = []
            def run(command, **kwargs):
                plan = json.loads((out/'measurement/plan.json').read_text())
                self.assertEqual(plan['retries'], 0)
                invoked.append(Path(command[0]).parent.name)
                if len(invoked) == 1:
                    raise subprocess.TimeoutExpired(command, 180, output=b'partial stdout', stderr=b'timeout stderr')
                return subprocess.CompletedProcess(command, 0, stdout.encode(), b'fixture stderr')
            with patch.object(review, 'source_identity', return_value={}), \
                 patch.object(review, 'build_proof', return_value={}), \
                 patch.object(review, 'args', SimpleNamespace(editor=out), create=True), \
                 patch.dict('sys.modules', {'prepare_bootstrap_dependencies': SimpleNamespace(validate_receipt=lambda _: None)}), \
                 patch.object(review.subprocess, 'run', side_effect=run), \
                 patch('builtins.print'), \
                 self.assertRaisesRegex(RuntimeError, 'failed samples retained'):
                review.measure(out)
            self.assertEqual(invoked, ['c-llvm', 'bootstrap', 'bootstrap', 'c-llvm']*3)
            evidence = out/'measurement'
            attempts = json.loads((evidence/'attempts.json').read_text())
            self.assertEqual(len(attempts), 12)
            self.assertTrue(attempts[0]['timeout'])
            self.assertIn('validation_error', attempts[0])
            self.assertEqual((evidence/'1-c-llvm.stdout').read_bytes(), b'partial stdout')
            self.assertEqual((evidence/'1-c-llvm.stderr').read_bytes(), b'timeout stderr')
            self.assertEqual(len(list(evidence.glob('*.stdout'))), 12)
            self.assertTrue((evidence/'failure.json').is_file())
            self.assertTrue(json.loads((evidence/'after.json').read_text())['verified'])
