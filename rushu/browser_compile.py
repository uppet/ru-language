"""Stateless compilation service for isolated browser runs, not kernel execution."""
import hashlib
import threading
from urllib.parse import quote

from rulang.browser_compiler import compile_browser, ROOT
from rulang.diagnostics import SourceOrigin, diagnostic
from rulang.frontend import RuError
from .kernel import KernelError, MAX_SOURCE

_COMPILE_SLOTS = threading.BoundedSemaphore(2)


def compile_request(body):
    code, cell_id = body.get('code'), body.get('cell_id')
    if not isinstance(code, str) or len(code) > MAX_SOURCE:
        raise KernelError('代码须为文字，且不超过 200000 字符')
    if not isinstance(cell_id, str) or not 1 <= len(cell_id) <= 128:
        raise KernelError('cell_id 须为 1 至 128 字符的文字')
    for name in ('execution_count', 'generation'):
        value = body.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 2**53 - 1:
            raise KernelError(name + ' 须为安全范围内正整数')
    try:
        code.encode('utf-8'); cell_id.encode('utf-8')
    except UnicodeError:
        raise KernelError('代码和 cell_id 须为有效 UTF-8 文字') from None
    count, generation = body['execution_count'], body['generation']
    origin = SourceOrigin(f'rushu-js://independent/{generation}/{quote(cell_id, safe="")}/{count}.ru',
                          'cell', cell_id, count, generation,
                          hashlib.sha256(code.encode('utf-8')).hexdigest())
    common = {'target': 'browser', 'independent': True, 'source_name': origin.source_name,
              'source': origin.metadata()}
    if not _COMPILE_SLOTS.acquire(blocking=False):
        raise KernelError('浏览器 JS 编译正忙，请稍后重试', 429)
    try:
        try:
            javascript = compile_browser(code, origin)
        except RuError as error:
            if not getattr(error, 'source_name', None) or error.source_name == ROOT:
                error.source_name = origin.source_name
                error.source_origin = origin
            else:
                from pathlib import Path
                error.source_name = 'ru-stdlib://' + Path(error.source_name).name
            detail = diagnostic(error, origin.source_name)
            return dict(common, error=detail['formatted'], diagnostic=detail)
        except RecursionError:
            error = RuError('浏览器 JS 编译嵌套过深；请简化代码', category='能力错误')
            detail = diagnostic(error, origin.source_name, origin)
            return dict(common, error=detail['formatted'], diagnostic=detail)
        return dict(common, javascript=javascript)
    finally:
        _COMPILE_SLOTS.release()
