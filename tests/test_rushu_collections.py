"""Collection methods preserve notebook state across actual spawned cells."""
import unittest
from rushu.kernel import Session
from test_rushu_kernel import wait_for, output


class NotebookCollectionTests(unittest.TestCase):
    def test_cross_cell_snapshot_mapping_sort_and_migration(self):
        session = Session()
        self.addCleanup(session.close)

        def run(source):
            after = session.snapshot()['cursor']
            session.execute(source, 'collections')
            return wait_for(session, after=after)

        defined = run("原 取 [3,1,2]. 算 平方 项: 得 项 * 项. 法")
        self.assertEqual(defined['events'][-1]['status'], 'ok')
        result = run("显 原 其 排序. 显 原 其 另成 算 平方. 显 原.")
        self.assertEqual(output(result), '[1, 2, 3]\n[9, 1, 4]\n[3, 1, 2]\n')
        result = run("原 其 逐位 作 位 项: 显 位 对 项. 原 其 弹. 完. 为. 显 原.")
        self.assertEqual(output(result), '(0 对 3)\n(1 对 1)\n(2 对 2)\n空\n[]\n')
        result = run("表 取 {'甲':7}. 表 其 逐目 作 目 相: 显 目 对 相. 为.")
        self.assertEqual(output(result), '(甲 对 7)\n空\n')
        result = run("表 其 列 作 目 相: 完. 为.")
        self.assertEqual(result['events'][-1]['status'], 'error')
        self.assertTrue(any('已改名为「逐目」' in event.get('message', '') for event in result['events']))
        self.assertEqual(output(run('显 表 其 量.')), '1\n')
