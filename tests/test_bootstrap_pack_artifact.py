import copy
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

from tools import bootstrap_pack_artifact as m


def metadata():
    run = dict(id=m.RUN, head_sha=m.COMMIT, event='push', path='.github/workflows/bootstrap-slot-address.yml',
               repository={'full_name': m.REPOSITORY}, head_repository={'full_name': m.REPOSITORY}, conclusion='failure')
    job = dict(id=m.JOB, run_id=m.RUN, head_sha=m.COMMIT, status='completed', conclusion='success', name='slot-bootstrap (windows-latest)')
    artifact = dict(id=m.ARTIFACT, workflow_run={'id': m.RUN, 'head_sha': m.COMMIT}, name='bootstrap-slot-windows-latest-'+m.COMMIT,
                    expired=False, digest='sha256:'+m.ZIP_SHA256, size_in_bytes=m.ZIP_SIZE)
    return run, {'total_count': 1, 'jobs': [job]}, {'total_count': 1, 'artifacts': [artifact]}


def archive(change=None, *, current=False, extra=()):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        for name in sorted((m.CURRENT_CORE if current else m.CORE | m.IGNORED) | set(extra)):
            info = zipfile.ZipInfo(name)
            # Preserve deliberately invalid raw names; ZipInfo otherwise normalizes them.
            info.filename = name
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            if change:
                change(info)
            z.writestr(info, b'fixture')
    return stream.getvalue()


class Response(io.BytesIO):
    status = 200
    headers = {}


class Opener:
    def __init__(self, steps):
        self.steps, self.requests = list(steps), []
    def open(self, request, timeout):
        self.requests.append(request)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return Response(step)


def redirect(url):
    return urllib.error.HTTPError('https://api.github.com/secret', 302, 'secret', {'Location': url}, io.BytesIO())


