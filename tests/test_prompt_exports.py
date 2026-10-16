"""Offline prompt export and non-destructive publication contracts."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.cli import main
from rulang.frontend import RuError
from rulang.generation import GenerationConfig, generation_system_prompt, request_response
from rulang.prompts import export_prompt


class PromptExportTests(unittest.TestCase):
    def test_notebook_request_and_export_match_exactly(self):
        response = io.BytesIO(json.dumps({"status": "completed", "output_text": "显 '好'."}).encode())
        response.status = 200
        with patch("rulang.generation.urlrequest.build_opener") as build:
            build.return_value.open.return_value = response
            request_response(GenerationConfig("test-export-dummy", "https://example.invalid/v1", "test"),
                             "画图", runtime_target="rushu")
            request = build.return_value.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["input"][0]["content"][0]["text"], export_prompt("rushu"))

    def test_browser_exports_match_builder_and_mock_request(self):
        for target in ("rushu", "ruguan"):
            text = export_prompt(target, runtime_target="browser-js")
            self.assertEqual(text, generation_system_prompt(target + "-browser-js"))
            self.assertIn("本次运行环境：如书显式 JS", text)
            self.assertEqual("本次任务聚焦如观" in text, target == "ruguan")
            raw = (ROOT / "rulang/language-spec.md").read_bytes()
            self.assertEqual(text.count(raw.decode()), 1)
            self.assertIn(hashlib.sha256(raw).hexdigest(), text)
            response = io.BytesIO(json.dumps({"status": "completed", "output_text": "显 42."}).encode())
            response.status = 200
            with patch("rulang.generation.urlrequest.build_opener") as build:
                build.return_value.open.return_value = response
                request_response(GenerationConfig("test-export-dummy", "https://example.invalid/v1", "test"),
                                 "画图", runtime_target=target + "-browser-js")
            payload = json.loads(build.return_value.open.call_args.args[0].data)
            self.assertEqual(payload["input"][0]["content"][0]["text"], text)

    def test_cli_explicit_targets_and_invalid_target(self):
        for command in ("rushu-prompt", "ruguan-prompt"):
            for target in ("python", "browser-js"):
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(main([command, "--target", target]), 0)
                self.assertEqual(stdout.getvalue(), export_prompt(command[:-7], runtime_target=target))
                self.assertEqual(stderr.getvalue(), "")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main([command, "--target", "js"])
            self.assertEqual(caught.exception.code, 2)
        for target in (None, [], {}, "js", True):
            with self.assertRaises(RuError):
                export_prompt(runtime_target=target)

    def test_complete_specification_once_and_current_hash(self):
        raw = (ROOT / "rulang/language-spec.md").read_bytes()
        for target in ("rushu", "ruguan"):
            with self.subTest(target=target):
                text = export_prompt(target)
                self.assertEqual(text.count(raw.decode()), 1)
                self.assertEqual(text.count("<ru-language-spec>"), 1)
                self.assertIn(hashlib.sha256(raw).hexdigest(), text)
                self.assertIn("如书 Python 代码格", text)
                self.assertIn("正弦 弧度", text)
                self.assertIn("造源", text)
        self.assertNotEqual(export_prompt("rushu"), export_prompt("ruguan"))
        self.assertIn("本次任务聚焦如观", export_prompt("ruguan"))

    def test_graphics_upgrade_contract_is_shared_by_both_exports_and_backends(self):
        raw = (ROOT / "rulang/language-spec.md").read_bytes()
        for target in ("rushu", "ruguan"):
            for backend in ("python", "browser-js"):
                with self.subTest(target=target, backend=backend):
                    prompt = export_prompt(target, runtime_target=backend)
                    self.assertEqual(prompt.count(raw.decode()), 1)
                    self.assertIn(hashlib.sha256(raw).hexdigest(), prompt)
                    for member in ("三角形 横一 纵一 横二 纵二 横三 纵三", "多边形 点阵",
                                   "平移 横 纵", "旋转 弧度", "缩放 横倍率 纵倍率",
                                   "图 其 保存", "图 其 恢复", "变换 a b c d e f",
                                   "重置变换", "裁剪 横 纵 宽 高", "取消裁剪"):
                        self.assertIn(member, prompt)
                    for contract in ("右乘", "nonzero", "3～256", "64 层", "32 个",
                                     "256 KiB", "画布坐标", "不会自动恢复", "保存栈必须配平"):
                        self.assertIn(contract, prompt)

    def test_alpha_color_contract_is_shared_by_both_exports_and_targets(self):
        raw = (ROOT / "rulang/language-spec.md").read_bytes()
        for target in ("rushu", "ruguan"):
            for backend in ("python", "browser-js"):
                with self.subTest(target=target, backend=backend):
                    prompt = export_prompt(target, runtime_target=backend)
                    self.assertEqual(prompt.count(raw.decode()), 1)
                    self.assertIn(hashlib.sha256(raw).hexdigest(), prompt)
                    for contract in ("#RRGGBB", "#RRGGBBAA", "颜色 红 绿 蓝 不透明度",
                                     "四个参数均必需", "0～255 的有限整数", "#rrggbbaa",
                                     "不钳位、不舍入", "不是画布成员", "不是新增保留字",
                                     "填色 空", "描边 空", "不保留上一帧像素",
                                     "透明底上完整重绘", "半透明背景拖尾"):
                        self.assertIn(contract, prompt)
                    self.assertNotIn("颜色只接受 `#RRGGBB`，", prompt)

    def test_all_generation_targets_share_canonical_standard_imports(self):
        raw = (ROOT / "rulang/language-spec.md").read_text(encoding="utf-8")
        for target in ("cli", "rushu", "ruguan", "rushu-browser-js", "ruguan-browser-js"):
            with self.subTest(target=target):
                prompt = generation_system_prompt(target)
                self.assertEqual(prompt.count(raw), 1)
                self.assertIn("外言 '如:观'", prompt)
                self.assertIn("外言 '如:竞'", prompt)
                self.assertNotIn("外言 '如观'", prompt)
                self.assertNotIn("外言 '如竞'", prompt)
                self.assertIn("不保留兼容别名", prompt)

    def test_native_library_knowledge_does_not_grant_generation_capability(self):
        raw = (ROOT / "rulang/language-spec.md").read_bytes()
        for target in ("cli", "rushu", "ruguan", "rushu-browser-js", "ruguan-browser-js"):
            with self.subTest(target=target):
                prompt = generation_system_prompt(target)
                self.assertEqual(prompt.count(raw.decode()), 1)
                self.assertIn(hashlib.sha256(raw).hexdigest(), prompt)
                guidance = prompt.split("<ru-language-spec>", 1)[0]
                for rule in ("如:密是标准原生库", "如见是随附三方 GUI 库、当前只有 Win32 驱动",
                             "Windows x64 C 原生后端只接受有限静态签名",
                             "独立产物不需要 Python 或 libffi",
                             "生成器不得自动启用 --allow-native",
                             "不得用 generate --run 执行原生程序",
                             "不得生成依赖原生调用的程序"):
                    self.assertIn(rule, guidance)
                for contract in ("ru check --target python", "后端／宿主权限边界",
                                 "默认 `check` 仍为 C", "不是沙箱", "同位宽整数／指针",
                                 "不执行模块顶层、不加载 DLL、不调用原生函数",
                                 "ru check --target c --allow-native",
                                 "C 原生回调内不能首次初始化外言",
                                 "独立目录中的随附三方 Win32 库入口"):
                    self.assertIn(contract, prompt)
                if target in ("rushu", "ruguan"):
                    self.assertIn("如书 Python 也不能启用如:密或如见", guidance)

    def test_grouping_and_build_path_mapping_are_reference_knowledge(self):
        for target in ('rushu', 'ruguan', 'rushu-browser-js', 'ruguan-browser-js'):
            with self.subTest(target=target):
                prompt = generation_system_prompt(target)
                self.assertIn("[(表 其 查 '键'), 值]", prompt)
                self.assertIn('--source-prefix-map OLD=NEW', prompt)
                self.assertIn('不是普通生成所必需', prompt)
                self.assertNotIn('--source-prefix-map', prompt.split('<ru-language-spec>', 1)[0])

    def test_generation_targets_include_collection_interfaces(self):
        for target in ("cli", "rushu", "ruguan", "rushu-browser-js", "ruguan-browser-js"):
            with self.subTest(target=target):
                prompt = generation_system_prompt(target)
                for name in ("排序", "先于", "另成", "逐位", "逐目"):
                    self.assertIn(name, prompt)
                self.assertNotIn("逐得", prompt)

    def test_all_generation_targets_teach_array_sort_and_transform(self):
        for target in ("cli", "rushu", "ruguan", "rushu-browser-js", "ruguan-browser-js"):
            with self.subTest(target=target):
                prompt = generation_system_prompt(target)
                for term in ("阵 其 排序", "阵 其 另成 算法:回调", "恰有两个参数的算",
                             "恰有一个参数的算", "精确的事实", "Unicode 码点",
                             "同一个形身份", "不深复制", "不筛选、不展开",
                             "不接受 `作`", "旧 `排序 列 比较` 接口不变",
                             "阵 其 逐位 回调:", "典 其 逐目 回调:", "目录的 `其 列` 不变",
                             "不能用 `破` 跳出回调外的遍历", "忽略回调返回值，包括假与空"):
                    self.assertIn(term, prompt)


    def test_browser_and_default_python_targets_are_distinct(self):
        browser = generation_system_prompt("rushu-browser-js")
        python = generation_system_prompt("rushu")
        cli = generation_system_prompt("cli")
        self.assertIn("独立浏览器 Worker", browser)
        self.assertIn("1～60 FPS", browser)
        self.assertIn("不读取或共享 Python 会话", browser)
        self.assertIn("无可强制的 64 MiB", browser)
        self.assertIn("Python 代码格（默认）", python)
        self.assertIn("不要使用浏览器 JS 专属", python)
        self.assertIn("不得生成依赖如观", cli)

    def test_export_never_loads_config_or_network(self):
        with patch("rulang.generation.load_config", side_effect=AssertionError("config read")), \
             patch("rulang.generation.urlrequest.build_opener", side_effect=AssertionError("network")), \
             patch("rulang.generation.request_response", side_effect=AssertionError("provider")):
            for target in ("rushu", "ruguan"):
                for runtime in ("python", "browser-js"):
                    expected = target if runtime == "python" else target + "-browser-js"
                    self.assertEqual(export_prompt(target, runtime_target=runtime), generation_system_prompt(expected))

    def test_cli_stdout_is_exact_and_stderr_empty(self):
        for command in ("rushu-prompt", "ruguan-prompt"):
            for args in ([], ["-o", "-"]):
                with self.subTest(command=command, args=args):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        self.assertEqual(main([command, *args]), 0)
                    self.assertEqual(stdout.getvalue(), export_prompt(command[:-7]))
                    self.assertEqual(stderr.getvalue(), "")

    def test_subprocess_utf8_ignores_locale_and_bad_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".ru-lang.json").write_text("bad config", encoding="utf-8")
            env = {**os.environ, "HOME": directory, "USERPROFILE": directory,
                   "RU_LLM_API_KEY_FILE": str(Path(directory, "absent-secret")),
                   "PYTHONIOENCODING": "ascii", "PYTHONUTF8": "0", "LC_ALL": "C"}
            result = subprocess.run([sys.executable, str(ROOT / "ru"), "rushu-prompt"],
                                    cwd=directory, env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, export_prompt("rushu").encode("utf-8"))
            self.assertEqual(result.stderr, b"")

    def test_file_output_is_exact_and_cli_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            for target in ("rushu", "ruguan"):
                output = Path(directory, target + " 提示.txt")
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(main([target + "-prompt", "--output", str(output)]), 0)
                self.assertEqual(output.read_bytes(), export_prompt(target).encode())
                self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")
                self.assertEqual(list(Path(directory).glob(".ru-prompt-*")), [])

    def test_existing_file_needs_force(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "prompt.txt")
            output.write_text("original")
            with self.assertRaises(RuError):
                export_prompt("rushu", output)
            self.assertEqual(output.read_text(), "original")
            # Temporary paths may use aliases such as Windows 8.3 short names.
            self.assertEqual(export_prompt("ruguan", output, force=True), output.resolve())
            self.assertEqual(output.read_text(), export_prompt("ruguan"))

    def test_force_accepts_new_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "prompt")
            export_prompt("rushu", output, force=True)
            self.assertEqual(output.read_text(), export_prompt("rushu"))

    def test_force_rejects_stdout(self):
        for output in (None, "-"):
            with self.assertRaises(RuError):
                export_prompt("rushu", output, force=True)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(["rushu-prompt", "--force"])
        self.assertEqual(error.exception.code, 2)

    def test_invalid_target(self):
        with self.assertRaises(RuError):
            export_prompt("invalid")

    def test_specification_and_hardlink_protected(self):
        specification = ROOT / "rulang/language-spec.md"
        before = specification.read_bytes()
        with self.assertRaises(RuError):
            export_prompt("rushu", specification, force=True)
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            alias = Path(directory, "alias.txt")
            os.link(specification, alias)
            with self.assertRaises(RuError):
                export_prompt("ruguan", alias, force=True)
            self.assertEqual(alias.read_bytes(), before)
        self.assertEqual(specification.read_bytes(), before)

    def test_symlink_directory_and_fifo_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "original"
            target.write_text("original")
            paths = [root / "link", root / "broken", root / "folder"]
            try:
                paths[0].symlink_to(target)
                paths[1].symlink_to(root / "absent")
            except (OSError, NotImplementedError):
                paths = [paths[-1]]
            paths[-1].mkdir()
            if hasattr(os, "mkfifo"):
                fifo = root / "fifo"
                os.mkfifo(fifo)
                paths.append(fifo)
            for path in paths:
                for force in (False, True):
                    with self.subTest(path=path, force=force), self.assertRaises(RuError):
                        export_prompt("rushu", path, force=force)
            self.assertEqual(target.read_text(), "original")

    def test_fsync_and_replace_failure_preserve_original_and_cleanup(self):
        for operation in ("fsync", "replace"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                output = Path(directory, "prompt.txt")
                output.write_text("original")
                with patch("rulang.prompts.os." + operation, side_effect=OSError("private detail")), self.assertRaises(RuError) as error:
                    export_prompt("rushu", output, force=True)
                self.assertNotIn("private detail", str(error.exception))
                self.assertEqual(output.read_text(), "original")
                self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_no_force_race_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "prompt.txt")
            link = os.link
            def race(source, destination):
                output.write_text("concurrent writer")
                return link(source, destination)
            with patch("rulang.prompts.os.link", side_effect=race), self.assertRaises(RuError):
                export_prompt("rushu", output)
            self.assertEqual(output.read_text(), "concurrent writer")
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_force_rechecks_destination_after_temporary_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "prompt.txt"
            original = root / "original.txt"
            original.write_text("keep")
            def replace_with_link(_descriptor):
                try:
                    output.symlink_to(original)
                except (OSError, NotImplementedError):
                    self.skipTest("symlink creation unavailable")
            with patch("rulang.prompts.os.fsync", side_effect=replace_with_link), self.assertRaises(RuError):
                export_prompt("rushu", output, force=True)
            self.assertTrue(output.is_symlink())
            self.assertEqual(original.read_text(), "keep")
            self.assertEqual(list(root.glob(".ru-prompt-*")), [])

    def test_missing_directory_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(main(["ruguan-prompt", "-o", str(Path(directory, "absent/prompt.txt"))]), 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("提示导出错误", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_invalid_specification_never_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "prompt.txt")
            output.write_text("original")
            with patch("rulang.generation.resources.files") as resources:
                resources.return_value.joinpath.return_value.open.return_value = io.BytesIO(b"bad spec")
                with self.assertRaises(RuError):
                    export_prompt("rushu", output, force=True)
            self.assertEqual(output.read_text(), "original")
            self.assertEqual(list(Path(directory).iterdir()), [output])


if __name__ == "__main__":
    unittest.main()
