"""Immutable string metadata, Unicode semantics and monotonic offset regression."""
import io
import random
import tempfile
import unittest

from test_runtime_pruning import CC, build, generate, run
from rulang.frontend import parse
from rulang.interpreter import Interpreter


def quote(text):
    return "'" + text.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') + "'"


@unittest.skipUnless(CC, 'C compiler unavailable')
class StringCursorTests(unittest.TestCase):
    def check_program(self, source, expected):
        output = io.StringIO()
        Interpreter(io.StringIO(), output).execute(parse(source))
        self.assertEqual(output.getvalue(), expected)
        with tempfile.TemporaryDirectory() as directory:
            for full in (False, True):
                with self.subTest(full=full):
                    result = run(build(generate(source, full=full), directory, 'strings'))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected)
                    self.assertIn('RU_GC live=0 ', result.stderr)

    def test_unicode_forward_reverse_and_shared_alias(self):
        text = 'a甲😀e\u0301é\U0010ffff乙'
        source = f'文 取 {quote(text)}. 别 取 文. 显 文 其 量.\n'
        expected = str(len(text))+'\n'
        for i in [*range(len(text)), *reversed(range(len(text))), 0, 5, 1, 6]:
            source += f'显 别[{i}]. 显 文[{i}:{i+1}].\n'
            expected += (text[i]+'\n')*2
        for a, b in [(0, 0), (len(text), len(text)), (0, len(text)), (1, 6), (2, 2), (0, 3)]:
            source += f'显 文[{a}:{b}].\n'
            expected += text[a:b]+'\n'
        source += "显 文 == 别. 显 文[:]. 显 文 其 量.\n"
        expected += '真\n'+text+'\n'+str(len(text))+'\n'
        self.check_program(source, expected)

    def test_random_unicode_slices_and_independent_outputs(self):
        rng = random.Random(8675309)
        alphabet = ['a', '甲', '😀', '\u0301', 'é', '\u007f', '\u0080', '\u07ff', '\u0800', '\uffff', '\U0010ffff']
        text = ''.join(rng.choice(alphabet) for _ in range(600))
        source = f'文 取 {quote(text)}.\n'
        expected = ''
        for _ in range(100):
            a, b = sorted([rng.randrange(len(text)+1), rng.randrange(len(text)+1)])
            source += f'片 取 文[{a}:{b}]. 显 片. 显 片 其 量.\n'
            expected += text[a:b]+'\n'+str(b-a)+'\n'
        self.check_program(source, expected)

    def test_concatenation_and_empty_strings(self):
        self.check_program("""
左 取 '甲😀'. 右 取 'é乙'.
显 左 其 量. 显 左[1]. 显 右 其 量.
合 取 左 + 右. 显 合 其 量. 显 合[1:3]. 显 左[0].
显 '' 其 量. 显 ''[:]. 显 合[4:].
显 'ascii'[1:4]. 显 'ascii'[4].
""", '2\n😀\n2\n4\n😀é\n甲\n0\n\n\nsci\ni\n')

    def test_threshold_unicode_concat_and_short_long_results(self):
        source, expected = '', ''
        for byte_length in (1023, 1024, 1025):
            text = '甲😀éa'*102 + 'a'*(byte_length-1020)
            self.assertEqual(len(text.encode('utf-8')), byte_length)
            source += f'文 取 {quote(text)}. 别 取 文. 显 文 其 量. 显 别[{len(text)-1}].\n'
            expected += str(len(text))+'\na\n'
            for a, b in [(0, 3), (0, len(text)), (1, len(text)), (0, len(text)-1)]:
                source += f'片 取 文[{a}:{b}]. 显 片. 显 片 其 量.\n'
                expected += text[a:b]+'\n'+str(b-a)+'\n'
            source += f"合 取 'x' + 文. 显 合 其 量. 显 合[1:]. 显 文 == 别.\n"
            expected += str(len(text)+1)+'\n'+text+'\n真\n'
        self.check_program(source, expected)

    def test_cache_feature_follows_conservative_reachability(self):
        # Footer caching is a source-size/performance tradeoff: pruned products
        # only opt in when a slice implementation can actually be reached.
        for source in ("显 '甲😀'.", "显 '甲😀' 其 量.", "显 '甲😀'[0].",
                       "算 查 值: 得 值 其 量. 法. 显 查 '甲😀'.",
                       "算 查 值: 得 值 其 位 1. 法. 显 查 '甲😀'."):
            with self.subTest(source=source):
                self.assertNotIn('RuStringIndex', generate(source))
                self.assertIn('RuStringIndex', generate(source, full=True))
        for source in ("显 '甲😀'[:].",
                       "算 查 值: 得 值 其 段 始:0 终:1. 法. 显 查 '甲😀'.",
                       "文 取 '甲😀'. 显 文[0]. 显 文[:]. 显 文 其 量."):
            with self.subTest(source=source):
                for full in (False, True):
                    generated = generate(source, full=full)
                    self.assertIn('RuStringIndex', generated)
                    self.assertIn('ru_string_index_write', generated)
                    self.assertIn('ru_string_index_read', generated)

    def test_bounds_are_checked_after_cache_warmup(self):
        for suffix, diagnostic in [("显 文[3].", "索引越界"),
                                   ("显 文[0:4].", "索引越界"),
                                   ("显 文[2:1].", "切片开始不能大于结束"),
                                   ("显 文[-1].", "索引须为非负整数")]:
            source = "文 取 '甲😀a'. 文 其 量. 文[1:3]. " + suffix
            with tempfile.TemporaryDirectory() as directory:
                for full in (False, True):
                    with self.subTest(suffix=suffix, full=full):
                        result = run(build(generate(source, full=full), directory, 'bounds'))
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(diagnostic, result.stderr)
                        self.assertIn('RU_GC live=0 ', result.stderr)

    def test_footer_allocation_overflow_fails_before_allocating(self):
        generated = generate("显 '甲😀' 其 量.", full=True)
        generated = generated.replace('int main(int argc, char **argv)', 'int ru_original_main(int argc, char **argv)')
        for expression in ('SIZE_MAX', 'SIZE_MAX-sizeof(RuString)-sizeof(RuStringIndex)'):
            probe = generated + '\nint main(void) { volatile size_t n = '+expression+'; (void)ru_string_allocation_size(n,7); return 2; }\n'
            with tempfile.TemporaryDirectory() as directory:
                result = run(build(probe, directory, 'overflow'))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('字符串过长', result.stderr)

    def test_cursor_metadata_progress_and_lazy_construction(self):
        # Deterministic mechanism assertion, not a machine-dependent timing gate.
        # The buffer is filled after allocation, just like concat/IO constructors.
        generated = generate("显 '甲😀a'[0:2] 其 量.", full=True)
        generated = generated.replace('int main(int argc, char **argv)', 'int ru_original_main(int argc, char **argv)')
        generated += r'''
int main(void) {
    size_t i, len;
    Val v = ru_string_alloc(1024, 1), alias, part;
    RuStringIndex index;
    for (i = 0; i < 128; ++i)
        memcpy(v.s->data+i*8, "\xe7\x94\xb2\xf0\x9f\x98\x80" "a", 8);
    if (ru_string_index_read(v).chars != SIZE_MAX) return 1;
    alias = v_copy(v);
    if (ru_utf8_len(v) != 384 || ru_string_index_read(v).chars != 384) return 2;
    if (ru_utf8_offset(alias, 1) != 3) return 3;
    index = ru_string_index_read(v);
    if (index.cursor_char != 1 || index.cursor_byte != 3) return 4;
    if (ru_utf8_offset(v, 2) != 7 || ru_utf8_offset(v, 384) != 1024) return 5;
    index = ru_string_index_read(v);
    if (index.cursor_char != 384 || index.cursor_byte != 1024) return 6;
    if (ru_utf8_offset(v, 0) != 0) return 7;
    index = ru_string_index_read(v);
    if (index.cursor_char != 0 || index.cursor_byte != 0) return 8;
    part = v_slice(v, v_num(1), v_num(2), 1);
    if (ru_utf8_len(part) != 1 || part.s->len != 4 || ru_string_index_read(v).chars != 384) return 9;
    v_drop(part); v_drop(alias); v_drop(v); ru_gc();
    /* Exercise unaligned footer locations and both sides of the threshold. */
    for (len = 1020; len < 1040; ++len) {
        size_t bytes = sizeof(RuString)+len+1;
        v = ru_string_alloc(len, 1);
        memset(v.s->data, 'a', len);
        if (len >= RU_STRING_INDEX_MIN_BYTES) bytes += sizeof(RuStringIndex);
        if (ru_string_allocation_size(len, 1) != bytes) return 10;
        if (ru_utf8_len(v) != len || ru_utf8_offset(v, len-1) != len-1) return 11;
        if (v.s->data[len] != 0) return 12;
        v_drop(v); ru_gc();
    }
    if (ru_string_allocation_size(1, 1) != sizeof(RuString)+2) return 13;
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            result = run(build(generated, directory, 'metadata'))
            self.assertEqual(result.returncode, 0, result.stderr)