class OldArtifactTests(unittest.TestCase):
    def test_metadata_allows_separate_gui_failure(self):
        m.validate_metadata(*metadata())

    def test_metadata_identity_and_completeness_rejections(self):
        for mutate in (
            lambda r,j,a: r.update(head_sha='0'*40),
            lambda r,j,a: r.update(repository={'full_name':'attacker/repo'}),
            lambda r,j,a: j['jobs'][0].update(head_sha='0'*40),
            lambda r,j,a: j['jobs'][0].update(conclusion='cancelled'),
            lambda r,j,a: a['artifacts'][0].update(expired=True),
            lambda r,j,a: a['artifacts'][0].update(digest='sha256:'+'0'*64),
            lambda r,j,a: a['artifacts'][0].update(workflow_run={'id':m.RUN+1,'head_sha':m.COMMIT}),
            lambda r,j,a: j.update(total_count=2),
            lambda r,j,a: j['jobs'].append(copy.deepcopy(j['jobs'][0])),
        ):
            values = metadata(); mutate(*values)
            with self.subTest(mutate=mutate), self.assertRaises(RuntimeError):
                m.validate_metadata(*values)

    def test_json_duplicate_invalid_utf8_bounds(self):
        for raw in (b'{"a":1,"a":2}', b'\xff', b' '*(m.MAX_JSON+1)):
            with self.assertRaises(RuntimeError): m.decode(raw)

    def test_zip_exact_core_extraction(self):
        self.assertEqual(set(m.extract_core(archive())), m.CORE)

    def test_zip_paths_modes_unknown_duplicate(self):
        for mode in ('traversal','absolute','backslash','unknown','duplicate','symlink'):
            def change(info):
                if info.filename != 'stage1.exe': return
                if mode == 'symlink': info.external_attr = (stat.S_IFLNK | 0o777)<<16
                else: info.filename = {'traversal':'../stage1.exe','absolute':'/stage1.exe','backslash':'a\\stage1.exe',
                                       'unknown':'unknown','duplicate':'stage2.exe'}[mode]
            with self.subTest(mode=mode), self.assertRaises(RuntimeError): m.extract_core(archive(change))

    def test_tampered_archive_fails_pin_before_extract(self):
        with patch.object(m,'extract_core',side_effect=AssertionError('must not extract')):
            with self.assertRaises(RuntimeError): m.verify_archive(b'wrong')

    def test_zip_expansion_bound(self):
        with patch.object(m,'MAX_MEMBER',1), self.assertRaises(RuntimeError): m.extract_core(archive())
        with patch.object(m,'MAX_EXPANDED',1), self.assertRaises(RuntimeError): m.extract_core(archive())

    def test_redirect_strips_token_and_only_get(self):
        opener = Opener([redirect('https://productionresultssa1.blob.core.windows.net/a?sig=secret'), b'zip'])
        self.assertEqual(m.fetch('artifacts/'+str(m.ARTIFACT)+'/zip','TOKEN',archive=True,opener=opener),b'zip')
        self.assertEqual(opener.requests[0].get_header('Authorization'),'Bearer TOKEN')
        self.assertIsNone(opener.requests[1].get_header('Authorization'))
        self.assertTrue(all(r.get_method()=='GET' for r in opener.requests))

    def test_redirect_rejects_unsafe_hosts_and_api_return(self):
        for url in ('http://objects.githubusercontent.com/a','https://evil.test/a','https://objects.githubusercontent.com.evil/a',
                    'https://api.github.com/a','https://user@objects.githubusercontent.com/a','https://objects.githubusercontent.com:80/a',
                    'https://objects.githubusercontent.com:bad/a','https://objects.githubusercontent.com/a#secret'):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                m.fetch('artifacts/'+str(m.ARTIFACT)+'/zip','TOKEN',archive=True,opener=Opener([redirect(url)]))

    def test_metadata_redirect_and_arbitrary_path_rejected(self):
        with self.assertRaises(RuntimeError): m.fetch('runs/'+str(m.RUN),'TOKEN',opener=Opener([redirect('https://objects.githubusercontent.com/a')]))
        with self.assertRaises(RuntimeError): m.fetch('evil','TOKEN',opener=Opener([]))
        with self.assertRaises(RuntimeError): m.fetch('runs/'+str(m.RUN),'TOKEN',archive=True,opener=Opener([]))

    def test_redirect_limit(self):
        opener=Opener([redirect('https://objects.githubusercontent.com/a') for _ in range(4)])
        with self.assertRaises(RuntimeError): m.fetch('artifacts/'+str(m.ARTIFACT)+'/zip','TOKEN',archive=True,opener=opener)
        self.assertEqual(len(opener.requests),4)

    def test_missing_credentials_no_network_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp).resolve()/'fresh'
            with patch.object(m,'fetch',side_effect=AssertionError('network')):
                for token in (None,'','\nsecret'):
                    with self.assertRaises(RuntimeError): m.obtain(out,token)
            self.assertFalse(out.exists())

    def test_response_bounds(self):
        with self.assertRaises(RuntimeError): m.bounded_read(Response(b'123'),2)
        response=Response(b''); response.headers={'Content-Length':'999'}
        with self.assertRaises(RuntimeError): m.bounded_read(response,2)

    def test_output_requires_exact_members_and_no_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp).resolve()
            with self.assertRaises(RuntimeError): m.verify_output(path)
            target=path/'file'; target.write_bytes(b'x')
            link=path/'link'
            try: link.symlink_to(target)
            except OSError: return  # Windows link privilege is not needed for reparse-model check below.
            with self.assertRaises(RuntimeError): m.read_fixed(link,1)

    def test_windows_reparse_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp).resolve()
            real=path.lstat()
            class Info:
                st_mode=real.st_mode
                st_file_attributes=0x400
            with patch.object(Path,'lstat',return_value=Info()), patch.object(Path,'resolve',return_value=path):
                with self.assertRaises(RuntimeError): m.no_links(path)

    def test_main_error_never_logs_secret(self):
        import contextlib
        import sys
        err=io.StringIO()
        with patch.object(sys,'argv',['loader','old','--output','/unused','--receipt-output','/unused-pin.json']), patch.object(m,'obtain',side_effect=RuntimeError('TOKEN https://signed?sig=secret')), contextlib.redirect_stderr(err):
            self.assertEqual(m.main(),1)
        self.assertNotIn('TOKEN',err.getvalue()); self.assertNotIn('sig=',err.getvalue())


