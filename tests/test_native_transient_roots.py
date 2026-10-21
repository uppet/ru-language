"""Native callback root-index regressions in generated native C.

Windows x64 uses the actual emitted Windows platform layer. Other POSIX hosts
use the existing owned test adapter and provide generic C ownership/state
evidence only, never Windows ABI acceptance. All instrumentation is confined to
generated artifacts; production must not gain test switches or a POSIX backend.
"""
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from rulang.compiler import Compiler
from rulang.frontend import parse
from test_native_c_backend import WINDOWS_X64, bounded_run
from test_native_c_runtime import portable_test_source


PREFIX = "密 取 外言 '如:密'.\n"


def function_span(source, name):
    match = re.search(r'(?m)^static [^\n;]*\b' + name + r'\([^;]*?\)\s*\{', source)
    if not match:
        raise AssertionError('missing generated function: ' + name)
    depth, end = 1, match.end()
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return match.start(), end


ORACLE = r'''
#include <assert.h>
/* Deliberately independent of rn_transient_link/unlink and snapshot traversal:
 * enumerate the full heap, then compare every heap against the linked index. */
static size_t test_oracle(void)
{
    RuHeap *h, *node, *previous = NULL;
    size_t heaps = 0, expected = 0, listed = 0;
    for (h = ru_heap; h; h = h->next) {
        ++heaps;
        assert(h->roots >= h->permanent_roots);
        expected += h->roots > h->permanent_roots;
    }
    for (node = ru_transient_roots; node; node = node->transient_next) {
        int found = 0;
        assert(++listed <= heaps); /* duplicates/cycles cannot loop forever */
        for (h = ru_heap; h; h = h->next) if (h == node) found = 1;
        assert(found);
        assert(node->transient_prev == previous);
        assert(node->roots > node->permanent_roots);
        previous = node;
    }
    assert(expected == listed);
    for (h = ru_heap; h; h = h->next) {
        size_t occurrences = 0;
        for (node = ru_transient_roots; node; node = node->transient_next)
            occurrences += node == h;
        assert(occurrences == (size_t)(h->roots > h->permanent_roots));
        if (!occurrences) assert(!h->transient_prev && !h->transient_next);
    }
    return listed;
}
static void test_begin(void)
{
    ru_init();
    ru_next_gc = SIZE_MAX;
    assert(!ru_heap && !ru_transient_roots);
}
static void test_end(void)
{
    assert(test_oracle() == 0);
    ru_gc();
    assert(!ru_heap && !ru_live && !ru_transient_roots);
}
static void test_snapshot(RuNativeTrap *trap)
{
    RuHeap *h;
    size_t i, expected = 0;
    assert(trap);
    for (h = ru_heap; h; h = h->next) {
        size_t found = 0;
        for (i = 0; i < trap->root_count; ++i) if (trap->roots[i].heap == h) {
            ++found;
            assert(trap->roots[i].transient == h->roots - h->permanent_roots);
        }
        assert(found == (size_t)(h->roots > h->permanent_roots));
        expected += h->roots > h->permanent_roots;
    }
    assert(expected == trap->root_count);
    for (i = 1; i < trap->root_count; ++i)
        assert((uintptr_t)trap->roots[i-1].heap < (uintptr_t)trap->roots[i].heap);
    test_oracle();
}
/* Traps under test come from the production freelist allocator: rn_trap_new
 * pops a recycled node (or calloc's one) and rn_trap_release returns roots
 * memory and recycles the node.  Tests that own a trap outright can simply
 * free it; tests that interleave with dispatch use the release pair. */
static RuNativeTrap *test_trap_new(void)
{
    return rn_trap_new();
}
static void test_free_trap(RuNativeTrap *trap)
{
    ru_native_trap = trap->previous;
    free(trap->roots);
    free(trap);
}
'''


