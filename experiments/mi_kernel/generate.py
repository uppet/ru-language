"""Experimental internal typed IR. Not a parser or public Ru language syntax.

MIT; see ../../LICENSE. Uses existing native ABI names/layout/signature objects.
Only the checked u8/u32/read-only-view subset is intentionally accepted.
"""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from rulang.native_c import C_TYPES, NativeCSignature, PRIMITIVE_IDS
from rulang.native_runtime import PRIMITIVES, NativeSignature

HERE = Path(__file__).resolve().parent
U32_MAX = 4294967295
TYPES = {'非负8': 'u8', '非负32': 'u32'}


def signature(result, params):
    """Normalize new internal spelling into the OLD ABI descriptor; no caller."""
    names = tuple(TYPES.get(p, p) for p in params)
    result = TYPES.get(result, result)
    if any(t not in ('u8', 'u32', '指针') for t in (result,) + names):
        raise ValueError('实验不支持此签名类型')
    legacy = NativeSignature(PRIMITIVES[result], tuple(PRIMITIVES[t] for t in names), 'cdecl')
    normalized = NativeCSignature(legacy.result.name, tuple(p.name for p in legacy.params))
    return normalized


def validate_legacy_fixture(ir):
    if set(ir) != {'version', 'params', 'locals', 'body', 'return'} or ir['version'] != 1:
        raise ValueError('实验 IR 版本／字段不支持')
    if ir['params'] != {'data': 'borrow_ro_u8', 'length': 'u32', 'seed': 'u32'}:
        raise ValueError('仅支持不逃逸只读字节视图签名')
    env = dict(ir['params'])
    def expr(e, allow_load=False):
        if not isinstance(e, list) or not e: raise ValueError('非法表达式')
        op, *a = e
        if op == 'const' and len(a) == 2:
            t, v = a
            if t not in ('u8','u32') or type(v) is not int or not 0 <= v <= (255 if t == 'u8' else U32_MAX):
                raise ValueError('上下文常量超出类型范围')
            return t
        if op == 'var' and len(a) == 1 and a[0] in env: return env[a[0]]
        if op == 'load' and allow_load and len(a) == 1 and expr(a[0]) == 'u32': return 'u8'
        if op in ('eq','ne','lt') and len(a) == 2:
            l, r = expr(a[0]), expr(a[1])
            if l != r or l not in ('u8','u32'): raise ValueError('比较类型不匹配')
            return 'fact'
        if op in ('and','or') and len(a) == 2 and all(expr(v)=='fact' for v in a): return 'fact'
        if op == 'truth' and len(a) == 1 and expr(a[0]) in ('u8','u32'): return 'fact'
        raise ValueError('不支持的表达式／隐式转换')
    for name, typ, initial in ir['locals']:
        if not name.isascii() or not name.isidentifier() or name in env or typ not in ('u8','u32'):
            raise ValueError('非法／重复局部变量')
        if expr(initial) != typ: raise ValueError('局部初始化类型不匹配')
        env[name] = typ
    if env.get('count') != 'u32': raise ValueError('缺少部分结果槽')
    writable = {n for n, _, _ in ir['locals']}
    def body(stmts):
        for s in stmts:
            op, *a = s
            if op == 'set' and len(a) == 2 and a[0] in writable and expr(a[1], allow_load=True) == env[a[0]]: continue
            if op == 'add_checked' and len(a) == 2 and a[0] in writable and env[a[0]] == 'u32' and expr(a[1]) == 'u32': continue
            if op in ('if','while') and len(a) == 2 and expr(a[0]) == 'fact':
                body(a[1]); continue
            raise ValueError('不支持的语句／视图逃逸／类型改变')
    body(ir['body'])
    if expr(ir['return']) != 'u32': raise ValueError('借用不得返回／装箱／保存')
    return env


