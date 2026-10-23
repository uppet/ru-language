"""Portable fixed-wrapper diagnostic contracts; not Windows execution."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

PATH=Path(__file__).resolve().parents[1]/'tools/diagnose_bootstrap_launcher_windows.py'
spec=importlib.util.spec_from_file_location('launcher_diagnostic',PATH)
diag=importlib.util.module_from_spec(spec);spec.loader.exec_module(diag)


class LauncherDiagnosticTests(unittest.TestCase):
    def test_fixed_c_is_only_sentinel_main_not_a_language_frontend(self):
        self.assertIn(b'int main(int argc, char **argv)',diag.SOURCE)
        self.assertIn(diag.MARKER.encode(),diag.SOURCE)
        self.assertIn(diag.SENTINEL.encode(),diag.SOURCE)
        self.assertNotIn(b'system(',diag.SOURCE)
        self.assertNotIn(b'LoadLibrary',diag.SOURCE)

    def test_plan_preserves_main_fixed_wrapper_gui_crt_and_locked_linker(self):
        tools={'clang':'clang.exe','resource-compiler':'rc.exe'}
        flags=['-fuse-ld=link.exe','-Blocked dir']
        plan=diag.plans(tools,Path('app'),Path('owned'),'x86_64-pc-windows-msvc19.0',flags)
        self.assertEqual(len(plan),4)
        self.assertIn(str(Path('app')/'packaging/bootstrap_gui_launcher.c'),plan[1])
        self.assertIn('/ENTRY:wWinMainCRTStartup',plan[-1])
        self.assertIn('/SUBSYSTEM:WINDOWS',plan[-1])
        for index in (0,1,3):self.assertEqual(plan[index][1],'--target=x86_64-pc-windows-msvc19.0')
        self.assertEqual([x for x in plan[-1] if x.startswith(('-fuse-ld','-B'))],flags)
        self.assertFalse(any('main=' in x or x.endswith('.ll') for argv in plan for x in argv))

    def test_valid_failure_does_not_hide_invalid_and_sentinel_failure_stays_red(self):
        class Gate:
            @staticmethod
            def identity(path):
                p=Path(path);b=p.read_bytes()
                return {'path':str(p.resolve()),'sha256':hashlib.sha256(b).hexdigest(),'size':len(b)}
        for mode in ('good','invalid-entered-main','valid-no-sentinel','gate-failed','invalid-side-effect-even-gate-pass'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);binary=root/'input.exe';binary.write_bytes(b'fixed GUI')
                calls=[]
                def run(api,exe,args,invalid,marker):
                    calls.append((invalid,args,marker))
                    if (not invalid and mode!='valid-no-sentinel') or (invalid and mode in ('invalid-entered-main','invalid-side-effect-even-gate-pass')):
                        (exe.parent/diag.SENTINEL).write_bytes(b'entered\n')
                    return {'passed':mode!='gate-failed','executed':True,'cleanup_killed':False}
                gate=Gate();gate.run_child=run;copies=[]
                results=diag.run_cases(gate,object(),gate.identity(binary),root,copies)
                self.assertEqual([c[0] for c in calls],[False,True])
                self.assertEqual(calls[1][1],['\ud800'])
                self.assertEqual(len(copies),2)
                self.assertEqual(results['valid-main']['passed'],mode not in ('valid-no-sentinel','gate-failed'))
                self.assertEqual(results['invalid-surrogate']['passed'],mode not in ('invalid-entered-main','invalid-side-effect-even-gate-pass','gate-failed'))
                self.assertFalse(any('bootstrap_acceptance' in row for row in results.values()))

    def test_copy_changed_is_not_executed(self):
        class Gate:
            def identity(self,path):return {'path':str(path),'sha256':'wrong','size':1}
            def run_child(self,*args,**kwargs):self.fail('must not execute')
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);binary=p/'source.exe';binary.write_bytes(b'x')
            with self.assertRaisesRegex(ValueError,'copy changed'):
                diag.run_cases(Gate(),object(),{'path':str(binary),'sha256':'expected','size':1},p,[])

    def test_main_writes_failed_diagnostic_and_never_bootstrap_permission(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);config=p/'config.json';config.write_text('{}');out=p/'out.json'
            with patch.object(diag.sys,'argv',['probe','--config',str(config),'--owned-root',str(p/'owned'),'--output',str(out)]),patch.object(diag,'diagnose',side_effect=ValueError('tool identity mismatch')):
                self.assertEqual(diag.main(),1)
            result=json.loads(out.read_bytes())
            self.assertFalse(result['release_permission']);self.assertFalse(result['bootstrap_acceptance'])
            self.assertEqual(result['status'],'diagnostic-failed')

    def test_tool_only_build_receipt_uses_fixed_sources_without_stage3(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();app=root/'app';language=root/'language';owned=root/'owned'
            appnames=('tools/build_bootstrap_release.py','tools/verify_bootstrap_editor_windows.py','packaging/bootstrap_gui_launcher.c','packaging/diagnostic_launcher.c','packaging/app.rc','packaging/app.manifest','assets/app-icon.ico')
            runames=('tools/diagnose_bootstrap_launcher_windows.py','tests/test_bootstrap_launcher_diagnostic.py','tools/diagnose_bootstrap_editor_fixture.py','.github/workflows/bootstrap-native.yml','rulang/toolchain_environment.py')
            for base,names in ((app,appnames),(language,runames)):
                for name in names:
                    p=base/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixed input')
            (language/'rulang/toolchain_environment.py').write_text('def llvm_environment(): return {}\n')
            def identity(path):
                p=Path(path);b=p.read_bytes();return {'path':str(p.resolve()),'sha256':diag.digest(b),'size':len(b)}
            def snapshot(path,*pins):return {str(p.relative_to(path)).replace('\\','/'):identity(p)['sha256'] for p in path.rglob('*') if p.is_file() and '__pycache__' not in str(p)}
            tools={name:str(root/(name+'.exe')) for name in ('clang','llvm-as','llvm-link','opt','llvm-dis','llc','linker','resource-compiler')}
            for p in tools.values():Path(p).write_bytes(b'locked')
            hashes={name:identity(p)['sha256'] for name,p in tools.items()}
            def validate(paths,expected):
                for name,p in paths.items():self.assertEqual(identity(p)['sha256'],expected[name])
            def verify(record):self.assertEqual(identity(record['path']),record);return Path(record['path'])
            selections=[]
            def inspect(argv,*args):selections.append(argv);return {'command':argv}
            driver=SimpleNamespace(__file__=str(app/appnames[0]),snapshot=snapshot,verify_app_baseline=lambda *a:None,
                identity=identity,validate_toolchain=validate,explicit_linker_flags=lambda r:['-fuse-ld=link.exe','-B'+str(root)],
                inspect_linker_command=inspect,verify_linker_selection=lambda *a,**kw:None,verify_gui_pe=lambda p:self.assertEqual(p.read_bytes(),b'output'))
            children=[]
            def child(api,binary,args,invalid,marker):
                children.append((binary,args,invalid))
                if not invalid:(binary.parent/diag.SENTINEL).write_bytes(b'entered\n')
                return {'passed':True,'executed':True}
            gate=SimpleNamespace(__file__=str(app/appnames[1]),identity=identity,verify_identity=verify,
                run_child=child,load_windows_harness=lambda app:SimpleNamespace(Windows=lambda:object()),verify_log_records=lambda results:None)
            def fresh(path,roots):path.mkdir();return path
            helper=SimpleNamespace(__file__=str(language/'tools/diagnose_bootstrap_editor_fixture.py'),fresh_owned=fresh)
            modules={'build_bootstrap_release':driver,'verify_bootstrap_editor_windows':gate,'diagnose_bootstrap_editor_fixture':helper}
            commands=[]
            def execute(argv,**kw):
                commands.append(argv);self.assertEqual(kw['timeout'],600)
                if '--version' in argv:stdout=b'clang version 14.0.6\n'
                elif '-S' in argv:stdout=b'target triple = "x86_64-pc-windows-msvc19.0"\ntarget datalayout = "e-m:w"\n'
                else:
                    flag='/fo' if '/fo' in argv else '-o';Path(argv[argv.index(flag)+1]).write_bytes(b'output');stdout=b''
                kw['stdout'].write(stdout);kw['stderr'].write(b'');return SimpleNamespace(returncode=0)
            config={'schema':'ru-notepad-bootstrap-llvm-config-v1','app_source':{'path':str(app),'commit':'a'*40,'tree':'b'*40},'ru_source':{'path':str(language),'commit':'c'*40,'tree':'d'*40},'app_baseline':{},'tool_paths':tools,'tool_sha256':hashes}
            with patch.object(diag.sys,'platform','win32'),patch.object(diag.platform,'machine',return_value='AMD64'), \
                    patch.object(diag,'__file__',str(language/runames[0])),patch.object(diag.importlib,'import_module',side_effect=lambda name:modules[name]), \
                    patch.object(diag.subprocess,'run',execute),patch.object(diag.sys,'dont_write_bytecode',True):
                result=diag.diagnose(config,owned)
            self.assertEqual(result['status'],'diagnostic-passed',result.get('error'))
            self.assertFalse(result['bootstrap_acceptance']);self.assertFalse(result['release_permission'])
            self.assertEqual(len(commands),6);self.assertEqual(len(selections),1)
            self.assertEqual([c[2] for c in children],[False,True])
            self.assertEqual(len(result['production_glue_inputs']),5)
            self.assertTrue(all('environment' not in row for row in result['commands']))
            self.assertNotIn('bootstrap',result)

    def test_workflow_early_upload_cannot_mask_failure_or_replace_gui_gate(self):
        source=(PATH.parents[1]/'.github/workflows/bootstrap-native.yml').read_text(encoding='utf-8')
        self.assertLess(source.index('id: launcher_diag'),source.index('Fresh three-stage bootstrap and complete fixed-point report'))
        self.assertIn("if ('${{ steps.launcher_diag.outcome }}' -ne 'success') { exit 1 }",source)
        self.assertIn('Real owned-process GUI resources Unicode argv DLL ABI callbacks and window lifecycle',source)
        early=source[source.index('      - name: Upload early fixed-wrapper'):source.index('      - name: Fresh three-stage')]
        self.assertIn('if: always()',early)
        self.assertIn('launcher-preflight.json',early)
        self.assertIn('launcher-owned/**/*.log',early)
        self.assertNotIn('*.exe',early);self.assertNotIn('*.zip',early)
        self.assertIn('timeout-minutes: 60',source)

    def test_nonwindows_cannot_issue_commands(self):
        with patch.object(diag.sys,'platform','linux'),patch.object(diag.subprocess,'run',side_effect=AssertionError('unexpected execution')):
            with self.assertRaisesRegex(ValueError,'real Windows'):diag.diagnose({},Path('unused'))


if __name__=='__main__':unittest.main()
