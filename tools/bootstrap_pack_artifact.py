#!/usr/bin/env python3
"""Read-only pinned 46c/pack Windows evidence loader; never GUI/performance acceptance.

The existing B source/provenance validator must subsequently bind the untouched
verification bytes to the separate clean exact46c/current source checkout and trusted tools.
No API writes, arbitrary URL/identity flags, source execution, or token receipts.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import struct
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

# Direct -I CLI must resolve only its own checked-out tools package, not PYTHONPATH.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.bootstrap_compare import compare_native

REPOSITORY = 'uppet/ru-language'
COMMIT = '46c81ccfde815b8917be9107288b9a80b08758c9'
TREE = '19c4199f3381bca19be01d5e703ef0b691ec7f8b'
RUN = 39916413909
JOB = 120290848444
ARTIFACT = 12485855661
ZIP_SHA256 = 'cae8af83d9f36928eab6e15e8d7d559e1b5a9b7fbcdf63ceec77b5fab56ff17d'
ZIP_SIZE = 27012695
STAGE3_SHA256 = 'c52c32f261353663ec25b8e2212c05809e740a973495617fafcdbbfec6d23e76'
VERIFICATION_SHA256 = 'fa54666afd7c8ce0125783f95982f079305979a7d058ffb6a3540404da1d5499'
API = 'https://api.github.com/repos/' + REPOSITORY + '/actions/'
MAX_JSON = 4 * 1024 * 1024
MAX_ZIP = 32 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_MEMBER = 96 * 1024 * 1024
CORE = frozenset(['verification.json', 'report.json', 'native-frontend-tests.json', 'native-windows-tests.json',
                  'stage1.exe', 'stage2.exe', 'stage3.exe', 'stage2.ll', 'stage3.ll',
                  'stage2.exe.frontend.ll', 'stage3.exe.frontend.ll', 'stage2.exe.metadata.c', 'stage3.exe.metadata.c'])
IGNORED = frozenset(['notepad-console-link/application.ll', 'notepad-console-link/compile-proof.json', 'notepad-console-link/ru_notepad-console.exe', 'notepad-console-link/ru_notepad-console.exe.frontend.ll', 'notepad-console-link/ru_notepad-console.exe.metadata.c', 'notepad-console-link/verification.json', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/expected.stdout', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/lifetime.ru', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/pure-ru-negative-source/compiler.ru', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/pure-ru-negative-source/native_emit.ru', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python-unsafe-unwind.stderr', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python-unsafe-unwind.stdout', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python-unsafe-unwind/linked.bc', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python-unsafe-unwind/optimized.bc', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python-unsafe-unwind/program.bc', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python-unsafe-unwind/program.exe', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python-unsafe-unwind/program.ll', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python-unsafe-unwind/program.o', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python-unsafe-unwind/runtime.bc', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python-unsafe-unwind/runtime.c', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python-unsafe-unwind/standalone.ll', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python.stderr', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python.stdout', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python/linked.bc', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python/optimized.bc', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python/program.bc', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python/program.exe', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python/program.ll', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python/program.o', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python/runtime.bc', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python/runtime.c', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/python/standalone.ll', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/receipt.json', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3-unsafe-compiler/build-proof.json', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3-unsafe-compiler/program.exe', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3-unsafe-compiler/program.exe.frontend.ll', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3-unsafe-compiler/program.exe.metadata.c', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3-unsafe-compiler/standalone.ll', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3-unsafe-unwind.stderr', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3-unsafe-unwind.stdout', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3-unsafe-unwind/build-proof.json', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3-unsafe-unwind/program.exe', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3-unsafe-unwind/program.exe.frontend.ll', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3-unsafe-unwind/program.exe.metadata.c', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3-unsafe-unwind/standalone.ll', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3.stderr', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3.stdout', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3/build-proof.json', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3/program.exe', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3/program.exe.frontend.ll', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3/program.exe.metadata.c', 'slot-runtime-artifacts-7db413cdb5c5453eadefd3ccb20d8b79/slot-lifetime-esz_pcro/stage3/standalone.ll', 'slot-runtime-tests.json', 'slot-unit-tests.json', 'slot-unit-tests.log', 'slot-verification.json', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/acceptance.json', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/acceptance.json', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/application.ll', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/bridge.c', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/compile-proof.json', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/main.ru', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/owned_bridge.dll', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/owned_bridge.exp', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/owned_bridge.lib', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/panic_module.ru', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/program.exe', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/program.exe.frontend.ll', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/program.exe.metadata.c', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/runtime.instrumented.c', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/runtime.original.c', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/stderr.txt', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/probe/stdout.txt', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/production/acceptance.json', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/production/application.ll', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/production/bridge.c', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/production/compile-proof.json', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/production/main.ru', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/production/owned_bridge.dll', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/production/owned_bridge.exp', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/production/owned_bridge.lib', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/production/panic_module.ru', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/production/program.exe', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/production/program.exe.frontend.ll', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/production/program.exe.metadata.c', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/production/stderr.txt', 'slot-windows-artifacts-3dadf3611f904e1ebe7c9c8282569ad2/test_parent_temporaries_survive_nested_callback_panic_retry/production/stdout.txt', 'slot-windows-tests.json'])
GATES = frozenset(['source_ir_and_abi_fixed_point', 'native_binary_fixed_point',
                  'same_nonempty_suite_for_each_stage', 'every_planned_case_ran',
                  'every_case_passed_without_skips', 'test_runner_success_without_skips',
                  'inputs_unchanged', 'artifacts_unchanged_during_tests'])

SLOT_REPORTS = frozenset(['slot-runtime-tests.json', 'slot-unit-tests.json', 'slot-unit-tests.log',
                         'slot-verification.json', 'slot-windows-tests.json'])
PACK_REPORTS = frozenset(['pack-runtime-tests.json', 'pack-unit-tests.json', 'pack-unit-tests.log',
                         'pack-verification.json', 'pack-windows-tests.json'])
CURRENT_CORE = CORE | SLOT_REPORTS | PACK_REPORTS
PACK_REFERENCES = frozenset(['verification.json', 'report.json', 'native-frontend-tests.json',
    'native-windows-tests.json', 'slot-runtime-tests.json', 'slot-windows-tests.json',
    'slot-unit-tests.json', 'slot-verification.json', 'pack-runtime-tests.json',
    'pack-windows-tests.json', 'pack-unit-tests.json'])


OLD = {'COMMIT': COMMIT, 'TREE': TREE, 'RUN': RUN, 'JOB': JOB, 'ARTIFACT': ARTIFACT, 'ZIP_SHA256': ZIP_SHA256, 'ZIP_SIZE': ZIP_SIZE, 'STAGE3_SHA256': STAGE3_SHA256, 'VERIFICATION_SHA256': VERIFICATION_SHA256, 'current': False}

def identity_values(identity):
    return OLD if identity is None else identity


class ArtifactError(RuntimeError):
    """Only internal checked reasons may be disclosed; never transport payloads."""
    def __init__(self, message, *, http_status=None):
        super().__init__(message)
        self.http_status = http_status


def require(value, message):
    if not value:
        raise ArtifactError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def decode(data):
    require(len(data) <= MAX_JSON, 'JSON exceeds fixed bound')
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'duplicate JSON key')
            out[key] = value
        return out
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_constant=lambda _: require(False, 'nonfinite JSON'))
    except (UnicodeError, ValueError, RecursionError):
        raise ArtifactError('invalid bounded UTF8 JSON') from None


def one(rows, identity, label):
    require(isinstance(rows, list) and len(rows) <= 100, 'invalid ' + label + ' collection')
    require(all(isinstance(row, dict) and type(row.get('id')) is int for row in rows), 'invalid API row')
    ids = [row['id'] for row in rows]
    require(len(ids) == len(set(ids)), 'duplicate API identity')
    found = [row for row in rows if row['id'] == identity]
    require(len(found) == 1, 'pinned ' + label + ' missing')
    return found[0]


def validate_metadata(run, jobs, artifacts, *, identity=None):
    identity = identity_values(identity)
    COMMIT, TREE, RUN, JOB, ARTIFACT, ZIP_SHA256, ZIP_SIZE, STAGE3_SHA256, VERIFICATION_SHA256 = (identity['COMMIT'], identity['TREE'], identity['RUN'], identity['JOB'], identity['ARTIFACT'], identity['ZIP_SHA256'], identity['ZIP_SIZE'], identity['STAGE3_SHA256'], identity['VERIFICATION_SHA256'])
    require(run.get('id') == RUN and run.get('head_sha') == COMMIT and
            run.get('event') == 'push' and run.get('path') == ('.github/workflows/bootstrap-argument-pack.yml' if identity['current'] else '.github/workflows/bootstrap-slot-address.yml') and
            run.get('repository', {}).get('full_name') == REPOSITORY and
            run.get('head_repository', {}).get('full_name') == REPOSITORY, 'old run identity mismatch')
    if identity['current']:
        require(run.get('head_branch') == 'feature/bootstrap-argument-pack-20261023',
                'current pack branch mismatch')
    # Only this exact successful Windows core job attests the compiler bundle.
    # GUI and measurement jobs have separate acceptance and cannot be inferred here.
    job = one(jobs.get('jobs'), JOB, 'job')
    require(job.get('run_id') == RUN and job.get('head_sha') == COMMIT and
            job.get('status') == 'completed' and job.get('conclusion') == 'success' and
            job.get('name') == ('pack-bootstrap (windows-latest)' if identity['current'] else 'slot-bootstrap (windows-latest)'), 'old Windows core job not successful')
    artifact = one(artifacts.get('artifacts'), ARTIFACT, 'artifact')
    require(artifact.get('workflow_run', {}).get('id') == RUN and
            artifact.get('workflow_run', {}).get('head_sha') == COMMIT and
            artifact.get('name') == ('bootstrap-pack-windows-latest-' if identity['current'] else 'bootstrap-slot-windows-latest-') + COMMIT and
            artifact.get('expired') is False and artifact.get('digest') == 'sha256:' + ZIP_SHA256 and
            artifact.get('size_in_bytes') == ZIP_SIZE, 'old artifact identity/expiry/digest mismatch')
    for collection, key in ((jobs, 'jobs'), (artifacts, 'artifacts')):
        total = collection.get('total_count', len(collection[key]))
        require(type(total) is int and total == len(collection[key]), 'paginated API collection incomplete')
    return artifact


def canonical_member(name):
    """Generated ASCII names must mean the same file on POSIX and Windows."""
    if not isinstance(name, str) or not 0 < len(name) <= 512 or not name.isascii():
        return False
    parts = name.split('/')
    for part in parts:
        if not 0 < len(part) <= 255 or re.fullmatch(r'[A-Za-z0-9_.-]+', part) is None:
            return False
        if part in ('.', '..') or part.endswith('.'):
            return False
        stem = part.split('.')[0].upper()
        if stem in {'CON', 'PRN', 'AUX', 'NUL'} or re.fullmatch(r'(?:COM|LPT)[1-9]', stem):
            return False
    return str(PurePosixPath(name)) == name and not PureWindowsPath(name).is_absolute()


def validate_member_names(names):
    require(all(canonical_member(name) for name in names), 'unsafe ZIP member')
    folded = [name.casefold() for name in names]
    require(len(folded) == len(set(folded)), 'ambiguous Windows ZIP member')
    present = set(folded)
    require(not any('/'.join(name.split('/')[:index]) in present
        for name in folded for index in range(1, len(name.split('/')))), 'ZIP file directory collision')


def extract_core(raw, *, current=False):
    """Bounded ZIP validation; current returns the complete pack evidence bundle."""
    require(len(raw) <= MAX_ZIP, 'archive exceeds fixed bound')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            # ZipInfo normalizes Windows separators and truncates at NUL while reading.
            require(all(entry.orig_filename == entry.filename for entry in entries),
                    'unsafe ZIP member')
            names = [entry.filename for entry in entries]
            require(len(names) <= 512 and len(names) == len(set(names)) and
                    (set(names) == CORE | IGNORED if not current else
                     CURRENT_CORE <= set(names) and all(current_member(name) for name in names)),
                    'archive member inventory mismatch')
            validate_member_names(names)
            require(sum(entry.file_size for entry in entries) <= MAX_EXPANDED, 'expanded archive exceeds bound')
            for entry in entries:
                mode = entry.external_attr >> 16
                require(not entry.is_dir() and stat.S_IFMT(mode) in (0, stat.S_IFREG) and
                        not (entry.external_attr & 0x400) and not (entry.flag_bits & 1) and
                        entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) and
                        0 <= entry.file_size <= MAX_MEMBER, 'unsafe ZIP member')
            wanted = names if current else CORE
            result = {name: archive.read(name) for name in sorted(wanted)}
            require(all(len(data) == archive.getinfo(name).file_size for name, data in result.items()),
                    'ZIP size mismatch')
            return result
    except (zipfile.BadZipFile, NotImplementedError, EOFError, OSError):
        raise ArtifactError('invalid ZIP data') from None


def pack_contract():
    # This is the current checked-out verifier, never code supplied by a bundle.
    from tools import verify_bootstrap_pack_ci
    return verify_bootstrap_pack_ci


def validate_toolchain_shape(toolchain):
    require(isinstance(toolchain, dict) and re.search(r'clang version 14\.', toolchain.get('version', '')) and
            re.fullmatch(r'x86_64-pc-windows-msvc(?:[0-9]+(?:\.[0-9]+)*)?', toolchain.get('triple', '')) and
            isinstance(toolchain.get('data_layout'), str) and bool(toolchain['data_layout']) and
            isinstance(toolchain.get('link_flags'), list) and
            all(isinstance(flag, str) for flag in toolchain['link_flags']) and
            isinstance(toolchain.get('clang_argv'), list) and len(toolchain['clang_argv']) == 1 and
            isinstance(toolchain['clang_argv'][0], str), 'pack toolchain shape mismatch')
    executables = toolchain.get('executables', {})
    require(set(executables) == {'clang', 'llvm-as', 'llvm-link', 'opt', 'llvm-dis', 'llc'} and
            all(isinstance(item, dict) and isinstance(item.get('path'), str) and bool(item['path']) and
                re.fullmatch('[a-f0-9]{64}', item.get('sha256', '')) for item in executables.values()) and
            toolchain.get('resolved_clang') == executables['clang']['path'], 'pack toolchain executable identity missing')


def validate_pack_bundle(files, identity):
    """Bind current pack reports, exact cases, implementation and every retained byte.

    Legacy slot detailed artifacts remain in the separate original upload. Their
    referenced report bytes are bound here; this is not a substitute for that CI.
    """
    pack = pack_contract()
    frozen_pack_inputs = {kind:pack.evidence_inputs(kind) for kind in ('runtime', 'windows')}
    frozen_slot_inputs = {kind:pack.slot.evidence_inputs(kind) for kind in ('runtime', 'windows')}
    frozen_unit_inputs = pack.unit_inputs()
    frozen_unit_cases = pack.unit_cases()
    aggregate = decode(files['pack-verification.json'])
    compiler_hash = identity['STAGE3_SHA256']
    bootstrap_hash = identity['VERIFICATION_SHA256']
    require(aggregate.get('format') == 1 and aggregate.get('complete') is True and
            aggregate.get('platform') == 'win32' and aggregate.get('commit') == identity['COMMIT'] and
            aggregate.get('compiler_sha256') == compiler_hash and
            aggregate.get('bootstrap_report_sha256') == bootstrap_hash and
            aggregate.get('required_kinds') == ['runtime', 'windows'], 'pack aggregate identity mismatch')
    toolchain = aggregate.get('toolchain')
    validate_toolchain_shape(toolchain)
    references = aggregate.get('reports', {})
    require(set(references) == PACK_REFERENCES and
            all(references[name] == digest(files[name]) for name in PACK_REFERENCES), 'pack referenced report changed')
    require(decode(files['report.json']) == decode(files['verification.json']).get('bootstrap'),
            'pack bootstrap report mismatch')
    legacy = decode(files['slot-verification.json'])
    require(legacy.get('format') == 1 and legacy.get('complete') is True and
            legacy.get('platform') == 'win32' and legacy.get('commit') == identity['COMMIT'] and
            legacy.get('compiler_sha256') == compiler_hash and
            legacy.get('bootstrap_report_sha256') == bootstrap_hash and
            legacy.get('required_kinds') == ['runtime', 'windows'] and legacy.get('toolchain') == toolchain,
            'pack legacy aggregate identity mismatch')
    legacy_references = {'native-frontend-tests.json', 'native-windows-tests.json',
                         'slot-runtime-tests.json', 'slot-windows-tests.json'}
    require(set(legacy.get('reports', {})) == legacy_references and
            all(legacy['reports'][name] == references[name] for name in legacy_references),
            'pack legacy report binding mismatch')
    compiler_path = None
    consumed = set()
    for prefix, verifier in (('slot', pack.slot), ('pack', pack)):
        for kind in ('runtime', 'windows'):
            report = decode(files[prefix+'-'+kind+'-tests.json'])
            verifier.validate_results(report, kind)
            require(report.get('format') == 1 and report.get('complete') is True and
                    report.get('platform') == 'win32' and report.get('commit') == identity['COMMIT'] and
                    report.get('compiler_sha256') == compiler_hash and
                    report.get('bootstrap_report_sha256') == bootstrap_hash and
                    report.get('inputs') == (frozen_pack_inputs if prefix == 'pack' else frozen_slot_inputs)[kind] and
                    report.get('toolchain') == toolchain, 'pack case source or compiler identity mismatch')
            value = report.get('compiler')
            require(isinstance(value, str) and PureWindowsPath(value).is_absolute() and
                    PureWindowsPath(value).name == 'stage3.exe', 'pack compiler path malformed')
            if compiler_path is None:
                compiler_path = value
            require(value == compiler_path, 'pack compiler path disagreement')
            if prefix == 'pack':
                directory = report.get('evidence_directory', '')
                require(re.fullmatch('pack-'+kind+r'-artifacts-[a-f0-9]{32}', directory),
                        'pack evidence directory identity mismatch')
                present = {name[len(directory)+1:]:digest(data) for name, data in files.items()
                           if name.startswith(directory+'/')}
                require(present and report.get('artifacts') == present, 'pack evidence bytes changed')
                consumed.update(directory+'/'+name for name in present)
    require(consumed == set(files)-CURRENT_CORE, 'unreferenced pack evidence member')
    for kind in ('frontend', 'windows'):
        require(decode(files['native-'+kind+'-tests.json']).get('compiler') == compiler_path,
                'pack legacy native compiler path mismatch')
    units = decode(files['pack-unit-tests.json'])
    planned = units.get('planned')
    require(units.get('complete') is True and units.get('inputs') == frozen_unit_inputs and
            planned == frozen_unit_cases, 'pack portable input or inventory mismatch')
    require(all(type(units.get(key)) is int for key in ('executed', 'skipped', 'failures', 'errors')) and
            units['executed'] == len(planned) and units['skipped'] == units['failures'] == units['errors'] == 0 and
            sorted(row.get('id', '') for row in units.get('records', [])) == planned and
            all(row.get('status') == 'passed' for row in units['records']), 'pack portable result mismatch')
    log_hash = digest(files['pack-unit-tests.log'])
    require(units.get('log_sha256') == log_hash and aggregate.get('unit_log_sha256') == log_hash,
            'pack portable log changed')
    slot_units = decode(files['slot-unit-tests.json'])
    require(slot_units.get('complete') is True and
            slot_units.get('log_sha256') == digest(files['slot-unit-tests.log']), 'pack legacy portable log changed')
    require(frozen_unit_inputs == pack.unit_inputs() and
            all(frozen_pack_inputs[kind] == pack.evidence_inputs(kind) and
                frozen_slot_inputs[kind] == pack.slot.evidence_inputs(kind) for kind in ('runtime', 'windows')),
            'pack verifier inputs changed during validation')
    return aggregate


def verify_archive(raw, *, identity=None):
    identity = identity_values(identity)
    COMMIT, TREE, RUN, JOB, ARTIFACT, ZIP_SHA256, ZIP_SIZE, STAGE3_SHA256, VERIFICATION_SHA256 = (identity['COMMIT'], identity['TREE'], identity['RUN'], identity['JOB'], identity['ARTIFACT'], identity['ZIP_SHA256'], identity['ZIP_SIZE'], identity['STAGE3_SHA256'], identity['VERIFICATION_SHA256'])
    require(len(raw) == ZIP_SIZE and digest(raw) == ZIP_SHA256, 'pinned ZIP digest/size mismatch')
    files = extract_core(raw, current=identity['current'])
    require(digest(files['verification.json']) == VERIFICATION_SHA256 and
            digest(files['stage3.exe']) == STAGE3_SHA256, 'pinned core identity mismatch')
    report = decode(files['verification.json'])
    require(report.get('m4_complete') is True and report.get('platform') == 'win32' and
            report.get('tests_run') == 105 and report.get('skipped') == report.get('errors') == report.get('failures') == 0 and
            set(report.get('gates', {})) == GATES and all(x is True for x in report['gates'].values()), 'M4 suite incomplete')
    plans = report.get('planned_cases_by_stage', {})
    require(set(plans) == {'1', '2', '3'} and plans['1'] == plans['2'] == plans['3'] and
            len(plans['1']) == len(set(plans['1'])) == 35, '35-case generation plan mismatch')
    classes = ['BootstrapStage1Tests', 'BootstrapStage2Tests', 'BootstrapTests']
    require(set(report.get('stages', {})) == {'1', '2', '3'}, 'generation results missing')
    for index, cls in enumerate(classes, 1):
        rows = report['stages'][str(index)]
        require(len(rows) == 35 and sorted(row.get('case', '') for row in rows) == sorted(plans['1']) and
                all(row.get('status') == 'passed' and row.get('stage') == index and
                    row.get('id') == '_ru_bootstrap_acceptance.' + cls + '.' + row['case'] for row in rows), 'generation result mismatch')
    inventory = report.get('input_sha256', {})
    require((0 < len(inventory) <= 512 if identity['current'] else len(inventory) == 64) and all(isinstance(name, str) and not PurePosixPath(name).is_absolute() and
            not PureWindowsPath(name).is_absolute() and '\\' not in name and '..' not in PurePosixPath(name).parts and
            re.fullmatch('[a-f0-9]{64}', value) for name, value in inventory.items()), 'source inventory shape mismatch')
    expected = CORE - {'verification.json', 'report.json', 'native-frontend-tests.json', 'native-windows-tests.json'}
    seen = set()
    for original, value in report.get('artifact_sha256', {}).items():
        name = PureWindowsPath(original).name
        require(name in expected and name not in seen and digest(files[name]) == value, 'M4 artifact mismatch')
        seen.add(name)
    require(seen == expected, 'complete nine-artifact identity required')
    for name in ('stage1.exe', 'stage2.exe', 'stage3.exe'):
        data = files[name]
        require(len(data) >= 64 and data[:2] == b'MZ', 'not PE')
        offset = struct.unpack_from('<I', data, 60)[0]
        require(offset + 26 <= len(data) and data[offset:offset+4] == b'PE\0\0' and
                struct.unpack_from('<H', data, offset+4)[0] == 0x8664 and
                struct.unpack_from('<H', data, offset+24)[0] == 0x20b, 'not x64 PE32+')
    for suffix in ('frontend.ll', 'metadata.c'):
        require(files['stage2.exe.' + suffix] == files['stage3.exe.' + suffix], 'IR/ABI fixed point mismatch')
    require(report.get('native_comparison', {}).get('normalized_equal') is True and
            report.get('bootstrap', {}).get('fixed_point') is True, 'reported native fixed point missing')
    comparison = compare_native(files['stage2.exe'], files['stage3.exe'])
    require(comparison['normalized_equal'] is True and comparison == report['native_comparison'],
            'recomputed native fixed point differs from report')
    for kind, count in (('frontend', 9), ('windows', 17)):
        row = decode(files['native-' + kind + '-tests.json'])
        require(row.get('scope') == 'real-stage3-' + kind and row.get('complete') is True and
                row.get('planned') == row.get('executed') == count and
                row.get('skipped') == row.get('errors') == row.get('failures') == 0 and
                row.get('compiler_sha256') == STAGE3_SHA256, 'native core gate mismatch')
    if identity['current']:
        validate_pack_bundle(files, identity)
    return files


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def safe_download_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (parsed.scheme == 'https' and parsed.username is None and parsed.password is None and
            port in (None, 443) and not parsed.fragment and
            (parsed.hostname == 'objects.githubusercontent.com' or
             re.fullmatch(r'productionresultssa[a-z0-9]*\.blob\.core\.windows\.net', parsed.hostname or '') is not None))


def bounded_read(response, limit):
    length = response.headers.get('Content-Length')
    if length is not None:
        require(length.isdigit() and int(length) <= limit, 'response exceeds fixed bound')
    data = response.read(limit + 1)
    require(len(data) <= limit, 'response exceeds fixed bound')
    return data


def fetch(path, token, *, archive=False, opener=None, identity=None):
    identity = identity_values(identity)
    RUN, ARTIFACT = identity['RUN'], identity['ARTIFACT']
    require(path in ('runs/' + str(RUN), 'runs/' + str(RUN) + '/jobs?per_page=100',
                     'runs/' + str(RUN) + '/artifacts?per_page=100', 'artifacts/' + str(ARTIFACT) + '/zip'), 'unpinned API path')
    require(archive == (path == 'artifacts/' + str(ARTIFACT) + '/zip'), 'request kind mismatch')
    require(isinstance(token, str) and bool(token.strip()) and '\r' not in token and '\n' not in token, 'GITHUB_TOKEN required')
    opener = opener or urllib.request.build_opener(NoRedirect())
    url = API + path
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'ru-pack-artifact-loader'}
    for index in range(4):
        try:
            request = urllib.request.Request(url, headers=headers, method='GET')
            with opener.open(request, timeout=120) as response:
                require(response.status == 200, 'artifact request failed')
                return bounded_read(response, MAX_ZIP if archive else MAX_JSON)
        except urllib.error.HTTPError as error:
            location = error.headers.get('Location')
            code = error.code
            error.close()
            if not (archive and code in (301, 302, 303, 307, 308) and index < 3 and
                    isinstance(location, str) and safe_download_url(location)):
                raise ArtifactError('pinned API/download request failed', http_status=code) from None
            url = location
            headers = {'User-Agent': 'ru-pack-artifact-loader'}  # Never send credentials after redirect.
        except (urllib.error.URLError, OSError, ValueError):
            raise ArtifactError('pinned API/download transport unavailable') from None
    raise ArtifactError('artifact redirect limit exceeded')


def make_receipt(all_files, *, identity=None):
    identity = identity_values(identity)
    COMMIT, TREE, RUN, JOB, ARTIFACT, ZIP_SHA256, ZIP_SIZE, STAGE3_SHA256, VERIFICATION_SHA256 = (identity['COMMIT'], identity['TREE'], identity['RUN'], identity['JOB'], identity['ARTIFACT'], identity['ZIP_SHA256'], identity['ZIP_SIZE'], identity['STAGE3_SHA256'], identity['VERIFICATION_SHA256'])
    return {'schema': ('ru-pack-current-artifact-v1' if identity['current'] else 'ru-pack-old46c-artifact-v1'), 'scope': 'downloaded fixed old core, source checkout/tool validation still required',
               'repository': REPOSITORY, 'commit': COMMIT, 'tree': TREE, 'run_id': RUN, 'job_id': JOB,
               'artifact_id': ARTIFACT, 'zip_sha256': ZIP_SHA256, 'stage3_sha256': STAGE3_SHA256,
               'verification_sha256': VERIFICATION_SHA256, 'files': {name: digest(data) for name, data in all_files.items()},
               'identity': identity, 'required_source_binding': 'existing B bootstrap_provenance.validate against clean exact identity.commit checkout; report bytes unchanged'}


def no_links(path):
    """Reject POSIX symlinks and Windows reparse points, including ancestors."""
    require(path.is_absolute() and path.resolve() == path, 'canonical absolute artifact path required')
    for part in (path, *path.parents):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode) and
                not (getattr(info, 'st_file_attributes', 0) & 0x400), 'artifact link/reparse forbidden')


def read_fixed(path, limit):
    no_links(path)
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_size <= limit, 'artifact file shape/bound mismatch')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    after = path.stat()
    no_links(path)
    fields = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    require(len(data) <= limit and all(getattr(before, field) == getattr(after, field) for field in fields),
            'artifact changed during read')
    return data


def materialized_inventory(directory):
    """Count files and required directories, rejecting links/reparse aliases."""
    files = set()
    directories = set()
    for item in directory.rglob('*'):
        no_links(item)
        relative = item.relative_to(directory).as_posix()
        require(canonical_member(relative), 'unsafe materialized artifact path')
        if item.is_dir():
            directories.add(relative)
        else:
            require(item.is_file(), 'artifact file shape/bound mismatch')
            files.add(relative)
    validate_member_names(files)
    expected_directories = {'/'.join(name.split('/')[:index])
        for name in files for index in range(1, len(name.split('/')))}
    require(directories == expected_directories, 'artifact directory inventory mismatch')
    return files


def verify_output(directory, *, expected_receipt_sha256=None):
    """Offline revalidation, never trusts a self-reported receipt hash baseline."""
    directory = Path(directory)
    no_links(directory)
    require(directory.is_dir() and (directory/'receipt.json').is_file(), 'artifact directory inventory mismatch')
    receipt_raw = read_fixed(directory/'receipt.json', MAX_JSON)
    receipt = decode(receipt_raw)
    identity = receipt.get('identity')
    if identity != OLD:
        require(expected_receipt_sha256 is not None and digest(receipt_raw) == expected_receipt_sha256,
                'current receipt requires independent original digest pin')
        require(isinstance(identity, dict) and identity.get('current') is True, 'unknown artifact identity')
    raw = {name: read_fixed(directory/name, MAX_JSON) for name in ('run.json', 'jobs.json', 'artifacts.json')}
    validate_metadata(*(decode(raw[name]) for name in ('run.json', 'jobs.json', 'artifacts.json')), identity=identity)
    archive = read_fixed(directory/'archive.zip', MAX_ZIP)
    core = verify_archive(archive, identity=identity)
    all_files = {**raw, **core, 'archive.zip': archive}
    require(materialized_inventory(directory) == set(all_files) | {'receipt.json'},
            'artifact directory inventory mismatch')
    require(receipt == make_receipt(all_files, identity=identity), 'artifact receipt identity mismatch')
    for name, expected in all_files.items():
        require(read_fixed(directory/name, MAX_ZIP if name == 'archive.zip' else MAX_MEMBER) == expected,
                'extracted artifact differs from pinned archive')
    require(read_fixed(directory/'receipt.json', MAX_JSON) == receipt_raw, 'receipt changed')
    require(materialized_inventory(directory) == set(all_files) | {'receipt.json'},
            'artifact directory inventory mismatch')
    return receipt


def obtain(output, token, *, identity=None):
    identity = identity_values(identity)
    COMMIT, TREE, RUN, JOB, ARTIFACT, ZIP_SHA256, ZIP_SIZE, STAGE3_SHA256, VERIFICATION_SHA256 = (identity['COMMIT'], identity['TREE'], identity['RUN'], identity['JOB'], identity['ARTIFACT'], identity['ZIP_SHA256'], identity['ZIP_SIZE'], identity['STAGE3_SHA256'], identity['VERIFICATION_SHA256'])
    output = Path(output)
    require(output.is_absolute() and not output.exists() and not output.is_symlink(), 'fresh absolute output directory required')
    require(output.parent.is_dir() and output.parent.resolve() == output.parent, 'canonical output parent required')
    no_links(output.parent)
    # Validate token before creating output or performing any network operation.
    require(isinstance(token, str) and bool(token.strip()) and '\r' not in token and '\n' not in token, 'GITHUB_TOKEN required')
    raw = {name: fetch(path, token, identity=identity) for name, path in (
        ('run.json', 'runs/' + str(RUN)), ('jobs.json', 'runs/' + str(RUN) + '/jobs?per_page=100'),
        ('artifacts.json', 'runs/' + str(RUN) + '/artifacts?per_page=100'))}
    validate_metadata(*(decode(raw[name]) for name in ('run.json', 'jobs.json', 'artifacts.json')), identity=identity)
    archive = fetch('artifacts/' + str(ARTIFACT) + '/zip', token, archive=True, identity=identity)
    files = verify_archive(archive, identity=identity)
    return save_bundle(output, raw, archive, files, identity)


def save_bundle(output, raw, archive, files, identity):
    output.mkdir(exist_ok=False)
    all_files = {**raw, **files, 'archive.zip': archive}
    validate_member_names(all_files)
    for name, data in all_files.items():
        target = output/name
        target.parent.mkdir(parents=True, exist_ok=True)
        no_links(target.parent)
        with target.open('xb') as stream:
            stream.write(data)
        no_links(target)
    receipt = make_receipt(all_files, identity=identity)
    with (output/'receipt.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(receipt, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
    require(all(digest((output/name).read_bytes()) == value for name, value in receipt['files'].items()), 'saved artifact changed')
    return receipt


def current_member(name):
    if not canonical_member(name):
        return False
    if name in CURRENT_CORE:
        return True
    return re.fullmatch(r'pack-(?:runtime|windows)-artifacts-[a-f0-9]{32}/.+', name) is not None


def select_current(run, jobs, artifacts, *, run_id, commit, tree):
    require(type(run_id) is int and run_id > 0 and re.fullmatch('[a-f0-9]{40}', commit) and
            re.fullmatch('[a-f0-9]{40}', tree), 'current context malformed')
    candidates = [row for row in jobs.get('jobs', []) if row.get('name') == 'pack-bootstrap (windows-latest)']
    require(len(candidates) == 1, 'exact current Windows matrix job required')
    job = candidates[0]
    candidates = [row for row in artifacts.get('artifacts', [])
                  if row.get('name') == 'bootstrap-pack-windows-latest-' + commit]
    require(len(candidates) == 1, 'exact current Windows artifact required')
    artifact = candidates[0]
    require(type(artifact.get('size_in_bytes')) is int and 0 < artifact['size_in_bytes'] <= MAX_ZIP and
            re.fullmatch(r'sha256:[a-f0-9]{64}', artifact.get('digest', '')), 'current digest/size unavailable')
    identity = dict(COMMIT=commit, TREE=tree, RUN=run_id, JOB=job.get('id'), ARTIFACT=artifact.get('id'),
                    ZIP_SHA256=artifact['digest'][7:], ZIP_SIZE=artifact['size_in_bytes'],
                    STAGE3_SHA256=None, VERIFICATION_SHA256=None, current=True)
    validate_metadata(run, jobs, artifacts, identity=identity)
    return identity


def obtain_current(output, token, *, run_id, commit, tree):
    output = Path(output)
    require(output.is_absolute() and not output.exists() and not output.is_symlink(), 'fresh absolute output required')
    no_links(output.parent)
    # The run and SHA come from the current Actions context, not latest-branch lookup.
    require(type(run_id) is int and run_id > 0 and re.fullmatch('[a-f0-9]{40}', commit) and
            re.fullmatch('[a-f0-9]{40}', tree), 'current context malformed')
    provisional = dict(OLD, RUN=run_id, COMMIT=commit, TREE=tree, ARTIFACT=0, current=True)
    raw = {name: fetch(path, token, identity=provisional) for name, path in (
        ('run.json', 'runs/' + str(run_id)), ('jobs.json', 'runs/' + str(run_id) + '/jobs?per_page=100'),
        ('artifacts.json', 'runs/' + str(run_id) + '/artifacts?per_page=100'))}
    identity = select_current(*(decode(raw[name]) for name in ('run.json','jobs.json','artifacts.json')),
                              run_id=run_id, commit=commit, tree=tree)
    archive = fetch('artifacts/' + str(identity['ARTIFACT']) + '/zip', token, archive=True, identity=identity)
    require(len(archive) == identity['ZIP_SIZE'] and digest(archive) == identity['ZIP_SHA256'], 'current API ZIP digest mismatch')
    files = extract_core(archive, current=True)
    identity['STAGE3_SHA256'] = digest(files['stage3.exe'])
    identity['VERIFICATION_SHA256'] = digest(files['verification.json'])
    verify_archive(archive, identity=identity)
    return save_bundle(output, raw, archive, files, identity)


def current_checkout_tree():
    actions_workspace = Path(os.environ.get('GITHUB_WORKSPACE', ''))
    workspace = Path(__file__).resolve().parents[1]
    require(actions_workspace.is_absolute() and actions_workspace.is_dir() and workspace.is_dir() and
            (workspace == actions_workspace or actions_workspace in workspace.parents), 'current checkout unavailable')
    no_links(actions_workspace)
    no_links(workspace)
    values = []
    for revision in ('HEAD', 'HEAD^{tree}'):
        result = subprocess.run(['git', '-C', str(workspace), 'rev-parse', '--verify', revision],
                                capture_output=True, timeout=30, check=True)
        value = result.stdout.decode('ascii').strip()
        require(re.fullmatch('[a-f0-9]{40}', value), 'current Git identity malformed')
        values.append(value)
    require(values[0] == os.environ.get('GITHUB_SHA'), 'checkout is not current Actions SHA')
    return values[1]


SAFE_REASONS = frozenset(['35-case generation plan mismatch', 'GITHUB_TOKEN required', 'IR/ABI fixed point mismatch', 'JSON exceeds fixed bound', 'M4 artifact mismatch', 'M4 suite incomplete', 'ZIP size mismatch', 'archive exceeds fixed bound', 'archive member inventory mismatch', 'artifact changed during read', 'artifact directory inventory mismatch', 'artifact file shape/bound mismatch', 'artifact link/reparse forbidden', 'artifact receipt identity mismatch', 'artifact redirect limit exceeded', 'artifact request failed', 'canonical absolute artifact path required', 'canonical output parent required', 'checkout is not current Actions SHA', 'complete nine-artifact identity required', 'current API ZIP digest mismatch', 'current Git identity malformed', 'current checkout unavailable', 'current context malformed', 'current digest/size unavailable', 'current receipt requires independent original digest pin', 'duplicate API identity', 'duplicate JSON key', 'exact current Windows artifact required', 'exact current Windows matrix job required', 'expanded archive exceeds bound', 'extracted artifact differs from pinned archive', 'fresh absolute output directory required', 'fresh absolute output required', 'fresh absolute receipt pin required', 'generation result mismatch', 'generation results missing', 'invalid API row', 'invalid ZIP data', 'invalid artifact collection', 'invalid bounded UTF8 JSON', 'invalid job collection', 'native core gate mismatch', 'nonfinite JSON', 'not PE', 'not x64 PE32+', 'old Windows core job not successful', 'old artifact identity/expiry/digest mismatch', 'old run identity mismatch', 'paginated API collection incomplete', 'pinned API/download request failed', 'pinned API/download transport unavailable', 'pinned ZIP digest/size mismatch', 'pinned artifact missing', 'pinned core identity mismatch', 'pinned job missing', 'receipt changed', 'receipt pin must be outside artifact bundle', 'recomputed native fixed point differs from report', 'reported native fixed point missing', 'request kind mismatch', 'response exceeds fixed bound', 'saved artifact changed', 'source inventory shape mismatch', 'unknown artifact identity', 'unpinned API path', 'unsafe ZIP member'])

SAFE_REASONS = SAFE_REASONS | frozenset(['ambiguous Windows ZIP member', 'ZIP file directory collision',
    'unsafe materialized artifact path', 'pack toolchain shape mismatch', 'pack toolchain executable identity missing',
    'pack aggregate identity mismatch', 'pack referenced report changed', 'pack bootstrap report mismatch',
    'pack legacy aggregate identity mismatch', 'pack legacy report binding mismatch',
    'pack case source or compiler identity mismatch', 'pack compiler path malformed', 'pack compiler path disagreement',
    'pack evidence directory identity mismatch', 'pack evidence bytes changed', 'unreferenced pack evidence member',
    'pack legacy native compiler path mismatch', 'pack portable input or inventory mismatch',
    'pack portable result mismatch', 'pack portable log changed', 'pack legacy portable log changed',
    'current pack branch mismatch', 'pack verifier inputs changed during validation'])

def safe_failure(error):
    kind = type(error).__name__
    allowed_types = {'ArtifactError', 'HTTPError', 'URLError', 'CalledProcessError', 'TimeoutExpired',
                     'OSError', 'FileNotFoundError', 'PermissionError', 'ValueError', 'KeyError', 'TypeError'}
    result = {'schema':'ru-pack-artifact-failure-v1', 'complete':False,
              'error_type':kind if kind in allowed_types else 'UnexpectedError', 'reason':'unclassified_failure'}
    if isinstance(error, ArtifactError) and str(error) in SAFE_REASONS:
        result['reason'] = re.sub('[^a-z0-9]+', '_', str(error).lower()).strip('_')
        result['message'] = str(error)
        if type(error.http_status) is int and 100 <= error.http_status <= 599:
            result['http_status'] = error.http_status
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('mode', choices=('old', 'current'))
    parser.add_argument('--receipt-output', type=Path, required=True)
    
    args = parser.parse_args()
    try:
        pin_output = args.receipt_output
        require(pin_output.is_absolute() and not pin_output.exists() and not pin_output.is_symlink(), 'fresh absolute receipt pin required')
        no_links(pin_output.parent)
        require(args.output not in pin_output.parents, 'receipt pin must be outside artifact bundle')
        token = os.environ.get('GITHUB_TOKEN')
        if args.mode == 'old':
            receipt = obtain(args.output, token)
        else:
            receipt = obtain_current(args.output, token, run_id=int(os.environ.get('GITHUB_RUN_ID', '')),
                                     commit=os.environ.get('GITHUB_SHA', ''), tree=current_checkout_tree())
        receipt_hash = digest(read_fixed(args.output/'receipt.json', MAX_JSON))
        verify_output(args.output, expected_receipt_sha256=receipt_hash)
        with pin_output.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump({'path': str(args.output/'receipt.json'), 'sha256':receipt_hash}, stream, sort_keys=True)
            stream.write('\n')
    except Exception as error:
        print(json.dumps(safe_failure(error), sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps({'schema':receipt['schema'], 'commit':receipt['commit'], 'artifact_id':receipt['artifact_id'],
                      'zip_sha256':receipt['zip_sha256'], 'receipt_sha256':receipt_hash}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
