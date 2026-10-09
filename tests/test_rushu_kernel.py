"""Notebook kernel lifecycle: explicitly spawned workers on every platform."""
from collections import deque
import multiprocessing
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rushu.kernel import (KernelError, MAX_INPUT, MAX_OUTPUT, MAX_OUTPUT_EVENTS,
                          MAX_SOURCE, Session, SessionManager)


def wait_for(session, state="idle", timeout=10, after=0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = session.poll(after)
        if result["state"] == state:
            return result
        if result["state"] == "dead" and state != "dead":
            raise AssertionError("Kernel died: " + repr(result))
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for " + state + ": " + repr(session.poll(after)))


def output(result, stream="stdout"):
    return "".join(event["text"] for event in result["events"]
                   if event["type"] == "output" and event["stream"] == stream)


class KernelTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.addCleanup(self.session.close)

    def run_cell(self, code, cell="cell"):
        after = self.session.snapshot()["cursor"]
        self.session.execute(code, cell)
        return wait_for(self.session, after=after)

    def test_spawn_shared_state_counter_echo_and_separate_notebooks(self):
        self.assertEqual(self.session.process._start_method, "spawn")
        first = self.run_cell("值 取 40. 显 '你好😀'.", "first")
        self.assertEqual(output(first), "你好😀\n")
        self.assertEqual(first["execution_count"], 1)
        second = self.run_cell("值 + 2.", "second")
        self.assertEqual(output(second), "42\n")
        self.assertEqual(second["execution_count"], 2)
        self.assertTrue(all(e["cell_id"] == "second" for e in second["events"]))
        self.assertTrue(all(e["execution_count"] == 2 for e in second["events"]))
        other = Session()
        try:
            other.execute("显 值.", "isolated")
            failed = wait_for(other)
            self.assertEqual(failed["events"][-1]["status"], "error")
            self.assertIn("未定义名称", failed["events"][0]["message"])
        finally:
            other.close()

    def test_procedure_finish_null_and_suppressed_echo(self):
        self.run_cell("作 停: 试 完. 救 因 显 因. 终. 显 9. 为 作 自然: 为")
        self.assertEqual(output(self.run_cell("停. 自然. 回 取 作: 完. 为. 回().")), "")
        self.assertEqual(output(self.run_cell("显 停. 显 自然. 显 回(). 空.")), "空\n" * 4)
        bad = self.run_cell("完.")
        self.assertEqual(bad["events"][-1]["status"], "error")
        self.assertEqual(output(self.run_cell("显 停 == 空.")), "真\n")

    def test_declarations_can_be_reexecuted_and_share_functions(self):
        self.run_cell("算 平方 值 为 数: 得 值*值. 法")
        self.assertEqual(output(self.run_cell("平方 5.")), "25\n")
        self.run_cell("算 平方 值 为 数: 得 值+值. 法")
        self.assertEqual(output(self.run_cell("平方 5.")), "10\n")
        bad = self.run_cell("算 同名: 得 1. 法 算 同名: 得 2. 法")
        self.assertEqual(bad["events"][-1]["status"], "error")

    def test_optional_parameter_types_persist_across_cells(self):
        defined = self.run_cell("算 保留 值: 得 值. 法 "
                                "回 取 算 值, 数值 为 数: 得 值. 法. "
                                "作 输出 值: 显 值. 为")
        self.assertEqual(defined["events"][-1]["status"], "ok")
        self.assertEqual(output(self.run_cell("显 (保留 空). 显 (回 '好' 2). 输出 [1,2].")),
                         "空\n好\n[1, 2]\n")
        bad = self.run_cell("回 空 '错'.")
        self.assertEqual(bad["events"][-1]["status"], "error")
        self.assertEqual(output(self.run_cell("保留 7.")), "7\n")

    def test_input_prompts_empty_line_checked_stream_and_eof(self):
        self.session.execute("甲 取 读 提示:'输入😀：'. 显 甲. 显 (读取 其 读) 其 值. 显 ((读取 其 读) 其 值) == 空.", "input")
        waiting = wait_for(self.session, "waiting_input")
        self.assertEqual(output(waiting), "输入😀：")
        request = waiting["request_id"]
        with self.assertRaises(KernelError):
            self.session.provide_input("stale", "wrong")
        self.session.provide_input(request, "中文")
        waiting = wait_for(self.session, "waiting_input")
        self.assertNotEqual(waiting["request_id"], request)
        self.session.provide_input(waiting["request_id"], "")
        waiting = wait_for(self.session, "waiting_input")
        self.session.provide_input(waiting["request_id"], eof=True)
        result = wait_for(self.session)
        self.assertEqual(output(result), "输入😀：中文\n\n真\n")
        self.assertEqual(result["events"][-1]["status"], "ok")
        # EOF belongs to that execution; the next cell can request input again.
        self.session.execute("显 读.", "next")
        waiting = wait_for(self.session, "waiting_input")
        self.session.provide_input(waiting["request_id"], "新行")
        self.assertTrue(output(wait_for(self.session)).endswith("新行\n"))

    def test_pasted_multiline_input_is_consumed_in_order(self):
        self.session.execute("显 读. 显 读.", "paste")
        waiting = wait_for(self.session, "waiting_input")
        self.session.provide_input(waiting["request_id"], "甲\n乙")
        result = wait_for(self.session)
        self.assertEqual(output(result), "甲\n乙\n")
        self.assertEqual(len([e for e in result["events"] if e["type"] == "input_request"]), 1)

    def test_builtin_stdout_stderr_are_redirected(self):
        result = self.run_cell("显出 其 写 内容:'正常😀'. 错误 其 写 内容:'诊断😀'.")
        self.assertIn("正常😀", output(result))
        self.assertEqual(output(result, "stderr"), "诊断😀")

    def test_runtime_and_syntax_errors_are_local_then_kernel_continues(self):
        result = self.run_cell("值 取 3.\n显 未定义.")
        error = next(e for e in result["events"] if e["type"] == "error")
        self.assertEqual(error["line"], 2)
        self.assertEqual(error["category"], "运行错误")
        self.assertEqual(result["events"][-1]["status"], "error")
        self.assertEqual(output(self.run_cell("值 + 1.")), "4\n")
        result = self.run_cell("显 ).")
        self.assertEqual(result["events"][-1]["status"], "error")
        self.assertEqual(output(self.run_cell("显 7.")), "7\n")

    def test_generation_document_is_not_executed(self):
        result = self.run_cell("显 '不应执行'.\n如是我言")
        self.assertEqual(output(result), "")
        self.assertEqual(result["events"][0]["category"], "生成入口错误")

    def test_busy_session_rejects_concurrent_execution(self):
        self.session.execute("循 环", "infinite")
        with self.assertRaises(KernelError) as caught:
            self.session.execute("显 1.", "competing")
        self.assertEqual(caught.exception.status, 409)

    def test_stop_kills_infinite_loop_and_resets_all_state(self):
        self.run_cell("值 取 42.")
        self.session.execute("循 环", "infinite")
        old_pid = self.session.process.pid
        generation = self.session.generation
        started = time.monotonic()
        snapshot = self.session.reset("stop")
        self.assertLess(time.monotonic() - started, 5)
        self.assertNotEqual(self.session.process.pid, old_pid)
        self.assertEqual(snapshot["state"], "idle")
        self.assertEqual(snapshot["execution_count"], 0)
        self.assertEqual(snapshot["generation"], generation + 1)
        self.assertFalse(any(p.pid == old_pid for p in multiprocessing.active_children()))
        result = self.run_cell("显 值.")
        self.assertEqual(result["events"][-1]["status"], "error")
        self.assertEqual(output(self.run_cell("显 '重新开始'.")), "重新开始\n")

    def test_restart_while_waiting_input_invalidates_old_request(self):
        self.session.execute("显 读 提示:'问'.", "waiting")
        waiting = wait_for(self.session, "waiting_input")
        self.session.reset()
        with self.assertRaises(KernelError):
            self.session.provide_input(waiting["request_id"], "late")
        self.assertEqual(output(self.run_cell("显 9.")), "9\n")

    def test_delayed_execution_cannot_cross_a_session_reset(self):
        old_generation = self.session.generation
        reset = self.session.reset("stop")
        with self.assertRaises(KernelError) as caught:
            self.session.execute("显 '不应执行'.", "delayed", old_generation)
        self.assertEqual(caught.exception.status, 409)
        snapshot = self.session.snapshot()
        self.assertEqual(snapshot["state"], "idle")
        self.assertEqual(snapshot["execution_count"], 0)
        self.assertEqual(snapshot["cursor"], reset["cursor"])
        self.session.execute("显 '新会话'.", "fresh", reset["generation"])
        self.assertEqual(output(wait_for(self.session)), "新会话\n")

    def test_invalid_generation_does_not_consume_execution_counter(self):
        for expected in (True, False, 0, -1, "1", 1.0, []):
            with self.assertRaises(KernelError) as caught:
                self.session.execute("显 1.", "cell", expected)
            self.assertEqual(caught.exception.status, 400)
            self.assertEqual(self.session.snapshot()["execution_count"], 0)

    def test_large_output_is_bounded_and_does_not_deadlock(self):
        # Repeated output exercises both live delivery and silent truncation.
        result = self.run_cell("循 3000 次 显 '甲😀'. 环")
        events = [e for e in result["events"] if e["type"] == "output"]
        self.assertLessEqual(len(events), MAX_OUTPUT_EVENTS + 1)
        self.assertTrue(any(e.get("truncated") for e in events))
        self.assertEqual(result["events"][-1]["status"], "ok")
        self.assertEqual(output(self.run_cell("显 1.")), "1\n")
        result = self.run_cell("字 取 '好'. 循 20 次 字 取 字+字. 环 显 字.")
        text = output(result)
        self.assertEqual(len(text), MAX_OUTPUT)
        self.assertIn("截断", output(result, "stderr"))

    def test_event_history_has_a_character_budget(self):
        for _ in range(5):
            self.run_cell("字 取 '好'. 循 18 次 字 取 字+字. 环 显 字.")
        result = self.session.poll(0)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(sum(len(e.get("text", "")) + len(e.get("message", ""))
                                 for e in result["events"]), 1_048_576)
        self.assertEqual(result["cursor"], result["events"][-1]["seq"])

    def test_input_and_source_validation(self):
        for code in (None, 4, "x" * (MAX_SOURCE + 1)):
            with self.assertRaises(KernelError):
                self.session.execute(code, "cell")
        for cell in (None, "", "x" * 129):
            with self.assertRaises(KernelError):
                self.session.execute("", cell)
        with self.assertRaises(KernelError):
            self.session.provide_input("request", "x" * (MAX_INPUT + 1))
        with self.assertRaises(KernelError):
            self.session.poll(-1)
        with self.assertRaises(KernelError):
            self.session.poll(999)

    def test_trusted_local_imports_keep_notebook_streams(self):
        with tempfile.TemporaryDirectory() as temp:
            module = Path(temp) / "library.ru"
            module.write_text("显 '外言已载入'. 算 问: 得 读 提示:'模块输入：'. 法", encoding="utf-8")
            path = str(module).replace("\\", "\\\\").replace("'", "\\'")
            self.session.execute(f"模 取 外言 '{path}'. 显 模 其 问.", "module")
            waiting = wait_for(self.session, "waiting_input")
            self.assertEqual(output(waiting), "外言已载入\n模块输入：")
            self.session.provide_input(waiting["request_id"], "回声")
            self.assertTrue(output(wait_for(self.session)).endswith("回声\n"))

    def test_contest_read_all_waits_for_eof_and_keeps_all_input(self):
        source = (ROOT / "examples" / "contest_sum_eof.ru").read_text(encoding="utf-8")
        self.session.execute(source, "contest")
        waiting = wait_for(self.session, "waiting_input")
        self.session.provide_input(waiting["request_id"], "1 2\n3 4")
        waiting = wait_for(self.session, "waiting_input")
        self.assertEqual(output(waiting), "")
        self.session.provide_input(waiting["request_id"], "5 6")
        waiting = wait_for(self.session, "waiting_input")
        self.session.provide_input(waiting["request_id"], eof=True)
        result = wait_for(self.session)
        self.assertEqual(output(result), "3\n7\n11\n")
        self.assertEqual(result["events"][-1]["status"], "ok")

    def test_unexpected_worker_exit_is_visible_and_restartable(self):
        self.session.process.terminate()
        wait_for(self.session, "dead")
        with self.assertRaises(KernelError):
            self.session.execute("显 2.", "cell")
        self.session.reset()
        self.assertEqual(output(self.run_cell("显 2.")), "2\n")

    def test_repeated_reset_and_startup_death_preserve_replacement_events(self):
        # Reuse OS handles repeatedly while prior collectors are shutting down.
        # This catches close/recv races that a single restart rarely exposes.
        for iteration in range(24):
            with self.subTest(iteration=iteration):
                self.session.reset("stop" if iteration % 2 else "restart")
                if iteration % 4 == 0:
                    self.session.process.terminate()
                    wait_for(self.session, "dead")
                    self.session.reset()
                if iteration % 5 == 0:
                    result = self.run_cell("循 3000 次 显 '好'. 环")
                    self.assertEqual(result["events"][-1]["status"], "ok")
                    self.assertTrue(any(event.get("truncated") for event in result["events"]))
                else:
                    result = self.run_cell("显 " + str(iteration) + ".")
                    self.assertEqual(output(result), str(iteration) + "\n")
                    self.assertEqual(result["events"][-1]["status"], "ok")
                self.assertEqual(self.session.snapshot()["state"], "idle")


class SessionManagerTests(unittest.TestCase):
    def test_limit_delete_and_server_cleanup(self):
        manager = SessionManager(limit=2)
        self.addCleanup(manager.close)
        first, second = manager.create(), manager.create()
        pids = {first.process.pid, second.process.pid}
        with self.assertRaises(KernelError) as caught:
            manager.create()
        self.assertEqual(caught.exception.status, 429)
        manager.delete(first.id)
        with self.assertRaises(KernelError):
            manager.get(first.id)
        with self.assertRaises(KernelError):
            first.snapshot()
        manager.close()
        manager.close()
        self.assertFalse(pids & {p.pid for p in multiprocessing.active_children()})
        with self.assertRaises(KernelError):
            manager.create()


class InputAdapterTests(unittest.TestCase):
    def test_zero_sized_and_mixed_reads_preserve_pending_text(self):
        from rushu.kernel import _Input

        class Connection:
            def __init__(self):
                self.requests = []
                self.replies = iter([{"text": "甲\n乙"}, {"text": "丙"}, {"eof": True}])

            def send(self, event):
                self.requests.append(event)

            def recv(self):
                return dict(next(self.replies), kind="input", request_id=self.requests[-1]["request_id"])

        connection = Connection()
        stream = _Input(connection)
        self.assertEqual(stream.read(0), "")
        self.assertEqual(stream.readline(0), "")
        self.assertEqual(connection.requests, [])
        self.assertEqual(stream.read(1), "甲")
        self.assertEqual(stream.readline(), "\n")
        self.assertEqual(stream.read(3), "乙\n丙")
        self.assertEqual(stream.read(), "\n")
        self.assertEqual(stream.readline(), "")
        self.assertEqual(len(connection.requests), 3)


class CollectorExitTests(unittest.TestCase):
    def collect_after_exit(self, events, generation=1):
        # A readable sentinel plus an intentionally still-open writer simulates
        # Windows terminating a worker before its spawn bootstrap duplicates
        # and releases the pipe handle. recv() alone would wait forever here.
        context = multiprocessing.get_context("spawn")
        receiver, writer = context.Pipe(duplex=False)
        sentinel, signal_exit = context.Pipe(duplex=False)
        for connection in (receiver, writer, sentinel, signal_exit):
            self.addCleanup(connection.close)
        session = Session.__new__(Session)
        session.lock = threading.RLock()
        session.events = deque()
        session.event_text = session.cursor = 0
        session.execution_count = 1
        session.generation = generation
        session.state = "running"
        session.cell_id = "before-exit"
        session.request_id = None
        session.closed = False
        for event in events:
            writer.send(event)
        signal_exit.send("exited")
        collector = threading.Thread(target=session._collect,
            args=(receiver, sentinel, 1), daemon=True)
        collector.start()
        collector.join(timeout=5)
        self.assertFalse(collector.is_alive(), "collector waited for EOF after process exit")
        return session

    def test_process_sentinel_reports_death_without_pipe_eof(self):
        session = self.collect_after_exit([])
        self.assertEqual(session.state, "dead")
        self.assertEqual([event["type"] for event in session.events], ["error", "done"])
        self.assertEqual(session.events[-1]["status"], "error")

    def test_process_exit_drains_already_buffered_output_in_order(self):
        session = self.collect_after_exit([
            {"type": "output", "stream": "stdout", "text": "最后输出\n"},
            {"type": "done", "status": "ok"},
        ])
        self.assertEqual(session.state, "dead")
        self.assertEqual([event["type"] for event in session.events],
                         ["output", "done", "error", "done"])
        self.assertEqual(session.events[0]["text"], "最后输出\n")
        self.assertEqual(session.events[1]["status"], "ok")

    def test_old_process_exit_cannot_mark_replacement_dead(self):
        session = self.collect_after_exit([], generation=2)
        self.assertEqual(session.state, "running")
        self.assertEqual(list(session.events), [])


if __name__ == "__main__":
    unittest.main()
