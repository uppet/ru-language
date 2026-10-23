"""Portable scope/deadline guards, never real measurement evidence."""
from pathlib import Path
import hashlib
import unittest
import tempfile
from unittest.mock import patch
from types import SimpleNamespace
import stat
import textwrap
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import bootstrap_address_artifact as loader
ROOT=Path(__file__).resolve().parents[1]
PARENT_CODE="from pathlib import Path\nfrom tools import bootstrap_address_artifact as loader\nparent = Path.cwd() / 'bin' / 'bootstrap'\noutput = parent / 'address-current'\nfor ancestor in (parent, *parent.parents):\n    try:\n        ancestor.lstat()\n    except FileNotFoundError:\n        continue\n    loader.no_links(ancestor)\n    loader.require(ancestor.is_dir(), 'artifact ancestor must be a directory')\nparent.mkdir(parents=True, exist_ok=True)\nloader.no_links(parent)\nloader.require(not output.exists() and not output.is_symlink(), 'artifact output must remain fresh')\n"
NEW=ROOT/'.github/workflows/bootstrap-slot-address.yml'
OLD=ROOT/'.github/workflows/bootstrap-slot-reuse.yml'


def parent_code(text):
    block=text.split('      - name: Prepare only the fixed compiler artifact parent with reparse guards\n',1)[1].split('      - name:',1)[0]
    return textwrap.dedent(block.split("          @'\n",1)[1].split("          '@ | python -",1)[0])


def validate(text):
    functional,measurement=text.split('\n  address-measurement:\n')
    normalized=functional.replace('name: Experimental bootstrap slot address acceptance and measurement','name: Experimental bootstrap slot reuse acceptance',1).replace('branches: [feature/bootstrap-slot-address-20261023]','branches: [feature/bootstrap-slot-reuse-20261023]',1)
    if normalized!=OLD.read_text(encoding='utf-8'):raise ValueError('existing functionality/jobs changed')
    for required in ('needs: [slot-bootstrap, bootstrap-editor-gui]','timeout-minutes: 75',
                     'ref: 925707005a80cf935d12ea4fc88316d941452955',
                     'ref: 2cb3b8c81ba300745b244c51b50d5625430fbe4f',
                     'EDITOR_TREE: 5c63f94cd9e3816608cc95b834f91428bbeb3c49',
                     "'tree':'986c5ef4ec650d949f9bcd6f32177bb8ba371190'",
                     'run: python tools/bootstrap_address_build.py --config',
                     'run: python tools/measure_bootstrap_addresses.py --prepared',
                     'if: always()','if-no-files-found: error','actions: read'):
        if required not in measurement:raise ValueError('measurement contract missing: '+required)
    code=parent_code(text)
    if PARENT_CODE != code:raise ValueError('artifact parent preparation contract changed')
    if text.index('Prepare only the fixed compiler artifact parent')>text.index('Download exact old925 and current'):raise ValueError('artifact parent prepared too late')
    for forbidden in ('continue-on-error:','cancel-in-progress: true','libLLVM17','dev_codegen','actions: write','contents: write','bootstrap.py verify','--emit-c-via-gcc'):
        if forbidden in measurement:raise ValueError('measurement scope widened')
    if measurement.count('GITHUB_TOKEN:')!=1:raise ValueError('token must be download-step only')
    if measurement.count('timeout-minutes:')!=1:raise ValueError('measurement deadline changed')
    upload=measurement.split('      - name: Preserve all measurement JSON',1)[1]
    if '**/*.json' not in upload or '**/*.log' not in upload or '**/*.exe' in upload:raise ValueError('upload scope changed')
    for line in measurement.splitlines():
        if 'persist-credentials:' in line and 'false' not in line:raise ValueError('checkout credential persistence')

class AddressWorkflowTests(unittest.TestCase):
    def test_scope_and_original_jobs_byte_equal(self):validate(NEW.read_text(encoding='utf-8'))
    def test_mutations_cannot_weaken_scope_or_budget(self):
        text=NEW.read_text(encoding='utf-8')
        for a,b in [('timeout-minutes: 75','timeout-minutes: 90'),('timeout-minutes: 45','timeout-minutes: 90'),
                    ('needs: [slot-bootstrap, bootstrap-editor-gui]','needs: slot-bootstrap'),('if: always()','if: success()'),
                    ('actions: read','actions: write'),('5c63f94cd9e3816608cc95b834f91428bbeb3c49','wrong'),
                    ('925707005a80cf935d12ea4fc88316d941452955','main'),('persist-credentials: false','persist-credentials: true')]:
            with self.subTest(a=a),self.assertRaises(ValueError):validate(text.replace(a,b))
    def test_clock_oracle_cleanup_contract_unchanged(self):
        text=(ROOT/'tools/diagnose_bootstrap_slot_control.py').read_text(encoding='utf-8')
        outside=text.split('def language_delta(',1)[0]+text.split('\ndef compare(',1)[1]
        self.assertEqual(hashlib.sha256(outside.encode()).hexdigest(),'0c0e5e9df0eb5a6f613b9bb4e00e0acc13777fcf8029d9f8233efed78b2452be')

    def test_fresh_checkout_parent_preparation_reaches_loader(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();output=root/'bin/bootstrap/address-current'
            with patch.object(loader,'fetch',side_effect=RuntimeError('NETWORK-SENTINEL')) as fetch:
                with self.assertRaises(FileNotFoundError):loader.obtain_current(output,'x',run_id=1,commit='a'*40,tree='b'*40)
                fetch.assert_not_called()
                with patch.object(Path,'cwd',return_value=root):exec(parent_code(NEW.read_text(encoding='utf-8')), {})
                self.assertTrue(output.parent.is_dir());self.assertFalse(output.exists())
                with self.assertRaisesRegex(RuntimeError,'NETWORK-SENTINEL'):loader.obtain_current(output,'x',run_id=1,commit='a'*40,tree='b'*40)
                fetch.assert_called_once()
    def test_parent_does_not_reuse_output_or_follow_link(self):
        code=parent_code(NEW.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();output=root/'bin/bootstrap/address-current';output.mkdir(parents=True)
            (output/'keep').write_bytes(b'unchanged')
            with patch.object(Path,'cwd',return_value=root),self.assertRaises(RuntimeError):exec(code,{})
            self.assertEqual((output/'keep').read_bytes(),b'unchanged')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();(root/'bin').mkdir()
            original=Path.lstat
            def lstat(path,*args,**kwargs):
                info=original(path,*args,**kwargs)
                if path==root/'bin':return SimpleNamespace(st_mode=info.st_mode,st_file_attributes=0x400)
                return info
            with patch.object(Path,'cwd',return_value=root),patch.object(Path,'lstat',lstat),self.assertRaises(RuntimeError):exec(code,{})
            self.assertFalse((root/'bin/bootstrap').exists())
    def test_parent_entry_mutations_rejected(self):
        source=NEW.read_text(encoding='utf-8')
        for old,new in [("parent.mkdir(parents=True, exist_ok=True)","output.mkdir(parents=True, exist_ok=True)"),
                        ('loader.no_links(ancestor)','pass'),('loader.no_links(parent)','pass'),
                        ("'bin' / 'bootstrap'","'other' / 'bootstrap'")]:
            with self.subTest(old=old),self.assertRaises(ValueError):validate(source.replace(old,new))

    def test_original_workflow_frozen(self):
        self.assertEqual(hashlib.sha256(OLD.read_bytes()).hexdigest(),'6d9d9ce7cd21cd4bfcf28cbf63fcb3bed7c8dfb3e2f679e7f82bab19cc40c307')

if __name__=='__main__':unittest.main()
