"""Versioned callback work accounting; ordinary non-GUI execution is unmetered.

Raw event counts remain observable independently of weighted protective units.
Explicit recording policies are internal calibration, not product acceptance.
"""
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass

_KINDS = ('expr', 'stmt', 'loop', 'call', 'helper_item', 'bulk_unit')
_CURRENT_BUDGET = ContextVar('ru_execution_budget', default=None)


@dataclass(frozen=True)
class BudgetPolicy:
    work_limit: object
    sample_every: int
    calibration_only: bool = True
    model_version: str = "logical-work-v2"

    def __post_init__(self):
        if type(self.calibration_only) is not bool:
            raise ValueError('calibration_only must be boolean')
        if self.model_version not in ('raw-v1', 'logical-work-v2'):
            raise ValueError('unknown work accounting model')
        if not self.calibration_only and (self.work_limit is None or self.model_version != 'logical-work-v2'):
            raise ValueError('production callbacks require the v2 weighted work limit')
        if self.work_limit is not None and (type(self.work_limit) is not int or self.work_limit < 0):
            raise ValueError('work_limit must be a nonnegative integer or None')
        if type(self.sample_every) is not int or self.sample_every < 1:
            raise ValueError('sample_every must be a positive integer')


DEFAULT_BUDGET_POLICY = BudgetPolicy(262144, 256, calibration_only=False)


@dataclass(frozen=True)
class BudgetSnapshot:
    schema_version: int
    event_sequence: int
    counts: tuple
    total: int
    attempted_total: int
    work_limit: object
    first_exhaustion_kind: object
    elapsed_sample: object
    net_allocated_sample: object
    closed: bool
    raw_total: int
    weighted_counts: tuple
    charged_units: int
    attempted_units: int
    model_version: str


class Budget:
    def __init__(self, policy, *, clock, memory, started, memory_start,
                 seconds=1.0, memory_limit=64 * 1024 * 1024, event_sequence=0,
                 node=None):
        if not isinstance(policy, BudgetPolicy):
            raise TypeError('policy must be BudgetPolicy')
        self.policy, self.clock, self.memory = policy, clock, memory
        self.started, self.deadline = started, started + seconds
        self.memory_start, self.memory_limit = memory_start, memory_limit
        self.seconds, self.event_sequence, self.node = seconds, event_sequence, node
        self.counts = dict.fromkeys(_KINDS, 0)
        self.weighted_counts = dict.fromkeys(_KINDS, 0)
        self.total = self.attempted_total = 0
        self.charged_units = self.attempted_units = 0
        self.next_sample = policy.sample_every
        self.error = self.first_exhaustion_kind = None
        self.elapsed_sample = self.net_allocated_sample = None
        self.closed = False
        self._finalized_callbacks = set()

    def _fail(self, kind, message):
        if self.error is None:
            # frontend imports these budget primitives, so defer the error type.
            from .frontend import BudgetExceeded
            self.first_exhaustion_kind = kind
            token = self.node.token if self.node is not None else None
            self.error = BudgetExceeded(message, token.line if token else 1,
                                        token.col if token else 1, category='预算错误')
            self.error.kind = kind
            if self.node is not None:
                from .diagnostics import at_token
                at_token(self.error, self.node.token)
        raise self.error

    def guard(self):
        if self.error is not None:
            raise self.error
        if self.closed:
            self._fail('closed', '如观回调预算上下文已结束；不能在旧上下文继续执行')

    def check(self):
        self.guard()
        sampled = self.clock()
        self.elapsed_sample = sampled - self.started
        if sampled > self.deadline:
            comparison = ('；微小超限差额经浮点运算舍入'
                          if self.elapsed_sample <= self.seconds else '')
            self._fail('time', f'如观回调超过时间预算（实际约 {self.elapsed_sample!r} 秒墙钟耗时，阈值 {self.seconds:g} 秒{comparison}）；已关闭交互，请简化回调后重跑')
        self.net_allocated_sample = self.memory() - self.memory_start
        if self.net_allocated_sample > self.memory_limit:
            self._fail('memory', f'如观新增内存超过分配预算（实际 {self.net_allocated_sample} 字节，阈值 {self.memory_limit} 字节／{self.memory_limit / (1024 * 1024):g} MiB）；已关闭交互，请减少数据后重跑')

    def charge(self, kind, amount=1):
        self.guard()
        if kind not in self.counts or type(amount) is not int or amount < 0:
            raise ValueError('invalid work accounting event')
        self.attempted_total = self.total + amount
        # One conservative bulk fee per atomic operation. Do not carry small
        # operations together: each has its own dispatch/allocation overhead.
        units = ((amount + 63) // 64
                 if kind == 'bulk_unit' and self.policy.model_version == 'logical-work-v2'
                 else amount)
        self.attempted_units = self.charged_units + units
        limit = self.policy.work_limit
        if limit is not None and self.attempted_units > limit:
            self._fail('work', f'如观回调超过逻辑工作预算（已收费 {self.charged_units} 工作单位，本次拟收费后 {self.attempted_units} 工作单位，阈值 {limit} 工作单位；模型 {self.policy.model_version}）；已关闭交互，请简化回调后重跑')
        self.total = self.attempted_total
        self.charged_units = self.attempted_units
        self.counts[kind] += amount
        self.weighted_counts[kind] += units
        if amount == 0 or self.charged_units >= self.next_sample:
            self.next_sample = self.charged_units + self.policy.sample_every
            self.check()

    def close(self):
        self.closed = True

    def snapshot(self):
        return BudgetSnapshot(2, self.event_sequence, tuple(self.counts.items()),
                              self.total, self.attempted_total, self.policy.work_limit,
                              self.first_exhaustion_kind, self.elapsed_sample,
                              self.net_allocated_sample, self.closed, self.total,
                              tuple(self.weighted_counts.items()), self.charged_units,
                              self.attempted_units, self.policy.model_version)


