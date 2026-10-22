# Private bootstrap dense-v1 protocol (integration candidate)

## Verified starting points

- Current built-in module catalog (`rulang/modules.py`) and six bundled `.ru`
  modules provide no JSON parser callable from Ru. The JSON reader in
  `rulang/mi_source.py` is Python-only.
- `bootstrap/compiler.ru::规范路` only normalizes separators/dot components;
  it is **not filesystem realpath or Windows file identity resolution**.
- `tools/bootstrap.py::compile_native` already has pre-read source inventory,
  source/dependency hash checks, staged outputs and metadata protocol checking
  for native builds. Extend these protections to dense-only builds too.
- The approved helper accepts ordered parameter/local pairs and only UTF8 view
  contracts. Keep the original source algorithms and LLVM-only dense bodies.

## Data protocol (no application source parsed in Python)

Host option: `--experimental-mi-manifest PATH` on `tools/bootstrap.py build`.

Native compiler invocation retains the seven current positions including
SOURCES.json, followed by the existing optional native flag and then exactly:

    --dense-utf8=bootstrap-dense-v1 PACKET_PATH PLAN_PATH

Dense-only and dense+native are distinct; UTF8 borrowing alone does not grant
or require DLL capability. Exact flag/order/count checks reject unknown or
repeated options. Preserve existing six/seven/eight-argument compatibility.

The host parses original JSON as **data only**, rejects duplicate object keys,
nonfinite numbers, unknown fields/version, malformed objects and oversized
inputs. It preserves JSON parameter insertion order. It never discovers
imports, reads ASTs, invokes MiSourcePlan/SourceLowerer, emits kernels or decides
whether a function is eligible. All `.ru` reads on the host are byte hashing.

Serialize a strict string/array-only packet (Ru quoted strings, arrays, commas):

    ["bootstrap-dense-v1", CANONICAL_ORIGINAL_MANIFEST_PATH,
     [CANONICAL_INVENTORY_SOURCE_PATH, ...],
     [[ORIGINAL_MODULE_TEXT, CANONICAL_MODULE_PATH, FUNCTION_NAME,
       [[PARAM_NAME, TYPE], ...], RESULT_TYPE,
       [EFFECT, ...], [[LOCAL_NAME, TYPE], ...],
       [[VIEW_PARAM, BEGIN_PARAM, END_PARAM], ...]], ...]]

No source strings, source AST, kernel IR, symbol names or C code are transmitted.
Use bounded input (proposal: 4 MiB packet, <=256 functions, <=10000 source paths,
<=64 params/locals/ranges per record, <=16 decode nesting). Reject control/NUL
characters and surrogate code points in packet strings; this narrow v1 does
not support such filenames. Existing Unicode identifiers remain supported.

PureRu decoder reuses `词法` but consumes **only string tokens, '[' ',' ']' and
EOF**, recursively. It does not invoke the expression parser or evaluate Ru.
Then validate exact packet shape/counts/string fields and pair uniqueness.
This is a private transport decoder, not general JSON or public language syntax.

## Canonical identity policy

Use the host's existing filesystem canonicalization only for file-I/O inventory
and transport. Expand inventory protection to `allow_native OR dense`.
Canonical packet paths are absolute `Path.resolve().as_posix()` values. Reject
symlink/reparse aliases and case/spelling aliases in dense-v1 instead of
silently equating them. Host verifies regular files, containment and physical
aliases; frontend exact path membership is mandatory. This intentionally
narrows accepted paths, not language/application semantics.

Before `载言` opens any application module under dense mode, its lexically
normalized path must exactly equal an inventory canonical path. Thus an import
alias cannot create a second module identity or escape pre-read inventory.
PureRu normalizes manifest-relative module text (or a supported absolute path),
requires equality with the transmitted canonical module path and membership
in the same inventory, then requires that module to be already loaded. It must
not auto-import a manifest-only module. If filesystem and lexical paths differ,
fail closed and explain the path restriction; do not claim 规范路 did realpath.

Trust boundary: PureRu verifies lexically canonical strings, exact declared
inventory membership and loaded-module/internal-function identity. It cannot
stat/realpath a fabricated standalone inventory or certify physical file
identity. Physical symlink/hardlink/reparse/case alias exclusion and byte
freezing belong to the host inventory builder; standalone packet acceptance
is **not** a physical-identity attestation. The approved build proof requires
that host-generated frozen inventory. Detectable residual absolute `..`
components are rejected independently by PureRu before file lookup.

Final selection is entirely in PureRu: matching canonical loaded module ID plus
unique top-level function node (`种=function`, parent empty, exact name). Bind
its internal function ID, reject repeated selection, unknown/nested/ambiguous
functions, mismatched ordered parameters/annotations and unsupported types or
effects. Use the helper for exact type/effect/body validation. Validate range
records and preserve them for wrapper generation. Construct the **entire** plan
before any LLVM/metadata/proof output publication; failure selects no fallback.

