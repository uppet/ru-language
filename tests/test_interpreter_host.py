"""Exercise opt-in temporary-frame ownership with the actual native runtime."""
import os
from pathlib import Path
import subprocess
import sys
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
        runtime = integrate_host(runtime_source({}, '', full=True)+'\n'+bridge.read_text(encoding='utf-8'))
        checks = r'''
#include <assert.h>
static RuFunction *rul_function_descriptor(int32_t id) { (void)id; return NULL; }
static RuClass *rul_class_descriptor(int32_t id) { (void)id; return NULL; }
static Val rul_module_import(int32_t id) { (void)id; return v_null(); }
int main(void) {
    RuLLVMFrame *outer, *inner, *empty, *last;
    Val returned=v_null();
    int i;
    ru_init();
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
    rul_copy(&returned,rul_slot(inner,2));
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
            source = Path(temp)/'frames.c'
            binary = Path(temp)/('frames.exe' if sys.platform == 'win32' else 'frames')
            source.write_text('#define RU_ENABLE_MODULO 1\n'+runtime+checks, encoding='utf-8')
            toolchain.run(toolchain.clang+['-std=c99', '-O2', str(source), '-o', str(binary),
                                           *toolchain.link_flags])
            result = subprocess.run([str(binary)], capture_output=True, text=True,
                encoding='utf-8', timeout=30,
                env={**os.environ, 'RU_GC_THRESHOLD': '1', 'RU_GC_STATS': '1'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('live=0', result.stderr)


if __name__ == '__main__':
    unittest.main()