if __name__=='__main__': unittest.main()


class CurrentArtifactTests(unittest.TestCase):
    def values(self):
        values=metadata()
        values[0]['path']='.github/workflows/bootstrap-argument-pack.yml'
        values[0]['head_branch']='feature/bootstrap-argument-pack-20261023'
        values[1]['jobs'][0]['name']='pack-bootstrap (windows-latest)'
        values[2]['artifacts'][0]['name']='bootstrap-pack-windows-latest-'+m.COMMIT
        return values

    def test_current_exact_successful_matrix_selection(self):
        identity=m.select_current(*self.values(),run_id=m.RUN,commit=m.COMMIT,tree=m.TREE)
        self.assertTrue(identity['current'])
        self.assertEqual(identity['ARTIFACT'],m.ARTIFACT)

    def test_current_ambiguous_failed_stale_or_wrong_workflow(self):
        for mutate in (
            lambda r,j,a:j['jobs'].append(dict(j['jobs'][0],id=m.JOB+1)),
            lambda r,j,a:a['artifacts'].append(dict(a['artifacts'][0],id=m.ARTIFACT+1)),
            lambda r,j,a:j['jobs'][0].update(conclusion='failure'),
            lambda r,j,a:r.update(head_sha='1'*40),
            lambda r,j,a:r.update(path='.github/workflows/bootstrap-native.yml'),
            lambda r,j,a:r.update(head_branch='main'),
            lambda r,j,a:a['artifacts'][0].update(expired=True),
            lambda r,j,a:a['artifacts'][0].update(size_in_bytes=m.MAX_ZIP+1),
            lambda r,j,a:a['artifacts'][0].update(digest=''),
        ):
            values=self.values(); mutate(*values)
            with self.subTest(mutate=mutate), self.assertRaises(RuntimeError):
                m.select_current(*values,run_id=m.RUN,commit=m.COMMIT,tree=m.TREE)

    def test_current_member_scope_and_structural_checks(self):
        self.assertTrue(m.current_member('pack-runtime-artifacts-'+'a'*32+'/case/runtime.c'))
        self.assertFalse(m.current_member('arbitrary.txt'))
        self.assertFalse(m.current_member('pack-runtime-artifacts-wrong/case/runtime.c'))
        self.assertFalse(m.current_member('slot-runtime-artifacts-'+'a'*32+'/case/runtime.c'))
        def traversal(info):
            if info.filename=='stage1.exe': info.filename='../stage1.exe'
        with self.assertRaises(RuntimeError):m.extract_core(archive(traversal,current=True),current=True)

    def test_current_missing_context_hard_failure(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(m,'fetch',side_effect=AssertionError('network')):
            for run,commit,tree in ((0,m.COMMIT,m.TREE),(m.RUN,'',m.TREE),(m.RUN,m.COMMIT,'')):
                with self.assertRaises(RuntimeError):
                    m.obtain_current(Path(tmp).resolve()/'new',None,run_id=run,commit=commit,tree=tree)

    def test_current_receipt_requires_external_pin_before_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp).resolve()
            names=m.CURRENT_CORE|{'archive.zip','run.json','jobs.json','artifacts.json','receipt.json'}
            for name in names:(output/name).write_bytes(b'{}')
            (output/'receipt.json').write_text(json.dumps({'identity':dict(m.OLD,current=True)}),encoding='utf-8')
            with patch.object(m,'verify_archive',side_effect=AssertionError('not reached')):
                with self.assertRaises(RuntimeError):m.verify_output(output)
                with self.assertRaises(RuntimeError):m.verify_output(output,expected_receipt_sha256='0'*64)