class NativeTransientRootEmissionTests(unittest.TestCase):
    def test_native_only_index_and_snapshot_boundary(self):
        source = Compiler(parse(PREFIX), 'root-test.ru', allow_native=True,
                          full_runtime=True).compile()
        self.assertIn('transient_prev', source)
        self.assertIn('transient_next', source)
        self.assertIn('ru_transient_roots', source)
        for name in ('rn_transient_link', 'rn_transient_unlink'):
            start, end = function_span(source, name)
            self.assertNotRegex(source[start:end], r'\b(?:malloc|calloc|realloc|ru_alloc)\s*\(')
        start, end = function_span(source, 'rn_trap_new')
        snapshot = source[start:end]
        self.assertNotRegex(snapshot, r'\bru_heap\b', 'snapshot must never enumerate the full heap')
        self.assertIn('qsort(', snapshot, 'this change must preserve sorted snapshots')
        start, end = function_span(source, 'rn_trap_restore')
        restore = source[start:end]
        self.assertIn('bsearch(', restore)
        self.assertRegex(restore, r'for\s*\(heap\s*=\s*ru_heap;')
        self.assertRegex(restore, r'heap->mark\s*=\s*0;')
        for full in (False, True):
            plain = Compiler(parse("显 'ordinary'."), 'ordinary.ru',
                             allow_native=True, full_runtime=full).compile()
            for symbol in ('transient_prev', 'transient_next', 'ru_transient_roots',
                           'rn_transient_link', 'rn_transient_unlink'):
                self.assertNotIn(symbol, plain)


@unittest.skipUnless((os.name == 'posix' or WINDOWS_X64) and shutil.which('gcc'),
                     'native root-state tests require Windows x64 GCC or owned POSIX adapter GCC')
