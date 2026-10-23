#!/usr/bin/env python3
"""Read-only pinned old-slot Windows artifact loader; never bootstrap acceptance.

The existing B source/provenance validator must subsequently bind the untouched
verification bytes to the separate clean exact925/current source checkout and trusted tools.
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
COMMIT = '925707005a80cf935d12ea4fc88316d941452955'
TREE = '986c5ef4ec650d949f9bcd6f32177bb8ba371190'
RUN = 39888101539
JOB = 120200970044
ARTIFACT = 12474435880
ZIP_SHA256 = '2a6ff14ab3a6da449cbb81769c8f1b89e8819cd574b0fa65fbf3a295509fd4af'
ZIP_SIZE = 25689587
STAGE3_SHA256 = 'b797aa421a81d17469d4de8c1ce1a4169f49960051ea673413aef7c77fe51f15'
VERIFICATION_SHA256 = 'd154b4e3af666e39f3f18e7051b6a4d900446635cb86ac64216c9a05195b375d'
API = 'https://api.github.com/repos/' + REPOSITORY + '/actions/'
MAX_JSON = 4 * 1024 * 1024
MAX_ZIP = 32 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_MEMBER = 96 * 1024 * 1024
CORE = frozenset(['verification.json', 'report.json', 'native-frontend-tests.json', 'native-windows-tests.json',
                  'stage1.exe', 'stage2.exe', 'stage3.exe', 'stage2.ll', 'stage3.ll',
                  'stage2.exe.frontend.ll', 'stage3.exe.frontend.ll', 'stage2.exe.metadata.c', 'stage3.exe.metadata.c'])
IGNORED = frozenset(['notepad-console-link/application.ll', 'notepad-console-link/compile-proof.json', 'notepad-console-link/ru_notepad-console.exe', 'notepad-console-link/ru_notepad-console.exe.frontend.ll', 'notepad-console-link/ru_notepad-console.exe.metadata.c', 'notepad-console-link/verification.json', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/expected.stdout', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/lifetime.ru', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/pure-ru-negative-source/compiler.ru', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/pure-ru-negative-source/native_emit.ru', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python-unsafe-unwind.stderr', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python-unsafe-unwind.stdout', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python-unsafe-unwind/linked.bc', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python-unsafe-unwind/optimized.bc', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python-unsafe-unwind/program.bc', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python-unsafe-unwind/program.exe', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python-unsafe-unwind/program.ll', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python-unsafe-unwind/program.o', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python-unsafe-unwind/runtime.bc', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python-unsafe-unwind/runtime.c', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python-unsafe-unwind/standalone.ll', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python.stderr', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python.stdout', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python/linked.bc', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python/optimized.bc', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python/program.bc', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python/program.exe', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python/program.ll', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python/program.o', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python/runtime.bc', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python/runtime.c', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/python/standalone.ll', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/receipt.json', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3-unsafe-compiler/build-proof.json', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3-unsafe-compiler/program.exe', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3-unsafe-compiler/program.exe.frontend.ll', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3-unsafe-compiler/program.exe.metadata.c', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3-unsafe-compiler/standalone.ll', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3-unsafe-unwind.stderr', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3-unsafe-unwind.stdout', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3-unsafe-unwind/build-proof.json', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3-unsafe-unwind/program.exe', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3-unsafe-unwind/program.exe.frontend.ll', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3-unsafe-unwind/program.exe.metadata.c', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3-unsafe-unwind/standalone.ll', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3.stderr', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3.stdout', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3/build-proof.json', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3/program.exe', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3/program.exe.frontend.ll', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3/program.exe.metadata.c', 'slot-runtime-artifacts-ab29babf5ea942d78b762ad56eb4ee72/slot-lifetime-f0q28ju4/stage3/standalone.ll', 'slot-runtime-tests.json', 'slot-unit-tests.json', 'slot-unit-tests.log', 'slot-verification.json', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/acceptance.json', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/acceptance.json', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/application.ll', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/bridge.c', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/compile-proof.json', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/main.ru', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/owned_bridge.dll', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/owned_bridge.exp', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/owned_bridge.lib', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/panic_module.ru', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/program.exe', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/program.exe.frontend.ll', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/program.exe.metadata.c', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/runtime.instrumented.c', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/runtime.original.c', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/stderr.txt', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/probe/stdout.txt', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/production/acceptance.json', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/production/application.ll', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/production/bridge.c', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/production/compile-proof.json', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/production/main.ru', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/production/owned_bridge.dll', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/production/owned_bridge.exp', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/production/owned_bridge.lib', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/production/panic_module.ru', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/production/program.exe', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/production/program.exe.frontend.ll', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/production/program.exe.metadata.c', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/production/stderr.txt', 'slot-windows-artifacts-6737849ad7f14c90b67c9dcbf24f60bf/test_parent_temporaries_survive_nested_callback_panic_retry/production/stdout.txt', 'slot-windows-tests.json'])
GATES = frozenset(['source_ir_and_abi_fixed_point', 'native_binary_fixed_point',
                  'same_nonempty_suite_for_each_stage', 'every_planned_case_ran',
                  'every_case_passed_without_skips', 'test_runner_success_without_skips',
                  'inputs_unchanged', 'artifacts_unchanged_during_tests'])


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
            run.get('event') == 'push' and run.get('path') == ('.github/workflows/bootstrap-slot-address.yml' if identity['current'] else '.github/workflows/bootstrap-slot-reuse.yml') and
            run.get('repository', {}).get('full_name') == REPOSITORY and
            run.get('head_repository', {}).get('full_name') == REPOSITORY, 'old run identity mismatch')
    # The overall run has a separately diagnosed GUI failure; only this exact
    # successful Windows core job attests the pinned compiler bundle.
    job = one(jobs.get('jobs'), JOB, 'job')
    require(job.get('run_id') == RUN and job.get('head_sha') == COMMIT and
            job.get('status') == 'completed' and job.get('conclusion') == 'success' and
            job.get('name') == 'slot-bootstrap (windows-latest)', 'old Windows core job not successful')
    artifact = one(artifacts.get('artifacts'), ARTIFACT, 'artifact')
    require(artifact.get('workflow_run', {}).get('id') == RUN and
            artifact.get('workflow_run', {}).get('head_sha') == COMMIT and
            artifact.get('name') == 'bootstrap-slot-windows-latest-' + COMMIT and
            artifact.get('expired') is False and artifact.get('digest') == 'sha256:' + ZIP_SHA256 and
            artifact.get('size_in_bytes') == ZIP_SIZE, 'old artifact identity/expiry/digest mismatch')
    for collection, key in ((jobs, 'jobs'), (artifacts, 'artifacts')):
        total = collection.get('total_count', len(collection[key]))
        require(type(total) is int and total == len(collection[key]), 'paginated API collection incomplete')
    return artifact


def extract_core(raw, *, current=False):
    """Pure bounded ZIP structural validator; production calls only after pin check."""
    require(len(raw) <= MAX_ZIP, 'archive exceeds fixed bound')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            require(len(names) <= 512 and len(names) == len(set(names)) and
                    (set(names) == CORE | IGNORED if not current else CORE <= set(names) and all(current_member(name) for name in names)), 'archive member inventory mismatch')
            require(sum(entry.file_size for entry in entries) <= MAX_EXPANDED, 'expanded archive exceeds bound')
            for entry in entries:
                path = PurePosixPath(entry.filename)
                mode = entry.external_attr >> 16
                require(not path.is_absolute() and '..' not in path.parts and '\\' not in entry.filename and
                        not PureWindowsPath(entry.filename).is_absolute() and not entry.is_dir() and
                        stat.S_IFMT(mode) in (0, stat.S_IFREG) and not (entry.flag_bits & 1) and
                        entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) and
                        0 <= entry.file_size <= MAX_MEMBER, 'unsafe ZIP member')
            result = {name: archive.read(name) for name in sorted(CORE)}
            require(all(len(result[name]) == archive.getinfo(name).file_size for name in CORE), 'ZIP size mismatch')
            return result
    except (zipfile.BadZipFile, NotImplementedError, EOFError, OSError):
        raise ArtifactError('invalid ZIP data') from None


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
    require((0 < len(inventory) <= 512 if identity['current'] else len(inventory) == 62) and all(isinstance(name, str) and not PurePosixPath(name).is_absolute() and
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
               'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'ru-slot-old-artifact-loader'}
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
            headers = {'User-Agent': 'ru-slot-old-artifact-loader'}  # Never send credentials after redirect.
        except (urllib.error.URLError, OSError, ValueError):
            raise ArtifactError('pinned API/download transport unavailable') from None
    raise ArtifactError('artifact redirect limit exceeded')


def make_receipt(all_files, *, identity=None):
    identity = identity_values(identity)
    COMMIT, TREE, RUN, JOB, ARTIFACT, ZIP_SHA256, ZIP_SIZE, STAGE3_SHA256, VERIFICATION_SHA256 = (identity['COMMIT'], identity['TREE'], identity['RUN'], identity['JOB'], identity['ARTIFACT'], identity['ZIP_SHA256'], identity['ZIP_SIZE'], identity['STAGE3_SHA256'], identity['VERIFICATION_SHA256'])
    return {'schema': ('ru-slot-address-current-artifact-v1' if identity['current'] else 'ru-slot-address-old925-artifact-v1'), 'scope': 'downloaded fixed old core, source checkout/tool validation still required',
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


def verify_output(directory, *, expected_receipt_sha256=None):
    """Offline revalidation, never trusts a self-reported receipt hash baseline."""
    directory = Path(directory)
    no_links(directory)
    names = CORE | {'archive.zip', 'run.json', 'jobs.json', 'artifacts.json', 'receipt.json'}
    require(directory.is_dir() and {p.name for p in directory.iterdir()} == names, 'artifact directory inventory mismatch')
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
    receipt = decode(read_fixed(directory/'receipt.json', MAX_JSON))
    require(receipt == make_receipt(all_files, identity=identity), 'artifact receipt identity mismatch')
    for name, expected in all_files.items():
        require(read_fixed(directory/name, MAX_ZIP if name == 'archive.zip' else MAX_MEMBER) == expected,
                'extracted artifact differs from pinned archive')
    require(decode(read_fixed(directory/'receipt.json', MAX_JSON)) == receipt, 'receipt changed')
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
    for name, data in all_files.items():
        with (output/name).open('xb') as stream:
            stream.write(data)
    receipt = make_receipt(all_files, identity=identity)
    with (output/'receipt.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(receipt, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
    require(all(digest((output/name).read_bytes()) == value for name, value in receipt['files'].items()), 'saved artifact changed')
    return receipt


def current_member(name):
    if name in CORE or name in {'slot-runtime-tests.json', 'slot-unit-tests.json', 'slot-unit-tests.log',
                               'slot-verification.json', 'slot-windows-tests.json'}:
        return True
    if name in {n for n in IGNORED if n.startswith('notepad-console-link/')}:
        return True
    return re.fullmatch(r'slot-(?:runtime|windows)-artifacts-[a-f0-9]{32}/[^\\]+', name) is not None


def select_current(run, jobs, artifacts, *, run_id, commit, tree):
    require(type(run_id) is int and run_id > 0 and re.fullmatch('[a-f0-9]{40}', commit) and
            re.fullmatch('[a-f0-9]{40}', tree), 'current context malformed')
    candidates = [row for row in jobs.get('jobs', []) if row.get('name') == 'slot-bootstrap (windows-latest)']
    require(len(candidates) == 1, 'exact current Windows matrix job required')
    job = candidates[0]
    candidates = [row for row in artifacts.get('artifacts', [])
                  if row.get('name') == 'bootstrap-slot-windows-latest-' + commit]
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

def safe_failure(error):
    kind = type(error).__name__
    allowed_types = {'ArtifactError', 'HTTPError', 'URLError', 'CalledProcessError', 'TimeoutExpired',
                     'OSError', 'FileNotFoundError', 'PermissionError', 'ValueError', 'KeyError', 'TypeError'}
    result = {'schema':'ru-address-artifact-failure-v1', 'complete':False,
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