class CheckoutIdentityTests(unittest.TestCase):
    def test_context_tree_requires_exact_current_sha_and_readonly_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace=str(Path(tmp).resolve())
            repo=Path(workspace)/'language'; repo.mkdir()
            class Result:
                def __init__(self,value): self.stdout=(value+'\n').encode('ascii')
            with patch.object(m,'__file__',str(repo/'tools/bootstrap_pack_artifact.py')), patch.dict(m.os.environ,{'GITHUB_WORKSPACE':workspace,'GITHUB_SHA':m.COMMIT}), \
                 patch.object(m.subprocess,'run',side_effect=[Result(m.COMMIT),Result(m.TREE)]) as run:
                self.assertEqual(m.current_checkout_tree(),m.TREE)
                self.assertEqual([x.args[0][-2:] for x in run.call_args_list],[['--verify','HEAD'],['--verify','HEAD^{tree}']])
            with patch.object(m,'__file__',str(repo/'tools/bootstrap_pack_artifact.py')), patch.dict(m.os.environ,{'GITHUB_WORKSPACE':workspace,'GITHUB_SHA':'0'*40}), \
                 patch.object(m.subprocess,'run',side_effect=[Result(m.COMMIT),Result(m.TREE)]):
                with self.assertRaises(RuntimeError):m.current_checkout_tree()


class IsolatedCLITests(unittest.TestCase):
    def test_direct_isolated_cli_help_without_pythonpath(self):
        import os, subprocess, sys
        env=dict(os.environ);env.pop('PYTHONPATH',None)
        result=subprocess.run([sys.executable,'-I',m.__file__,'--help'],capture_output=True,timeout=30,env=env)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(b'--receipt-output',result.stdout)


class FailureEvidenceTests(unittest.TestCase):
    def test_fixed_reason_and_http_status_retained(self):
        result=m.safe_failure(m.ArtifactError('pinned API/download request failed',http_status=403))
        self.assertEqual(result['reason'],'pinned_api_download_request_failed')
        self.assertEqual(result['http_status'],403)
        self.assertFalse(result['complete'])

    def test_untrusted_exception_payload_never_disclosed(self):
        for error in (RuntimeError('TOKEN https://signed?sig=secret'),m.ArtifactError('TOKEN https://signed?sig=secret'),
                      urllib.error.HTTPError('https://signed?sig=secret',403,'TOKEN',{},None)):
            output=json.dumps(m.safe_failure(error))
            self.assertNotIn('TOKEN',output);self.assertNotIn('sig=',output)
            self.assertNotIn('https:',output)


