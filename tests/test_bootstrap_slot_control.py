"""Portable fourth-route policy tests, not Windows/runtime performance evidence."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('slot_control', ROOT/'tools/diagnose_bootstrap_slot_control.py')
control = importlib.util.module_from_spec(spec); spec.loader.exec_module(control)


class SlotControlTests(unittest.TestCase):
    def test_exact_roots_graph_and_relocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            app, old, new = [root/name for name in ('app','old','new')]
            for directory in (app,old,new): directory.mkdir()
            for path in (app/'main.ru',old/'same.ru',new/'same.ru'): path.write_bytes(b'source')
            first = [control.identity(app/'main.ru'),control.identity(old/'same.ru')]
            second = [control.identity(app/'main.ru'),control.identity(new/'same.ru')]
            self.assertEqual(control.graph(first,app,old),control.graph(second,app,new))
            for bad in (first+first[:1],first+[control.identity(new/'same.ru')]):
                with self.assertRaises(ValueError): control.graph(bad,app,old)
            (old/'same.ru').write_bytes(b'tampered')
            with self.assertRaises(ValueError): control.graph(first,app,old)

    def test_overlapping_roots_empty_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            with self.assertRaises(ValueError): control.graph([],root,root/'child')
            with self.assertRaises(ValueError): control.graph([],root/'a',root/'b')

    def test_exact_production_delta_no_runtime_or_flags_change(self):
        tree=ast.parse((ROOT/'tools/diagnose_bootstrap_slot_control.py').read_text(encoding='utf-8'))
        func=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='language_delta')
        allowed=ast.literal_eval(func.body[0].value)
        digests={
            'bootstrap/compiler.ru':'d83691c0eb9af56d8954224b49906b1fb8b910e520577ead43efc9671e269a60',
            'rulang/llvm_compiler.py':'1edd71ceaa97b5eed6e8ea519dbe32bfc88b510df54b33f3af1c787bbb7b6f26',
            'tests/test_bootstrap_editor_diagnostic.py':'0a257f51a6f90c4b78a6a9524366f5f92e71497d6b565e9b0a352ad2cf5365e2'}
        old={'rulang/runtime.h':'unchanged',**dict.fromkeys(digests,'old')}
        new={**old,**dict.fromkeys(allowed,'added'),**digests}
        self.assertEqual(control.language_delta(old,new),sorted(allowed))
        for bad in ({**new,'rulang/runtime.h':'changed'},{**new,'bootstrap/compiler.ru':'wrong'}, {k:v for k,v in new.items() if k!='rulang/runtime.h'}, {k:v for k,v in new.items() if k!='tools/bootstrap_slot_old_artifact.py'}):
            with self.assertRaises(ValueError): control.language_delta(old,bad)

    def test_read_raw_binding_and_frozen_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            p=Path(temporary).resolve()/'中文.json'; p.write_bytes(b'{"a":1}\n')
            value,record=control.read(p); self.assertEqual(value,{'a':1})
            self.assertEqual(record['sha256'],hashlib.sha256(p.read_bytes()).hexdigest())
            p.write_bytes(b'{"a":2}\n')
            with self.assertRaises(ValueError): control.check([record])

    def test_fresh_write_and_utf8(self):
        with tempfile.TemporaryDirectory() as temporary:
            p=Path(temporary).resolve()/'receipt.json'; control.save(p,{'a':'中文'})
            self.assertEqual(p.read_bytes(),'{\n  "a": "中文"\n}\n'.encode())
            with self.assertRaises(FileExistsError): control.save(p,{})

    def test_platform_and_download_token_fail_closed(self):
        with patch.object(control.sys,'platform','linux'):
            with self.assertRaisesRegex(ValueError,'Windows'): control.context({})
        with patch.object(control.sys,'platform','win32'),patch.dict(control.os.environ,{'GITHUB_TOKEN':'not-a-real-token'}):
            with self.assertRaisesRegex(ValueError,'download step'): control.context({})

    def test_context_distinguishes_mingw_dependencies_from_llvm_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve(); app=root/'app'; app.mkdir()
            base={'app_source':{'path':str(app),'commit':control.APP,'tree':control.APP_TREE},
                'ru_source':{'path':str(ROOT),'commit':'current','tree':'current'},
                'tool_paths':{'clang':'llvm'},'tool_sha256':{'clang':'llvmhash'},
                'mingw_tool_paths':{'cc':'gcc'},'mingw_tool_sha256':{'cc':'gcchash'}}
            config={'base_config':str(root/'base.json'),'gate_config':str(root/'gate.json'),
                'old_source':str(root/'old'),'old_artifact':str(root/'artifact')}
            (root/'base.json').write_bytes(json.dumps(base).encode())
            (root/'gate.json').write_bytes(json.dumps({'dependencies_receipt':str(root/'deps.json')}).encode())
            new={'source_pins':{k:base[k] for k in ('ru_source','app_source')},'tool_paths':base['tool_paths'],
                'tool_sha256':base['tool_sha256'],'source_sha256':{'app_source':{'a':'hash'}}}
            dependencies={'app_source':base['app_source'],'source_sha256':{'a':'hash'},
                'tool_paths':base['mingw_tool_paths'],'tool_sha256':base['mingw_tool_sha256']}
            names=('verify_bootstrap_editor_windows','build_bootstrap_release','prepare_bootstrap_dependencies')
            modules={name:SimpleNamespace(__name__=name,__file__=str(app/'tools'/(name+'.py'))) for name in names}
            modules[names[0]].validate_receipts=lambda config:{'dll_probe_receipt':new}
            modules[names[1]].snapshot=lambda *args:None
            modules[names[2]].validate_receipt=lambda path:dependencies
            modules[names[2]].dependency_environment=lambda tools,env:{'PATH':tools['cc']}
            imports={'bootstrap_slot_old_artifact':SimpleNamespace(verify_output=lambda path:{'fixed':True}),
                'diagnose_bootstrap_editor_fixture':SimpleNamespace()}
            with patch.object(control.sys,'platform','win32'),patch.dict(control.sys.modules,imports),patch.dict(control.os.environ,{},clear=True),patch.object(control.importlib,'import_module',side_effect=lambda name:modules[name]):
                self.assertEqual(control.context(config)[5]['PATH'],'gcc')
                dependencies['tool_paths']={'cc':'different'}
                with self.assertRaisesRegex(ValueError,'dependency tools'):control.context(config)

    def test_copies_bound_to_proven_executable_and_four_dependency_sources(self):
        import copy
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve(); original=root/'original'; original.mkdir()
            owned=root/'owned'; runtime=owned/'runtime'; runtime.mkdir(parents=True)
            names=('Scintilla.dll','Lexilla.dll','RuSyntax.dll','RuSyntaxWrongAbi.dll')
            sources={}
            for name in ('ru_notepad.exe',*names):
                (original/name).write_bytes(name.encode()); (runtime/name).write_bytes(name.encode())
                sources[name]=control.identity(original/name)
            old={'final_binary':sources['ru_notepad.exe']}; dependencies={'binaries':{name:sources[name] for name in names}}
            gate=SimpleNamespace(DLLS=names[:3]); config={'owned_root':str(owned)}
            prepared={'exe':str(runtime/'ru_notepad.exe'),'copies':[control.identity(runtime/name) for name in ('ru_notepad.exe',*names)]}
            control.verify_copies(prepared,config,old,dependencies,gate)
            changed=copy.deepcopy(prepared); changed['exe']=str(original/'ru_notepad.exe')
            with self.assertRaisesRegex(ValueError,'outside exact'): control.verify_copies(changed,config,old,dependencies,gate)
            for name in ('ru_notepad.exe','RuSyntax.dll'):
                raw=(runtime/name).read_bytes(); (runtime/name).write_bytes(b'replacement')
                changed=copy.deepcopy(prepared)
                changed['copies']=[control.identity(record['path']) for record in changed['copies']]
                with self.subTest(name=name),self.assertRaisesRegex(ValueError,'proven executable/dependency'):
                    control.verify_copies(changed,config,old,dependencies,gate)
                (runtime/name).write_bytes(raw)
            for records in (prepared['copies'][:-1],prepared['copies'][:-1]+prepared['copies'][:1]):
                with self.assertRaises(ValueError):control.verify_copies(dict(prepared,copies=records),config,old,dependencies,gate)

    def run_model(self, mutation=None, passed=True):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            paths={name:root/(name+'.json') for name in ('config','prepared','three','newreceipt','input')}
            for path in paths.values(): path.write_bytes(b'{}\n')
            cfg={'owned_root':str(root/'owned')}; cfg_record=control.identity(paths['config'])
            artifact={'immutable':'old'}; env={'PATH':'same','GITHUB_ENV':'same-step'}
            input_record=control.identity(paths['input'])
            prepared={'schema':control.SCHEMA,'phase':'prepared-not-executed','config':cfg_record,'old_artifact':artifact,
                'old_receipt':str(root/'owned/build/build-receipt.json'),'source_graph':[],'inputs':[input_record], 'copies':[], 'exe':str(root/'old.exe')}
            paths['prepared'].write_bytes(json.dumps(prepared).encode())
            three={'schema':'three','fixed_order':['a','b','new'],'runtime_seconds_per_child':60,'runtime_environment':env,
                'runtime_environment_sha256':hashlib.sha256(json.dumps(env,sort_keys=True).encode()).hexdigest(),
                'stage3_receipt':control.identity(paths['newreceipt']),'status':'diagnostic-complete','results':{'a':{},'b':{},'new':{}},
                'inputs':[input_record],'copies':[], 'entry':input_record,'dependencies_receipt':input_record}
            if mutation=='environment': three['runtime_environment']={'PATH':'wrong'}
            if mutation=='incomplete': three['results'].pop('new')
            paths['three'].write_bytes(json.dumps(three).encode())
            gate=SimpleNamespace(load_windows_harness=lambda app:SimpleNamespace(Windows=lambda:object()))
            new={'source_pins':{'ru_source':{'commit':'new'}}}; old={'source_pins':{'ru_source':{'commit':control.OLD}}}
            def execute(*args):
                if mutation=='input-after-read': paths['input'].write_bytes(b'changed')
                if mutation=='report-after-read': paths['three'].write_bytes(b'changed')
                return {'passed':passed,'cleanup_killed':not passed}
            diagnostic=SimpleNamespace(SCHEMA='three',ORDER=('a','b','new'),runtime_child=execute,partial_log=lambda *args:{'available':False})
            ctx=({}, {'dll_probe_receipt':str(paths['newreceipt'])},new,artifact,{},env,[gate,None,None],diagnostic,[])
            ctx=({ 'app_source':{'path':str(root)}},*ctx[1:])
            with patch.object(control,'context',return_value=ctx),patch.object(control,'validate_old',return_value=(old,[],[])),patch.object(control,'verify_copies'):
                return control.run(cfg,cfg_record,paths['prepared'],paths['three'])

    def test_original_environment_same_step_and_censored_retained(self):
        self.assertTrue(self.run_model()['old']['passed'])
        row=self.run_model(passed=False)
        self.assertFalse(row['old']['passed']); self.assertFalse(row['performance_acceptance'])
        self.assertEqual(row['old_source_provenance']['commit'],control.OLD)

    def test_environment_incomplete_and_post_read_changes_rejected(self):
        for mutation in ('environment','incomplete','input-after-read','report-after-read'):
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): self.run_model(mutation)

    def test_no_ast_frontend_or_report_rewrite(self):
        source=(ROOT/'tools/diagnose_bootstrap_slot_control.py').read_text(encoding='utf-8')
        for bad in ('rulang.frontend','MiSourcePlan','load_module_graph','emit_c(','.replace("main"'):
            self.assertNotIn(bad,source)
        self.assertIn('driver.build(old_config',source)
        self.assertIn("driver.verify_proof(proof",source)
        self.assertIn('loader.verify_output',source)
        self.assertIn('context(config)\n    validate_old',source)


if __name__=='__main__': unittest.main()
