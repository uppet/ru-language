# Private dense helper (integration candidate)

`dense_emit.ru` is a narrow bootstrap compiler helper, not a public language API.
The candidate now connects it through dense_plan.ru, dense_bridge.ru and explicit
compiler options; both dense and native capabilities remain default-off.
See DENSE_PROTOCOL.md for the private data contract and identity restrictions.

## Interface

- `密降型 函 约 文件`: existing bootstrap function AST, normalized contract,
  diagnostic source path -> private typed IR.
- `密LLVM IR 符号`: **only IR returned by 密降型**, compiler-generated safe
  ASCII identifier -> LLVM text defining `@<symbol>_llvm`.

Contract `params` is ordered `[[name,type], ...]`, **not a map**; `locals` is an
optional ordered name/type pair list. `result` is `u8` or `u32`; effects must be
exactly `['borrow-read','no-escape','no-callback','no-gc','may-fail']`.
Optional `ranges` contains maps with exactly `view`, `begin`, `end` keys; their
parameters must identify the one view and two u32 parameters. Only
`borrow_ro_utf8`, `u8`, `u32` are accepted at this boundary. Internal IR uses
`borrow_ro_u8` for the readonly byte view; this does **not** accept NativeMemory.

The caller must validate manifest structure, bind unique loaded top-level
function identities using canonical module identity and function name, reject
duplicates, preserve parameter ordering, and generate symbols from internal
IDs. No kernel names are special-cased. This helper does not read manifest JSON,
parse application source, choose functions, or resolve module paths.

AST fields are those in bootstrap/compiler.ru (69d5097): `种/行/列`; number
`值` retains exact token text, binary `左/右/算符`, index `左/位`, member
`左/名/参`, function `参/体/作`, bind/return/unary `值`, if `条/是/否`, loop
`次/体`. Lowering failures use `卒` with file:line:column diagnostics. Partial
IR is not returned after failure. The integration caller must finish all plans
before publishing artifacts.

Supported operations mirror the checked existing Mi subset needed by the five
wij kernels: contextual exact decimal u8/u32 constants, byte load/length,
checked add/sub, unsigned comparisons, numeric truth (including zero is true),
short circuit and/or/not, integer locals, if, bounded repeat, break and return.
Definite initialization and invariant local types are checked. No implicit
narrowing, calls, allocation, GC, callbacks, view writes/escape, or unbounded
loops. Every kernel exit writes four u32 slots: status/value/line/column;
success writes zero source coordinates. Status 1 is bounds, 2 is arithmetic
under/overflow. All scalar ABI arguments are i32; u8 is truncated only after
the future wrapper has validated its range. No LLVM noalias/nocapture/readonly
attributes are asserted.

## Integration and remaining gates

`dense_plan.ru` validates data-only packets and binds exact inventory/module/
top-level function identities before any emission. `dense_bridge.ru` emits only
checked boundary wrappers; compiler.ru selects the resulting LLVM bodies and
preserves ordinary descriptors. The host owns frozen JSON-data transport and
fixed runtime assembly; no application source parsing or lowering occurs there.

Still required before product/default enable: independent review and real
LLVM14 stage1/2/3 execution/fixed-point; native callback failure/retry and owner
lifecycle acceptance; all original FFI gates; editor correctness and controlled
performance measurements. Development evidence is not those release gates.

The permitted C metadata/runtime wrappers must never contain kernel bodies.
The unrelated DLL ABI-thunk helper native_emit.ru is unchanged.

## Development verification

`python -m unittest tests.test_bootstrap_dense_helper -v` builds a C-seeded
native test driver. The driver dynamically parses kernel source through pureRu
bootstrap/compiler.ru, then runs pureRu lowering/emission. Python's existing
SourceLowerer/LLVM emitter are independent test-only oracles; they are not a
bootstrap implementation dependency. Five fixture algorithms are copied
byte-for-byte from wij; their manifest is a provenance fixture, not a working
build manifest (its original relative module path is retained).

These tests compare complete LLVM text (excluding empty lines), negative
contracts/effects/types, definite assignment, source spans, symbol safety, and
generic renamed/changed algorithms. They are not LLVM14/stage3 execution.

`RU_BOOTSTRAP_DENSE_TEST_COMPILER=/path/to/compiler python -m unittest
 tests.test_bootstrap_dense_frontend -v` exercises the protocol, binding,
selection, metadata order and fail-closed behavior directly, including bypass
of host validation. The chosen compiler's provenance must be reported; a
C-seeded executable is development evidence only.