class CanonicalZipTests(unittest.TestCase):
    def test_current_exact_reports_plus_evidence_retained(self):
        name = 'pack-runtime-artifacts-'+'a'*32+'/case/program.exe'
        files=m.extract_core(archive(current=True,extra=(name,)),current=True)
        self.assertEqual(set(files),m.CURRENT_CORE|{name})
        self.assertEqual(files[name],b'fixture')

    def test_windows_canonical_components(self):
        invalid=('C:/x','/x','../x','a/../b','a/./b','a//b','a\\b','a:b','a.','a ','CON',
                 'con.txt','AUX.txt','NUL','PRN.exe','com1.dll','LPT9.log','a/COM2.exe','x\u00e9','a/'+'x'*256,
                 'a/'*256+'x')
        for name in invalid:
            with self.subTest(name=name):self.assertFalse(m.canonical_member(name))
        for name in ('case/program.exe','case/a_b-1.txt','pack-runtime-artifacts-'+'a'*32+'/x'):
            self.assertTrue(m.canonical_member(name))

    def test_current_paths_reject_ads_traversal_devices_and_aliases(self):
        prefix='pack-runtime-artifacts-'+'a'*32+'/'
        for suffix in ('a:stream','a/../b','./x','x.','CON.txt','a\\x','x\u00e9'):
            with self.subTest(suffix=suffix):
                raw=archive(current=True,extra=(prefix+suffix,))
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    self.assertIn(prefix+suffix,[entry.orig_filename for entry in z.infolist()])
                with self.assertRaises(RuntimeError):m.extract_core(raw,current=True)
        for extra in ((prefix+'A',prefix+'a'),(prefix+'A',prefix+'a/child')):
            with self.subTest(extra=extra),self.assertRaises(RuntimeError):
                m.extract_core(archive(current=True,extra=extra),current=True)

    def test_raw_names_survive_both_writer_reader_models_and_are_rejected(self):
        prefix='pack-runtime-artifacts-'+'a'*32+'/'
        for writer in ('/','\\'):
            for suffix in ('a\\x','a\0hidden','../x','a:stream','CON.txt'):
                name=prefix+suffix
                with patch.object(zipfile.os,'sep',writer):raw=archive(current=True,extra=(name,))
                for reader in ('/','\\'):
                    with self.subTest(writer=writer,reader=reader,suffix=suffix),patch.object(zipfile.os,'sep',reader):
                        with zipfile.ZipFile(io.BytesIO(raw)) as z:
                            entry=next(item for item in z.infolist() if item.orig_filename==name)
                            expected=name.split('\0')[0].replace(reader,'/')
                            self.assertEqual(entry.filename,expected)
                        with self.assertRaises(RuntimeError):m.extract_core(raw,current=True)
            with patch.object(zipfile.os,'sep',writer):
                good=archive(current=True,extra=(prefix+'a/x',))
                unknown=archive(current=True,extra=('unknown.txt',))
            for reader in ('/','\\'):
                with patch.object(zipfile.os,'sep',reader):
                    self.assertEqual(set(m.extract_core(good,current=True)),m.CURRENT_CORE|{prefix+'a/x'})
                    with self.assertRaises(RuntimeError):m.extract_core(unknown,current=True)

    def test_raw_name_guard_negative_control_exposes_reader_aliases(self):
        import inspect
        source=inspect.getsource(m.extract_core)
        guard="            require(all(entry.orig_filename == entry.filename for entry in entries),\n                    'unsafe ZIP member')\n"
        self.assertEqual(source.count(guard),1)
        namespace=dict(vars(m))
        exec(compile(source.replace(guard,'',1),'<raw-name-guard-negative-control>','exec'),namespace)
        unsafe=namespace['extract_core']
        prefix='pack-runtime-artifacts-'+'a'*32+'/'
        for suffix in ('a\\x','a\0hidden'):
            name=prefix+suffix
            for writer in ('/','\\'):
                with patch.object(zipfile.os,'sep',writer):raw=archive(current=True,extra=(name,))
                with self.subTest(writer=writer,suffix=suffix),patch.object(zipfile.os,'sep','\\'):
                    with zipfile.ZipFile(io.BytesIO(raw)) as z:
                        self.assertIn(name,[entry.orig_filename for entry in z.infolist()])
                    with self.assertRaises(RuntimeError):m.extract_core(raw,current=True)
                    normalized=name.split('\0')[0].replace('\\','/')
                    self.assertIn(normalized,unsafe(raw,current=True))

    def test_windows_reparse_zip_attribute_rejected(self):
        def change(info):
            if info.filename=='stage1.exe':info.external_attr|=0x400
        with self.assertRaises(RuntimeError):m.extract_core(archive(change,current=True),current=True)

    def test_old_inventory_never_accepts_current_expansion(self):
        with self.assertRaises(RuntimeError):m.extract_core(archive(current=True))
        with self.assertRaises(RuntimeError):m.extract_core(archive(extra=('pack-unit-tests.json',)))
        self.assertEqual(len(m.CORE|m.IGNORED),101)

    def test_materialized_inventory_requires_exact_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/'a').mkdir();(root/'a/file').write_bytes(b'x')
            self.assertEqual(m.materialized_inventory(root),{'a/file'})
            (root/'empty').mkdir()
            with self.assertRaises(RuntimeError):m.materialized_inventory(root)

    def test_nested_save_and_readback_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp).resolve()/'bundle'
            identity=dict(m.OLD,current=True)
            raw={name:b'{}' for name in ('run.json','jobs.json','artifacts.json')}
            name='pack-runtime-artifacts-'+'a'*32+'/case/result.txt'
            files={'stage3.exe':b'PE',name:b'detail'}
            receipt=m.save_bundle(output,raw,b'zip',files,identity)
            self.assertEqual((output/name).read_bytes(),b'detail')
            self.assertEqual(receipt['files'][name],m.digest(b'detail'))
            self.assertEqual(m.materialized_inventory(output),set(receipt['files'])|{'receipt.json'})


