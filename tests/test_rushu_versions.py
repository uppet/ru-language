import http.client
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang import __version__ as ru_version
from rushu import __version__ as rushu_version
from rushu.server import make_server
from rushu.versions import version_info


class VersionTests(unittest.TestCase):
    def test_native_library_versions(self):
        self.assertEqual(ru_version, "0.22.0")
        self.assertEqual(rushu_version, "0.8.8")

    def test_installed_versions(self):
        info = version_info()
        self.assertEqual(info, {'ru': ru_version, 'rushu': rushu_version, 'specification': ru_version})

    def test_missing_or_invalid_spec_is_unknown(self):
        with patch('rushu.versions.resources.files', side_effect=OSError):
            self.assertIsNone(version_info()['specification'])
        for text in ['# 如语言规范 9.0.0\n规范版本：0.1.0\n', '规范版本：<script>\n', '']:
            with patch('rushu.versions.resources.files') as files:
                files.return_value.joinpath.return_value.open.return_value = io.StringIO(text)
                self.assertIsNone(version_info()['specification'])

    def test_spec_version_is_not_assumed_equal_to_runtime(self):
        with patch('rushu.versions.resources.files') as files:
            files.return_value.joinpath.return_value.open.return_value = io.StringIO('# 如语言规范 9.8.7\n规范版本：9.8.7\n')
            self.assertEqual(version_info()['specification'], '9.8.7')

    def test_http_security_and_payload(self):
        server = make_server(token='versions-test-abcdefghijklmnop')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for method, path, token, expected in [('GET', '/api/versions', None, 401), ('GET', '/api/versions', server.token, 200), ('POST', '/api/versions', server.token, 405), ('GET', '/api/versions?x=1', server.token, 400)]:
                connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                headers = {'Origin': server.origin}
                if token:
                    headers['X-Rushu-Token'] = token
                connection.request(method, path, headers=headers)
                response = connection.getresponse()
                payload = json.loads(response.read())
                self.assertEqual(response.status, expected, payload)
                if expected == 200:
                    self.assertEqual(payload, version_info())
                connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
