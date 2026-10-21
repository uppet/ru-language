"""Foreign shell paths must not replace the native Windows SDK search path."""
import os
import unittest
from unittest.mock import patch

from rulang.toolchain_environment import llvm_environment


class LLVMEnvironmentTests(unittest.TestCase):
    def test_windows_ignores_posix_lists_without_changing_parent(self):
        foreign = {
            'INCLUDE': 'c:/msys64/usr/include/:c:/msys64/include/:',
            'LIB': 'c:/msys64/usr/lib/:',
            'CPATH': '/c/msys64/usr/include',
            'C_INCLUDE_PATH': '/usr/include',
            'CPLUS_INCLUDE_PATH': '/mingw64/include',
            'LIBRARY_PATH': '/usr/lib:/mingw64/lib',
            'PATH': r'C:\Windows;S:\Apps\Git\usr\bin',
            'TEMP': r'C:\Temp',
        }
        with patch.dict(os.environ, foreign, clear=True), \
                patch('rulang.toolchain_environment.sys.platform', 'win32'):
            child = llvm_environment()
            self.assertEqual(child, {'PATH': foreign['PATH'], 'TEMP': foreign['TEMP']})
            self.assertEqual(dict(os.environ), foreign)

    def test_windows_preserves_developer_prompt_paths_and_unrelated_settings(self):
        native = {
            'INCLUDE': r'C:\Program Files\VS\include;C:/SDK/中文/include;',
            'EXTERNAL_INCLUDE': r'\\server\SDK\include',
            'LIB': r'C:\VS\lib\x64;C:/SDK/lib/x64;',
            'LIBPATH': r'C:\VS\lib\x64',
            'CPATH': r'C:\extra\include;relative/include',
            'C_INCLUDE_PATH': 'C:/headers',
            'VCToolsInstallDir': r'C:\VS\Tools\MSVC\14.51',
            'WindowsSdkDir': r'C:\SDK',
            'PATH': r'C:\VS\bin;C:\Windows',
        }
        with patch.dict(os.environ, native, clear=True), \
                patch('rulang.toolchain_environment.sys.platform', 'win32'):
            self.assertEqual(llvm_environment(), dict(os.environ))

    def test_linux_preserves_posix_search_paths(self):
        native = {'INCLUDE': '/usr/include:/opt/sdk', 'LIB': '/usr/lib:',
                  'CPATH': '/usr/include:/opt/中文/include', 'PATH': '/usr/bin:/bin'}
        with patch.dict(os.environ, native, clear=True), \
                patch('rulang.toolchain_environment.sys.platform', 'linux'):
            self.assertEqual(llvm_environment(), native)


if __name__ == '__main__':
    unittest.main()