def pack_fixture():
    from tools import verify_bootstrap_pack_ci as pack
    compiler=r'D:\a\ru-language\native-ci\stage3.exe'
    toolchain={'version':'clang version 14.0.6', 'triple':'x86_64-pc-windows-msvc',
        'data_layout':'e-m:w-p270:32:32', 'link_flags':[], 'clang_argv':['clang.exe'],
        'resolved_clang':'C:/LLVM/clang.exe',
        'executables':{name:{'path':'C:/LLVM/'+name+'.exe','sha256':'1'*64}
                       for name in ('clang','llvm-as','llvm-link','opt','llvm-dis','llc')}}
    files={name:b'core' for name in m.CURRENT_CORE}
    def put(name,value):files[name]=json.dumps(value,sort_keys=True).encode()
    bootstrap={'fixed_point':True}
    put('verification.json',{'bootstrap':bootstrap});put('report.json',bootstrap)
    identity=dict(m.OLD,current=True,STAGE3_SHA256=m.digest(files['stage3.exe']),
                  VERIFICATION_SHA256=m.digest(files['verification.json']))
    common={'format':1,'complete':True,'platform':'win32','commit':identity['COMMIT'],
        'compiler':compiler,'compiler_sha256':identity['STAGE3_SHA256'],
        'bootstrap_report_sha256':identity['VERIFICATION_SHA256'],'toolchain':toolchain}
    for prefix,verifier in (('slot',pack.slot),('pack',pack)):
        for kind in ('runtime','windows'):
            planned=verifier.required_cases(kind)
            row=dict(common,kind=kind,planned=planned,records=[{'id':name,'status':'passed'} for name in planned],
                     executed=len(planned),skipped=0,failures=0,errors=0,runner_success=True,
                     inputs={'source':prefix},status='passed')
            if prefix=='pack':
                dirname='pack-'+kind+'-artifacts-'+('a' if kind=='runtime' else 'b')*32
                files[dirname+'/case/output.txt']=kind.encode()
                row.update(evidence_directory=dirname,artifacts={'case/output.txt':m.digest(kind.encode())})
            put(prefix+'-'+kind+'-tests.json',row)
    for kind in ('frontend','windows'):put('native-'+kind+'-tests.json',{'compiler':compiler})
    files['slot-unit-tests.log']=b'old unit log'
    put('slot-unit-tests.json',{'complete':True,'log_sha256':m.digest(files['slot-unit-tests.log'])})
    files['pack-unit-tests.log']=b'unit log'
    put('pack-unit-tests.json',{'complete':True,'inputs':{'implementation':'current'},'planned':['portable.exact'],
        'records':[{'id':'portable.exact','status':'passed'}],'executed':1,'skipped':0,'failures':0,'errors':0,
        'log_sha256':m.digest(files['pack-unit-tests.log'])})
    refs={name:m.digest(files[name]) for name in ('native-frontend-tests.json','native-windows-tests.json',
          'slot-runtime-tests.json','slot-windows-tests.json')}
    put('slot-verification.json',dict(common,required_kinds=['runtime','windows'],reports=refs))
    put('pack-verification.json',dict(common,required_kinds=['runtime','windows'],
        reports={name:m.digest(files[name]) for name in m.PACK_REFERENCES},
        unit_log_sha256=m.digest(files['pack-unit-tests.log'])))
    return files,identity,pack


