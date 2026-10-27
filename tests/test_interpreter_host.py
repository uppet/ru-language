"""Exercise opt-in temporary-frame ownership with the actual native runtime."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from rulang.c_runtime import runtime_source
from rulang.frontend import RuError
from rulang.interpreter_host import integrate_host
from rulang.llvm_toolchain import LLVMToolchain


class InterpreterFrameTests(unittest.TestCase):
    def test_written_slots_nested_returns_and_repeated_clear_release_all_roots(self):
        try:
            toolchain = LLVMToolchain()
        except RuError as error:
            self.skipTest(str(error))
        bridge = Path(__file__).resolve().parents[1]/'rulang/llvm_runtime.h'
        runtime = integrate_host(runtime_source({}, '', full=True, llvm=True)+'\n'+bridge.read_text(encoding='utf-8'))
        checks = r'''
#include <assert.h>
static RuFunction *rul_function_descriptor(int32_t id) { (void)id; return NULL; }
static RuClass *rul_class_descriptor(int32_t id) { (void)id; return NULL; }
static Val rul_module_import(int32_t id) { (void)id; return v_null(); }
static int borrowed_calls;
static Val borrowed_identity(Env *global, Val self, int line, Val *args) {
    (void)global; (void)self; (void)line;
    ++borrowed_calls; return v_copy(args[0]);
}
int main(void) {
    RuLLVMFrame *outer, *inner, *empty, *last;
    Val returned=v_null();
    int i;
    ru_init();
    {
        const char *names[]={"value"}, *types[]={""};
        const char *positional[]={NULL}, *named[]={"value"};
        RuFunction descriptor={0};
        descriptor.name="borrowed";descriptor.count=1;descriptor.names=names;
        descriptor.types=types;descriptor.code=borrowed_identity;
        Val callable=v_function(&descriptor,NULL,v_null());
        Val *arguments=ru_scratch_alloc(sizeof(Val),1);
        arguments[0]=v_str("caller-owned");
        for(i=0;i<2;++i) {
            const char **keys=i?named:positional;
            ru_call_depth=500;
            Val failed=v_call(callable,1,keys,arguments,1);
            assert(ru_panicking && failed.kind==RU_NULL && borrowed_calls==i);
            /* A failed borrowed call must not free its caller's scratch block.
             * Named binding must free only its own reordered argument block. */
            if(!ru_scratch || ru_scratch->data!=arguments)return 61;
            assert(!strcmp(arguments[0].s->data,"caller-owned"));
            ru_call_depth=0;ru_panic_clear();
            Val retried=v_call(callable,1,keys,arguments,1);
            assert(!ru_panicking && borrowed_calls==i+1);
            assert(!strcmp(retried.s->data,"caller-owned"));v_drop(retried);
            assert(ru_scratch && ru_scratch->data==arguments);
        }
        v_drop(arguments[0]);ru_scratch_free(arguments);v_drop(callable);
    }
    {
        union { double align; void *pointer; unsigned char bytes[4096]; } storage;
        RuLLVMFrame *stack_frame=(RuLLVMFrame *)storage.bytes;
        assert(rul_frame_size(4)<=sizeof(storage.bytes));
        rul_frame_init(stack_frame,4);
        rul_init_string(rul_slot(stack_frame,0),"stack literal");
        rul_init_number(rul_slot(stack_frame,1),7);
        assert(stack_frame->active_count==2);
        rul_clear_count(stack_frame,1);
        assert(stack_frame->active_count==1 && stack_frame->values[0].kind==RU_NULL);
        rul_frame_drop(stack_frame);
        assert(ru_llvm_active_frames==NULL);
    }
    {
        union { double align; void *pointer; unsigned char bytes[4096]; } storage;
        Val ignored=v_null();
        RuLLVMFrame *local=(RuLLVMFrame *)storage.bytes;
        assert(rul_local_frame_size(3)<=sizeof(storage.bytes));
        rul_local_frame_init(local,3);
        rul_local_frame_roots(local,3,0);
        void *first=rul_local_slot(local,0,&ignored);
        void *second=rul_local_slot(local,1,&ignored);
        assert(first==&local->values[0] && second==&local->values[1]);
        rul_init_string(first,"first");rul_init_number(second,17);
        assert(local->active_count==2 && ignored.kind==RU_NULL);
        rul_local_clear_mask(local,1,0,0);
        assert(local->active_count==1 && local->values[0].kind==RU_NULL);
        rul_init_string(first,"reused");
        assert(local->active_count==2);
        rul_local_clear_mask(local,2,0,0);
        assert(local->active_count==0 && !local->written[0] && !local->written[1]);
        rul_local_frame_drop(local);
        assert(ru_llvm_active_frames==NULL);
    }
    outer=rul_frame_new(1000);
    for(i=0;i<1000;++i)assert(outer->values[i].kind==RU_NULL);
    rul_number(rul_slot(outer,999),42);
    rul_string(rul_slot(outer,1),"literal");
    /* An overwritten slot must occur just once in the pending clear list. */
    rul_string(rul_slot(outer,1),"replacement");
    assert(outer->active_count==2);
    inner=rul_frame_new(5);
    rul_string(rul_slot(inner,2),"returned");
    /* A callee can return into an outer frame or an initialized C-stack Val. */
    rul_copy(rul_slot(outer,600),rul_slot(inner,2));
    rul_return_copy(&returned,rul_slot(inner,2));
    rul_frame_free(inner);
    assert(outer->active_count==3);
    assert(!strcmp(outer->values[600].s->data,"returned"));
    assert(!strcmp(returned.s->data,"returned"));
    rul_clear_count(outer,2);
    assert(outer->active_count==2);
    assert(outer->values[1].kind==RU_NULL);
    assert(outer->values[999].kind==RU_NUM);
    assert(!strcmp(outer->values[600].s->data,"returned"));
    rul_clear_count(outer,601);
    assert(outer->active_count==1);
    assert(outer->values[600].kind==RU_NULL);
    assert(outer->values[999].kind==RU_NUM);
    for(i=0;i<100;++i) {
        rul_clear(outer);rul_clear(outer);
        assert(outer->active_count==0);
        assert(outer->values[999].kind==RU_NULL);
        assert(outer->values[1].kind==RU_NULL);
        assert(outer->values[600].kind==RU_NULL);
        rul_number(rul_slot(outer,999),i);
        rul_string(rul_slot(outer,1),"literal");
    }
    empty=rul_frame_new(0);last=rul_frame_new(1);
    /* Also unlink a non-top frame without invalidating the active top. */
    rul_frame_free(empty);rul_number(rul_slot(last,0),7);
    rul_frame_free(last);rul_frame_free(outer);v_drop(returned);
    assert(ru_llvm_active_frames==NULL);
    ru_shutdown();return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='ru-interpreter-frames-') as temp:
            # Use the product's runtime link, including its LLVM support code.
            program = (f'target triple = "{toolchain.triple}"\n'
                       f'target datalayout = "{toolchain.data_layout}"\n')
            binary, _ = toolchain.compile(program, '#define RU_ENABLE_MODULO 1\n'+runtime+checks, Path(temp))
            result = subprocess.run([str(binary)], capture_output=True, text=True,
                encoding='utf-8', timeout=30,
                env={**os.environ, 'RU_GC_THRESHOLD': '1', 'RU_GC_STATS': '1'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('live=0', result.stderr)


if __name__ == '__main__':
    unittest.main()
