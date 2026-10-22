"""Host contract: opt-in and packaging only, no Python source frontend fallback."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import bootstrap

TRIPLE = 'x86_64-pc-windows-msvc'
MARKER = '/* RU_BOOTSTRAP_NATIVE_V1 '+TRIPLE+' */\n'


def link_trace(args):
    def quote(arg):
        return '"'+''.join(('\\'+c if c in ('"','\\','$') else c) for c in arg)+'"'
    return ('clang version 14.0.6\nTarget: '+TRIPLE+'\nThread model: posix\nInstalledDir: fixture\n '+
            ' '.join(quote(arg) for arg in args)+'\r\n').encode('utf-8')


class FakeToolchain:
    clang = ['fixture-clang']
    @staticmethod
    def run(command, input=None):
        return ''
    triple = TRIPLE
    data_layout = 'e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128'
    def compile(self, ir, runtime, stage):
        self.runtime = runtime
        output, standalone = stage/'native.exe', stage/'linked.ll'
        if getattr(self, 'link_flags', None):
            obj = stage/'program.o'
            obj.write_bytes(b'owned-object')
            self.run(self.clang+[str(obj), '-o', str(output), *self.link_flags])
        output.write_bytes(b'MZfake-toolchain')
        standalone.write_bytes(ir.encode('utf-8'))
        return output, standalone


class BootstrapNativeHostTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.compiler, self.source, self.output = [self.root/n for n in ('stage3.exe','main.ru','output.exe')]
        self.compiler.write_bytes(b'MZfake-stage3')
        self.source.write_text("密 取 外言 '如:密'.",encoding='utf-8')
        self.output.write_bytes(b'preserved')
        self.toolchain = FakeToolchain()
        self.metadata = MARKER+'/* typed thunks emitted by native compiler */\n'
        self.ir = 'target triple = "'+TRIPLE+'"\n'
        self.calls = []
        self.link_calls = []

    def frontend(self, args, **kwargs):
        if args[0] == 'fixture-clang':
            self.link_calls.append((list(args), dict(kwargs)))
            if args[-1] == '-###':
                flags = [x for x in args if x.startswith(('-fuse-ld=', '-B'))]
                path = Path(flags[1][2:])/flags[0].split('=',1)[1]
                return SimpleNamespace(returncode=0, stdout=b'', stderr=link_trace([str(path), '-out:fixture']))
            return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        self.calls.append(args)
        Path(args[2]).write_text(self.ir,encoding='utf-8')
        Path(args[3]).write_text(self.metadata,encoding='utf-8')
        Path(args[7]).write_text(json.dumps([str(self.source)]),encoding='utf-8')
        return SimpleNamespace(returncode=0,stdout='',stderr='')

    def invoke(self, allow=True, platform='win32', **options):
        with ExitStack() as stack:
            for name in ('rulang.frontend.parse','rulang.modules.load_module_graph',
                         'rulang.native_c.NativeCPlan.__init__','rulang.native_c.NativeCPlan.emit_c',
                         'rulang.compiler.Compiler.compile'):
                stack.enter_context(patch(name,side_effect=AssertionError('Python frontend fallback: '+name)))
            stack.enter_context(patch.object(bootstrap.sys,'platform',platform))
            stack.enter_context(patch.object(bootstrap.subprocess,'run',side_effect=self.frontend))
            return bootstrap.compile_native(self.compiler,self.source,self.output,self.toolchain,allow_native=allow,**options)

    def test_explicit_native_passes_versioned_flag_without_python_frontend(self):
        self.invoke()
        self.assertEqual(self.calls[0][-1],'--allow-native=bootstrap-native-v1')
        self.assertIn('ru_native_callback_dispatch',self.toolchain.runtime)
        self.assertEqual(self.output.read_bytes(),b'MZfake-toolchain')

    def test_default_path_does_not_enable_native(self):
        self.metadata = '/* ordinary metadata */\n'
        self.invoke(allow=False)
        self.assertEqual(len(self.calls[0]),8)
        self.assertNotIn('ru_native_callback_dispatch',self.toolchain.runtime)

    def test_default_rejects_unexpected_native_metadata(self):
        with self.assertRaises((ValueError,RuntimeError)):
            self.invoke(allow=False)
        self.assertEqual(self.output.read_bytes(),b'preserved')

    def test_native_requires_matching_marker_and_triple(self):
        for metadata, ir in [('',self.ir),(MARKER,'target triple = "x86_64-unknown-linux-gnu"\n')]:
            with self.subTest(metadata=metadata,ir=ir):
                self.metadata,self.ir = metadata,ir
                with self.assertRaises((ValueError,RuntimeError)):
                    self.invoke()
                self.assertEqual(self.output.read_bytes(),b'preserved')

    def test_native_requires_real_supported_host_and_target(self):
        with self.assertRaises((ValueError,RuntimeError)):
            self.invoke(platform='linux')
        self.assertEqual(self.calls,[])
        self.toolchain.triple = 'aarch64-pc-windows-msvc'
        with self.assertRaises((ValueError,RuntimeError)):
            self.invoke()
        self.assertEqual(self.calls,[])

    def test_proof_records_exact_inputs_and_outputs(self):
        proof = self.root/'proof.json'
        evidence = self.invoke(proof=proof)
        self.assertEqual(json.loads(proof.read_text()),evidence)
        self.assertEqual(evidence['compiler']['sha256'],bootstrap.digest(self.compiler.read_bytes()))
        self.assertEqual(evidence['dependencies'][0]['sha256'],bootstrap.digest(self.source.read_bytes()))
        self.assertEqual(evidence['runtime_sha256'],bootstrap.digest(self.toolchain.runtime.encode()))
        self.assertEqual(evidence['standalone_ir_sha256'],bootstrap.digest(self.ir.encode()))
        self.assertEqual(evidence['binary_sha256'],bootstrap.digest(self.output.read_bytes()))

    def test_explicit_linker_is_hashed_and_pinned_without_mutating_caller(self):
        linker = self.root/'link.exe'
        linker.write_bytes(b'MZowned-linker-fixture')
        proof = self.root/'proof.json'
        evidence = self.invoke(linker=linker, proof=proof)
        self.assertEqual(evidence['linker'], bootstrap.file_identity(linker))
        self.assertEqual(evidence['toolchain']['link_flags'], bootstrap.explicit_linker_flags(bootstrap.file_identity(linker)))
        self.assertIn(evidence['linker'], evidence['host_inputs'])
        self.assertFalse(hasattr(self.toolchain, 'link_flags'))
        self.assertEqual(len(self.link_calls), 2)
        dry, actual = self.link_calls
        self.assertEqual(dry[0], actual[0]+['-###'])
        self.assertEqual(dry[1], actual[1])
        self.assertEqual(evidence['linker_selection']['command'], actual[0])
        self.assertEqual(actual[0][1], '--target='+self.toolchain.triple)

    def test_explicit_link_uses_exact_versioned_ir_target(self):
        old = self.toolchain.triple
        self.toolchain.triple = old+'19.51.36260'
        self.ir = self.ir.replace(old, self.toolchain.triple)
        self.metadata = self.metadata.replace(old, self.toolchain.triple)
        linker = self.root/'link.exe';linker.write_bytes(b'original')
        original = self.frontend
        def targeted(args, **kwargs):
            result = original(args, **kwargs)
            if args[-1] == '-###':
                self.assertEqual(args[1], '--target='+self.toolchain.triple)
                result.stderr = result.stderr.replace(('Target: '+old+'\n').encode(), ('Target: '+self.toolchain.triple+'\n').encode())
            return result
        self.frontend = targeted
        evidence = self.invoke(linker=linker)
        self.assertEqual(evidence['linker_selection']['command'][1], '--target='+self.toolchain.triple)

    def test_wrong_dry_run_selection_never_executes_link_or_publishes(self):
        linker = self.root/'link.exe';linker.write_bytes(b'original')
        original = self.frontend
        def wrong(args, **kwargs):
            result = original(args, **kwargs)
            if args[-1] == '-###':
                result.stderr = link_trace(['other-link.exe',str(linker)])
            return result
        self.frontend = wrong
        with self.assertRaises(ValueError):
            self.invoke(linker=linker,proof=self.root/'proof.json')
        self.assertEqual(len(self.link_calls),1)
        self.assertEqual(self.link_calls[0][0][-1],'-###')
        self.assertFalse((self.root/'proof.json').exists())
        self.assertEqual(self.output.read_bytes(),b'preserved')

    def test_no_linker_preserves_default_behavior(self):
        evidence = self.invoke()
        self.assertIsNone(evidence['linker'])
        self.assertIsNone(evidence['toolchain']['link_flags'])

    def test_explicit_linker_rejects_wrong_platform_or_target_before_frontend(self):
        linker = self.root/'link.exe'
        linker.write_bytes(b'fixture')
        with self.assertRaises(ValueError):
            self.invoke(linker=linker, platform='linux', allow=False)
        self.toolchain.triple = 'aarch64-pc-windows-msvc'
        with self.assertRaises(ValueError):
            self.invoke(linker=linker, allow=False)
        self.assertEqual(self.calls, [])

    def test_explicit_linker_rejects_missing_directory_relative_and_injection(self):
        directory = self.root/'link.exe'
        directory.mkdir()
        for path in ('link.exe', self.root/'missing'/'link.exe', directory,
                     self.root/'other.exe', str(self.root/'bad\nlink.exe'), str(self.root/'bad"link.exe')):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.invoke(linker=path)
        self.assertEqual(self.calls, [])

    def test_explicit_linker_rejects_existing_linker_override(self):
        linker = self.root/'lld-link.exe'
        linker.write_bytes(b'fixture')
        self.toolchain.link_flags = ['-fuse-ld=other']
        with self.assertRaises(ValueError):
            self.invoke(linker=linker)
        self.assertEqual(self.calls, [])

    def test_explicit_linker_cli_passes_only_explicit_option(self):
        linker = self.root/'link.exe'
        with patch.object(bootstrap, 'LLVMToolchain', return_value=self.toolchain), \
                patch.object(bootstrap, 'compile_native') as compile_call:
            self.assertEqual(bootstrap.main(['build', str(self.source), '-o', str(self.output),
                                             '--linker', str(linker)]), 0)
        self.assertEqual(compile_call.call_args.kwargs['linker'], str(linker))

    def test_explicit_linker_rejects_symlink_marker(self):
        linker = self.root/'link.exe'
        linker.write_bytes(b'fixture')
        with patch.object(Path, 'is_symlink', return_value=True), self.assertRaises(ValueError):
            self.invoke(linker=linker)
        self.assertEqual(self.calls, [])

    def test_linker_is_protected_from_output_alias(self):
        linker = self.root/'link.exe'
        linker.write_bytes(b'fixture')
        with self.assertRaises(ValueError):
            self.invoke(linker=linker, proof=linker)
        self.assertEqual(linker.read_bytes(), b'fixture')
        self.assertEqual(self.calls, [])

    def test_changed_linker_rejects_publication(self):
        linker = self.root/'link.exe'
        linker.write_bytes(b'fixture')
        original = self.toolchain.compile
        def mutate(*args):
            linker.write_bytes(b'changed')
            return original(*args)
        with patch.object(self.toolchain, 'compile', side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, 'input changed'):
                self.invoke(linker=linker, proof=self.root/'proof.json')
        self.assertFalse((self.root/'proof.json').exists())
        self.assertEqual(self.output.read_bytes(), b'preserved')

    def test_linker_change_after_first_identity_cannot_replace_frozen_baseline(self):
        linker = self.root/'link.exe'
        linker.write_bytes(b'original')
        original = bootstrap.file_identity
        observed = False
        def mutate_after_identity(path):
            nonlocal observed
            result = original(path)
            if Path(path).resolve() == linker.resolve() and not observed:
                observed = True
                linker.write_bytes(b'changed-between-samples')
            return result
        with patch.object(bootstrap, 'file_identity', side_effect=mutate_after_identity):
            with self.assertRaisesRegex(RuntimeError, 'input changed'):
                self.invoke(linker=linker, proof=self.root/'proof.json')
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root/'proof.json').exists())
        self.assertEqual(self.output.read_bytes(), b'preserved')

    def test_standalone_ir_proof_hashes_exact_toolchain_bytes(self):
        emitted = self.ir.replace('\n','\r\n').encode('utf-8')
        saved = self.root/'saved.ll'
        original = self.toolchain.compile
        def crlf_toolchain(ir,runtime,stage):
            executable, standalone = original(ir,runtime,stage)
            standalone.write_bytes(emitted)
            return executable, standalone
        with patch.object(self.toolchain,'compile',side_effect=crlf_toolchain):
            evidence = self.invoke(emit_llvm=saved)
        self.assertEqual(saved.read_bytes(),emitted)
        self.assertEqual(evidence['standalone_ir_sha256'],bootstrap.digest(emitted))
        self.assertEqual(evidence['source_ir_sha256'],bootstrap.digest(self.ir.encode('utf-8')))
        self.assertNotEqual(evidence['standalone_ir_sha256'],evidence['source_ir_sha256'])

    def test_destinations_cannot_overwrite_inputs(self):
        for target in (self.source,self.compiler,bootstrap.ROOT/'rulang/native_runtime.h'):
            for option in ('proof','emit_llvm'):
                with self.subTest(target=target,option=option):
                    before = target.read_bytes()
                    with self.assertRaises((ValueError,RuntimeError)):
                        self.invoke(**{option:target})
                    self.assertEqual(target.read_bytes(),before)
        self.assertEqual(self.calls,[])

    def test_toolchain_failure_preserves_existing_outputs(self):
        proof, ir = self.root/'proof.json', self.root/'saved.ll'
        proof.write_bytes(b'old-proof')
        ir.write_bytes(b'old-ir')
        with patch.object(self.toolchain,'compile',side_effect=RuntimeError('link failed')):
            with self.assertRaisesRegex(RuntimeError,'link failed'):
                self.invoke(proof=proof,emit_llvm=ir,keep_frontend=True)
        self.assertEqual(proof.read_bytes(),b'old-proof')
        self.assertEqual(ir.read_bytes(),b'old-ir')
        self.assertEqual(self.output.read_bytes(),b'preserved')
        self.assertFalse(self.output.with_name(self.output.name+'.metadata.c').exists())

    def test_mutating_source_during_toolchain_rejects_publication(self):
        original = self.toolchain.compile
        def mutate(*args):
            self.source.write_text('changed',encoding='utf-8')
            return original(*args)
        with patch.object(self.toolchain,'compile',side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError,'input changed'):
                self.invoke(proof=self.root/'proof.json')
        self.assertEqual(self.output.read_bytes(),b'preserved')
        self.assertFalse((self.root/'proof.json').exists())

    def test_native_cannot_combine_with_interpreter_host(self):
        with self.assertRaises((ValueError,RuntimeError)):
            self.invoke(interpreter_host=True)
        self.assertEqual(self.calls,[])

    def test_malformed_manifest_rejects_before_toolchain(self):
        original = self.frontend
        for invalid in ({'path':str(self.source)},[None],['']):
            def malformed(args,**kwargs):
                result = original(args,**kwargs)
                Path(args[7]).write_text(json.dumps(invalid),encoding='utf-8')
                return result
            with self.subTest(invalid=invalid), patch.object(self,'frontend',side_effect=malformed):
                with self.assertRaisesRegex(ValueError,'manifest'):
                    self.invoke()
            self.assertEqual(self.output.read_bytes(),b'preserved')

    def test_versioned_msvc_target_matches_marker_and_ir_exactly(self):
        triple = TRIPLE+'19.20.0'
        self.toolchain.triple = triple
        self.metadata = '/* RU_BOOTSTRAP_NATIVE_V1 '+triple+' */\n'
        self.ir = 'target triple = "'+triple+'"\n'
        self.invoke()
        self.assertEqual(self.output.read_bytes(),b'MZfake-toolchain')

    def test_msvc_suffix_and_cross_version_marker_fail_closed(self):
        for triple in (TRIPLE+'evil',TRIPLE+'19..20',TRIPLE+'-gnu'):
            with self.subTest(triple=triple):
                self.toolchain.triple = triple
                with self.assertRaises((ValueError,RuntimeError)):
                    self.invoke()
        self.assertEqual(self.calls,[])
        self.toolchain.triple = TRIPLE+'19.20'
        self.ir = 'target triple = "'+self.toolchain.triple+'"\n'
        with self.assertRaises((ValueError,RuntimeError)):
            self.invoke() # unversioned marker must not match versioned toolchain
        self.assertEqual(self.output.read_bytes(),b'preserved')

    def test_import_mutation_during_frontend_cannot_forge_frozen_proof(self):
        child = self.root/'child.ru'
        child.write_text("显 'before'.",encoding='utf-8')
        original = self.frontend
        def mutate(args,**kwargs):
            result = original(args,**kwargs)
            Path(args[7]).write_text(json.dumps([str(self.source),str(child)]),encoding='utf-8')
            child.write_text("显 'after'.",encoding='utf-8')
            return result
        with patch.object(self,'frontend',side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError,'input changed'):
                self.invoke(proof=self.root/'proof.json')
        self.assertEqual(self.output.read_bytes(),b'preserved')
        self.assertFalse((self.root/'proof.json').exists())

    def test_inventory_symlink_cannot_escape_explicit_root(self):
        with tempfile.TemporaryDirectory() as external:
            outside = Path(external)/'outside.ru'
            outside.write_text('external',encoding='utf-8')
            try:
                (self.root/'escape.ru').symlink_to(outside)
            except (OSError,NotImplementedError) as error:
                self.skipTest('host cannot create symlink: '+str(error))
            with self.assertRaisesRegex(ValueError,'symlink'):
                self.invoke()
            self.assertEqual(self.calls,[])

    def test_manifest_path_traversal_is_rejected(self):
        original = self.frontend
        def traversal(args,**kwargs):
            result = original(args,**kwargs)
            Path(args[7]).write_text(json.dumps([str(self.root/'sub/../main.ru')]),encoding='utf-8')
            return result
        with patch.object(self,'frontend',side_effect=traversal):
            with self.assertRaises((ValueError,RuntimeError)):
                self.invoke()
        self.assertEqual(self.output.read_bytes(),b'preserved')

    def test_sparse_oversized_source_rejected_before_frontend(self):
        with self.source.open('wb') as stream:
            stream.truncate(64*1024*1024+1)
        with self.assertRaisesRegex(ValueError,'64 MiB'):
            self.invoke()
        self.assertEqual(self.calls,[])

    def test_inventory_aggregate_limit_includes_entry_source(self):
        for path in (self.source,self.root/'child.ru'):
            with path.open('wb') as stream:
                stream.truncate(33*1024*1024)
        with self.assertRaisesRegex(ValueError,'64 MiB|byte limit'):
            self.invoke()
        self.assertEqual(self.calls,[])

    def test_proof_is_published_last(self):
        proof = self.root/'proof.json'
        original = bootstrap.os.replace
        destinations = []
        def capture(source,destination):
            destinations.append(Path(destination))
            return original(source,destination)
        with patch.object(bootstrap.os,'replace',side_effect=capture):
            self.invoke(proof=proof,emit_llvm=self.root/'emit.ll',keep_frontend=True)
        self.assertEqual(destinations[-1],proof)
        self.assertIn(self.output,destinations[:-1])

    def test_publication_error_does_not_publish_new_proof(self):
        proof = self.root/'proof.json'
        proof.write_bytes(b'old-proof')
        original = bootstrap.os.replace
        def fail_executable(source,destination):
            if Path(destination) == self.output:
                raise OSError('publication failed')
            return original(source,destination)
        with patch.object(bootstrap.os,'replace',side_effect=fail_executable):
            with self.assertRaisesRegex(OSError,'publication failed'):
                self.invoke(proof=proof,keep_frontend=True)
        self.assertEqual(proof.read_bytes(),b'old-proof')
        self.assertEqual(self.output.read_bytes(),b'preserved')



class PinnedLinkerSelectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.linker = self.root/'sp ace 汉😀$'/'link.exe'
        self.linker.parent.mkdir()
        self.linker.write_bytes(b'original-linker')
        self.record = bootstrap.file_identity(self.linker)
        self.command = ['clang', str(self.root/'p.obj'), '-o', str(self.root/'p.exe'),
                        *bootstrap.explicit_linker_flags(self.record)]

    def probe(self, raw=None, mutate=None):
        raw = raw if raw is not None else link_trace([str(self.linker), '-out:p.exe'])
        def run(*args, **kwargs):
            self.assertEqual(args[0], self.command+['-###'])
            self.assertEqual(kwargs['env'], {'OWNED': 'yes'})
            self.assertEqual(kwargs['cwd'], str(self.root))
            if mutate:
                mutate()
            return SimpleNamespace(returncode=0, stderr=raw, stdout=b'')
        with patch.object(bootstrap.subprocess, 'run', side_effect=run):
            return bootstrap.inspect_linker_command(self.command, self.record, {'OWNED':'yes'}, str(self.root))

    def test_trace_strict_clang14_escape_roundtrip_and_raw_hash(self):
        raw = link_trace([str(self.linker), 'quote"back\\slash$dollar', '-out:p.exe'])
        result = self.probe(raw)
        self.assertEqual(result['selected_command'][0], str(self.linker))
        self.assertEqual(result['dry_run_stderr_sha256'], bootstrap.digest(raw))
        self.assertEqual(result['dry_run_stderr_utf8'].encode(), raw)
        self.assertEqual(result['command'], self.command)

    def test_zero_two_malformed_and_error_diagnostics_rejected(self):
        good = link_trace([str(self.linker), '-out:p.exe'])
        for raw in (b'', good+good.splitlines()[-1]+b'\n', good+b'clang: error: bad\n',
                    good.replace(b'"-out:p.exe"', b'"bad\\n"'),
                    good.replace(b'"-out:p.exe"', b'"truncated'),
                    good.replace(b'"-out:p.exe"', b'"@hidden.rsp"'),
                    good.replace(b'"-out:p.exe"', b'"ok"tail'),
                    good.replace(b'"-out:p.exe"', b'"control\x00"'),
                    good.replace(b'clang version 14.', b'clang version 15.')):
            with self.subTest(raw=raw[-80:]), self.assertRaises((ValueError, UnicodeError)):
                self.probe(raw)

    def test_same_basename_wrong_parent_or_target_prefix_no_fallback(self):
        other = self.root/'wrong'/'link.exe'
        other.parent.mkdir();other.write_bytes(self.linker.read_bytes())
        for path in (str(other), TRIPLE+'-'+str(self.linker), 'link.exe'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.probe(link_trace([path, str(self.linker)]))

    def test_replaced_or_missing_linker_during_probe_refused(self):
        for mutation in (lambda:self.linker.write_bytes(b'changed'), lambda:self.linker.unlink()):
            self.linker.write_bytes(b'original-linker')
            with self.assertRaises((ValueError, RuntimeError, OSError)):
                self.probe(mutate=mutation)

    def test_duplicate_or_conflicting_selector_rejected_before_probe(self):
        for flag in ('-B/other', '-fuse-ld=lld', '--ld-path=/other', '-###', '@other.rsp'):
            self.command.append(flag)
            with patch.object(bootstrap.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    bootstrap.inspect_linker_command(self.command,self.record,{},str(self.root))
                run.assert_not_called()
            self.command.pop()

    def test_target_rejection_retains_exact_raw_bytes_and_both_values(self):
        lines=link_trace([str(self.linker)]).splitlines(keepends=True)
        raw=b'\n \r\n'+lines[-1]+b''.join(lines[:-1])
        expected='x86_64-pc-windows-msvc19.51.36260'
        with patch.object(bootstrap.subprocess,'run',return_value=type('R',(),{'returncode':0,'stdout':b'','stderr':raw})()):
            with self.assertRaises(ValueError) as raised:
                bootstrap.inspect_linker_command(self.command,self.record,{},str(self.root),expected)
        diagnostic=json.loads(str(raised.exception).split(': ',1)[1])
        self.assertEqual(diagnostic['expected_target'],expected)
        self.assertEqual(diagnostic['observed_target'],'x86_64-pc-windows-msvc')
        self.assertEqual(diagnostic['dry_run_stderr_utf8'].encode(),raw)
        self.assertEqual(diagnostic['dry_run_stderr_sha256'],bootstrap.digest(raw))
        self.assertEqual(diagnostic['command'],self.command)
        self.assertEqual(diagnostic['status'],'rejected-diagnostic-only')


if __name__ == '__main__':
    unittest.main()
