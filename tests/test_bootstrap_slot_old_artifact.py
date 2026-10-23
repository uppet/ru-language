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

from tools import bootstrap_slot_old_artifact as m


def metadata():
    run = dict(id=m.RUN, head_sha=m.COMMIT, event='push', path='.github/workflows/bootstrap-native.yml',
               repository={'full_name': m.REPOSITORY}, head_repository={'full_name': m.REPOSITORY}, conclusion='failure')
    job = dict(id=m.JOB, run_id=m.RUN, head_sha=m.COMMIT, status='completed', conclusion='success', name='native-bootstrap (windows-latest)')
    artifact = dict(id=m.ARTIFACT, workflow_run={'id': m.RUN, 'head_sha': m.COMMIT}, name='bootstrap-native-windows-latest-'+m.COMMIT,
                    expired=False, digest='sha256:'+m.ZIP_SHA256, size_in_bytes=m.ZIP_SIZE)
    return run, {'total_count': 1, 'jobs': [job]}, {'total_count': 1, 'artifacts': [artifact]}


def archive(change=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        for name in sorted(m.CORE | m.IGNORED):
            info = zipfile.ZipInfo(name)
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
        with patch.object(sys,'argv',['loader','--output','/unused']), patch.object(m,'obtain',side_effect=RuntimeError('TOKEN https://signed?sig=secret')), contextlib.redirect_stderr(err):
            self.assertEqual(m.main(),1)
        self.assertNotIn('TOKEN',err.getvalue()); self.assertNotIn('sig=',err.getvalue())


if __name__=='__main__': unittest.main()
