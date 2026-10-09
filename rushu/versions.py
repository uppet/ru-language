"""Display installed package versions without requiring Git or generation setup."""
from importlib import resources
import re

from rulang import __version__ as ru_version
from . import __version__ as rushu_version


def version_info():
    spec_version = None
    try:
        with resources.files('rulang').joinpath('language-spec.md').open('r', encoding='utf-8') as stream:
            # The version header belongs at the start; never read unbounded data.
            header = stream.read(4096)
        matches = re.findall(r'^规范版本：([0-9]+\.[0-9]+\.[0-9]+)\s*$', header, re.MULTILINE)
        if len(matches) == 1 and header.lstrip('\ufeff').splitlines()[0] == '# 如语言规范 ' + matches[0]:
            spec_version = matches[0]
    except (OSError, UnicodeError, ValueError, ModuleNotFoundError):
        pass
    return {'ru': ru_version, 'specification': spec_version, 'rushu': rushu_version}