## Frontend ownership and emission hooks

1. `bootstrap/dense_plan.ru` (new): packet decoding/schema validation, contract
   normalization and manifest/loaded-module binding; return records keyed by
   internal function ID. It may accept the existing token array and loaded
   module/function lists to avoid importing compiler.ru and creating a cycle.
   Small path normalization call sites can remain in compiler.ru.
2. `bootstrap/dense_emit.ru` (existing reviewed helper): typed IR and LLVM bodies
   only. Symbols are `boot_dense_<internal-function-id>`, never manifest text.
3. `bootstrap/dense_bridge.ru` (new): pureRu generation of descriptor boundary
   C wrappers from validated plan records. No algorithm body generation.
4. `bootstrap/compiler.ru`: exact option parser, packet read before module load,
   inventory gate in 载言, dense plan after ordinary 语义, before emission;
   发全 omits selected ordinary bodies and appends helper LLVM;
   描述符 substitutes their bridges while preserving normal Ru descriptors,
   argument names and dynamic invocation behavior.
5. `rulang/bootstrap_dense_runtime.h` (new fixed code): private view struct and
   scalar/immutable-string validators only. Host appends this fixed header
   before metadata when dense enabled. No NativeMemory, generated algorithms,
   or dependency on Python Mi planning/lowering modules.
6. `tools/bootstrap_dense_protocol.py` (new): strict JSON-data transport,
   inventory path handling and metadata/proof protocol validation only.
   `tools/bootstrap.py` owns freezing, invocation, fixed runtime assembly,
   linking and atomic publication. `native_emit.ru` stays untouched.

## Descriptor bridge / borrow sequence

C metadata wrapper retains the ordinary signature:

    static Val boot_fn_N_bridge(Env *env, Val self, int call_line, Val *args)

It calls `extern void boot_dense_N_llvm(uint32_t *out, ...)`, with the reviewed
pointer/length/u32 scalar ABI, not a C aggregate ABI. Each selected wrapper:

1. Checks **all scalar arguments first**: RU_NUM, finite, integral, nonnegative,
   <=255 or <=UINT32_MAX before casting (no implicit coercion/truncation).
2. Requires RU_STR and byte length <=UINT32_MAX; obtains readonly data/length.
3. Checks every `begin <= end <= byte_length` contract at call_line.
4. Only now retains `Val owner=v_copy(args[view_index])`.
5. Calls the checked LLVM kernel with local `uint32_t out[4]`.
6. Releases `v_drop(owner)` immediately after return, before boxing or error.
7. For nonzero status, sets diagnostic source to the selected source file and
   translates out[2]/out[3] and status using existing ru_fail semantics.
   Otherwise returns v_num((double)out[1]).

Between retain and release: no allocation, GC, user/runtime callback, external
call or exception except the proven no-call/no-GC checked LLVM kernel itself.
No pointer escapes, mutable storage, NativeMemory permission or UI-yield borrow.
Calling synchronously inside a native callback is safe under this restricted
contract; NativeMemory's separate callback/reentry restrictions are unchanged.
All generated identifiers/types/C strings come from safe compiler IDs, finite
allowlists and the existing C string escaping helper.

## Metadata, proof and atomic host validation

Keep current native marker first for combined mode. Add one exact dense marker:

    /* RU_BOOTSTRAP_DENSE_UTF8_V1 */

Reject dense metadata without explicit dense option, missing marker with option,
unknown/repeated markers, target mismatch and unexpected proof counts.
Frontend PLAN_PATH emits JSON **output only** using existing JSON句:
protocol, selected internal IDs, canonical module paths, function names, safe
symbols and ordered parameter/result/effect/range contracts. Host cross-checks
count and the transport data, never recomputes eligibility or source lowering.

Freeze original manifest, transport packet, inventory, compiler, helper/compiler
inputs and fixed runtime headers before invocation. Protect them all from output
overlap. Reverify hashes after frontend and before publication; retain the
existing honest pre/post observation scope (not per-read snapshots; ABA not
excluded). Add original-manifest/packet/plan/hash identities to build proof.
Write all frontend files in the existing staging directory. Any plan, decoder,
compiler, link or verification failure preserves prior published artifacts.

## Required gates before product/default changes

- Direct-compiler hostile packets bypassing host checks: malformed/trailing
  data, strings pretending to be code, unsupported field counts, duplicate
  entries/pairs, version/types/effects/ranges, path aliases/unloaded modules,
  nested functions, order mismatch, mixed/second views, bad symbols.
- Generic changed/renamed kernel source, selected unsupported source must fail;
  unselected source keeps ordinary behavior; zero flags yields ordinary build.
- Wrapper tests: empty/Unicode/byte offsets; NaN/inf/fraction/negative/oversize
  scalar and u8 errors; reversed/outside ranges; owner lifetime and GC zero;
  bounds/overflow failure span; callback nested entry/failure/retry.
