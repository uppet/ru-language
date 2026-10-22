# Bootstrap native ABI v1 (isolated candidate)

This is not a release acceptance report. The required LLVM 14 three-generation
fixed point and real Windows execution remain separate gates.

## Source-processing boundary

`bootstrap/compiler.ru` owns tokenization, parsing, module loading, semantic
validation, LLVM emission, and finite native ABI discovery. Its ordinary Ru
helper `bootstrap/native_emit.ru` emits exactly typed C call/callback thunks.
There is no Python `NativeCPlan`, parser, module-loader or code-generator fallback
in the later-stage driver. The helper is an ordinary imported dependency and is
included in bootstrap input hashes and native frontend dependency lists.

The host may assemble the existing fixed native runtime, compile LLVM/C, link,
record hashes, and publish an output only after all checks. That runtime remains
responsible for DLL loading policy, Win64 value conversion, structures, pointer
owners, callback slots, GC roots, reentry, errors and callback failure hooks.

Native invocation appends `--allow-native=bootstrap-native-v1` after the existing
seven arguments (`SOURCE PROGRAM.ll METADATA.c TRIPLE DATA_LAYOUT STDLIB
SOURCES.json`). Six/seven argument nonnative invocations remain valid. The
frontend accepts only `x86_64-pc-windows-msvc` with an optional numeric dotted
version. Metadata starts with `/* RU_BOOTSTRAP_NATIVE_V1 <exact triple> */`.
The driver checks this marker against the exact IR/toolchain triple. The flag
is explicit; environment variables cannot enable application native capability.

## Deliberately conservative source subset

* Primitive types, signature aliases and DLL/function bindings must be
  statically identifiable. ABI return/parameter types and convention must be
  known; parameter arrays are literal rather than mutable aliases.
* Ordinary Ru wrappers forwarding their parameters directly to `__密` are
  recognized by AST shape, not by their filename or user-visible function name.
* Module exports and immutable aliases are followed. Function parameters/local
  bindings shadow module aliases. Rebinding native static declarations is
  rejected. Branches are inspected even when their conditions are not known.
* Signature operation references/capability escape and unknown signature
  components fail closed. Arbitrary higher-order signature construction is not
  supported. Known ordinary objects with similarly named methods are not native
  operations merely because of their member names.
* Structures are recognized as structure types and may **never** cross the ABI
  by value. Static literal declarations are checked early; dynamic field arrays
  are validated and laid out by the existing runtime. This is necessary for the
  editor's 64-field event buffer. It does not weaken static function signatures.
* DLL paths can be dynamic: their loading policy is runtime-owned and they do not
  change the ABI. Signature shape remains statically checked independently.
* The existing bounds remain: 64 parameters, 1024 signatures and 1024 callback
  slots per supported callback shape. Primitive IDs are unchanged (0..13).

Absolute imports use their absolute path rather than being incorrectly prefixed
with the importing module directory; relative imports retain existing behavior.

## Verification categories

The local development frontend can be built with the stage0 Python C backend and
GCC. Running that ELF verifies the **Ru** parser/planner/emitter without asking
Python to process application source. It is useful development evidence, **not**
a bootstrap LLVM stage3, fixed-point, Windows execution or release proof.

`tests/test_bootstrap_native_frontend.py` explicitly selects such a frontend via
`RU_BOOTSTRAP_FRONTEND_TEST_COMPILER`. Native runtime acceptance uses the separate
`RU_BOOTSTRAP_NATIVE_COMPILER` stage3 selection and required-Windows gate. Missing
LLVM or Windows must be disclosed, not counted as a passed execution test.

Before release retain all pre-existing bootstrap tests, exact IR/metadata fixed
point, source/dependency hash proof, forbidden-Python-frontend tests, and bare
artifact execution. Additionally compare the complete editor module graph's ABI
inventory and run direct Win64 scalar, structures, callback error/reentry/owner
and GUI lifecycle tests with the real stage3-built editor.

## Isolated feature CI (first round)

`.github/workflows/bootstrap-native.yml` runs only for the explicit
`feature/bootstrap-native-20261022` push filter or a manual dispatch. It does not
change existing CI coverage. Linux and Windows each build fresh generations,
require all 105 existing cases (35 per stage), zero skips, exact case identities,
all fixed-point gates, complete source inventory and nine artifact identities.
Both then execute native-frontend positive/negative contracts with that stage3.
Windows additionally executes all required native DLL/callback tests and compiles
the exact public editor baseline `d964ea9f7e27065aa5bbcced8d6c7526a6224dd1`
through stage3 and LLVM into a **console-link validation artifact only**. The
editor graph must match all 24 modules, 62 ABI shapes and two callback shapes.
Application Python frontend entrypoints are forbidden during this compilation.

The first round does not validate GUI resources, wWinMain, DLL distribution,
packaging, performance, current editor main, or the later wij dense optimization.
In particular `mi_manifest` and `borrow_utf8` lowering are not implemented by
this FFI feature. They require a separately reviewed native Ru/LLVM path; Python
lowering is not an acceptable fallback.
