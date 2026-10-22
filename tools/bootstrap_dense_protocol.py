"""Private dense-v1 *data* transport. Never imports a Ru parser or lowering pass.

File reads are bounded JSON data reads or raw byte identity observations. Neither
this module nor the host determines source eligibility or emits kernel code.
Pre/post identities do not exclude intervening ABA mutations.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

PROTOCOL = 'bootstrap-dense-v1'
PLAN_ENCODING = 'utf8-json-compact-lf-v1'
FLAG = '--dense-utf8=' + PROTOCOL
MARKER = '/* RU_BOOTSTRAP_DENSE_UTF8_V1 */'
EFFECTS = ['borrow-read', 'no-escape', 'no-callback', 'no-gc', 'may-fail']
TYPES = {'borrow_ro_utf8', 'u8', 'u32'}
JSON_BYTES = 1_048_576
PACKET_BYTES = 4_194_304
PACKET_SCALARS = 1_048_576
MAX_FILES = 10_000
SOURCE_BYTES = 67_108_864
MAX_FUNCTIONS = 256
MAX_FIELDS = 64
MAX_DEPTH = 16
MAX_NODES = 200_000
LINUX_TARGETS = {'x86_64-pc-linux-gnu', 'x86_64-unknown-linux-gnu'}


def fail(message):
    raise ValueError('dense-v1: ' + message)


def string(value, *, name=False):
    if not isinstance(value, str) or not value or len(value) > (256 if name else 4096):
        fail('invalid string length/type')
    if any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        fail('control or surrogate character in string')
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail('duplicate JSON field: ' + key)
        result[key] = value
    return result


def _constant(value):
    fail('nonfinite JSON number: ' + value)


def parse_json(data, limit=JSON_BYTES):
    """Bound depth before calling json.loads; reject duplicate keys everywhere."""
    if len(data) > limit:
        fail('JSON byte limit exceeded')
    text = data.decode('utf-8', errors='strict')
    depth, quoted, escaped = 0, False, False
    for c in text:
        if quoted:
            if escaped:
                escaped = False
            elif c == '\\':
                escaped = True
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted = True
        elif c in '[{':
            depth += 1
            if depth > MAX_DEPTH:
                fail('JSON nesting limit exceeded')
        elif c in ']}':
            depth -= 1
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (RecursionError, json.JSONDecodeError) as error:
        fail('invalid JSON: ' + str(error))
    nodes = [value]
    count = 0
    while nodes:
        item = nodes.pop()
        count += 1
        if count > MAX_NODES:
            fail('JSON node limit exceeded')
        if isinstance(item, dict):
            nodes.extend(item.keys())
            nodes.extend(item.values())
        elif isinstance(item, list):
            nodes.extend(item)
        elif isinstance(item, str):
            string(item)
        elif isinstance(item, float):
            # Also catches a finite lexical exponent overflowing to infinity.
            import math
            if not math.isfinite(item):
                fail('nonfinite JSON number')
    return value


def read_json(path, limit=JSON_BYTES):
    with Path(path).open('rb') as stream:
        return parse_json(stream.read(limit + 1), limit)


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        fail('missing/unknown object fields')
    return value


def _list(value, limit, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= limit:
        fail('invalid array count/type')
    return value


def canonical_file(path, *, resolve_cli=False):
    """CLI roots may resolve once; transport/module identities may not alias."""
    path = Path(path)
    spelling = Path(os.path.abspath(path))
    resolved = path.resolve(strict=True)
    if not resolve_cli and spelling.as_posix() != resolved.as_posix():
        fail('path is not frozen canonical spelling (aliases unsupported): ' + str(path))
    # Reject Windows alternate streams / UNC / device paths also on POSIX.
    name = resolved.as_posix()
    string(name)
    if name.startswith('//') or ':' in name[2:]:
        fail('unsupported path spelling: ' + name)
    if not stat.S_ISREG(resolved.stat().st_mode):
        fail('input must be a regular file: ' + name)
    return resolved


def identity(path, *, limit=SOURCE_BYTES):
    path = canonical_file(path)
    h, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while chunk := stream.read(min(1024 * 1024, limit - size + 1)):
            h.update(chunk)
            size += len(chunk)
            if size > limit:
                fail('input exceeds byte limit')
    return {'path': str(path), 'sha256': h.hexdigest(), 'size': size}


def verify(identities):
    for old in identities:
        if identity(old['path'], limit=old['size']) != old:
            fail('input changed before publication: ' + old['path'])


def reject_overlap(inputs, outputs):
    """Protect equal spellings, existing hardlinks and parent/directory outputs."""
    ins = [Path(p).resolve() for p in inputs]
    outs = [Path(p).resolve() for p in outputs]
    if len(set(outs)) != len(outs):
        fail('duplicate output paths')
    all_paths = ins + outs
    for i, out in enumerate(outs):
        if out.is_dir() or out in ins:
            fail('output overlaps input/directory: ' + str(out))
        if out.exists():
            for other in all_paths[:len(ins) + i]:
                if other.exists() and out.samefile(other):
                    fail('output physical alias: ' + str(out))


def inventory(source, roots):
    """Enumerate explicit trees only, without discovering/parsing imports."""
    source = canonical_file(source, resolve_cli=True)
    roots = {Path(p).resolve(strict=True) for p in roots} | {source.parent}
    if any(not root.is_dir() for root in roots):
        fail('inventory roots must be directories')
    paths = {source}
    for root in sorted(roots):
        for entry in root.rglob('*.ru'):
            path = canonical_file(entry)
            if not path.is_relative_to(root):
                fail('source escapes inventory root')
            paths.add(path)
            if len(paths) > MAX_FILES:
                fail('inventory path count exceeded')
    physical, result, total = set(), [], 0
    for path in sorted(paths):
        st = path.stat()
        key = (st.st_dev, st.st_ino)
        if key in physical:
            fail('physical source aliases unsupported')
        physical.add(key)
        item = identity(path)
        total += item['size']
        if total > SOURCE_BYTES:
            fail('inventory byte limit exceeded')
        result.append(item)
    return result


def _ordered_types(value):
    if not isinstance(value, dict) or len(value) > MAX_FIELDS:
        fail('invalid parameter/local object')
    result = []
    for name, type_ in value.items():
        string(name, name=True)
        if not isinstance(type_, str) or type_ not in TYPES:
            fail('unsupported boundary type')
        result.append([name, type_])
    return result


def prepare_transport(manifest_path, source_paths):
    manifest_path = canonical_file(manifest_path, resolve_cli=True)
    if not 1 <= len(source_paths) <= MAX_FILES:
        fail('invalid inventory count')
    paths = [canonical_file(p).as_posix() for p in source_paths]
    if not 1 <= len(paths) <= MAX_FILES or len(paths) != len(set(paths)):
        fail('invalid inventory count/duplicates')
    document = _object(read_json(manifest_path), {'version', 'functions'})
    if type(document['version']) is not int or document['version'] != 1:
        fail('unknown manifest version')
    records = []
    selected = set()
    for function in _list(document['functions'], MAX_FUNCTIONS, 1):
        _object(function, {'module', 'function', 'params', 'result', 'effects'}, {'locals', 'ranges'})
        module = string(function['module'])
        # Explicitly reject foreign path forms rather than accidentally treating
        # them as manifest-relative POSIX paths.
        normalized = module.replace('\\', '/')
        if normalized.startswith('//') or (':' in normalized and not re.match(r'^[A-Za-z]:/[^:]*$', normalized)):
            fail('unsupported module path spelling')
        path = Path(normalized)
        if not path.is_absolute():
            path = manifest_path.parent / path
        path = canonical_file(path).as_posix()
        if path not in paths:
            fail('manifest module absent from frozen inventory')
        name = string(function['function'], name=True)
        key = (path, name)
        if key in selected:
            fail('duplicate function selection')
        selected.add(key)
        params = _ordered_types(function['params'])
        locals_ = _ordered_types(function.get('locals', {}))
        if {n for n, _ in params} & {n for n, _ in locals_}:
            fail('locals collide with parameters')
        result = function['result']
        if result not in ('u8', 'u32') or function['effects'] != EFFECTS:
            fail('unsupported result/effect contract')
        ranges = []
        for item in _list(function.get('ranges', []), MAX_FIELDS):
            _object(item, {'view', 'begin', 'end'})
            triple = [string(item[k], name=True) for k in ('view', 'begin', 'end')]
            if triple in ranges:
                fail('duplicate range contract')
            ranges.append(triple)
        # Eligibility, source binding, view count and range parameter types are
        # exclusively the native frontend's responsibility.
        records.append([module, path, name, params, result, list(EFFECTS), locals_, ranges])
    return [PROTOCOL, manifest_path.as_posix(), paths, records]


def packet_bytes(packet):
    count, scalars, bytes_ = 0, 0, 0
    def charge(text):
        nonlocal scalars, bytes_
        scalars += len(text)
        bytes_ += len(text.encode("utf-8"))
        if scalars > PACKET_SCALARS or bytes_ > PACKET_BYTES:
            fail("packet byte/scalar limit exceeded")
        return text
    def emit(value, depth=0):
        nonlocal count
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            fail('packet node/depth limit exceeded')
        if isinstance(value, str):
            return charge('"' + string(value).replace('\\', '\\\\').replace('"', '\\"') + '"')
        if isinstance(value, list):
            charge('[' + ',' * max(0, len(value) - 1) + ']')
            return '[' + ','.join(emit(item, depth + 1) for item in value) + ']'
        fail('packet must contain strings and arrays only')
    text = emit(packet)
    data = text.encode('utf-8')
    if len(data) > PACKET_BYTES or len(text) > PACKET_SCALARS:
        fail('packet byte/scalar limit exceeded')
    return data


def write_packet(path, packet):
    # Exclusive creation prevents clobbering frozen inputs or prior outputs.
    data = packet_bytes(packet)
    with Path(path).open('xb') as stream:
        stream.write(data)
    return {'path': str(canonical_file(path)), 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}


def validate_metadata(metadata, ir, triple, *, enabled, native=False, data_layout=None):
    markers = re.findall(r'/\*\s*RU_BOOTSTRAP_DENSE_[^\n]*?\*/', metadata)
    if not enabled:
        if 'RU_BOOTSTRAP_DENSE_' in metadata:
            fail('dense metadata requires explicit dense option')
        return
    if markers != [MARKER] or metadata.count('RU_BOOTSTRAP_DENSE_') != 1:
        fail('missing/unknown/repeated dense metadata marker')
    lines = metadata.splitlines()
    if native and (metadata.count('RU_BOOTSTRAP_NATIVE_') != 1 or
                   not lines or lines[0] != '/* RU_BOOTSTRAP_NATIVE_V1 ' + triple + ' */'):
        fail('native metadata marker mismatch in combined mode')
    position = 1 if native else 0
    if len(lines) <= position or lines[position] != MARKER:
        fail('dense metadata marker order mismatch')
    if re.findall(r'^target triple = "([^"\n]+)"$', ir, re.M) != [triple]:
        fail('frontend target triple mismatch')
    if data_layout is None or re.findall(r'^target datalayout = "([^"\n]+)"$', ir, re.M) != [data_layout]:
        fail('frontend target data layout mismatch')


def validate_plan(path, packet, *, return_identity=False):
    """Cross-check frontend output against transport; never infer eligibility."""
    path = canonical_file(path)
    with path.open('rb') as stream:
        data = stream.read(PACKET_BYTES + 1)
    plan = parse_json(data, PACKET_BYTES)
    if not isinstance(plan, list) or len(plan) != 3 or plan[:2] != packet[:2]:
        fail('plan root/version/manifest mismatch')
    rows = _list(plan[2], MAX_FUNCTIONS, 1)
    if len(rows) != len(packet[3]):
        fail('plan selected count mismatch')
    ids = set()
    for row, contract in zip(rows, packet[3]):
        if not isinstance(row, list) or len(row) != 9:
            fail('plan record field count mismatch')
        module, name, function_id, symbol, params, result, effects, locals_, ranges = row
        if not isinstance(function_id, str) or not re.fullmatch(r'0|[1-9][0-9]{0,19}', function_id):
            fail('invalid selected internal function ID')
        if function_id in ids or symbol != 'boot_dense_' + function_id:
            fail('duplicate ID or invalid generated symbol')
        ids.add(function_id)
        if [module, name, params, result, effects, locals_, ranges] != contract[1:]:
            fail('plan ordered contract differs from transport')
    if data != plan_bytes(plan):
        fail('plan must use canonical UTF8 compact JSON with one final LF')
    observed = {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
    return (plan, observed) if return_identity else plan


def plan_bytes(plan):
    """PureRu JSON句 output for the restricted strings/arrays-only plan."""
    return (json.dumps(plan, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')


def verify_proof_hashes(proof):
    """Reconstruct transport/plan bytes after temporary staging files are gone."""
    if proof.get('dense_protocol') != PROTOCOL or proof.get('dense_plan_encoding') != PLAN_ENCODING:
        fail('unknown dense proof protocol/encoding')
    for key, data in (('dense_packet', packet_bytes(proof['dense_transport'])),
                      ('dense_plan', plan_bytes(proof['dense_selected_plan']))):
        observed = proof[key]
        if observed['size'] != len(data) or observed['sha256'] != hashlib.sha256(data).hexdigest():
            fail('dense proof reconstructed hash/size mismatch: ' + key)
