"""Cross-environment block reuse requires closed syntax, not just empty effects."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rulang import native_c as n
from rulang.frontend import parse
from rulang.modules import load_module_graph

PATH = str((Path(tempfile.gettempdir()) / 'native_closed_blocks.ru').resolve())


class ClosedPrimitiveBlockTests(unittest.TestCase):
    def plan(self):
        return n.NativeCPlan(load_module_graph(PATH, parse('A 取 0.')))

    def env(self, p, body, site):
        module = p._module_values[PATH].env
        return p._environment(module, 'function', site, body)

    def test_literal_expression_block_reuses_across_fresh_environments(self):
        p = self.plan()
        body = parse("1+2. 非 真. 'a'=='b'.")
        first, second = self.env(p, body, 'first'), self.env(p, body, 'second')
        self.assertEqual(p._block(body, first), [])
        key = ('closed-block', id(body))
        self.assertIn(key, p._expression_summaries)
        before, hits = p._steps, p._block_hits
        self.assertEqual(p._block(body, second), [])
        self.assertEqual(p._steps - before, 1)
        self.assertEqual(p._block_hits - hits, 1)

    def test_idempotent_private_bind_is_not_closed(self):
        p = self.plan()
        module = p._module_values[PATH].env
        module.put('X', n._Type('i32'))
        body = parse("X 取 'bad'.")
        old, fresh = self.env(p, body, 'old'), self.env(p, body, 'fresh')
        old.put('X', 'bad')
        before = p._revision
        p._block(body, old)
        self.assertEqual(p._revision, before)  # Empty change evidence is insufficient.
        self.assertNotIn(('closed-block', id(body)), p._expression_summaries)
        self.assertIsInstance(fresh.get('X'), n._Type)
        p._block(body, fresh)
        self.assertEqual(fresh.values['X'], 'bad')
        self.assertIn('bad', n._alternatives(fresh.get('X')))

    def test_names_returns_calls_and_allocations_never_share(self):
        for source in ('A.', "得 'cdecl'.", '[].', '1 对 2.',
                       "__密 其 类型 'i32'.", "X 取 1."):
            with self.subTest(source=source):
                p = self.plan(); body = parse(source)
                env = self.env(p, body, 'first')
                p._block(body, env); p._block(body, env)
                self.assertNotIn(('closed-block', id(body)), p._expression_summaries)

    def test_environment_reads_keep_their_own_values(self):
        p = self.plan(); body = parse('得 X.')
        a, b = self.env(p, body, 'a'), self.env(p, body, 'b')
        a.put('X', 'cdecl'); b.put('X', 'bad')
        self.assertEqual(p._block(body, a), ['cdecl'])
        self.assertEqual(p._block(body, b), ['bad'])
        self.assertNotIn(('closed-block', id(body)), p._expression_summaries)

    def test_incomplete_proof_does_not_publish_shared_entry(self):
        p = self.plan(); body = parse('1+2.')
        env = self.env(p, body, 'first')
        original = n._SummaryFrame
        class IncompleteFrame(original):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.complete = False
        with patch.object(n, '_SummaryFrame', IncompleteFrame):
            p._block(body, env)
        self.assertNotIn(('closed-block', id(body)), p._expression_summaries)

    def test_shared_entries_use_existing_bounded_lru(self):
        p = self.plan(); bodies = [parse(f'{i}+1.') for i in range(4)]
        with patch.object(n, 'MAX_EXPRESSION_SUMMARIES', 2):
            p._expression_summaries.clear()
            for i, body in enumerate(bodies):
                p._block(body, self.env(p, body, str(i)))
                self.assertLessEqual(len(p._expression_summaries), 2)
        self.assertTrue(any(key[0] == 'closed-block' for key in p._expression_summaries))

    def test_disabled_cache_does_not_publish_shared_entry(self):
        p = self.plan(); body = parse('1+2.')
        with patch.object(n, 'MAX_EXPRESSION_SUMMARIES', 0):
            p._block(body, self.env(p, body, 'first'))
        self.assertNotIn(('closed-block', id(body)), p._expression_summaries)


if __name__ == '__main__':
    unittest.main()