class NativeTransientRootRuntimeTests(unittest.TestCase):
    def build_and_run(self, body, *, transform=None, extra_c='', expected_code=0):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            if WINDOWS_X64:
                source = Compiler(parse(PREFIX), str(path / 'program.ru'),
                                  allow_native=True, full_runtime=True).compile()
            else:
                source = portable_test_source(PREFIX, str(path / 'program.ru'), full=True)
            source = source.replace('int main(int argc, char **argv)',
                                    'int test_generated_main(int argc, char **argv)')
            if transform:
                source = transform(source)
            source += ORACLE + extra_c + '\nint main(void) {\n' + body + '\nreturn 0;\n}\n'
            cfile = path / 'program.c'
            executable = path / ('program.exe' if WINDOWS_X64 else 'program')
            cfile.write_text(source, encoding='utf-8')
            command = ['gcc', '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror',
                       '-Wno-unused-function', '-pedantic', str(cfile), '-o',
                       str(executable), '-lm']
            if not WINDOWS_X64:
                command += ['-ldl', '-pthread']
            if os.environ.get('RU_NATIVE_TEST_SANITIZE') == '1':
                command[1:1] = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-g']
            result = bounded_run(command, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stderr, '', 'generated native C produced warnings')
            env = dict(os.environ, RU_GC_THRESHOLD='1')
            env.pop('RU_GC_STATS', None)
            result = bounded_run([str(executable)], timeout=45, env=env)
            self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
            return result

    def test_root_transitions_env_gc_and_head_middle_tail(self):
        result = self.build_and_run(r'''
    Val a, b, c, held, edge;
    Env unmanaged, *managed;
    RuNativeTrap *empty;
    test_begin();
    a = v_str("tail"); b = v_str("middle"); c = v_str("head");
    assert(test_oracle() == 3);
    assert(ru_transient_roots == c.heap);
    v_drop(b); assert(test_oracle() == 2); /* middle removal */
    v_drop(c); assert(test_oracle() == 1); /* head removal */
    v_drop(a); assert(test_oracle() == 0); /* tail/last removal */
    empty = test_trap_new(); test_snapshot(empty); assert(!empty->root_count);
    rn_trap_restore(empty); test_snapshot(empty); test_free_trap(empty);
    a = v_copy(a); b = v_copy(b); c = v_copy(c);
    assert(test_oracle() == 3);
    held = v_copy(a); assert(a.heap->roots == 2); test_oracle();
    v_drop(held); assert(a.heap->roots == 1); test_oracle();
    v_pin(a); assert(a.heap->roots == 2 && a.heap->permanent_roots == 1);
    assert(test_oracle() == 3);
    v_drop(a); assert(test_oracle() == 2); /* permanent only */
    v_pin(a); assert(test_oracle() == 2); /* paired pin cannot invent transient */
    v_unpin(a); assert(test_oracle() == 2);
    a = v_copy(a); assert(test_oracle() == 3);
    v_unpin(a); assert(a.heap->roots == 1 && !a.heap->permanent_roots);
    assert(test_oracle() == 3);
    env_init(&unmanaged, NULL);
    env_set(&unmanaged, "value", a); test_oracle();
    env_set(&unmanaged, "value", b); test_oracle();
    env_free(&unmanaged); test_oracle();
    managed = env_new(NULL, RU_SCOPE_FUNCTION, 0); test_oracle();
    env_set(managed, "value", c); test_oracle();
    env_free(managed); assert(test_oracle() == 3);
    edge = v_array(1, &b, 0); v_drop(b);
    ru_gc(); assert(test_oracle() == 3); /* graph-only b survives */
    assert(b.heap->roots == 0);
    v_drop(a); v_drop(c); v_drop(edge);
    test_end();
    puts("root-transitions-ok");
''')
        self.assertEqual(result.stdout, 'root-transitions-ok\n')
        self.assertEqual(result.stderr, '')

    def test_actual_native_heap_size_cost(self):
        result = self.build_and_run(r'''
    struct PreviousNativeHeap { size_t permanent_roots, roots; unsigned mark; int kind; void *next; };
    assert(sizeof(RuHeap) == sizeof(struct PreviousNativeHeap) + 2 * sizeof(void *));
    printf("heap=%zu previous=%zu delta=%zu pointer=%zu\n", sizeof(RuHeap),
           sizeof(struct PreviousNativeHeap), sizeof(RuHeap) - sizeof(struct PreviousNativeHeap), sizeof(void *));
''')
        values = re.fullmatch(r'heap=(\d+) previous=(\d+) delta=(\d+) pointer=(\d+)\n', result.stdout)
        self.assertIsNotNone(values)
        heap, previous, delta, pointer = map(int, values.groups())
        self.assertEqual(heap - previous, delta)
        self.assertEqual(delta, 2 * pointer)
        if pointer == 8:
            self.assertEqual(delta, 16)

    def test_normal_shutdown_disposes_still_rooted_heaps(self):
        result = self.build_and_run(r'''
    Val a, b, c;
    test_begin();
    a = v_str("unreleased-transient"); b = v_str("permanent-only");
    c = v_str("both-root-kinds");
    v_pin(b); v_drop(b); v_pin(c);
    assert(test_oracle() == 2);
    (void)a;
    /* Nonfatal process exit deliberately disposes remaining temporary roots
     * after GC. This exercises disposal of listed, not only swept, heaps. */
    ru_shutdown();
    assert(!ru_failed && ru_finished && !ru_heap && !ru_live && !ru_transient_roots);
    puts("normal-shutdown-empty");
''')
        self.assertEqual(result.stdout, 'normal-shutdown-empty\n')
        self.assertEqual(result.stderr, '')

    def test_nested_repeated_restore_permanent_changes_and_graph_marks(self):
        result = self.build_and_run(r'''
    Val a, b, child, graph, permanent, born, discarded, reason;
    RuNativeTrap *outer, *inner;
    void *outer_scratch;
    const char *saved_source = "outer-source";
    size_t live_before;
    test_begin();
    a = v_str("entry-a"); b = v_str("entry-b");
    child = v_str("graph-only"); graph = v_array(1, &child, 0); v_drop(child);
    permanent = v_str("permanent-only"); v_pin(permanent); v_drop(permanent);
    v_pin(a);
    outer_scratch = ru_scratch_alloc(17, 0);
    ru_call_depth = 7; ru_source = saved_source;
    outer = test_trap_new(); test_snapshot(outer); ru_native_trap = outer;
    assert(outer->root_count == 3 && !outer->previous);
    v_copy(a); v_pin(b); v_unpin(permanent);
    born = v_str("born-during-callback"); v_pin(born);
    discarded = v_str("born-then-destroyed"); v_drop(discarded);
    live_before = ru_live; ru_gc(); assert(ru_live == live_before - 2);
    ru_next_gc = SIZE_MAX;
    ru_scratch_alloc(19, 0);
    inner = test_trap_new(); test_snapshot(inner); ru_native_trap = inner;
    assert(inner != outer && inner->roots != outer->roots && inner->previous == outer);
    assert(inner->root_count == 4 && outer->root_count == 3);
    v_copy(a); v_copy(a); v_copy(graph); v_unpin(b);
    ru_scratch_alloc(23, 0); ru_call_depth = 99; ru_source = "abandoned-source";
    child.heap->mark = 2; graph.heap->mark = 2;
    reason = v_str("panic-state"); ru_panic_raise(reason, 11, 12); v_drop(reason);
    assert(ru_panicking);
    rn_trap_restore(inner);
    assert(!ru_panicking && !child.heap->mark && !graph.heap->mark);
    assert(a.heap->roots == 3 && a.heap->permanent_roots == 1);
    assert(b.heap->roots == 1 && !b.heap->permanent_roots);
    assert(born.heap->roots == 2 && born.heap->permanent_roots == 1);
    test_snapshot(inner);
    /* The failure action may throw again through the same trap. */
    v_copy(a); child.heap->mark = 2; ru_scratch_alloc(29, 0);
    rn_trap_restore(inner); test_snapshot(inner); assert(!child.heap->mark);
    test_free_trap(inner); assert(ru_native_trap == outer);
    v_pin(b); v_copy(born); child.heap->mark = 2;
    rn_trap_restore(outer);
    assert(a.heap->roots == 2 && a.heap->permanent_roots == 1);
    assert(b.heap->roots == 2 && b.heap->permanent_roots == 1);
    assert(born.heap->roots == 1 && born.heap->permanent_roots == 1);
    assert(!child.heap->mark && ru_call_depth == 7 && ru_source == saved_source);
    assert(ru_scratch && ru_scratch->data == outer_scratch && !ru_scratch->next);
    test_snapshot(outer);
    rn_trap_restore(outer); test_snapshot(outer);
    test_free_trap(outer); assert(!ru_native_trap);
    ru_scratch_free(outer_scratch);
    v_unpin(a); v_unpin(b); v_unpin(born);
    v_drop(a); v_drop(b); v_drop(graph);
    test_end(); puts("nested-restore-ok");
''')
        self.assertEqual(result.stdout, 'nested-restore-ok\n')
        self.assertEqual(result.stderr, '')

    def test_snapshot_visits_depend_on_transient_roots_not_heap_size(self):
        def instrument(source):
            start, end = function_span(source, 'rn_trap_new')
            snapshot = source[start:end]
            # Count each non-null node condition, including both the count and
            # copy passes. This measures mechanism, not noisy elapsed time.
            snapshot, count = re.subn(
                r'(for\s*\(heap\s*=\s*ru_transient_roots;\s*)heap(\s*;)',
                r'\1heap && (++test_snapshot_visits, 1)\2', snapshot)
            self.assertEqual(count, 2, 'expected exactly two transient-root passes')
            return (source[:start] + 'static size_t test_snapshot_visits;\n' +
                    snapshot + source[end:])

        result = self.build_and_run(r'''
    Val graph, child, pinned;
    RuNativeTrap *trap;
    size_t i, before, small, large;
    test_begin();
    graph = v_array(0, NULL, 0);
    pinned = v_str("persistent-only"); v_pin(pinned); v_drop(pinned);
    for (i = 0; i < 8; ++i) {
        Val ignored;
        child = v_str("graph-only"); ignored = v_append(graph, child, 0);
        v_drop(ignored); v_drop(child);
    }
    before = ru_live; test_snapshot_visits = 0;
    trap = test_trap_new(); test_snapshot(trap); small = test_snapshot_visits;
    assert(trap->root_count == 1); test_free_trap(trap);
    for (i = 0; i < 4096; ++i) {
        Val ignored;
        child = v_str("graph-only"); ignored = v_append(graph, child, 0);
        v_drop(ignored); v_drop(child);
    }
    test_snapshot_visits = 0;
    trap = test_trap_new(); test_snapshot(trap); large = test_snapshot_visits;
    assert(trap->root_count == 1 && ru_live == before + 4096);
    assert(small == 2 && large == small);
    printf("fixed-R=1 small-H=%zu large-H=%zu visits=%zu,%zu\n", before, ru_live, small, large);
    test_free_trap(trap); v_unpin(pinned); v_drop(graph); test_end();
''', transform=instrument)
        self.assertEqual(result.stdout, 'fixed-R=1 small-H=10 large-H=4106 visits=2,2\n')
        self.assertEqual(result.stderr, '')

    def test_fatal_shutdown_clears_index_transient_counts_and_heap(self):
        def instrument(source):
            start, end = function_span(source, 'ru_heap_dispose')
            dispose = source[start:end]
            self.assertEqual(dispose.count('free(heap);'), 1)
            dispose = dispose.replace('free(heap);', '''
    assert(!heap->transient_prev && !heap->transient_next);
    /* Terminal invalidation deliberately preserves old permanent counters;
     * roots >= permanent_roots applies only to normal/recoverable states. */
    if (ru_failed) assert(!heap->roots && !ru_transient_roots);
    free(heap);''')
            source = source[:start] + dispose + source[end:]
            return source.replace('#include <string.h>', '#include <string.h>\n#include <assert.h>', 1)

        extra_c = r'''
static void test_fatal_exit(void)
{
    assert(ru_finished && ru_failed);
    assert(!ru_heap && !ru_transient_roots && !ru_live);
    puts("fatal-shutdown-empty");
}
'''
        result = self.build_and_run(r'''
    Val a, b;
    Env module;
    test_begin();
    a = v_str("abandoned-frame"); b = v_str("permanent-and-transient");
    v_pin(b);
    env_init(&module, NULL); env_set(&module, "value", b);
    env_new(NULL, RU_SCOPE_FUNCTION, 0);
    test_oracle();
    assert(atexit(test_fatal_exit) == 0);
    (void)a;
    ru_fail(91, "test-fatal-shutdown");
''', transform=instrument, extra_c=extra_c, expected_code=1)
        self.assertEqual(result.stdout, 'fatal-shutdown-empty\n')
        self.assertIn(':91: error: 运行错误：test-fatal-shutdown\n', result.stderr)

    def test_callback_success_nested_error_panic_and_snapshot_oom(self):
        def instrument(source):
            start, end = function_span(source, 'rn_trap_new')
            snapshot = source[start:end]
            # The freelist recycles trap nodes: calloc fires only on a miss,
            # and malloc exactly once for the roots snapshot.  Both failure
            # paths return the node to the freelist before reporting NULL.
            self.assertEqual(snapshot.count('calloc('), 1)
            self.assertEqual(snapshot.count('malloc('), 1)
            snapshot = snapshot.replace('malloc(', 'test_trap_malloc(')
            wrappers = r'''
static int test_trap_oom_stage;
static void *test_trap_malloc(size_t size)
{
    if (test_trap_oom_stage) { test_trap_oom_stage = 0; return NULL; }
    return malloc(size);
}
'''
            source = source.replace('#include <string.h>', '#include <string.h>\n#include <assert.h>', 1)
            start, end = function_span(source, 'rn_trap_new')
            return source[:start] + wrappers + snapshot + source[end:]

        extra_c = r'''
static int test_callback_mode, test_callback_calls;
static unsigned test_callback_slot;
static Val test_callback_code(Env *env, Val self, int line, Val *args)
{
    RuNativeTrap *outer = ru_native_trap;
    (void)env; (void)self; (void)line; (void)args;
    ++test_callback_calls; test_oracle();
    assert(outer);
    if (test_callback_mode == 1) {
        v_str("abandoned-runtime-error-value");
        ru_fail(31, "callback-runtime-error");
    }
    if (test_callback_mode == 2) {
        Val reason = v_str("callback-panic");
        ru_panic_raise(reason, 32, 7); v_drop(reason);
        return v_null();
    }
    if (test_callback_mode == 3) {
        RuNativeRaw answer;
        test_callback_mode = 0;
        answer = ru_native_callback_dispatch(test_callback_slot, 0, NULL);
        assert(answer.i == 42 && ru_native_trap == outer);
        test_oracle();
    }
    if (test_callback_mode == 4 || test_callback_mode == 5) {
        RuNativeRaw answer;
        Val extras[65]; size_t i;
        int was_oom = (test_callback_mode == 4);
        /* Roots always come from malloc in the freelist design, whatever the
         * transient-root count.  Mode 4 OOMs that malloc; mode 5 succeeds.
         * Clear the mode first so the nested callback takes the plain path. */
        test_callback_mode = 0;
        for (i = 0; i < 65; ++i) { extras[i] = v_str("extra-root"); v_copy(extras[i]); }
        {
            size_t count = test_oracle();
            test_trap_oom_stage = was_oom;
            answer = ru_native_callback_dispatch(test_callback_slot, 0, NULL);
            assert(test_oracle() == count && !test_trap_oom_stage);
        }
        for (i = 0; i < 65; ++i) v_drop(extras[i]);
        if (was_oom) {
            assert(answer.i == -73 && ru_native_trap == outer);
            ru_fail(33, "outer-trap-survives-inner-oom");
        }
        assert(answer.i == 42 && ru_native_trap == outer);
        ru_fail(33, "outer-trap-survives-inner-malloc");
    }
    return v_num(42);
}
'''
        result = self.build_and_run(r'''
    RuFunction definition = {"owned-callback", 0, NULL, NULL, test_callback_code, 0};
    Val signature, callable, callback;
    RuNative *object, *sig;
    RuNativeSlot *slot;
    RuNativeRaw answer;
    RuNativeTrap *outer;
    size_t roots, permanent;
    int mode;
    test_begin(); ru_native_builtins(NULL); ru_native_depth = 1;
    signature = rn_new(RN_SIGNATURE, 0); sig = (RuNative *)signature.heap;
    sig->as.signature.id = 0; sig->as.signature.count = 0;
    sig->as.signature.result = ru_native_primitives[RN_I64];
    rn_edge(sig, rn_value(ru_native_primitives[RN_I64]), 0);
    callable = v_function(&definition, NULL, v_null());
    callback = rn_new(RN_CALLBACK, 0); object = (RuNative *)callback.heap;
    object->as.callback.signature = sig;
    object->as.callback.slot = test_callback_slot = ru_native_slot_count++;
    rn_edge(object, signature, 0); rn_edge(object, callable, 0);
    rn_edge(object, v_null(), 0); rn_edge(object, v_null(), 0);
    slot = ru_native_slots + test_callback_slot;
    slot->object = object; slot->fallback.i = -73; slot->signature = 0;
    slot->owner_thread = ru_native_thread_id;
    v_pin(callback); test_oracle();
    roots = callback.heap->roots; permanent = callback.heap->permanent_roots;
    for (mode = 0; mode <= 5; ++mode) {
        test_callback_mode = mode; ru_native_callback_error[0] = 0;
        rn_platform_set_error(778);
        answer = ru_native_callback_dispatch(test_callback_slot, 0, NULL);
        assert(answer.i == ((mode == 0 || mode == 3) ? 42 : -73));
        assert(rn_platform_error() == 778);
        assert(!ru_native_trap && !ru_native_callback_depth && !object->as.callback.active);
        assert(callback.heap->roots == roots && callback.heap->permanent_roots == permanent);
        if (mode == 1) assert(strstr(ru_native_callback_error, "callback-runtime-error"));
        if (mode == 2) assert(strstr(ru_native_callback_error, "callback-panic"));
        if (mode == 4) assert(strstr(ru_native_callback_error, "内存不足"));
        if (mode == 5) assert(strstr(ru_native_callback_error, "outer-trap-survives-inner-malloc"));
        assert(!ru_panicking); test_oracle();
    }
    /* With the trap node on the freelist, the roots malloc is the only
     * allocation that can still fail.  Stage 1 covers the success path;
     * stage 2 OOMs the roots malloc under an active outer trap.  The 65
     * extras mirror the callback-driven modes above and pin the snapshot
     * at a non-trivial size. */
    outer = test_trap_new(); assert(outer); ru_native_trap = outer;
    {
        Val extras[65]; size_t i;
        for (i = 0; i < 65; ++i) { extras[i] = v_str("extra-root"); v_copy(extras[i]); }
        test_callback_mode = 0; ru_native_callback_error[0] = 0;
        answer = ru_native_callback_dispatch(test_callback_slot, 0, NULL);
        assert(answer.i == 42 && !ru_native_callback_error[0]);
        assert(ru_native_trap == outer);
        assert(!ru_native_callback_depth && !object->as.callback.active);
        assert(callback.heap->roots == roots && callback.heap->permanent_roots == permanent);
        test_trap_oom_stage = 1;
        ru_native_callback_error[0] = 0;
        answer = ru_native_callback_dispatch(test_callback_slot, 0, NULL);
        assert(answer.i == -73 && !test_trap_oom_stage);
        assert(ru_native_trap == outer);
        assert(!ru_native_callback_depth && !object->as.callback.active);
        assert(callback.heap->roots == roots && callback.heap->permanent_roots == permanent);
        assert(strstr(ru_native_callback_error, "内存不足")); test_oracle();
        for (i = 0; i < 65; ++i) v_drop(extras[i]);
    }
    test_free_trap(outer);
    ru_native_callback_error[0] = 0; test_callback_mode = 0;
    answer = ru_native_callback_dispatch(test_callback_slot, 0, NULL);
    assert(answer.i == 42 && !ru_native_callback_error[0]); test_oracle();
    rn_callback_close(object); v_drop(callback); v_drop(callable); v_drop(signature);
    ru_native_depth = 0; ru_shutdown();
    assert(!ru_heap && !ru_live && !ru_transient_roots);
    puts("callback-success-nested-error-panic-oom-ok");
''', transform=instrument, extra_c=extra_c)
        self.assertEqual(result.stdout, 'callback-success-nested-error-panic-oom-ok\n')
        self.assertEqual(result.stderr, '')

    def test_seeded_transition_sequences_match_full_heap_oracle(self):
        result = self.build_and_run(r'''
    Val values[32], graph;
    size_t i, round;
    uint32_t seed = UINT32_C(0x42876f31);
    test_begin();
    for (i = 0; i < 32; ++i) values[i] = v_str("oracle-value");
    graph = v_array(32, values, 0);
    for (i = 0; i < 32; ++i) v_drop(values[i]);
    assert(test_oracle() == 1);
    for (round = 0; round < 2048; ++round) {
        RuHeap *heap, *previous, *next;
        unsigned operation;
        seed = seed * UINT32_C(1664525) + UINT32_C(1013904223);
        i = (seed >> 8) % 32; operation = (seed >> 24) % 4;
        heap = values[i].heap;
        previous = heap->transient_prev; next = heap->transient_next;
        if (operation == 0) v_copy(values[i]);
        if (operation == 1 && heap->roots > heap->permanent_roots) v_drop(values[i]);
        if (operation == 2) {
            v_pin(values[i]);
            assert(heap->transient_prev == previous && heap->transient_next == next);
        }
        if (operation == 3 && heap->permanent_roots) {
            v_unpin(values[i]);
            assert(heap->transient_prev == previous && heap->transient_next == next);
        }
        test_oracle();
        if (round % 31 == 0) {
            RuNativeTrap *trap = test_trap_new();
            test_snapshot(trap);
            v_copy(values[i]); v_pin(values[(i+1)%32]);
            values[(i+2)%32].heap->mark = 2;
            rn_trap_restore(trap); test_snapshot(trap);
            assert(!values[(i+2)%32].heap->mark);
            test_free_trap(trap);
            ru_gc(); ru_next_gc = SIZE_MAX; test_oracle();
        }
    }
    for (i = 0; i < 32; ++i) {
        while (values[i].heap->permanent_roots) v_unpin(values[i]);
        while (values[i].heap->roots) v_drop(values[i]);
        test_oracle();
    }
    v_drop(graph); test_end(); puts("seeded-transitions-ok");
''')
        self.assertEqual(result.stdout, 'seeded-transitions-ok\n')
        self.assertEqual(result.stderr, '')

    def test_many_transient_roots_stress_index_and_snapshot(self):
        def instrument(source):
            start, end = function_span(source, 'rn_trap_new')
            snapshot = source[start:end]
            snapshot, count = re.subn(
                r'(for\s*\(heap\s*=\s*ru_transient_roots;\s*)heap(\s*;)',
                r'\1heap && (++test_snapshot_visits, 1)\2', snapshot)
            self.assertEqual(count, 2, 'expected exactly two transient-root passes')
            return (source[:start] + 'static size_t test_snapshot_visits;\n' +
                    snapshot + source[end:])

        result = self.build_and_run(r'''
    Val *values, graph, child, pinned;
    RuNativeTrap *trap;
    size_t i, transient_total, visits, heaps_before;
    enum { COUNT = 2048 };
    test_begin();
    values = (Val *)malloc(COUNT * sizeof(*values));
    assert(values);
    /* Interleave: transient-rooted strings, one permanent-only anchor,
     * and a graph-only container so the heap mixes all three kinds. */
    graph = v_array(0, NULL, 0);
    for (i = 0; i < COUNT; ++i) {
        Val item;
        values[i] = v_str("stress-value");
        child = v_str("stress-graph-only");
        item = v_append(graph, child, 0);
        v_drop(item); v_drop(child);
    }
    pinned = v_str("stress-permanent-only");
    v_pin(pinned); v_drop(pinned);
    assert(test_oracle() == COUNT + 1);
    assert(ru_transient_roots && !ru_transient_roots->transient_prev);
    /* Walk the chain end-to-end: exactly COUNT+1 nodes, no cycles. */
    { RuHeap *node; size_t chain_len = 0;
      for (node = ru_transient_roots; node; node = node->transient_next) ++chain_len;
      assert(chain_len == COUNT + 1); }
    transient_total = test_oracle();
    test_snapshot_visits = 0;
    trap = test_trap_new(); test_snapshot(trap);
    visits = test_snapshot_visits;
    heaps_before = ru_live;
    assert(trap->root_count == transient_total);
    assert(visits == 2 * transient_total);
    assert(heaps_before > COUNT * 2);
    printf("count=%zu heaps=%zu visits=%zu\n", transient_total, heaps_before, visits);
    /* Drop half the transient roots while the trap is live. */
    for (i = 0; i < COUNT; i += 2) v_drop(values[i]);
    assert(test_oracle() == COUNT / 2 + 1);
    /* Restore revives the dropped roots from the trap snapshot. */
    rn_trap_restore(trap); test_snapshot(trap);
    assert(trap->root_count == transient_total);
    test_free_trap(trap);
    /* Clean up: restore revived even-index roots; drop everything. */
    for (i = 0; i < COUNT; ++i) v_drop(values[i]);
    v_drop(graph);
    v_unpin(pinned);
    free(values);
    test_end(); puts("many-transient-roots-ok");
''', transform=instrument)
        self.assertEqual(result.stdout, 'count=2049 heaps=4098 visits=4098\nmany-transient-roots-ok\n')
        self.assertEqual(result.stderr, '')

    def test_formatter_allocation_failure_clears_graph_only_marks_before_gc(self):
        def instrument(source):
            start, end = function_span(source, 'ru_native_scratch_realloc')
            function = source[start:end]
            self.assertEqual(function.count('realloc(data, size ? size : 1)'), 1)
            function = function.replace('realloc(data, size ? size : 1)',
                                        'test_format_realloc(data, size ? size : 1)')
            wrapper = r'''
static RuHeap *test_format_graph_only;
static int test_format_fail;
static void *test_format_realloc(void *data, size_t size)
{
    if (test_format_fail && test_format_graph_only->mark == 2) {
        test_format_fail = 0;
        return NULL;
    }
    return realloc(data, size);
}
'''
            return source[:start] + wrapper + function + source[end:]

        extra_c = r'''
/* A separate setjmp-containing function avoids GCC's inlining/clobber warning
 * on rn_trap_new's allocator locals, without weakening warnings or production. */
static void test_throw_from_formatter(Val graph, RuNativeTrap *trap)
{
    if (setjmp(trap->jump) == 0) {
        Val unexpected = v_to_string(graph); v_drop(unexpected);
        assert(0 && "formatter realloc failure did not throw");
    }
}
'''
        result = self.build_and_run(r'''
    char long_text[257];
    Val text, child, graph;
    RuNativeTrap *trap;
    size_t collections;
    test_begin(); memset(long_text, 'x', 256); long_text[256] = 0;
    text = v_str(long_text); child = v_array(1, &text, 0); v_drop(text);
    graph = v_array(1, &child, 0); v_drop(child);
    assert(!child.heap->roots && test_oracle() == 1);
    trap = test_trap_new(); test_snapshot(trap); ru_native_trap = trap;
    assert(trap->root_count == 1 && trap->roots[0].heap == graph.heap);
    test_format_graph_only = child.heap; test_format_fail = 1;
    test_throw_from_formatter(graph, trap);
    assert(!test_format_fail && strstr(trap->message, "内存不足"));
    /* These marks came from the actual formatter, including an unsnapshotted
     * graph-only child. No test assignment manufactures the mark=2 state. */
    assert(child.heap->mark == 2 && graph.heap->mark == 2);
    assert(!child.heap->roots);
    rn_trap_restore(trap);
    assert(!child.heap->mark && !graph.heap->mark && !ru_scratch);
    test_snapshot(trap); collections = ru_collections;
    text = v_to_string(graph);
    assert(ru_collections == collections); /* retry BEFORE any GC repair */
    assert(text.s->len == 260 && !strstr(text.s->data, "循环"));
    assert(!strncmp(text.s->data, "[[", 2) && !strcmp(text.s->data + 258, "]]"));
    assert(!memcmp(text.s->data + 2, long_text, 256));
    v_drop(text); test_free_trap(trap); v_drop(graph); test_end();
    puts("formatter-oom-retry-before-gc-ok");
''', transform=instrument, extra_c=extra_c)
        self.assertEqual(result.stdout, 'formatter-oom-retry-before-gc-ok\n')
        self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
