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
            'bootstrap/compiler.ru':'002f6995e9ca20307691ad015ca849a2570ada1043f1c089f8027a858cf34d7f',
            'rulang/llvm_compiler.py':'c4a1baa913c82fa24bbfba1d359f57699df4283b43945a42095c8f3721710dd2',
            'tests/test_bootstrap_editor_diagnostic.py':'0a257f51a6f90c4b78a6a9524366f5f92e71497d6b565e9b0a352ad2cf5365e2'}
        old={'rulang/runtime.h':'unchanged',**dict.fromkeys(digests,'old')}
        new={**old,**dict.fromkeys(allowed,'added'),**digests}
        self.assertEqual(control.language_delta(old,new),sorted(allowed))
        for bad in ({**new,'bootstrap/compiler.ru':'d83691c0eb9af56d8954224b49906b1fb8b910e520577ead43efc9671e269a60'}, {**new,'rulang/llvm_compiler.py':'1edd71ceaa97b5eed6e8ea519dbe32bfc88b510df54b33f3af1c787bbb7b6f26'}, {**new,'tools/unreviewed.py':'extra'}, {**new,'rulang/runtime.h':'changed'},{**new,'bootstrap/compiler.ru':'wrong'}, {k:v for k,v in new.items() if k!='rulang/runtime.h'}, {k:v for k,v in new.items() if k!='tools/bootstrap_slot_old_artifact.py'}):
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

    def run_model(self, mutation=None, passed=True, new_passed=True):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            paths={name:root/(name+'.json') for name in ('config','prepared','three','newreceipt','input')}
            for path in paths.values(): path.write_bytes(b'{}\n')
            cfg={'owned_root':str(root/'owned')}; cfg_record=control.identity(paths['config'])
            artifact={'immutable':'old'}; env={'PATH':'same','GITHUB_ENV':'same-step'}
            input_record=control.identity(paths['input'])
            prepared={'schema':control.SCHEMA,'phase':'prepared-not-executed','config':cfg_record,'old_artifact':artifact,
                'old_receipt':str(root/'owned/build/build-receipt.json'),'source_graph':KNOWN_GRAPH,'inputs':[input_record], 'copies':[], 'exe':str(root/'old.exe')}
            paths['prepared'].write_bytes(json.dumps(prepared).encode())
            three={'schema':'three','fixed_order':['a','b','new'],'runtime_seconds_per_child':60,'runtime_environment':env,
                'runtime_environment_sha256':hashlib.sha256(json.dumps(env,sort_keys=True).encode()).hexdigest(),
                'stage3_receipt':control.identity(paths['newreceipt']),'status':'diagnostic-complete','results':{name:{'passed':new_passed} for name in ('a','b','new')},
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
            with patch.object(control,'context',return_value=ctx),patch.object(control,'validate_old',return_value=(old,[],KNOWN_GRAPH)),patch.object(control,'verify_copies'):
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



# Frozen925 log is a test prefix only, never retroactively valid runtime evidence.
KNOWN_PARTIAL = 'Ru Notepad diagnostic log\n[launcher] Starting Ru program.\nPASS: production bulk decoder matches all six old-decoder fields across a full 64-event batch\nPASS: production bulk decoder checks high bits in the last event of a full batch\nPASS: production bulk decoder preserves exact near-32-MB event coordinates and unsigned metadata\nPASS: production bulk decoder rejects high-bit corruption 0 before combining words\nPASS: production bulk decoder rejects high-bit corruption 1 before combining words\nPASS: production bulk decoder rejects high-bit corruption 2 before combining words\nPASS: production bulk decoder ignores stale event bytes when the native count is zero\nPASS: production bulk decoder rejects a count exceeding its 1024-byte event capacity\nPASS: production bulk decoder rejects a negative count\nPASS: production bulk decoder rejects a fractional count\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 0\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 1\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 2\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 3\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 4\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 5\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 6\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 7\nPASS: production bulk decoder rejects a non-token before the styled range\nPASS: production bulk decoder preserves long identifier events starting before the styled range\nPASS: production bulk decoder preserves the 64-byte delayed keyword boundary\nPASS: production bulk decoder rejects decreasing event positions\nPASS: production bulk decoder preserves equal-position event ordering\nPASS: decoded event rows remain detached after source mutation and closure\nPASS: checked low49 decoding preserves event coordinates near the 32 MB boundary\nPASS: corrupt high event bits fail ordinarily before any lossy native conversion\nPASS: initial checkpoint failure releases the already-created native context exactly once\nPASS: failed initialization returns no released context or checkpoint to the plain fallback\nPASS: initial checkpoint failure keeps its specific visible warning outside rescue scope\nPASS: Ru attaches independently of Lexilla availability\nPASS: Ru uses real SCLEX_CONTAINER instead of borrowed lexer\nPASS: selection never performs eager lexical scanning\nPASS: real SCN_STYLENEEDED reaches the owning container bridge\nPASS: style-needed notification queues without synchronous rescanning\nPASS: container queue drains without fallback\nPASS: every UTF-8 byte of 算 is a keyword\nPASS: Han function name retains identifier style\nPASS: every Han and emoji byte in quoted string is styled\nPASS: number following multibyte source has correct byte offset\nPASS: function header has base fold level and header flag\nPASS: if header nests exactly once\nPASS: function and if body has depth two\nPASS: 法 closes matching function level\nPASS: styling and folding preserve exact UTF-8 text\nPASS: styling and folding never dirty a clean document\nPASS: styling and folding create no undo entry\nPASS: styling preserves selection anchor and caret\nPASS: Ru palette preserves line-number style\nPASS: dedicated fold margin is visible\nPASS: fold action accepts completed owning document\nPASS: collapse actually hides nested native lines\nPASS: collapse changes native expanded flag\nPASS: expand restores native line visibility\nPASS: plain switch reveals every previously hidden line\nPASS: plain switch clears old fold levels\nPASS: plain switch clears all Ru style bytes\nPASS: plain switch cancels scanner state\nPASS: C++ switch reveals every Ru fold even without Lexilla\nPASS: JSON switch reveals every Ru fold even without Lexilla\nPASS: first typing into empty Ru document restarts a nonterminal checkpoint\nPASS: EOF append never restores a finished scanner\nPASS: EOF undo and redo remain incrementally highlighted\nPASS: multiline quote initially styles Han bytes\nPASS: deleting opening quote invalidates multiline lexical state\nPASS: undo restores multiline quote state\nPASS: Ru block comment spans Han and emoji bytes\nPASS: Ru keyword resumes after the real 释. block-comment terminator\nPASS: same-length comment opener replacement invalidates lexical suffix\nPASS: undo restores Ru multiline comment state\nPASS: real native insert/delete notifications reached owning bridge\nPASS: style and fold notifications are observed without recursive text invalidation\nPASS: UTF-8 quote and emoji styles cross checkpoint boundary correctly\nPASS: deleting LF from checkpoint-adjacent CRLF safely resumes lexical state\nPASS: keyword offset adjusts correctly after CRLF partial deletion\nPASS: bounded timer returns before a large initial scan completes\nPASS: edit during incomplete work invalidates suffix without unsafe reuse\nPASS: unclosed BOF comment propagates through previously pending source\nPASS: removing existing collapsed function headers with BOF comment reveals every old hidden line\nPASS: tentative reference-call opener starts without a fold header\nPASS: temporary statement confirms an opener before the restart checkpoint\nPASS: checkpoint restore retracts a previously published earlier header and reveals its lines\nPASS: BOF insertion unequal edit queues its own revision and preserves exact dirty text\nPASS: BOF insertion incremental text/styles/all fold levels equal an independent fresh scan\nPASS: BOF insertion highlighting preserves one-edit undo and the original savepoint\nPASS: BOF deletion unequal edit queues its own revision and preserves exact dirty text\nPASS: BOF deletion incremental text/styles/all fold levels equal an independent fresh scan\nPASS: BOF deletion highlighting preserves one-edit undo and the original savepoint\nPASS: middle insertion unequal edit queues its own revision and preserves exact dirty text\nPASS: middle insertion incremental text/styles/all fold levels equal an independent fresh scan\nPASS: middle insertion highlighting preserves one-edit undo and the original savepoint\nPASS: middle deletion unequal edit queues its own revision and preserves exact dirty text\nPASS: middle deletion incremental text/styles/all fold levels equal an independent fresh scan\nPASS: middle deletion highlighting preserves one-edit undo and the original savepoint\nPASS: EOF insertion unequal edit queues its own revision and preserves exact dirty text\nPASS: EOF insertion incremental text/styles/all fold levels equal an independent fresh scan\nPASS: EOF insertion highlighting preserves one-edit undo and the original savepoint\nPASS: EOF deletion unequal edit queues its own revision and preserves exact dirty text\nPASS: EOF deletion incremental text/styles/all fold levels equal an independent fresh scan\nPASS: EOF deletion highlighting preserves one-edit undo and the original savepoint\nPASS: matrix multiline edit has published a bounded prefix while work remains pending\nPASS: repeated edits during pending work discard old states and match every fresh byte style and fold level\nPASS: edit in later function preserves unaffected collapsed earlier fold\nPASS: editing one HWND preserves another document byte styles\nPASS: editing one HWND never invalidates another document generation\nPASS: SETDOCPOINTER rejects queued stale document state\nPASS: replacement document obtains a fresh generation\nPASS: explicit release removes lifecycle state\nPASS: large Ru selection only queues work\nPASS: large Ru initial scan completes\nPASS: initial scan reads source exactly once in bounded chunks\nPASS: no native range exceeds 1024 UTF-8 bytes\nPASS: same-byte edit proves full-state checkpoint convergence\nPASS: ordinary edit does not rescan the full document\nPASS: performance edit preserves document length\nPASS: same-byte replacement retains Ru identifier byte style\nPASS: background styling preserves edited dirty state\nPASS: single undo after background scan reaches original savepoint\nPERF_RU size=100000 initial_ms=2175.37049999973 edit_ms=702.590199999977 initial_read_bytes=100000 edit_read_bytes=32768 reused_bytes=67232 max_read=1024 max_tick_ms=9.27929999958724 max_chunk_ms=2.73940000031143\nPASS: two distant coalesced replacements converge only after both changed ranges\nPASS: both coalesced replacements receive correct byte styles\nPASS: two edits retain their original undo history through convergence\nPASS: insertion and deletion at different positions can safely converge\nPASS: net-zero shifted replacement has correct combined identifier style\nPASS: net-zero edit revisits styles published beyond an intermediate checkpoint\nPASS: large Ru selection only queues work\n'


KNOWN_GRAPH = [{'repository': 'app', 'path': 'src/editor.ru', 'sha256': '8970ba9ed54095cb2df707e606f15140d76c639b705cbee5949c23e36e752c3e', 'size': 13352}, {'repository': 'app', 'path': 'src/i18n.ru', 'sha256': 'e5ed0325977748d3567d60e61f13f17e3db31c8b5afa7c34eec5703d649cbe85', 'size': 2354}, {'repository': 'app', 'path': 'src/i18n_catalog.ru', 'sha256': 'e2b6d48d25529c7d631652980ec45d6a5dc837467e505e58fbe581a352fe84db', 'size': 189710}, {'repository': 'app', 'path': 'src/markdown_policy.ru', 'sha256': 'e9658000e1c5fbe5fb49403af2a27eb11a0efb9d4bf5261617b760688ea2d720', 'size': 13382}, {'repository': 'app', 'path': 'src/markdown_syntax.ru', 'sha256': '8ae5c6b71f48fd3e374095cbcbb0e1585ba1aea54d2a592d03446d49da760ce3', 'size': 41454}, {'repository': 'app', 'path': 'src/ru_lexical.ru', 'sha256': '188b92786bb5d8a5f45d26d60cef87fbb059edf41ecef4976da8f9b8c82162e7', 'size': 40867}, {'repository': 'app', 'path': 'src/ru_native_syntax.ru', 'sha256': '7a46ce9621d658b5fbec64e2540d1a418d7aa6808eed18563656a80afce5ae38', 'size': 11736}, {'repository': 'app', 'path': 'src/ru_syntax.ru', 'sha256': '484061b2994db7e20c914bc61654eee726b632c620c8babce51bf73e20985442', 'size': 27616}, {'repository': 'app', 'path': 'src/syntax.ru', 'sha256': '1fc38616d696ff524398e51570135463918e349e2dd80d046a7bc53c0656391f', 'size': 13943}, {'repository': 'app', 'path': 'src/syntax_policy.ru', 'sha256': 'd863ddcc76a0c3eae587378476ad3a4dd460a38dddec358f72987c9e1262fad2', 'size': 2259}, {'repository': 'app', 'path': 'src/win32.ru', 'sha256': 'addd9b27f75864b15346664574b07fd536240019a9b3f5a33a02d73ab72a05b2', 'size': 16459}, {'repository': 'app', 'path': 'tests/bootstrap_pipeline/dll_abi_probe.ru', 'sha256': 'fc478d45a9f26e955b92c7d76e355fc573b2062ede7d2eb85cbaa135f31cf358', 'size': 2144}, {'repository': 'app', 'path': 'tests/editor_native.ru', 'sha256': '9b00df895196e081ead36041e4d336d17f8ee3a60c1422ea1cdfe0a8d9f138f2', 'size': 13451}, {'repository': 'app', 'path': 'tests/markdown_native.ru', 'sha256': '5f99ebd689d46d89e585dae4819abfce31f3dc16caed5d23a6a7f95bb62b199a', 'size': 29253}, {'repository': 'app', 'path': 'tests/ru_syntax_native.ru', 'sha256': '02b87a94f49818e197dc9996b9bf92419ec6e74a1a00c6ea22b41edbe0c5a3a2', 'size': 37188}, {'repository': 'language', 'path': 'rulang/stdlib/密.ru', 'sha256': '174a64c1c03499469ad825429db98577a314958cfb070d8c87bd03c4ca23700d', 'size': 1114}]
KNOWN_FULL = 'Ru Notepad diagnostic log\n[launcher] Starting Ru program.\nPASS: production bulk decoder matches all six old-decoder fields across a full 64-event batch\nPASS: production bulk decoder checks high bits in the last event of a full batch\nPASS: production bulk decoder preserves exact near-32-MB event coordinates and unsigned metadata\nPASS: production bulk decoder rejects high-bit corruption 0 before combining words\nPASS: production bulk decoder rejects high-bit corruption 1 before combining words\nPASS: production bulk decoder rejects high-bit corruption 2 before combining words\nPASS: production bulk decoder ignores stale event bytes when the native count is zero\nPASS: production bulk decoder rejects a count exceeding its 1024-byte event capacity\nPASS: production bulk decoder rejects a negative count\nPASS: production bulk decoder rejects a fractional count\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 0\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 1\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 2\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 3\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 4\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 5\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 6\nPASS: production bulk decoder rejects malformed kind/style/length/position/line 7\nPASS: production bulk decoder rejects a non-token before the styled range\nPASS: production bulk decoder preserves long identifier events starting before the styled range\nPASS: production bulk decoder preserves the 64-byte delayed keyword boundary\nPASS: production bulk decoder rejects decreasing event positions\nPASS: production bulk decoder preserves equal-position event ordering\nPASS: decoded event rows remain detached after source mutation and closure\nPASS: checked low49 decoding preserves event coordinates near the 32 MB boundary\nPASS: corrupt high event bits fail ordinarily before any lossy native conversion\nPASS: initial checkpoint failure releases the already-created native context exactly once\nPASS: failed initialization returns no released context or checkpoint to the plain fallback\nPASS: initial checkpoint failure keeps its specific visible warning outside rescue scope\nPASS: Ru attaches independently of Lexilla availability\nPASS: Ru uses real SCLEX_CONTAINER instead of borrowed lexer\nPASS: selection never performs eager lexical scanning\nPASS: real SCN_STYLENEEDED reaches the owning container bridge\nPASS: style-needed notification queues without synchronous rescanning\nPASS: container queue drains without fallback\nPASS: every UTF-8 byte of 算 is a keyword\nPASS: Han function name retains identifier style\nPASS: every Han and emoji byte in quoted string is styled\nPASS: number following multibyte source has correct byte offset\nPASS: function header has base fold level and header flag\nPASS: if header nests exactly once\nPASS: function and if body has depth two\nPASS: 法 closes matching function level\nPASS: styling and folding preserve exact UTF-8 text\nPASS: styling and folding never dirty a clean document\nPASS: styling and folding create no undo entry\nPASS: styling preserves selection anchor and caret\nPASS: Ru palette preserves line-number style\nPASS: dedicated fold margin is visible\nPASS: fold action accepts completed owning document\nPASS: collapse actually hides nested native lines\nPASS: collapse changes native expanded flag\nPASS: expand restores native line visibility\nPASS: plain switch reveals every previously hidden line\nPASS: plain switch clears old fold levels\nPASS: plain switch clears all Ru style bytes\nPASS: plain switch cancels scanner state\nPASS: C++ switch reveals every Ru fold even without Lexilla\nPASS: JSON switch reveals every Ru fold even without Lexilla\nPASS: first typing into empty Ru document restarts a nonterminal checkpoint\nPASS: EOF append never restores a finished scanner\nPASS: EOF undo and redo remain incrementally highlighted\nPASS: multiline quote initially styles Han bytes\nPASS: deleting opening quote invalidates multiline lexical state\nPASS: undo restores multiline quote state\nPASS: Ru block comment spans Han and emoji bytes\nPASS: Ru keyword resumes after the real 释. block-comment terminator\nPASS: same-length comment opener replacement invalidates lexical suffix\nPASS: undo restores Ru multiline comment state\nPASS: real native insert/delete notifications reached owning bridge\nPASS: style and fold notifications are observed without recursive text invalidation\nPASS: UTF-8 quote and emoji styles cross checkpoint boundary correctly\nPASS: deleting LF from checkpoint-adjacent CRLF safely resumes lexical state\nPASS: keyword offset adjusts correctly after CRLF partial deletion\nPASS: bounded timer returns before a large initial scan completes\nPASS: edit during incomplete work invalidates suffix without unsafe reuse\nPASS: unclosed BOF comment propagates through previously pending source\nPASS: removing existing collapsed function headers with BOF comment reveals every old hidden line\nPASS: tentative reference-call opener starts without a fold header\nPASS: temporary statement confirms an opener before the restart checkpoint\nPASS: checkpoint restore retracts a previously published earlier header and reveals its lines\nPASS: BOF insertion unequal edit queues its own revision and preserves exact dirty text\nPASS: BOF insertion incremental text/styles/all fold levels equal an independent fresh scan\nPASS: BOF insertion highlighting preserves one-edit undo and the original savepoint\nPASS: BOF deletion unequal edit queues its own revision and preserves exact dirty text\nPASS: BOF deletion incremental text/styles/all fold levels equal an independent fresh scan\nPASS: BOF deletion highlighting preserves one-edit undo and the original savepoint\nPASS: middle insertion unequal edit queues its own revision and preserves exact dirty text\nPASS: middle insertion incremental text/styles/all fold levels equal an independent fresh scan\nPASS: middle insertion highlighting preserves one-edit undo and the original savepoint\nPASS: middle deletion unequal edit queues its own revision and preserves exact dirty text\nPASS: middle deletion incremental text/styles/all fold levels equal an independent fresh scan\nPASS: middle deletion highlighting preserves one-edit undo and the original savepoint\nPASS: EOF insertion unequal edit queues its own revision and preserves exact dirty text\nPASS: EOF insertion incremental text/styles/all fold levels equal an independent fresh scan\nPASS: EOF insertion highlighting preserves one-edit undo and the original savepoint\nPASS: EOF deletion unequal edit queues its own revision and preserves exact dirty text\nPASS: EOF deletion incremental text/styles/all fold levels equal an independent fresh scan\nPASS: EOF deletion highlighting preserves one-edit undo and the original savepoint\nPASS: matrix multiline edit has published a bounded prefix while work remains pending\nPASS: repeated edits during pending work discard old states and match every fresh byte style and fold level\nPASS: edit in later function preserves unaffected collapsed earlier fold\nPASS: editing one HWND preserves another document byte styles\nPASS: editing one HWND never invalidates another document generation\nPASS: SETDOCPOINTER rejects queued stale document state\nPASS: replacement document obtains a fresh generation\nPASS: explicit release removes lifecycle state\nPASS: large Ru selection only queues work\nPASS: large Ru initial scan completes\nPASS: initial scan reads source exactly once in bounded chunks\nPASS: no native range exceeds 1024 UTF-8 bytes\nPASS: same-byte edit proves full-state checkpoint convergence\nPASS: ordinary edit does not rescan the full document\nPASS: performance edit preserves document length\nPASS: same-byte replacement retains Ru identifier byte style\nPASS: background styling preserves edited dirty state\nPASS: single undo after background scan reaches original savepoint\nPERF_RU size=100000 initial_ms=734.471999999834 edit_ms=256.227100000018 initial_read_bytes=100000 edit_read_bytes=32768 reused_bytes=67232 max_read=1024 max_tick_ms=8.36089999997057 max_chunk_ms=1.51560000004247\nPASS: two distant coalesced replacements converge only after both changed ranges\nPASS: both coalesced replacements receive correct byte styles\nPASS: two edits retain their original undo history through convergence\nPASS: insertion and deletion at different positions can safely converge\nPASS: net-zero shifted replacement has correct combined identifier style\nPASS: net-zero edit revisits styles published beyond an intermediate checkpoint\nPASS: large Ru selection only queues work\nPASS: large Ru initial scan completes\nPASS: initial scan reads source exactly once in bounded chunks\nPASS: no native range exceeds 1024 UTF-8 bytes\nPASS: same-byte edit proves full-state checkpoint convergence\nPASS: ordinary edit does not rescan the full document\nPASS: performance edit preserves document length\nPASS: same-byte replacement retains Ru identifier byte style\nPASS: background styling preserves edited dirty state\nPASS: single undo after background scan reaches original savepoint\nPERF_RU size=1000000 initial_ms=8997.86990000005 edit_ms=309.550499999896 initial_read_bytes=1000000 edit_read_bytes=32768 reused_bytes=967232 max_read=1024 max_tick_ms=8.49820000003092 max_chunk_ms=1.53110000002198\nPASS: GUI-equivalent synchronous corpus has the exact Unicode character and byte counts\nPASS: core synchronous fixture retains Scintilla default all-modification notifications\nPASS: GUI-equivalent synchronous selection queues work without draining it\nRU_GUI_SYNC size=1000000 source_chars=636370 wall_ms=6951.31339999987 read_bytes=1000000 max_read=1023 max_tick_ms=8.44599999999627 max_chunk_ms=1.94280000007711 chunks=8798\nPASS: GUI-equivalent synchronous scan finishes with exact bounded reads\nPASS: GUI-equivalent synchronous scan matches all sixteen head and tail style bytes\nPASS: GUI-equivalent synchronous styling preserves exact source, line count, savepoint and empty undo\nPASS: STYLES_NONE document suppresses Ru even when currently empty\nPASS: large-document mode schedules no scanning\nPASS: large-document styles storage remains disabled\nPASS: unexpected structural complexity reports plain fallback\nPASS: complexity fallback preserves exact clean source\nPASS: complexity fallback leaves all lines visible\nPASS: complexity fallback clears partial style bytes\nPASS: destroyed HWND cannot resume a stale queue\nPASS: surviving editor remains independently styled after sibling destroy\nPASS: all current and shared checkpoint roots explicitly close and release at final teardown\nTOTAL PASS: 149\nBOOTSTRAP_DLL_ABI_PASS:ru\n[launcher] Ru program returned with status 0.\n'

class CensoredObservationTests(unittest.TestCase):
    def model(self, mutate=None, text=None):
        import copy
        spec=importlib.util.spec_from_file_location('diagnostic_metric',ROOT/'tools/diagnose_bootstrap_editor_fixture.py')
        diagnostic=importlib.util.module_from_spec(spec);spec.loader.exec_module(diagnostic)
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary).resolve(); verified={}
            for name in ('Scintilla.dll','Lexilla.dll','RuSyntax.dll'):
                (directory/name).write_bytes(name.encode()); verified[name]=control.identity(directory/name)
            log=directory/'ru_notepad-owned.log'; log.write_bytes((KNOWN_PARTIAL if text is None else text).encode())
            metrics=[diagnostic.metric(line) for line in log.read_text(encoding='utf-8').splitlines() if line.startswith(('PERF_RU ','RU_GUI_SYNC '))]
            row={'passed':False,'executed':True,'cleanup_killed':True,'pid':71,'seconds':60.1,'error':'original timeout message retained',
                'observation':{'schema':'ru-notepad-child-observation-v2','clock':{'started_monotonic':0.0,'deadline_monotonic':60.0,'finished_monotonic':60.1,'budget_seconds':60},'nondeadline_errors':[],
                  'deadline_events':[{'source':'watchdog','budget_seconds':60,'observed_monotonic':60.0,'elapsed_seconds':60.0}],
                  'first_error':{'code':'deadline','phase':'runtime','observed_monotonic':60.02,'elapsed_seconds':60.02,'exception_type':'FunctionalDeadlineError','message':'original deadline'},
                  'cleanup':{'pid':71,'errors':[],'process_reaped':True,'exit_code':1,'windows_remaining':[], 'handshake_closed':True,'watchdog_stopped':True}},
                'diagnostic_module_observations':{'pid':71,'complete':True,'snapshots':2,'verified':verified},
                'partial_log':{'available':True,'identity':control.identity(log),'metrics':metrics}}
            if mutate:mutate(row)
            before=copy.deepcopy(row);result=control.classify_observation(row,directory,diagnostic)
            self.assertEqual(row,before,'classification must never alter old result')
            return result

    def test_exact_deadline_prefix_is_valid_observation_not_program_pass(self):
        result=self.model(); self.assertEqual(result['outcome'],'valid_censored')
        self.assertTrue(result['evidence_complete']);self.assertFalse(result['program_passed'])
        self.assertEqual(result['missing_metrics'],['PERF_RU:1000000','RU_GUI_SYNC:1000000','whole-fixture completion'])
        text=KNOWN_PARTIAL.replace('2175.37049999973','2100.125').replace('702.590199999977','700.5')
        self.assertEqual(self.model(text=text)['outcome'],'valid_censored')

    def test_partial_log_reader_is_bounded_before_hashing(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary).resolve()/'oversized.log';path.write_bytes(b'x'*(1024*1024+1))
            with patch.object(Path,'read_bytes',side_effect=AssertionError('unbounded read forbidden')):
                with self.assertRaisesRegex(ValueError,'exceeds bound'):
                    control.identity(path,max_bytes=1024*1024)

    def test_metrics_are_observed_not_invented_and_bad_utf8_rejected(self):
        lines=KNOWN_FULL.splitlines(True)
        length=next(i for i,line in enumerate(lines) if line.startswith('PERF_RU size=1000000 '))+1
        result=self.model(text=''.join(lines[:length]))
        self.assertIn('PERF_RU:1000000',result['completed_metrics'])
        self.assertNotIn('PERF_RU:1000000',result['missing_metrics'])
        self.assertIn('whole-fixture completion',result['missing_metrics'])
        def corrupt(row):
            path=Path(row['partial_log']['identity']['path']);path.write_bytes(b'bad\xff\n')
            row['partial_log']['identity']=control.identity(path);row['partial_log']['metrics']=[]
        self.assertEqual(self.model(corrupt)['outcome'],'invalid')

    def test_absolute_deadline_not_subtraction_threshold(self):
        def rounded(row):
            clock=row['observation']['clock'];clock.update(started_monotonic=4.002,deadline_monotonic=64.002,finished_monotonic=64.1)
            row['seconds']=clock['finished_monotonic']-clock['started_monotonic']
            for record in [row['observation']['first_error'],*row['observation']['deadline_events']]:
                record.update(observed_monotonic=64.002,elapsed_seconds=64.002-4.002)
        self.assertLess(64.002-4.002,60)
        self.assertEqual(self.model(rounded)['outcome'],'valid_censored')
        def early(row):
            import math
            rounded(row)
            for record in [row['observation']['first_error'],*row['observation']['deadline_events']]:
                now=math.nextafter(64.002,-math.inf)
                record.update(observed_monotonic=now,elapsed_seconds=now-4.002)
        self.assertEqual(self.model(early)['outcome'],'invalid')

    def test_clock_missing_forged_nonfinite_and_v1_rejected(self):
        for key,value in [('started_monotonic',1),('deadline_monotonic',61),('finished_monotonic',66),('started_monotonic',float('nan')),('deadline_monotonic',float('inf')),('budget_seconds',True)]:
            with self.subTest(key=key,value=value):
                self.assertEqual(self.model(lambda row:row['observation']['clock'].update({key:value}))['outcome'],'invalid')
        self.assertEqual(self.model(lambda row:row['observation'].pop('clock'))['outcome'],'invalid')
        self.assertEqual(self.model(lambda row:row['observation'].update(schema='ru-notepad-child-observation-v1'))['outcome'],'invalid')

    def test_every_nonempty_complete_strict_prefix_is_observational_only(self):
        lines=KNOWN_FULL.splitlines(True)
        for length in range(1,len(lines)):
            with self.subTest(length=length):
                result=self.model(text=''.join(lines[:length]))
                self.assertEqual(result['outcome'],'valid_censored')
                self.assertFalse(result['program_passed'])
                self.assertTrue(result['not_proof_of_progress_or_no_hang'])
        for text in ['',KNOWN_FULL,KNOWN_FULL+'extra\n',KNOWN_FULL[:40],KNOWN_PARTIAL+'FAIL: error\n',KNOWN_PARTIAL+'fatal: error\n']:
            self.assertEqual(self.model(text=text)['outcome'],'invalid')

    def test_frozen_oracle_order_duplicate_and_graph_mutations_rejected(self):
        lines=KNOWN_FULL.splitlines(True)
        for values in [lines[:10]+[lines[9]],lines[:5]+[lines[6],lines[5]],lines[:10]+['PASS: unknown\n']]:
            self.assertEqual(self.model(text=''.join(values))['outcome'],'invalid')
        control.validate_progress_graph(KNOWN_GRAPH)
        import copy
        bad=copy.deepcopy(KNOWN_GRAPH);bad[0]['sha256']='0'*64
        for graph in [bad,KNOWN_GRAPH[:-1],list(reversed(KNOWN_GRAPH))]:
            with self.assertRaises(ValueError):control.validate_progress_graph(graph)

    def test_925_missing_observation_is_not_upgraded(self):
        self.assertEqual(self.model(lambda row:row.pop('observation'))['outcome'],'invalid')

    def test_unknown_first_error_wins_even_when_later_deadline(self):
        for field,value in [('code','exception'),('exception_type','ValueError'),('phase','cleanup'),('elapsed_seconds',59.99)]:
            with self.subTest(field=field):
                self.assertEqual(self.model(lambda row:row['observation']['first_error'].update({field:value}))['outcome'],'invalid')
        self.assertEqual(self.model(lambda row:row['observation'].update(first_error=None))['outcome'],'invalid')

    def test_all_non_deadline_errors_reject_even_after_deadline(self):
        error={'code':'exception','phase':'runtime','elapsed_seconds':60.03,'exception_type':'ValueError','message':'independent later failure'}
        self.assertEqual(self.model(lambda row:row['observation'].update(nondeadline_errors=[error]))['outcome'],'invalid')
        self.assertEqual(self.model(lambda row:row['observation'].pop('nondeadline_errors'))['outcome'],'invalid')

    def test_postcheck_only_and_wrong_budget_or_timing_rejected(self):
        for field,value in [('source','elapsed-postcheck'),('budget_seconds',61),('budget_seconds',True),('elapsed_seconds',59.9),('elapsed_seconds',float('nan')),('elapsed_seconds',float('inf')),('elapsed_seconds',61)]:
            with self.subTest(field=field,value=value):
                self.assertEqual(self.model(lambda row:row['observation']['deadline_events'][0].update({field:value}))['outcome'],'invalid')
        for value in (59.9,65.1,float('nan'),True):
            self.assertEqual(self.model(lambda row:row.update(seconds=value))['outcome'],'invalid')

    def test_every_cleanup_condition_required(self):
        for field,value in [('pid',72),('errors',['wait failed']),('process_reaped',False),('exit_code',None),('exit_code',0),('windows_remaining',[1]),('handshake_closed',False),('watchdog_stopped',None)]:
            with self.subTest(field=field):
                self.assertEqual(self.model(lambda row:row['observation']['cleanup'].update({field:value}))['outcome'],'invalid')
        self.assertEqual(self.model(lambda row:row.update(exit_code=2))['outcome'],'invalid')

    def test_owned_mapping_log_and_status_required(self):
        mutations=[lambda row:row.update(passed=True),lambda row:row.update(executed=False),lambda row:row.update(cleanup_killed=False),
            lambda row:row['diagnostic_module_observations'].update(complete=False),lambda row:row['diagnostic_module_observations'].update(pid=72),
            lambda row:row['diagnostic_module_observations']['verified'].pop('RuSyntax.dll'),
            lambda row:row['partial_log'].update(available=False),lambda row:row['partial_log'].update(metrics=[]),
            lambda row:row['partial_log']['identity'].update(sha256='0'*64)]
        for mutation in mutations:self.assertEqual(self.model(mutation)['outcome'],'invalid')

    def test_known_prefix_only_no_assertion_or_work_changes(self):
        for text in (KNOWN_PARTIAL+'FAIL: hidden\n',KNOWN_PARTIAL.replace('PASS:','FAIL:',1),
                     KNOWN_PARTIAL.replace('edit_read_bytes=32768','edit_read_bytes=32767'),
                     KNOWN_PARTIAL.replace('initial_ms=2175.37049999973','initial_ms=60001'),
                     KNOWN_PARTIAL.replace('large Ru selection only queues work','unknown stop'),
                     KNOWN_PARTIAL.rstrip('\n')):
            with self.subTest(tail=text[-45:]):self.assertEqual(self.model(text=text)['outcome'],'invalid')

    def test_new_route_failure_still_fails_parent_despite_valid_old_censor(self):
        with patch.object(control,'classify_observation',return_value={'outcome':'valid_censored','evidence_complete':True,'program_passed':False}):
            result=SlotControlTests().run_model(passed=False,new_passed=True)
            self.assertTrue(result['diagnostic_integrity_passed']);self.assertFalse(result['old']['passed'])
            result=SlotControlTests().run_model(passed=False,new_passed=False)
            self.assertFalse(result['diagnostic_integrity_passed'])
        with patch.object(control,'classify_observation',return_value={'outcome':'invalid','evidence_complete':False}):
            self.assertFalse(SlotControlTests().run_model()['diagnostic_integrity_passed'])


if __name__=='__main__': unittest.main()
