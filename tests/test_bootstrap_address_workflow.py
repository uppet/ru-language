"""Portable scope/deadline guards, never real measurement evidence."""
from pathlib import Path
import hashlib
import unittest
ROOT=Path(__file__).resolve().parents[1]
NEW=ROOT/'.github/workflows/bootstrap-slot-address.yml'
OLD=ROOT/'.github/workflows/bootstrap-slot-reuse.yml'


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

    def test_original_workflow_frozen(self):
        self.assertEqual(hashlib.sha256(OLD.read_bytes()).hexdigest(),'6d9d9ce7cd21cd4bfcf28cbf63fcb3bed7c8dfb3e2f679e7f82bab19cc40c307')

if __name__=='__main__':unittest.main()