def current_budget():
    return _CURRENT_BUDGET.get()


def charge(kind, amount=1):
    budget = _CURRENT_BUDGET.get()
    if budget is not None and not _finalizer_active(budget):
        budget.charge(kind, amount)


def check_budget():
    budget = _CURRENT_BUDGET.get()
    if budget is not None and not _finalizer_active(budget):
        budget.check()


def guard_budget():
    budget = _CURRENT_BUDGET.get()
    if budget is not None:
        budget.guard()


def bulk(amount):
    """Conservative input fee plus mandatory checks, including empty input."""
    budget = _CURRENT_BUDGET.get()
    if budget is not None and not _finalizer_active(budget):
        budget.check()
        budget.charge('bulk_unit', amount)


def items(values):
    """Count actual input visits, not generator continuation transitions."""
    for value in values:
        charge('helper_item')
        yield value


@contextmanager
def activate_budget(budget):
    """Install a test/host budget; nesting inherits the existing context."""
    previous = current_budget()
    if previous is not None:
        previous.guard()
        yield previous
        return
    budget.guard()
    token = _CURRENT_BUDGET.set(budget)
    try:
        yield budget
    finally:
        budget.close()
        _CURRENT_BUDGET.reset(token)


def checked_operation(function):
    """Check an opaque/synchronous boundary, without changing call accounting."""
    from functools import wraps
    @wraps(function)
    def checked(*args, **kwargs):
        budget = current_budget()
        if budget is None or _finalizer_active(budget):
            return function(*args, **kwargs)
        budget.check()
        try:
            result = function(*args, **kwargs)
        except BaseException:
            # Preserve a user failure that happened before an overrun was
            # observed; only an already-sticky budget failure takes priority.
            budget.guard()
            raise
        budget.check()
        return result
    return checked


def json_input(value):
    """Meter the actual JSON serialization input (not arbitrary member reads)."""
    if current_budget() is None:
        return
    pending, seen = [value], set()
    while pending:
        current = pending.pop()
        charge('helper_item')
        if isinstance(current, str):
            bulk(len(current))
        elif isinstance(current, (list, tuple, dict)):
            if id(current) in seen:
                continue  # Keep json.dumps responsible for its normal cycle error.
            seen.add(id(current))
            if isinstance(current, dict):
                for key, item in current.items():
                    charge('helper_item')
                    if isinstance(key, str):
                        bulk(len(key))
                    pending.append(item)
            else:
                bulk(len(current))
                pending.extend(current)


def checked_member(kind_attribute):
    """Opaque checks only for the selected runtime, not failed dispatch probes."""
    def decorate(function):
        checked = checked_operation(function)
        from functools import wraps
        @wraps(function)
        def dispatch(owner, node, receiver, name, args):
            selected = (getattr(receiver, 'native_payload', None) is not None
                        if kind_attribute == 'native_payload' else
                        getattr(getattr(receiver, 'type', None), kind_attribute, None) is not None)
            if selected:
                return checked(owner, node, receiver, name, args)
            return function(owner, node, receiver, name, args)
        return dispatch
    return decorate


# Private, one-shot authority for the existing pre-registered native failure
# action. It never makes guard_budget() permissive or clears the sticky error.
_REGISTERED_FINALIZER = ContextVar('ru_registered_native_finalizer', default=None)


def _finalizer_active(budget):
    permit = _REGISTERED_FINALIZER.get()
    if (permit is None or permit[0] is not budget or budget.closed
            or not permit[5] or not permit[6] or budget.error is not permit[7]):
        return False
    import threading
    return (permit[1].thread is threading.current_thread()
            and permit[1].handling_failure and permit[2].context() is permit[1])


@contextmanager
def _registered_native_finalizer(budget, context, callback, function, values):
    import threading
    if (budget is not current_budget() or budget.error is None or budget.closed
            or _REGISTERED_FINALIZER.get() is not None
            or context.thread is not threading.current_thread()
            or callback.context() is not context or not context.handling_failure
            or callback.failure_hook is None or callback.failure_hook[0] is not function
            or callback.failure_hook[1] is not values
            or callback in budget._finalized_callbacks):
        budget.guard()  # Preserve the exact sticky failure, not a new error.
        raise RuntimeError('invalid registered native finalizer')
    frozen_values = tuple(values)
    budget._finalized_callbacks.add(callback)  # Consume even when the action fails.
    permit = [budget, context, callback, function, frozen_values, False, True, budget.error]
    token = _REGISTERED_FINALIZER.set(permit)
    try:
        yield frozen_values
    finally:
        permit[6] = False  # Revoke copies held by copy_context, not only this context.
        _REGISTERED_FINALIZER.reset(token)


def _enter_registered_native_finalizer(context, function, values):
    """Verify and consume the exact call; ordinary/private re-entry cannot reuse it."""
    permit = _REGISTERED_FINALIZER.get()
    if permit is None:
        guard_budget()
        return
    import threading
    budget = current_budget()
    if (budget is not permit[0] or budget.closed or budget.error is not permit[7]
            or context is not permit[1] or not context.handling_failure
            or permit[2].context() is not context
            or context.thread is not threading.current_thread()
            or function is not permit[3] or permit[5] or not permit[6]
            or len(values) != len(permit[4])
            or any(left is not right for left, right in zip(values, permit[4]))):
        permit[0].guard()
        raise RuntimeError('registered native finalizer cannot be transferred')
    permit[5] = True
