"""Portable diagnostic policy tests, never Windows execution evidence."""
import importlib.util
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1]/'tools/diagnose_bootstrap_editor_fixture.py'
spec = importlib.util.spec_from_file_location('fixture_diagnostic', PATH)
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


class DiagnosticPolicyTests(unittest.TestCase):
    def test_control_failure_does_not_skip_bootstrap(self):
        calls = []
        def failed(): calls.append('C-build'); raise ValueError('compiler timeout')
        rows = diag.run_pair(failed, lambda _: self.fail('must not run missing C binary'),
            lambda: calls.append('stage3') or {'executed': True, 'passed': False, 'censored': True})
        self.assertEqual(calls, ['C-build', 'stage3'])
        self.assertFalse(rows['python-c-baseline']['executed'])
        self.assertTrue(rows['stage3-llvm']['censored'])

    def test_fixed_order_and_c_success_cannot_replace_stage3_failure(self):
        calls = []
        rows = diag.run_pair(lambda: calls.append('build') or 'control.exe',
            lambda binary: calls.append(binary) or {'passed': True},
            lambda: calls.append('stage3') or {'passed': False})
        self.assertEqual(calls, ['build', 'control.exe', 'stage3'])
        self.assertTrue(rows['python-c-baseline']['passed'])
        self.assertFalse(rows['stage3-llvm']['passed'])

    def test_second_exception_preserves_control_evidence(self):
        rows = {}
        def fail(): raise ValueError('frozen input changed')
        with self.assertRaises(ValueError):
            diag.run_pair(lambda: 1, lambda _: {'passed': True}, fail, rows)
        self.assertEqual(rows, {'python-c-baseline': {'passed': True}})

    def test_phase_failure_retains_timing_and_error(self):
        result = {'phases': []}
        def fail(): raise ValueError('fixture failure')
        with patch.object(diag.time, 'monotonic', side_effect=[10, 12]):
            with self.assertRaises(ValueError): diag.phase(result, 'C-build', fail)
        self.assertEqual(result['phases'][0]['seconds'], 2)
        self.assertFalse(result['phases'][0]['completed'])
        self.assertEqual(result['phases'][0]['error'], 'fixture failure')

    def test_partial_log_censored_metrics_do_not_invent_missing_1MB(self):
        class Gate:
            @staticmethod
            def read_log_bytes(path): return path.read_bytes(), diag.identity(path)
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            self.assertEqual(diag.partial_log(root, Gate), {'available': False, 'metrics': []})
            log = root/'ru_notepad-owned.log'
            raw = b'PERF_RU size=100000 initial_ms=2763.30279999995 edit_ms=892.438200000208 initial_read_bytes=100000 edit_read_bytes=32768 reused_bytes=67232 max_read=1024 max_tick_ms=10.3783000002149 max_chunk_ms=5.43780000018887\r\nPASS: large Ru selection only queues work\r\n'
            log.write_bytes(raw)
            result = diag.partial_log(root, Gate)
            self.assertEqual(result['identity']['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(len(result['metrics']), 1)
            self.assertEqual(result['metrics'][0]['fields']['size'], '100000')
            self.assertEqual(result['last_output_lines'][-1], 'PASS: large Ru selection only queues work')

    def test_partial_log_read_hash_mutation_rejected(self):
        class Gate:
            @staticmethod
            def read_log_bytes(path):
                raw, record = path.read_bytes(), diag.identity(path)
                path.write_bytes(b'changed')
                return raw, record
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); (root/'ru_notepad-owned.log').write_bytes(b'original')
            with self.assertRaisesRegex(ValueError, 'log changed'): diag.partial_log(root, Gate)

    def test_same_four_dll_copy_identity_and_no_source_rebuild(self):
        class Gate:
            DLLS = ('Scintilla.dll', 'Lexilla.dll', 'RuSyntax.dll')
            @staticmethod
            def verify_identity(record):
                diag.require(diag.identity(record['path']) == record, 'changed')
                return Path(record['path'])
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); binary = root/'input.exe'; binary.write_bytes(b'fixture')
            deps = {'binaries': {}}
            for name in (*Gate.DLLS, 'RuSyntaxWrongAbi.dll'):
                p = root/name; p.write_bytes(name.encode()); deps['binaries'][name] = diag.identity(p)
            exe, copies = diag.stage(diag.identity(binary), root/'owned', deps, Gate)
            self.assertEqual(exe.read_bytes(), b'fixture')
            self.assertEqual(len(copies), 5)
            for name, record in deps['binaries'].items():
                self.assertEqual(diag.identity(root/'owned'/name)['sha256'], record['sha256'])
            (root/'RuSyntax.dll').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'changed'):
                diag.stage(diag.identity(binary), root/'second', deps, Gate)

    def test_runtime_environment_identical_and_restored_on_error(self):
        class Gate:
            DLLS = ('Scintilla.dll', 'Lexilla.dll', 'RuSyntax.dll')
            loaded_dlls = staticmethod(lambda pid: {})
            @staticmethod
            def run_child(api, exe, args, **kwargs):
                self.assertEqual(dict(diag.os.environ), {'SYSTEMROOT': 'owned', 'PATH': 'locked'})
                self.assertEqual(args, ['ru'])
                raise ValueError('child failure')
        before = dict(diag.os.environ)
        with self.assertRaises(ValueError):
            diag.runtime_child(Gate, object(), Path('app.exe'), {'SYSTEMROOT': 'owned', 'PATH': 'locked'})
        self.assertEqual(dict(diag.os.environ), before)

    def test_metric_fixed_schemas_actual_values_and_negative_controls(self):
        # 599 C run values rendered using immutable fixture's raw output schema;
        # source_sha256 is harness-enriched JSON, not raw fixture stdout.
        lines = [
            'PERF_RU size=100000 initial_ms=989.476599999703 edit_ms=332.500699999742 initial_read_bytes=100000 edit_read_bytes=32768 reused_bytes=67232 max_read=1024 max_tick_ms=8.45200000004843 max_chunk_ms=2.00940000033006',
            'PERF_RU size=1000000 initial_ms=13171.3136 edit_ms=459.345699999947 initial_read_bytes=1000000 edit_read_bytes=32768 reused_bytes=967232 max_read=1024 max_tick_ms=8.62090000044554 max_chunk_ms=3.31419999990612',
            'RU_GUI_SYNC size=1000000 source_chars=636370 wall_ms=10196.3553999998 read_bytes=1000000 max_read=1023 max_tick_ms=12.0474000000395 max_chunk_ms=5.42819999996573 chunks=8798',
        ]
        for line in lines:
            self.assertTrue(diag.metric(line)['fields'])
            for bad in (line+' size=1', line+' invented=1', line+' source_sha256='+'a'*64,
                        line.replace('size=100000', 'size=-100000', 1),
                        line.rsplit(' ',1)[0]):
                with self.assertRaises(ValueError): diag.metric(bad)
        for value in ('nan', 'inf', '1e999', '-1'):
            with self.assertRaises(ValueError):
                diag.metric(lines[2].replace('wall_ms=10196.3553999998', 'wall_ms='+value))

    def test_graph_missing_extra_changed_duplicate_fail(self):
        with tempfile.TemporaryDirectory() as root:
            a = {'path': str(Path(root)/'a.ru'), 'size': 1, 'sha256': 'a'*64}
            b = {'path': str(Path(root)/'b.ru'), 'size': 2, 'sha256': 'b'*64}
            diag.compare_graph([a,b], [b,a])
            for bad in ([a], [a,b,a], [a,dict(b,size=3)], [a,dict(b,sha256='c'*64)]):
                with self.assertRaises(ValueError): diag.compare_graph(bad,[a,b])

    def test_timeout_retains_actual_owned_module_observations(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            names = ('Scintilla.dll', 'Lexilla.dll', 'RuSyntax.dll')
            records = {}
            for name in names:
                path = directory/name; path.write_bytes(name.encode()); records[name] = diag.identity(path)
            class Gate:
                DLLS = names
                loaded_dlls = staticmethod(lambda pid: records)
                @staticmethod
                def run_child(api, exe, args, **kwargs):
                    Gate.loaded_dlls(71)
                    return {'pid':71, 'passed':False, 'cleanup_killed':True, 'error':'60s deadline'}
            original = Gate.loaded_dlls
            row = diag.runtime_child(Gate, object(), directory/'app.exe', {})
            self.assertFalse(row['passed'])
            self.assertTrue(row['cleanup_killed'])
            self.assertEqual(row['diagnostic_module_observations']['verified'], records)
            self.assertTrue(row['diagnostic_module_observations']['complete'])
            self.assertIs(Gate.loaded_dlls, original)
            wrong = dict(records['Scintilla.dll'], path=str(directory/'elsewhere.dll'))
            Gate.loaded_dlls = staticmethod(lambda pid: {'Scintilla.dll':wrong})
            with self.assertRaisesRegex(ValueError, 'owned DLL'):
                diag.runtime_child(Gate, object(), directory/'app.exe', {})

    def test_wrong_platform_rejected(self):
        with patch.object(diag.sys, 'platform', 'linux'):
            with self.assertRaisesRegex(ValueError, 'real Windows'): diag.diagnose({})


if __name__ == '__main__': unittest.main()
