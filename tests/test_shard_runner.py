"""Sharding must partition every discovered test exactly once."""
import unittest
from tools.run_test_shard import select_tests


class ShardRunnerTests(unittest.TestCase):
    def test_complete_disjoint_deterministic_partition(self):
        tests = [self.__class__(name) for name in (
            'test_complete_disjoint_deterministic_partition',
            'test_invalid_selection', 'test_duplicate_identities')]
        parts = [select_tests(unittest.TestSuite(tests), index, 3)[1] for index in range(3)]
        self.assertEqual(sorted(test.id() for part in parts for test in part),
                         sorted(test.id() for test in tests))
        self.assertEqual(select_tests(unittest.TestSuite(reversed(tests)), 0, 3)[1], parts[0])

    def test_invalid_selection(self):
        for shard, count in ((0, 0), (-1, 2), (2, 2)):
            with self.subTest(shard=shard, count=count), self.assertRaises(ValueError):
                select_tests(unittest.TestSuite(), shard, count)

    def test_duplicate_identities(self):
        with self.assertRaises(ValueError):
            select_tests(unittest.TestSuite([self, self]), 0, 1)