def lower_legacy_fixture(ir, target):
    env = validate_legacy_fixture(ir)
    names = {name: name for name in ir["params"]}
    names.update({name: f"local_{i}" for i, (name, _, _) in enumerate(ir["locals"])})
    count = names["count"]
    lines = []
    serial = 0
    def emit(s, depth): lines.append('    '*depth+s)
    def expr(e, depth):
        nonlocal serial
        op,*a=e
        if op=='const':return str(a[1]) + ('u' if target=='c' else '')
        if op=='var':return names[a[0]]
        if op=='truth':return '1' if target=='c' else 'true'  # every numeric value incl. 0 is true
        if op=='load':
            i=expr(a[0], depth); serial+=1; v=f'byte_{serial}'
            emit(f'if ({i} >= length) '+ ('return (MiResult){MI_BOUNDS, '+count+'};' if target=='c' else 'return {status: MI_BOUNDS, count: '+count+'};'),depth)
            emit((f'{C_TYPES["u8"]} ' if target=='c' else 'const ')+f'{v} = data[{i}];',depth)
            return v
        x,y=[expr(v,depth) for v in a]
        sign={'eq':'==','ne':'!=','lt':'<','and':'&&','or':'||'}[op]
        return f'({x} {sign} {y})'
    def body(stmts, depth):
        for op,*a in stmts:
            if op=='set':emit(f'{names[a[0]]} = {expr(a[1],depth)};',depth)
            elif op=='add_checked':
                rhs=expr(a[1],depth); limit='UINT32_MAX' if target=='c' else '4294967295'
                emit(f'if ({rhs} > {limit} - {names[a[0]]}) '+('return (MiResult){MI_OVERFLOW, '+count+'};' if target=='c' else 'return {status: MI_OVERFLOW, count: '+count+'};'),depth)
                emit(f'{names[a[0]]} += {rhs};',depth)
            else:
                # validate() permits only scalar/pure condition operands;
                # inspect operation nodes there, never substrings of identifiers.
                cond=expr(a[0],depth); emit(f'{op} ({cond}) {{',depth); body(a[1],depth+1);emit('}',depth)
    for name,typ,init in ir['locals']:
        val=expr(init,1); emit((C_TYPES[typ] if target=='c' else 'let')+f' {names[name]} = {val};',1)
    body(ir['body'],1)
    val=expr(ir['return'],1)
    emit(('return (MiResult){MI_OK, '+val+'};') if target=='c' else 'return {status: MI_OK, count: '+val+'};',1)
    return '\n'.join(lines)


