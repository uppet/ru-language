#!/usr/bin/env python3
"""Run real-browser QA against a local server using the native Ru interpreter.

Requires Playwright in NODE_PATH and an explicitly supplied browser executable.
The server and every native session are closed even when browser QA fails.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rushu.server import make_server
from rushu.native_kernel import NativeProcess


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--browser', required=True)
    parser.add_argument('--node', default='node')
    parser.add_argument('--artifacts', type=Path)
    args = parser.parse_args(argv)
    directory = args.artifacts or Path(tempfile.mkdtemp(prefix='rushu-native-browser-'))
    directory.mkdir(parents=True, exist_ok=True)
    server = make_server(native_kernel=args.kernel.resolve(strict=True))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    environment = {**os.environ, 'RUSHU_QA_URL': server.url,
                   'RUSHU_QA_DIR': str(directory.resolve()), 'CHROMIUM_PATH': args.browser}
    try:
        with patch('rulang.frontend.parse', side_effect=AssertionError('Python parser in native browser QA')), \
                patch('rulang.interpreter.Interpreter.execute', side_effect=AssertionError('Python interpreter in native browser QA')), \
                patch('rulang.graphics_runtime.GraphicsHost.create', side_effect=AssertionError('Python canvas in native browser QA')), \
                patch('rulang.graphics_runtime.GraphicsHost.handle', side_effect=AssertionError('Python graphics callback in native browser QA')):
            result = subprocess.run([args.node, str(ROOT/'rushu/tests/native-kernel-browser.cjs')],
                                    cwd=ROOT, env=environment, timeout=120)
            if any(not isinstance(session.process, NativeProcess) for session in server.sessions.sessions.values()):
                raise AssertionError('browser QA used a Python execution process')
            return result.returncode
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


if __name__ == '__main__':
    raise SystemExit(main())
