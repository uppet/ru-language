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
    def test_command_timeout_contract_keeps_llvm120_and_existing600(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); rows=[];seen=[]
            def invoked(argv,**kwargs):
                seen.append(kwargs['timeout']);kwargs['stdout'].write(b'out\r\n');kwargs['stderr'].write(b'')
                return SimpleNamespace(returncode=0)
            with patch.object(diag.subprocess,'run',invoked):
                self.assertEqual(diag.command(['tool'],root,{},'default',rows),'out\r\n')
                self.assertEqual(diag.command(['tool'],root,{},'llvm',rows,input='',timeout=120),'out\r\n')
            self.assertEqual(seen,[600,120])
            self.assertEqual([r['timeout_seconds'] for r in rows],[600,120])
            self.assertEqual(rows[0]['stdout']['sha256'],hashlib.sha256(b'out\r\n').hexdigest())

    def test_three_controls_have_fixed_order_and_independent_failures(self):
        for failed in ('none','gcc','llvm','both'):
            calls=[]
            def build(name):
                calls.append('build-'+name)
                if failed in (name,'both'): raise ValueError('failed '+name)
                return name
            def run(name): calls.append('run-'+name); return {'passed':True}
            rows=diag.run_three(lambda:build('gcc'),run,lambda:build('llvm'),run,
                lambda:calls.append('stage3') or {'passed':False,'censored':True})
            self.assertEqual(calls[-1],'stage3')
            self.assertEqual(list(rows),list(diag.ORDER))
            self.assertFalse(rows['stage3-llvm']['passed'])
            self.assertFalse(rows['python-c-baseline']['passed']) if failed in ('gcc','both') else None
            self.assertFalse(rows['python-c-via-llvm-control']['passed']) if failed in ('llvm','both') else None

    def test_c_via_llvm_keeps_main_and_explicit_pure_object_link(self):
        # Protocol model only: no claim this fake is Windows/LLVM execution.
        import json
        class Gate:
            @staticmethod
            def verify_identity(record):
                if diag.identity(record['path']) != record: raise ValueError('identity changed')
                return Path(record['path'])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); generated=root/'probe.c';generated.write_bytes(b'int main(int argc,char **argv){return 0;}\n')
            names=('clang','llvm-as','llvm-link','opt','llvm-dis','llc','linker')
            tools={name:str(root/(name+'.exe')) for name in names}
            for path in tools.values(): Path(path).write_bytes(b'locked tool')
            reused={}
            for name in ('launcher.obj','application.res'):
                path=root/name;path.write_bytes(name.encode());reused[name]=diag.identity(path)
            receipt={'tool_paths':tools,'tool_sha256':{k:diag.identity(v)['sha256'] for k,v in tools.items()},
                     'target_triple':'x86_64-pc-windows-msvc19.0','data_layout':'e-m:w','linked_inputs':reused}
            selections=[];commands=[]
            class Driver:
                @staticmethod
                def validate_toolchain(paths,hashes):
                    for name,path in paths.items():
                        if diag.identity(path)['sha256'] != hashes[name]: raise ValueError('tool changed')
                @staticmethod
                def explicit_linker_flags(record): return ['-fuse-ld=link.exe','-B'+str(root)]
                @staticmethod
                def inspect_linker_command(argv,record,env,cwd,triple):
                    self.assertEqual(argv[1],'--target='+triple)
                    selections.append(list(argv));return {'command':list(argv)}
                @staticmethod
                def verify_linker_selection(selection,tools,expected_command,triple): self.assertEqual(selection['command'],expected_command)
                @staticmethod
                def link_commands(tools,ir,wrapper,app,directory,triple):
                    return [[tools['llc'],str(ir),'-o',str(directory/'application.obj')],
                            [tools['clang'],'--target='+triple,str(directory/'application.obj'),str(directory/'launcher.obj'),str(directory/'application.res'),'-o',str(directory/'ru_notepad.exe'),*Driver.explicit_linker_flags({})]]
                @staticmethod
                def verify_gui_pe(path): self.assertTrue(path.is_file())
            class Chain:
                def __init__(self,clang):
                    self.clang=[clang];self.tools={k:tools[k] for k in names if k not in ('clang','linker')}
                    self.triple=receipt['target_triple'];self.data_layout=receipt['data_layout']
                    self.run([clang,'--version'])
                def compile(self,program,runtime,directory,full_runtime):
                    self_test.assertFalse(full_runtime)
                    (directory/'program.ll').write_bytes(program.encode());(directory/'runtime.c').write_bytes(runtime.encode())
                    for name in ('program.bc','runtime.bc','linked.bc','optimized.bc','standalone.ll','program.o'):
                        self.run([self.tools['llc'],'-o',str(directory/name)])
                    self.run(self.clang+[str(directory/'program.o'),'-o',str(directory/'program.exe'),*self.link_flags])
                    return directory/'program.exe',directory/'standalone.ll'
            self_test=self
            def fake_command(argv,cwd,env,label,evidence,input=None,timeout=600):
                commands.append(list(argv));evidence.append({'argv':argv})
                if '-o' in argv:
                    output = argv[argv.index('-o')+1]
                    if output != '-':
                        target = Path(output)
                        (target if target.is_absolute() else cwd/target).write_bytes(b'generated output')
                return 'clang version 14.0.6'
            result={'control_source_graph':{'generated_c':diag.identity(generated)}}
            with patch.object(diag,'command',fake_command):
                binary=diag.compile_c_via_llvm(Chain,generated,root/'build',receipt,Driver,Gate,{},result,lambda:None)
            self.assertEqual(len(selections),2)
            self.assertEqual((root/'build/runtime.c').read_bytes(),generated.read_bytes())
            self.assertEqual((root/'build/program.ll').read_text(), 'target datalayout = "e-m:w"\ntarget triple = "x86_64-pc-windows-msvc19.0"\n')
            self.assertFalse(result['llvm_control']['bootstrap_proof'])
            self.assertFalse(result['llvm_control']['release_permission'])
            self.assertEqual(binary['path'],str(root/'build/ru_notepad.exe'))
            self.assertEqual(result['llvm_control']['reused_gui_inputs'],reused)
            # No frontend subprocess or generated-C rewrite in this worker.
            self.assertTrue(all(argv[0] in tools.values() for argv in commands))
            class WrongTarget(Chain):
                def __init__(self,clang): super().__init__(clang); self.triple='x86_64-pc-windows-msvcOTHER'
            with patch.object(diag,'command',fake_command):
                with self.assertRaisesRegex(ValueError,'target/layout differs'):
                    diag.compile_c_via_llvm(WrongTarget,generated,root/'wrong-target',receipt,Driver,Gate,{},result,lambda:None)
            class WrongTools(Chain):
                def __init__(self,clang): super().__init__(clang); self.tools['llc']='untrusted-llc'
            with patch.object(diag,'command',fake_command):
                with self.assertRaisesRegex(ValueError,'different tools'):
                    diag.compile_c_via_llvm(WrongTools,generated,root/'wrong-tools',receipt,Driver,Gate,{},result,lambda:None)
            class BadLink(Chain):
                def compile(self,program,runtime,directory,full_runtime):
                    self.run(self.clang+[str(directory/'program.o'),'-o',str(directory/'program.exe')])
            with patch.object(diag,'command',fake_command):
                with self.assertRaisesRegex(ValueError,'unexpected LLVM console linker argv'):
                    diag.compile_c_via_llvm(BadLink,generated,root/'implicit-link',receipt,Driver,Gate,{},result,lambda:None)
            def mutate_runtime(argv,cwd,env,label,evidence,input=None,timeout=600):
                output=fake_command(argv,cwd,env,label,evidence,input)
                if (cwd/'runtime.c').exists(): (cwd/'runtime.c').write_bytes(b'changed runtime')
                return output
            with patch.object(diag,'command',mutate_runtime):
                with self.assertRaisesRegex(ValueError,'identity changed'):
                    diag.compile_c_via_llvm(Chain,generated,root/'runtime-mutation',receipt,Driver,Gate,{},result,lambda:None)
            def mutate_tool(argv,cwd,env,label,evidence,input=None,timeout=600):
                output=fake_command(argv,cwd,env,label,evidence,input)
                Path(tools['llc']).write_bytes(b'replaced tool')
                return output
            with patch.object(diag,'command',mutate_tool):
                with self.assertRaisesRegex(ValueError,'tool changed'):
                    diag.compile_c_via_llvm(Chain,generated,root/'tool-mutation',receipt,Driver,Gate,{},result,lambda:None)
            Path(tools['llc']).write_bytes(b'locked tool')
            # Load the actual repository class, stubbing only unrelated imports
            # and OS/tool responses. Its constructor/compile bodies are unedited.
            import types, sys
            package=types.ModuleType('_diagnostic_real');package.__path__=[]
            frontend=types.ModuleType('_diagnostic_real.frontend');frontend.RuError=ValueError
            compiler=types.ModuleType('_diagnostic_real.llvm_compiler');compiler.LLVMCompiler=object
            environment=types.ModuleType('_diagnostic_real.toolchain_environment');environment.llvm_environment=lambda:{}
            cli=types.ModuleType('_diagnostic_real.cli');cli.compiler_command=lambda selected:[selected]
            spec=importlib.util.spec_from_file_location('_diagnostic_real.llvm_toolchain',PATH.parents[1]/'rulang/llvm_toolchain.py')
            module=importlib.util.module_from_spec(spec)
            stubs={m.__name__:m for m in (package,frontend,compiler,environment,cli)}
            with patch.dict(sys.modules,stubs): spec.loader.exec_module(module)
            limits=[]
            def real_command(argv,cwd,env,label,evidence,input=None,timeout=600):
                limits.append((label,timeout));fake_command(argv,cwd,env,label,evidence,input,timeout)
                if '--version' in argv: return 'clang version 14.0.6' if argv[0] == tools['clang'] else 'LLVM version 14.0.6'
                if '-S' in argv: return 'target datalayout = "e-m:w"\ntarget triple = "x86_64-pc-windows-msvc19.0"\n'
                return ''
            original_write = Path.write_bytes
            def owned_write(path, data):
                self.assertTrue(path.resolve().is_relative_to(root), 'mock wrote outside owned temporary fixture: '+str(path))
                return original_write(path, data)
            import os
            previous_cwd = Path.cwd()
            with tempfile.TemporaryDirectory() as clean_cwd:
                os.chdir(clean_cwd)
                try:
                    before = list(Path.cwd().iterdir())
                    with patch.object(Path,'write_bytes',owned_write),patch.dict(sys.modules,stubs),patch.object(module.sys,'platform','win32'), \
                         patch.object(module.platform,'machine',return_value='AMD64'),patch.object(module.os,'access',return_value=True), \
                         patch.object(diag,'command',real_command):
                        diag.compile_c_via_llvm(module.LLVMToolchain,generated,root/'real-chain',receipt,Driver,Gate,{},result,lambda:None)
                    self.assertEqual(list(Path.cwd().iterdir()), before, 'LLVM mock polluted caller cwd')
                finally:
                    os.chdir(previous_cwd)
            self.assertTrue(all(seconds == (120 if label.startswith('llvm-') else 600) for label,seconds in limits))
            actual=result['llvm_control']['commands']
            passes=[arg for cmd in actual for arg in cmd['argv'] if arg.startswith('-passes=')]
            self.assertEqual(passes,['-passes=internalize,default<O2>,globaldce'])
            self.assertEqual(len(result['llvm_control']['linker_selections']),2)
            generated.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'shared generated C changed'):
                diag.compile_c_via_llvm(Chain,generated,root/'rejected',receipt,Driver,Gate,{},result,lambda:None)


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