def generate(out=HERE/'generated'):
    ir=json.loads((HERE/'scan.ir.json').read_text()); out.mkdir(exist_ok=True)
    c='''/* Generated experiment, not production Ru syntax. MIT: repository LICENSE. */
#ifndef MI_KERNEL_H
#define MI_KERNEL_H
#include <stdint.h>
#include <stddef.h>
enum { MI_OK, MI_BOUNDS, MI_OVERFLOW, MI_CLOSED, MI_BORROWED, MI_RANGE };
typedef struct { int status; uint32_t count; } MiResult;
/* Internal-only owner/view; callers must supply genuine storage extent.
   No raw user addresses. Thread-confined; not an FFI or concurrency protocol. */
typedef struct { const uint8_t *data; uint32_t size; uint32_t borrows; int closed; } MiOwner;
static inline int mi_close(MiOwner *owner) {
    if (owner->borrows) return MI_BORROWED;
    owner->closed = 1; return MI_OK;
}
static inline int mi_truth_u32(uint32_t value) { (void)value; return 1; }
static MiResult mi_kernel(const uint8_t *data, uint32_t length, uint32_t seed) {
'''+lower_legacy_fixture(ir,'c')+'''
}
/* Internal scalar failure state is NOT a C ABI signature extension. */
static MiResult mi_scan(MiOwner *owner, uint32_t offset, uint32_t length, uint32_t seed) {
    if (owner->closed) return (MiResult){MI_CLOSED, seed};
    if (offset > owner->size || length > owner->size - offset)
        return (MiResult){MI_BOUNDS, seed};
    if ((length && !owner->data) || owner->borrows == UINT32_MAX)
        return (MiResult){MI_RANGE, seed};
    ++owner->borrows;
    /* Avoid even +0 arithmetic on NULL for the legal empty view. */
    const uint8_t *view = length ? owner->data + offset : NULL;
    MiResult result = mi_kernel(view, length, seed);
    --owner->borrows;
    return result;
}
/* Fixture ordinary-input adapter: validate BEFORE any uint32_t narrowing. */
static inline MiResult mi_scan_checked(MiOwner *owner, int64_t offset, int64_t length, int64_t seed) {
    if (seed < 0 || seed > UINT32_MAX) return (MiResult){MI_RANGE, 0};
    if (offset < 0 || offset > UINT32_MAX || length < 0 || length > UINT32_MAX)
        return (MiResult){MI_RANGE, (uint32_t)seed};
    return mi_scan(owner, (uint32_t)offset, (uint32_t)length, (uint32_t)seed);
}
#endif
'''
    js='''// Generated semantic model. No native-address or no-GC promise for JS.
'use strict';
const [MI_OK, MI_BOUNDS, MI_OVERFLOW, MI_CLOSED, MI_BORROWED, MI_RANGE] = [0,1,2,3,4,5];
function truthU32(value) { return true; }
function kernel(data, length, seed) {
'''+lower_legacy_fixture(ir,'js')+'''
}
function u32(x) { return Number.isInteger(x) && x >= 0 && x <= 4294967295; }
class Owner {
    #data; #closed = false; #borrows = 0;
    constructor(bytes) {
        if (!(bytes instanceof Uint8Array) || bytes.length > 4294967295)
            throw new TypeError('需要范围内的字节输入');
        // Explicit copy at owner creation; no arbitrary external mutable alias.
        this.#data = new Uint8Array(bytes);
    }
    get borrows() { return this.#borrows; }
    close() {
        if (this.#borrows) return MI_BORROWED;
        this.#closed = true; this.#data = null; return MI_OK;
    }
    scan(offset, length, seed) {
        if (!u32(seed)) return {status:MI_RANGE, count:0};
        if (!u32(offset) || !u32(length)) return {status:MI_RANGE, count:seed};
        if (this.#closed) return {status:MI_CLOSED, count:seed};
        if (offset > this.#data.length || length > this.#data.length - offset)
            return {status:MI_BOUNDS, count:seed};
        ++this.#borrows;
        try { return kernel(this.#data.subarray(offset, offset+length), length, seed); }
        finally { --this.#borrows; }
    }
}
function scan(owner, offset, length, seed=0) {
    if (!(owner instanceof Owner)) throw new TypeError('需要受管理 owner');
    return owner.scan(offset, length, seed);
}
module.exports = {Owner, scan, truthU32};
'''
    (out/'kernel.h').write_text(c, encoding="utf-8", newline="\n");(out/'kernel.js').write_text(js, encoding="utf-8", newline="\n")
    sig=signature('非负32', ['非负8','非负32'])
    metadata={'experimental':True,'schema':1,'types':{name:{'legacy':t,'id':PRIMITIVE_IDS[t], 'c':C_TYPES[t], 'size':PRIMITIVES[t].size,'alignment':PRIMITIVES[t].alignment} for name,t in TYPES.items()}, 'scalar_signature_example':{'result':sig.result,'params':sig.params}, 'effects':['borrow-read','may-fail'],'abi_note':'mi_kernel uses internal status; not exported FFI','hot_c_gc_allocations':0,'hot_c_boxings':0,'hot_c_input_copied_bytes':0,'ordinary_boundary':'experimental owner wrapper; no Ru AST/CLI integration'}
    (out/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n', encoding='utf-8', newline='\n')

# v1 is retained only to reproduce historical line-terminator evidence. New
# source compilation and v2 IR always use the fully signature-driven backend.
from rulang.mi_ir import validate as validate_source_ir, lower as lower_source_ir


def validate(ir):
    return validate_source_ir(ir) if ir.get('version') == 2 else validate_legacy_fixture(ir)


def lower(ir, target, symbol='ru_mi_kernel'):
    return lower_source_ir(ir, target, symbol) if ir.get('version') == 2 else lower_legacy_fixture(ir, target)


def generate_source(manifest, out, entry=None):
    """Generate all signatures/bodies from source-selected frontend AST nodes."""
    from hashlib import sha256
    from rulang.frontend import parse
    from rulang.modules import load_module_graph
    from rulang.mi_source import MiSourcePlan, read_manifest
    import os
    manifest = Path(manifest).resolve()
    document = read_manifest(manifest)
    modules = {}
    entries = [Path(entry).resolve()] if entry else [(manifest.parent / row['module']).resolve() for row in document['functions']]
    for source in entries:
        modules.update(load_module_graph(source, parse(source.read_text(encoding='utf-8'))))
    plan = MiSourcePlan(modules, manifest)
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    for target, name in (('c', 'kernel.h'), ('js', 'kernel.js'), ('llvm', 'kernel.ll')):
        (out / name).write_text(plan.compute_source(target), encoding='utf-8', newline='\n')
    records = [{'module': Path(os.path.relpath(r['module'], manifest.parent)).as_posix(),
                'function': r['function'], 'symbol': r['symbol'], 'ir': r['ir'], 'ranges': r['ranges'],
                'source_sha256': sha256(Path(r['module']).read_bytes()).hexdigest()} for r in plan.records]
    from rulang.mi_ir import UTF8
    for record, selected in zip(records, plan.records):
        if UTF8 in selected['input_contracts'].values():
            record['input_contracts'] = selected['input_contracts']
    (out / 'ir.json').write_text(json.dumps(records, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    metadata = {'experimental': True, 'schema': 2, 'manifest_sha256': sha256(manifest.read_bytes()).hexdigest(),
        'source_count': len(records), 'ordinary_bridge': 'C/LLVM NativeMemory synchronous readonly on Windows x64; scalar C/LLVM also on Linux; explicit --experimental-mi-manifest',
        'llvm_scope': 'direct checked IR to LLVM 14; pointer/u32 private ABI; no generated C kernel body',
        'self_hosted_mi_frontend': False,
        'js_scope': 'same IR compute semantics only, no NativeMemory or physical ABI promise',
        'kernel_gc_allocations': 0, 'kernel_boxings': 0, 'kernel_input_copied_bytes': 0,
        'boundary_allocations': 'owner snapshot may allocate; ordinary adapters measured separately',
        'ordinary_input_copy': 'UTF8 adapter explicitly copies once per input block; never zero-copy',
        's1_acceptance': 'not complete'}
    if any(UTF8 in r['input_contracts'].values() for r in plan.records):
        metadata['immutable_utf8_boundary'] = 'retain ordinary immutable UTF8 string; byte offsets/length; no allocation or copy; synchronous callback entry allowed'
        metadata['boundary_allocations'] = 'immutable UTF8 retain does not allocate; NativeMemory owner snapshot may allocate'
        metadata['ordinary_input_copy'] = 'borrow_ro_utf8 borrows string storage without copying; borrow_ro_u8 retains the original NativeMemory contract'
    (out / 'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    return plan


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Internal dense source/IR generator; no public dense syntax')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--entry', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    from rulang.frontend import RuError
    from rulang.cli import report
    try:
        if args.manifest:
            generate_source(args.manifest, args.out or HERE.parent / 'mi_source' / 'generated', args.entry)
        else:
            generate(args.out or HERE / 'generated')
    except RuError as error:
        report(error, str(args.manifest or '<密实验>'))
        raise SystemExit(1)
    except (OSError, UnicodeError) as error:
        report(RuError(str(error), category='编译错误'), str(args.manifest or '<密实验>'))
        raise SystemExit(1)