class PackEvidenceTests(unittest.TestCase):
    def validate(self,files,identity,pack):
        with patch.object(pack,'evidence_inputs',return_value={'source':'pack'}), \
             patch.object(pack.slot,'evidence_inputs',return_value={'source':'slot'}), \
             patch.object(pack,'unit_inputs',return_value={'implementation':'current'}), \
             patch.object(pack,'unit_cases',return_value=['portable.exact']):
            return m.validate_pack_bundle(files,identity)

    def mutate(self,files,name,change,*,rebind=True):
        value=json.loads(files[name]);change(value);files[name]=json.dumps(value,sort_keys=True).encode()
        if rebind:
            aggregate=json.loads(files['pack-verification.json'])
            if name in aggregate['reports']:aggregate['reports'][name]=m.digest(files[name])
            files['pack-verification.json']=json.dumps(aggregate,sort_keys=True).encode()

    def test_complete_exact_runtime_windows_and_unit_evidence(self):
        files,identity,pack=pack_fixture()
        self.assertTrue(self.validate(files,identity,pack)['complete'])
        self.assertEqual(len(pack.required_cases('runtime')),71)
        self.assertEqual(len(pack.required_cases('windows')),1)

    def test_green_job_or_partial_aggregate_cannot_replace_evidence(self):
        for change in (lambda row:row.update(complete=False),lambda row:row.update(required_kinds=['runtime']),
                       lambda row:row.update(commit='0'*40),lambda row:row.update(reports={})):
            files,identity,pack=pack_fixture();self.mutate(files,'pack-verification.json',change)
            with self.assertRaises(RuntimeError):self.validate(files,identity,pack)

    def test_exact_runtime_case_plan_and_pass_counts(self):
        for change in (lambda row:row.update(planned=row['planned'][:-1]),
                       lambda row:row['records'][0].update(status='skipped'),
                       lambda row:row.update(executed=True),lambda row:row.update(runner_success=False)):
            files,identity,pack=pack_fixture();self.mutate(files,'pack-runtime-tests.json',change)
            with self.assertRaises((RuntimeError,ValueError)):self.validate(files,identity,pack)

    def test_current_source_compiler_toolchain_binding(self):
        changes=(lambda row:row.update(inputs={'source':'stale'}),lambda row:row.update(compiler_sha256='0'*64),
                 lambda row:row.update(bootstrap_report_sha256='0'*64),lambda row:row.update(compiler=r'D:\other\stage3.exe'),
                 lambda row:row.update(toolchain={}))
        for change in changes:
            files,identity,pack=pack_fixture();self.mutate(files,'pack-windows-tests.json',change)
            with self.assertRaises(RuntimeError):self.validate(files,identity,pack)

    def test_unit_inventory_implementation_and_integer_counts(self):
        changes=(lambda row:row.update(inputs={'implementation':'old'}),
                 lambda row:row.update(planned=['invented.single'],records=[{'id':'invented.single','status':'passed'}]),
                 lambda row:row.update(executed=True),lambda row:row.update(skipped=True),
                 lambda row:row['records'][0].update(status='failed'))
        for change in changes:
            files,identity,pack=pack_fixture();self.mutate(files,'pack-unit-tests.json',change)
            with self.assertRaises(RuntimeError):self.validate(files,identity,pack)

    def test_changed_or_unreferenced_artifact_and_log_rejected(self):
        files,identity,pack=pack_fixture();name=next(n for n in files if n.startswith('pack-runtime-artifacts-'))
        files[name]=b'tampered'
        with self.assertRaises(RuntimeError):self.validate(files,identity,pack)
        files,identity,pack=pack_fixture();files['pack-runtime-artifacts-'+'c'*32+'/extra']=b'extra'
        with self.assertRaises(RuntimeError):self.validate(files,identity,pack)
        for name in ('pack-unit-tests.log','slot-unit-tests.log'):
            files,identity,pack=pack_fixture();files[name]=b'tampered'
            with self.assertRaises(RuntimeError):self.validate(files,identity,pack)

    def test_no_rebaseline_of_already_bound_report(self):
        files,identity,pack=pack_fixture()
        self.mutate(files,'pack-runtime-tests.json',lambda row:row.update(scope='different'),rebind=False)
        with self.assertRaises(RuntimeError):self.validate(files,identity,pack)

    def test_legacy_aggregate_and_generation_report_still_bound(self):
        for name,change in (('slot-verification.json',lambda row:row.update(complete=False)),
                            ('report.json',lambda row:row.update(fixed_point=False)),
                            ('slot-runtime-tests.json',lambda row:row.update(complete=False))):
            files,identity,pack=pack_fixture();self.mutate(files,name,change)
            with self.assertRaises(RuntimeError):self.validate(files,identity,pack)