- No-host-source-processing guards include Python parse/module loader/compiler,
  MiSourcePlan/SourceLowerer and both Mi emitters. Host JSON parsing alone allowed.
- Actual LLVM14 stage1/2/3 helper execution, fixed point and metadata equality;
  all original FFI gates retained. Then full editor checks and measured A/B.

## Exact v1 limits and normalization rules

These limits are protocol validation, not hints. Check before allocation/recursion
where possible; exceeding any bound is a compile error, never truncation.

| Item | Limit |
|---|---:|
| Original JSON bytes (host) | 1,048,576 |
| Packet UTF8 bytes (host) | 4,194,304 |
| Packet Unicode scalars before lexing (frontend) | 1,048,576 |
| Decoded arrays+strings (frontend) | 200,000 |
| Recursive array nesting | 16 |
| Inventory paths | 10,000 |
| Frozen source bytes combined | 67,108,864 |
| Selected functions | 1..256 |
| Parameters/function | 0..64 |
| Locals hints/function | 0..64 |
| Ranges/function | 0..64 |
| Effects/function | exactly 5 |
| Individual string Unicode scalars | 4,096 |
| Function/parameter/local names | 1..256 |
| Path strings | 1..4,096 |
| Version/type/effect labels | exact enumerated values |

The frontend `件.读` already rejects malformed UTF8 (`io_runtime.h:261`). Host
uses strict UTF8. Packet writer uses UTF8 without BOM and double-quoted strings,
escaping only `"` and `\\` (all C0 controls/DEL disallowed in string values).
Frontend may use the existing lexer string grammar, but validates decoded
values against the same limits/control prohibition and accepts no non-data
tokens. No `\\u` escapes are needed; write Unicode scalars directly. Identifiers
are compared exactly as Ru parser names, no Unicode normalization/casefold.
Paths convert directory separators and dot-components using 规范路; **not**
basename-only matching. Dense v1 accepts POSIX absolute or drive-absolute
Windows paths only; reject UNC/device paths, drive-relative paths and alternate
data streams. Windows short-path, case and reparse aliases in imports or module
records must fail exact canonical-inventory comparison. CLI root/source paths
may first be resolved by the host; both host and frontend then use that same
canonical spelling. Manifest module text is resolved relative to canonical
manifest parent and must itself produce the exact canonical selected path.

Suggested stable diagnostics:

- `dense-v1: 路径不是冻结规范路径（别名／大小写／短路径不支持）：<path>`
- `dense-v1: 清单模块未加载：<path>`
- `dense-v1: 清单函数须在模块顶层唯一匹配：<name>`
- `dense-v1: 重复函数绑定／参数／局部／范围／清单字段`
- `dense-v1: 数据包字段／版本／数量／深度／长度无效`

Duplicate JSON keys at every object level are rejected by host before any
conversion. Unknown original JSON root/function/range fields are rejected;
transport row lengths are exact, so unknown positional fields fail in PureRu.
Inventory paths must be unique; repeat selection of a function ID is invalid.
Parameter/local names must each be unique; locals cannot collide with params.
Identical range triples are rejected as redundant duplicate contracts.
Effects must match the five existing values in **exact existing order**;
missing, extra, repeated or reordered effects reject. Parameter order must
exactly match source order; host retains original JSON object pair order;
no sorting of params. Local hints retain input order too. Duplicate module
paths across records are allowed when they select distinct top-level functions.

Both options default off. Existing native-only marker and protocol remain
unchanged, at the start of metadata. Dense marker appears exactly once only
with dense enabled (after native marker in combined mode). Every other mode
must reject that marker. Dense-only works on the existing Linux/Windows x64
LLVM platform set; native still requires explicit Windows x64 capability.

## Exact frontend plan JSON

The plan is a three-element array:
`["bootstrap-dense-v1", canonicalManifestPath, selectedRecords]`.
Each selected record has nine elements:
`[canonicalModulePath, functionName, functionIdDecimalString, safeSymbol,
orderedParamPairs, resultType, orderedEffects, orderedLocalPairs, rangeTriples]`.
Order matches packet record order. Symbols are `boot_dense_` plus the nonnegative
internal function ID in decimal. Target identity is validated from LLVM's target
triple and existing metadata markers, not a redundant plan field.

### Dense v1 target allowlist (shared fixture)

Only `x86_64-pc-linux-gnu`, `x86_64-unknown-linux-gnu`, and the existing strict
`x86_64-pc-windows-msvc` optionally followed by nonempty dot-separated decimal
version components are accepted for dense mode. Musl, other Linux vendors,
x32, extra target fields and substring-only fake Linux OS names are deliberately
not part of v1. Ordinary builds without dense keep their existing behavior.
`tests/fixtures/dense/targets.json` is the shared host/frontend test matrix.
