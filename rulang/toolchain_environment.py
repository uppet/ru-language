"""Keep POSIX search-path lists out of native Windows LLVM processes."""
import ntpath
import os
import re
import sys


def llvm_environment():
    """Copy the environment, retaining valid Windows SDK/developer settings.

    Git Bash startup files can export colon-separated GCC paths as INCLUDE or
    LIB. LLVM's MSVC target expects semicolons; a nonempty INCLUDE also disables
    its automatic SDK header lookup. Ignore only lists with POSIX syntax, in the
    child process. Never change the calling shell or its PATH.
    """
    environment = os.environ.copy()
    if sys.platform == 'win32':
        variables = ('INCLUDE', 'EXTERNAL_INCLUDE', 'LIB', 'LIBPATH', 'CPATH',
                     'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'OBJC_INCLUDE_PATH',
                     'OBJCPLUS_INCLUDE_PATH', 'LIBRARY_PATH')
        for name in variables:
            for entry in environment.get(name, '').split(';'):
                entry = entry.strip().strip('"')
                # A drive colon is valid; subsequent colons are POSIX separators.
                # Single /c/... and /usr/... entries also need a POSIX runtime.
                if (':' in ntpath.splitdrive(entry)[1] or
                        re.match(r'^/(?:[a-zA-Z](?:/|$)|usr(?:/|$)|mingw\d*/|ucrt\d*/|clang\w*/)', entry)):
                    environment.pop(name, None)
                    break
    return environment