class PackReadbackTests(unittest.TestCase):
    def test_source_hashes_not_rebaselined_during_validation(self):
        files,identity,pack=pack_fixture()
        with patch.object(pack,'evidence_inputs',return_value={'source':'pack'}), \
             patch.object(pack.slot,'evidence_inputs',return_value={'source':'slot'}), \
             patch.object(pack,'unit_inputs',side_effect=[{'implementation':'current'},{'implementation':'changed'}]), \
             patch.object(pack,'unit_cases',return_value=['portable.exact']):
            with self.assertRaisesRegex(RuntimeError,'inputs changed'):
                m.validate_pack_bundle(files,identity)

    def test_current_readback_nested_inventory_and_exact_external_pin(self):
        files,identity,pack=pack_fixture()
        raw={name:b'{}' for name in ('run.json','jobs.json','artifacts.json')}
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp).resolve()/'bundle';receipt=m.save_bundle(output,raw,b'zip',files,identity)
            pin=m.digest((output/'receipt.json').read_bytes())
            with patch.object(m,'validate_metadata'),patch.object(m,'verify_archive',return_value=files):
                self.assertEqual(m.verify_output(output,expected_receipt_sha256=pin),receipt)
                nested=next(n for n in files if n.startswith('pack-runtime-artifacts-'))
                (output/nested).write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError,'extracted artifact differs'):
                    m.verify_output(output,expected_receipt_sha256=pin)

    def test_receipt_cannot_change_after_original_pin_check(self):
        files,identity,pack=pack_fixture()
        raw={name:b'{}' for name in ('run.json','jobs.json','artifacts.json')}
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp).resolve()/'bundle';m.save_bundle(output,raw,b'zip',files,identity)
            pin=m.digest((output/'receipt.json').read_bytes())
            def mutate(*args,**kwargs):
                (output/'receipt.json').write_bytes((output/'receipt.json').read_bytes()+b' ')
                return files
            with patch.object(m,'validate_metadata'),patch.object(m,'verify_archive',side_effect=mutate):
                with self.assertRaisesRegex(RuntimeError,'receipt changed'):
                    m.verify_output(output,expected_receipt_sha256=pin)

    def test_only_current_declared_llvm14_windows_toolchain_shape(self):
        files,identity,pack=pack_fixture();tc=json.loads(files['pack-verification.json'])['toolchain']
        for mutate in (lambda t:t.update(version='clang version 17.0'),lambda t:t.update(triple='x86_64-pc-linux-gnu'),
                       lambda t:t.update(clang_argv=['wrapper','clang']),lambda t:t['executables'].pop('llc'),
                       lambda t:t['executables']['clang'].update(sha256='bad'),lambda t:t.update(resolved_clang='other')):
            changed=copy.deepcopy(tc);mutate(changed)
            with self.assertRaises(RuntimeError):m.validate_toolchain_shape(changed)


class FrozenOld46cTests(unittest.TestCase):
    def test_exact_immutable_46c_identity_inventory_and_bounds(self):
        self.assertEqual(m.COMMIT,'46c81ccfde815b8917be9107288b9a80b08758c9')
        self.assertEqual(m.TREE,'19c4199f3381bca19be01d5e703ef0b691ec7f8b')
        self.assertEqual((m.RUN,m.JOB,m.ARTIFACT),(39916413909,120290848444,12485855661))
        self.assertEqual((m.ZIP_SIZE,m.ZIP_SHA256),(27012695,'cae8af83d9f36928eab6e15e8d7d559e1b5a9b7fbcdf63ceec77b5fab56ff17d'))
        self.assertEqual(m.STAGE3_SHA256,'c52c32f261353663ec25b8e2212c05809e740a973495617fafcdbbfec6d23e76')
        self.assertEqual(m.VERIFICATION_SHA256,'fa54666afd7c8ce0125783f95982f079305979a7d058ffb6a3540404da1d5499')
        self.assertEqual(m.digest(json.dumps(sorted(m.CORE|m.IGNORED),separators=(',',':')).encode()),
            '4f4975a6ac5d97fd067d9269f38831b369b88ef43a96c3c2b2bbb550735e4510')
        self.assertEqual((m.MAX_ZIP,m.MAX_EXPANDED,m.MAX_MEMBER),(32*1024*1024,256*1024*1024,96*1024*1024))
