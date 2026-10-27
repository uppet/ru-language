"""IR promotion preconditions and allocation-free shared runtime fast paths."""
import re
import subprocess
import tempfile
import unittest

from rulang.frontend import parse
from rulang.llvm_compiler import LLVMCompiler
from test_c_bindings import CC, build, generate


class LLVMLoweringTests(unittest.TestCase):
    def test_fixed_allocas_precede_calls_and_initializers(self):
        source = """
算 累计 值:
 总数 取 0.
 循 值 次
  总数 取 总数+([值,总数] 其 量).
 环.
 得 总数.
法.
显 (累计 3).
"""
        ir = LLVMCompiler(parse(source)).compile()
        seen = 0
        for body in re.findall(r'define void @[^}]+}', ir):
            non_alloca = False
            for line in body.splitlines()[2:]:
                if ' = alloca ' in line:
                    if any(size in line for size in ('%frame_bytes', '%value_bytes', '%argpack_bytes')):
                        continue  # Its C-owned size folds when the helper is inlined.
                    self.assertFalse(non_alloca, line)
                    seen += 1
                else:
                    non_alloca = True
        self.assertGreater(seen, 0)

    def test_frame_storage_limit_keeps_large_values_off_the_stack(self):
        source = '算 小: 得 [' + ','.join(map(str, range(63))) + ']. 法.\n'
        source += '算 大: 得 [' + ','.join(map(str, range(64))) + ']. 法.'
        ir = LLVMCompiler(parse(source)).compile()
        self.assertIn('call void @rul_local_frame_init(i8* %frame, i32 64)', ir)
        self.assertIn('call i8* @rul_frame_new(i32 65)', ir)
        # The existing real 63/64-element frame test exercises both paths with
        # escaped results, deep recursion and forced GC on both frontends.

    def test_direct_returns_initialize_fresh_storage(self):
        ir = LLVMCompiler(parse('算 看 值: 得 值. 法. 作 空作: 完. 为.')).compile()
        self.assertIn('i8* noalias writeonly %out)', ir)
        self.assertIn('call void @rul_return_copy(i8* %out,', ir)
        self.assertIn('call void @rul_return_null(i8* %out)', ir)
        self.assertNotIn('call void @rul_copy(i8* %out,', ir)
        self.assertNotIn('call void @rul_null(i8* %out)', ir)

    def test_cache_selection_matches_repeated_local_c_bindings(self):
        sources = [
            '算 一次 值: 得 值. 法. 显 (一次 1).',
            '算 外 起: 值 取 起. 算 内: 值 取 值+1. 得 值. 法. 得 算 内. 法.',
            '算 看: 段: 值 取 1. 显 值+值. 落. 得 0. 法.',
        ]
        for source in sources:
            with self.subTest(source=source):
                ir = LLVMCompiler(parse(source)).compile()
                self.assertNotRegex(ir, r'call void @rul_(?:init_)?get_cached\(')
                self.assertNotIn('call void @rul_bind_cached(', ir)
        ir = LLVMCompiler(parse('算 重复 值: 值 取 值+1. 得 值. 法.')).compile()
        self.assertIn('call void @rul_init_get_cached(', ir)
        self.assertIn('call void @rul_bind_cached(', ir)


@unittest.skipUnless(CC, 'C compiler required')
class RuntimeFastPathTests(unittest.TestCase):
    def test_scalar_equality_and_positional_calls_need_no_scratch_allocation(self):
        # Compile the real full runtime, including structural pair equality.
        # Count allocation requests only within the operations under test.
        prelude = """
#ifndef _WIN32
#define _POSIX_C_SOURCE 200809L
#endif
#include <stdlib.h>
static size_t allocations;
static void *counted_malloc(size_t size) { ++allocations; return malloc(size); }
#define malloc counted_malloc
#define main generated_main
"""
        probe = r'''
#undef main
static Val *original_arguments;
static Val probe(Env *env, Val self, int line, Val *args)
{
    (void)env; (void)self; (void)line;
    return v_fact(args == original_arguments && args[0].n == 3 && args[1].n == 7);
}
int main(void)
{
    Env env = {0};
    const char *names[] = {"a", "b"}, *types[] = {"", ""}, *keys[] = {NULL, NULL};
    RuFunction function = {"probe", 2, names, types, probe, 0};
    Val a, b, callable, result, args[] = {v_num(3), v_num(7)};
    size_t before;
    ru_init();
    a=v_str("same"); b=v_str("same");
    before=allocations;
    if(!v_equal(a,b,1) || !v_equal(v_num(3),v_num(3),1) ||
       v_equal(v_num(1),v_fact(1),1) || allocations!=before) return 1;
    callable=v_function(&function,&env,v_null());
    original_arguments=args; before=allocations;
    result=v_call(callable,2,keys,args,1);
    if(!v_truth(result) || allocations!=before) return 2;
    v_drop(result); v_drop(callable); v_drop(a); v_drop(b);
    ru_shutdown(); return 0;
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            binary = build(prelude + generate('显 1.', full=True) + probe, temporary, 'fast-paths')
            result = subprocess.run([str(binary)], capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))


if __name__ == '__main__':
    unittest.main()
