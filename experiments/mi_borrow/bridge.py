"""Private synchronous byte-view bridge, not a public language/FFI API.

Only fixed trusted no-callback compute is allowed. Tokens never leave this module
in product use. Tests inspect the private acquire/release lifecycle explicitly.
"""
import ctypes as C
from rulang import native_runtime as native

_borrow_top = None  # Private, strictly nested synchronous scopes.


def _acquire(memory, offset, length, seed, *, context):
    global _borrow_top
    context.check()
    if context.depth or context.callback_depth:
        native._fault("密视图暂不支持原生调用或回调重入")
    if not isinstance(memory, native.NativeMemory):
        native._fault('密视图需要拥有型 NativeMemory')
    memory.check()
    for value in (offset, length, seed):
        if type(value) is not int or not 0 <= value <= 0xffffffff:
            native._fault('密视图范围须为 u32')
    if offset > memory.size or length > memory.size - offset:
        native._fault('密视图超出缓冲边界')
    root = memory.root
    # Snapshot before changing counts: allocation/check failure cannot borrow.
    owners = []
    native._retain(memory, owners, set())
    native._check_anchors(memory)
    address = memory.address + offset
    # Allocate all count objects and token storage BEFORE committing state.
    root_count = root.mi_read_borrows + 1
    active_count = native._mi_active_borrows + 1
    token = [root, owners, address, length, root.mi_read_borrows,
             native._mi_active_borrows, _borrow_top]
    root.mi_read_borrows = root_count
    native._mi_active_borrows = active_count
    _borrow_top = token
    return token


def _release(token):
    global _borrow_top
    # Validate before touching ANY state. Private scopes cannot escape/reorder.
    if _borrow_top is not token or token is None:
        native._fault('密借用必须按LIFO顺序释放且不可重复释放')
    root = token[0]
    # Restore already-allocated count objects; no arithmetic/allocation here.
    root.mi_read_borrows = token[4]
    native._mi_active_borrows = token[5]
    _borrow_top = token[6]
    token.clear()


def scan(memory, offset, length, seed=0, *, context):
    token = _acquire(memory, offset, length, seed, context=context)
    status, count, previous = 0, seed, 0
    try:
        # Reference oracle only; C bridge calls the existing generated mi_kernel.
        for i in range(length):
            byte = C.c_ubyte.from_address(token[2] + i).value
            if byte == 13 or (byte == 10 and previous != 13):
                if count == 0xffffffff:
                    status = 1
                    break
                count += 1
            previous = byte
    finally:
        _release(token)
    if status:
        native._fault('密内核整数溢出')
    return count
