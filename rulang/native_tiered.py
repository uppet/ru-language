"""Production ABI planning with conservative, finite heap refinement.

The cheap stage merges allocation histories at one callsite/callee pair. It may
accept only a single exact ABI shape per constructor; ambiguity or a static
rejection triggers a fresh full-callpath plan, never a reset of tainted owners.
Resource failures and cancellation are not refinement signals. Both stages use
the same monotone transfer rules and final signature revalidation.
"""
import gc
from time import perf_counter
from . import native_c as n
from .frontend import RuError, BudgetExceeded

class _Refine(Exception):
    pass

class _CoarsePlan(n.NativeCPlan):
    def _invoke(self, function, args, node):
        previous = self._heap_context
        if isinstance(function, n._Function):
            self._heap_context = ((id(node), id(function.node)),)
        try:
            return self._invoke_heap_body(function, args, node)
        finally:
            self._heap_context = previous

    def _single_shape(self, results, arrays):
        result_names = set()
        for value in results:
            if not isinstance(value, n._Type):
                raise _Refine('unresolved result')
            result_names.add(value.name)
            if len(result_names) > 1:
                raise _Refine('multiple result types')
        shape = None
        seen_arrays = set()
        for array in arrays:
            if not isinstance(array, n._Array) or array.items is None:
                raise _Refine('unresolved parameters')
            if len(array.items) > 64:
                raise _Refine('runtime parameter arity contract')
            self._observe(array)
            if id(array) in seen_arrays:
                continue
            seen_arrays.add(id(array))
            slots = []
            for cell in array.items:
                types = set()
                for value in n._alternatives(cell):
                    if not isinstance(value, n._Type):
                        raise _Refine('unresolved parameter type')
                    types.add(value.name)
                    if len(types) > 1:
                        raise _Refine('multiple parameter types')
                if len(types) != 1:
                    raise _Refine('empty parameter type')
                slots.append(next(iter(types)))
            current = tuple(slots)
            if shape is not None and shape != current:
                raise _Refine('different parameter shapes')
            shape = current
        if not result_names or shape is None:
            raise _Refine('no unique shape')

    def _native(self, operation, args, node):
        if operation.receiver is not n.LIBRARY and operation.name == '签名':
            values = self._bind('签名', args, ['返回', '参数', '约定'], node)
            self._single_shape(n._alternatives(values['返回']), n._alternatives(values['参数']))
        return super()._native(operation, args, node)

    def _before_signature_revalidation(self, params, result, origin):
        # Late alias joins can create a product even without another constructor.
        self._single_shape((n._Type(result),), (params,))


def build_native_c_plan(modules, *, diagnostics=None):
    started = perf_counter()
    stages = []
    reason = None
    completed = False
    def record(stage):
        def receive(stats):
            stages.append(dict(stats, stage=stage))
        return receive
    try:
        try:
            plan = _CoarsePlan(modules, diagnostics=record('coarse'))
        except _Refine as error:
            reason = str(error)
        except BudgetExceeded:
            raise
        except RuError as error:
            if error.category != '原生编译错误':
                raise
            reason = 'coarse static rejection: ' + error.message
        else:
            completed = True
            return plan
        # Outside except: no retained exception/traceback/failed plan. Env callbacks
        # create cycles; collect them before allocating the full-path graph.
        gc.collect()
        plan = n.NativeCPlan(modules, diagnostics=record('full'))
        completed = True
        return plan
    finally:
        if diagnostics is not None:
            summary = {
                'schema': 2, 'phase': 'native-signatures',
                'strategy': 'coarse-then-full',
                'stages': stages, 'refinement_reason': reason,
                'steps': sum(row['steps'] for row in stages),
                'function_evaluations': sum(row['function_evaluations'] for row in stages),
                'seconds': perf_counter() - started,
                'stage_seconds': sum(row['seconds'] for row in stages),
                'completed': bool(stages and stages[-1]['completed']),
            }
            for name in ('summary_hits', 'expression_hits', 'block_hits', 'literal_array_hits'):
                summary[name] = sum(row[name] for row in stages)
            for name in ('module_steps', 'function_evaluations_by_site'):
                combined = {}
                for row in stages:
                    for key, value in row[name].items():
                        combined[key] = combined.get(key, 0) + value
                summary[name] = combined
            final = stages[-1] if stages else {}
            for name in ('modules', 'signatures', 'resource_failure', 'step_limit'):
                summary[name] = final.get(name)
            try:
                diagnostics(summary)
            except BaseException:
                if completed:
                    raise
