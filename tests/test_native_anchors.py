"""Guard native integration anchors against C header drift.

``integrate_runtime`` and ``integrate_io`` rewrite the portable C headers with
dozens of source-level anchors, each asserted to match exactly once.  A
formatting-only change to ``runtime.h`` or ``io_runtime.h`` (a space, a
comment) then breaks the native build at source-integration time with a
``ValueError`` far from the offending edit.  These tests verify every literal
anchor against the on-disk header so drift surfaces as a pinpoint failure
here, next to the change that caused it.
"""
import ast
import inspect
from pathlib import Path
import unittest

from rulang import native_c_runtime

HEADER_NAMES = {
    "integrate_runtime": "runtime.h",
    "integrate_io": "io_runtime.h",
}


def _collect_anchors(function_name):
    """Return (anchor, expected_count) pairs for every literal anchor.

    Covers direct string arguments to ``_replace``, anchors stored in a
    local variable (e.g. ``marker``), tuple pairs in ``for old, new in
    (...)`` loops, and ``source.index(...)`` anchors.  Anything dynamically
    constructed is counted as skipped so the totals stay honest.
    """
    tree = ast.parse(inspect.getsource(native_c_runtime))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    local_strings = {}
    for node in ast.walk(function):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            local_strings[node.targets[0].id] = node.value.value
    loop_targets = set()
    for node in ast.walk(function):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple):
            for name in node.target.elts:
                if isinstance(name, ast.Name):
                    loop_targets.add(name.id)
    anchors = []
    skipped = 0
    for node in ast.walk(function):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id == "_replace":
            if len(node.args) < 2:
                skipped += 1
                continue
            first = node.args[1]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                text = first.value
            elif isinstance(first, ast.Name) and first.id in local_strings:
                text = local_strings[first.id]
            elif isinstance(first, ast.Name) and first.id in loop_targets:
                # Covered by the tuple-pair extraction below.
                continue
            else:
                skipped += 1
                continue
            expected = 1
            for keyword in node.keywords:
                if keyword.arg == "count" and isinstance(keyword.value, ast.Constant):
                    expected = keyword.value.value
            anchors.append((text, expected))
    for node in ast.walk(function):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "index" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            continue
        anchors.append((node.args[0].value, 1))
    for node in ast.walk(function):
        if not (isinstance(node, ast.For) and isinstance(node.target, ast.Tuple)
                and isinstance(node.iter, (ast.Tuple, ast.List))):
            continue
        replaces = [child for child in ast.walk(node)
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                    and child.func.id == "_replace"]
        if not replaces:
            continue
        for item in node.iter.elts:
            if (isinstance(item, ast.Tuple) and item.elts
                    and isinstance(item.elts[0], ast.Constant)
                    and isinstance(item.elts[0].value, str)):
                anchors.append((item.elts[0].value, 1))
    return anchors, skipped


class NativeAnchorTests(unittest.TestCase):
    def _check(self, function_name, minimum):
        header_path = Path(native_c_runtime.__file__).parent / HEADER_NAMES[function_name]
        header = header_path.read_text(encoding="utf-8")
        anchors, skipped = _collect_anchors(function_name)
        self.assertGreaterEqual(len(anchors), minimum)
        for anchor, expected in anchors:
            with self.subTest(header=header_path.name, anchor=anchor[:72]):
                self.assertEqual(
                    header.count(anchor), expected,
                    f"anchor appears {header.count(anchor)}× in {header_path.name} "
                    f"(expected {expected}); the C header drifted from "
                    f"{function_name}",
                )
        return anchors, skipped

    def test_integrate_runtime_anchors_match_runtime_h(self):
        anchors, skipped = self._check("integrate_runtime", minimum=40)
        self.assertEqual(skipped, 0, "anchors dynamically built and unchecked")

    def test_integrate_io_anchors_match_io_runtime_h(self):
        self._check("integrate_io", minimum=5)


if __name__ == "__main__":
    unittest.main()
