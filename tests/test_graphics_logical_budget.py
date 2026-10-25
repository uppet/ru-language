"""Deterministic opt-in logical-budget contracts; not calibration timings."""
from contextvars import copy_context
from dataclasses import FrozenInstanceError
import io
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from rulang.execution_budget import (Budget, BudgetPolicy, activate_budget, bulk, checked_operation,
                                    charge, check_budget, current_budget)
from rulang.frontend import BudgetExceeded, RuError, parse
from rulang.graphics_runtime import GraphicsHost, MAX_CALLBACK_SECONDS, MAX_GRAPHICS_MEMORY
from rulang.interpreter import Interpreter, Panic


class LogicalBudgetTests(unittest.TestCase):
    def budget(self, limit=1000, cadence=64):
        samples={'time':0.0,'memory':100}
        budget=Budget(BudgetPolicy(limit,cadence),clock=lambda:samples['time'],
                      memory=lambda:samples['memory'],started=0.0,memory_start=100)
        return budget,samples

    def vm(self):
        return Interpreter(stdout=io.StringIO())

    def assert_idle(self, vm):
        self.assertEqual((vm.structure_depth,vm.depth,vm.call_state),(0,0,[0]))
        self.assertIsNone(current_budget())

    def test_structure_limit_precedes_new_work_overrun_but_not_existing_sticky_error(self):
        from rulang.interpreter import STRUCTURE_DEPTH_LIMIT
        self.assertEqual(STRUCTURE_DEPTH_LIMIT,8000)
        for source in ('显 1.','显 1+2.'):
            # Literal uses the leaf fast path; binary enters the expression frame.
            for already_sticky in (False,True):
                with self.subTest(source=source,already_sticky=already_sticky):
                    vm=self.vm();vm.structure_depth=STRUCTURE_DEPTH_LIMIT
                    expression=parse(source)[0].data['expr']
                    budget,_=self.budget(limit=0)
                    with activate_budget(budget):
                        first=None
                        if already_sticky:
                            with self.assertRaises(BudgetExceeded) as exhausted: charge('expr')
                            first=exhausted.exception
                        with self.assertRaises(RuError) as caught:
                            vm.expr(expression,vm.global_scope)
                        if already_sticky:
                            self.assertIs(caught.exception,first)
                            self.assertEqual(caught.exception.kind,'work')
                        else:
                            self.assertNotIsInstance(caught.exception,BudgetExceeded)
                            self.assertIn('结构超过 8000',str(caught.exception))
                            self.assertIsNone(budget.error)
                        self.assertEqual(budget.total,0)
                        self.assertEqual((vm.structure_depth,vm.depth,vm.call_state),(8000,0,[0]))
                    self.assertIsNone(current_budget())

    def test_import_and_parser_preserve_first_budget_error_and_business_error_behavior(self):
        from rulang.frontend import Parser
        from rulang.diagnostics import SourceOrigin
        from rulang.modules import load_module_graph
        origin_node=parse('\n'*16+'      显 1.',SourceOrigin('rushu://budget/original.ru'))[0]
        def fingerprint(error):
            return (error.message,error.line,error.col,getattr(error,'source_name',None),
                    getattr(error,'source_origin',None))
        def trip(budget,seen):
            budget.policy=BudgetPolicy(0,64)
            try: charge('helper_item')
            except BudgetExceeded as error:
                seen.append((error,fingerprint(error)))
                raise
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'entry.ru'
            source="\n\n库 取 外言 'dependency.ru'."
            root.write_text(source,encoding='utf-8')
            for through_graph in (False,True):
                for located in (False,True):
                    with self.subTest(through_graph=through_graph,located=located):
                        program=parse(source);expression=program[0].data['expr']
                        vm=self.vm();vm.source_path=str(root)
                        budget,_=self.budget(limit=None)
                        budget.node=origin_node if located else None
                        seen=[]
                        with activate_budget(budget),patch('rulang.modules.resolve_import',side_effect=lambda *a:trip(budget,seen)):
                            with self.assertRaises(BudgetExceeded) as caught:
                                if through_graph: load_module_graph(root,program)
                                else: vm.expr(expression,vm.global_scope)
                        self.assertEqual(len(seen),1)
                        self.assertIs(caught.exception,seen[0][0])
                        self.assertEqual(fingerprint(caught.exception),seen[0][1])
                        self.assert_idle(vm)
            # A normal unresolved import still receives its original import
            # location, rather than becoming a budget error or losing provenance.
            for through_graph in (False,True):
                program=parse(source);expression=program[0].data['expr']
                ordinary=RuError('ordinary missing module',91,7,'模块错误')
                vm=self.vm();vm.source_path=str(root);budget,_=self.budget(limit=None)
                with activate_budget(budget),patch('rulang.modules.resolve_import',side_effect=ordinary):
                    with self.assertRaises(RuError) as caught:
                        if through_graph: load_module_graph(root,program)
                        else: vm.expr(expression,vm.global_scope)
                self.assertIs(caught.exception,ordinary)
                self.assertEqual((ordinary.line,ordinary.col),(expression.token.line,expression.token.col))
                if through_graph: self.assertEqual(ordinary.source_name,str(root.resolve()))
                self.assertIsNone(budget.error)
                self.assert_idle(vm)
        # Memoization must never turn an exhausted budget into a cached syntax
        # alternative; ordinary syntax failures must still be memoized.
        parser=Parser('算 回: 得 1. 法')
        budget,_=self.budget(limit=None);budget.node=origin_node;seen=[]
        with activate_budget(budget):
            with self.assertRaises(BudgetExceeded) as caught:
                parser.callable_parse('named',lambda:trip(budget,seen))
        self.assertIs(caught.exception,seen[0][0])
        self.assertEqual(fingerprint(caught.exception),seen[0][1])
        self.assertEqual(parser.callable_cache,{})
        for source,method,fallback in (('循 环','expression','parse'),
                                       ('算 回 值:1.','function','expression'),
                                       ('算 值:1.','literal','reference')):
            with self.subTest(speculation=source):
                parser=Parser(source);budget,_=self.budget(limit=None);budget.node=origin_node;seen=[]
                with activate_budget(budget),patch.object(parser,method,side_effect=lambda *a:trip(budget,seen)), \
                     patch.object(parser,fallback) as alternate:
                    with self.assertRaises(BudgetExceeded) as caught:
                        if method=='literal': parser.expression()
                        else: parser.statement()
                self.assertIs(caught.exception,seen[0][0])
                self.assertEqual(fingerprint(caught.exception),seen[0][1])
                alternate.assert_not_called()
                self.assertEqual(parser.callable_cache,{})
        parser=Parser('算 回: 得 1. 法');ordinary=RuError('ordinary syntax',3,4)
        calls=[]
        def fail_syntax(): calls.append(1);raise ordinary
        for _ in range(2):
            with self.assertRaises(RuError) as caught: parser.callable_parse('named',fail_syntax)
            self.assertIs(caught.exception,ordinary)
        self.assertEqual(calls,[1]);self.assertEqual(len(parser.callable_cache),1)
        parser=Parser('循 环')
        with patch.object(parser,'expression',side_effect=RuError('not a loop count')):
            loop=parser.statement()
        self.assertEqual(loop.kind,'loop');self.assertIsNone(loop.data['count'])

    def test_package_resolution_preserves_sticky_error_and_manifest_privacy(self):
        from contextlib import redirect_stderr
        from types import SimpleNamespace
        from rulang import packages
        from rulang.cli import report
        from rulang.diagnostics import SourceOrigin
        origin=parse('\n'*18+'        显 1.',SourceOrigin('rushu://budget/first.ru'))[0]
        def fields(error):
            return (error.message,error.args,error.category,error.line,error.col,
                    getattr(error,'source_name',None),getattr(error,'source_text',None),
                    getattr(error,'suppress_source',None))
        def trip(budget,seen):
            budget.policy=BudgetPolicy(0,64)
            try: charge('helper_item')
            except BudgetExceeded as error:
                seen.append((error,fields(error)))
                raise
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();manifest=root/'集录.ru'
            secret='SYNTHETIC_TOKEN_MUST_NOT_APPEAR'
            text="# "+secret+"\n{'名':'工程','公开': []}."
            manifest.write_text(text,encoding='utf-8')
            budget,_=self.budget(limit=None);budget.node=origin;seen=[]
            with activate_budget(budget),patch.object(packages.Parser,'expression',side_effect=lambda *a,**k:trip(budget,seen)):
                with self.assertRaises(BudgetExceeded) as caught: packages.load_manifest(manifest)
            self.assertIs(caught.exception,seen[0][0])
            self.assertEqual(fields(caught.exception),seen[0][1])
            self.assertFalse(hasattr(caught.exception,'source_text'))
            self.assertNotIn(secret,str(caught.exception))
            # Ordinary malformed manifests retain the existing package error,
            # source position, and source suppression in user-visible reports.
            malformed="# "+secret+"\n{'名':'工程','公开':[}."
            manifest.write_text(malformed,encoding='utf-8')
            with self.assertRaises(RuError) as ordinary: packages.load_manifest(manifest)
            self.assertNotIsInstance(ordinary.exception,BudgetExceeded)
            self.assertEqual(ordinary.exception.category,'包错误')
            self.assertEqual(ordinary.exception.line,2)
            self.assertEqual(ordinary.exception.source_name,str(manifest))
            self.assertTrue(ordinary.exception.suppress_source)
            output=io.StringIO()
            with redirect_stderr(output): report(ordinary.exception,str(manifest),malformed)
            self.assertNotIn(secret,output.getvalue())
            self.assertNotIn("'公开'",output.getvalue())
            # Resolve a real offline local dependency under one unchanged budget.
            app=root/'app';lib=root/'lib';app.mkdir();(lib/'src').mkdir(parents=True)
            (app/'集录.ru').write_text("{'名':'应用','依赖':{'库':{'路径':'../lib'}}}.",encoding='utf-8')
            (lib/'集录.ru').write_text("{'名':'工程','公开':['项']}.",encoding='utf-8')
            importer=app/'main.ru';importer.write_text('显 1.',encoding='utf-8')
            target=lib/'src/项.ru';target.write_text('值 取 1.',encoding='utf-8')
            resolver=packages.PackageResolver(importer);budget,_=self.budget(limit=None)
            with activate_budget(budget):
                self.assertEqual(resolver.path(target,importer),str(target))
                self.assertIs(current_budget(),budget)
                first_total=budget.total
                self.assertGreater(first_total,0)
                self.assertEqual(resolver.path(target,importer),str(target))
                self.assertGreaterEqual(budget.total,first_total)
                self.assertIs(current_budget(),budget)
            # An exhausted first edge must not be treated as an unavailable
            # optional dependency and fall through to a second edge.
            source=SimpleNamespace(root=app,dependencies={'first':{},'second':{}})
            destination=SimpleNamespace(root=lib,public={('工程','项'):target})
            resolver=packages.PackageResolver.__new__(packages.PackageResolver)
            budget,_=self.budget(limit=None);budget.node=origin;seen=[]
            with activate_budget(budget),patch.object(resolver,'owner',side_effect=lambda path:source if path==importer else destination), \
                 patch.object(resolver,'dependency',side_effect=lambda *a:trip(budget,seen)) as dependency:
                with self.assertRaises(BudgetExceeded) as caught: resolver.path(target,importer)
            self.assertEqual(dependency.call_count,1)
            self.assertIs(caught.exception,seen[0][0])
            self.assertEqual(fields(caught.exception),seen[0][1])
            with patch.object(resolver,'owner',side_effect=lambda path:source if path==importer else destination), \
                 patch.object(resolver,'dependency',side_effect=[RuError('ordinary unavailable edge'),destination]) as dependency:
                self.assertEqual(resolver.path(target,importer),str(target))
            self.assertEqual(dependency.call_count,2)
        budget,_=self.budget(limit=None);budget.node=origin;seen=[]
        with activate_budget(budget),patch.object(packages,'lex',side_effect=lambda *a:trip(budget,seen)):
            with self.assertRaises(BudgetExceeded) as caught: packages._identifier('工程')
        self.assertIs(caught.exception,seen[0][0]);self.assertEqual(fields(caught.exception),seen[0][1])
        with patch.object(packages,'lex',side_effect=RuError('ordinary invalid identifier')):
            self.assertFalse(packages._identifier('bad'))
        self.assertIsNone(current_budget())

    def test_v2_bulk_is_rounded_per_operation_not_after_accumulation(self):
        for amount in (0,1,63,64,65,10**100):
            for entry in ('direct','bulk'):
                with self.subTest(amount=amount,entry=entry):
                    budget,_=self.budget(limit=None)
                    with activate_budget(budget):
                        if entry=='direct': budget.charge('bulk_unit',amount)
                        else: bulk(amount)
                    snapshot=budget.snapshot()
                    self.assertEqual(snapshot.schema_version,2)
                    self.assertEqual(snapshot.model_version,'logical-work-v2')
                    self.assertEqual(snapshot.raw_total,amount)
                    self.assertEqual(snapshot.total,amount)
                    self.assertEqual(dict(snapshot.counts)['bulk_unit'],amount)
                    self.assertEqual(dict(snapshot.weighted_counts)['bulk_unit'],(amount+63)//64)
                    self.assertEqual(snapshot.charged_units,(amount+63)//64)
        for pieces,expected in (([1]*64,64),([64],1),([63,1],2),([0,0],0)):
            budget,_=self.budget(limit=None)
            with activate_budget(budget):
                for amount in pieces: bulk(amount)
            self.assertEqual(budget.snapshot().charged_units,expected)
            self.assertEqual(budget.snapshot().raw_total,sum(pieces))

    def test_v2_weighted_limit_and_sampling_keep_raw_attempts_separate(self):
        budget,_=self.budget(limit=2)
        budget.charge('bulk_unit',65)
        self.assertEqual((budget.snapshot().charged_units,budget.total),(2,65))
        with self.assertRaises(BudgetExceeded): budget.charge('bulk_unit',1)
        snapshot=budget.snapshot()
        self.assertEqual((snapshot.charged_units,snapshot.attempted_units),(2,3))
        self.assertEqual((snapshot.total,snapshot.raw_total,snapshot.attempted_total),(65,65,66))
        from unittest.mock import Mock
        clock=Mock(return_value=0.);memory=Mock(return_value=0)
        sampled=Budget(BudgetPolicy(None,4),clock=clock,memory=memory,started=0.,memory_start=0)
        sampled.charge('bulk_unit',192)  # Three weighted units, not 192 cadence units.
        clock.assert_not_called();memory.assert_not_called()
        sampled.charge('bulk_unit',1)
        self.assertEqual((clock.call_count,memory.call_count),(1,1))
        self.assertEqual(sampled.snapshot().charged_units,4)

    def test_v2_unicode_text_and_byte_helper_units_remain_distinct(self):
        import json
        from rulang.io_runtime import _decode
        text='😀'*33+'甲'
        vm=self.vm();expression=parse('显 '+json.dumps(text[:-1],ensure_ascii=False)+"+'甲'.")[0].data['expr']
        budget,_=self.budget(limit=None)
        with activate_budget(budget): self.assertEqual(vm.expr(expression,vm.global_scope),text)
        self.assertEqual(dict(budget.snapshot().counts)['bulk_unit'],34)
        self.assertEqual(dict(budget.snapshot().weighted_counts)['bulk_unit'],1)
        budget,_=self.budget(limit=None)
        with activate_budget(budget): self.assertEqual(_decode(text.encode('utf-8')),text)
        # UTF8 byte input plus the decoded text validation are separate operations.
        self.assertEqual(dict(budget.snapshot().counts)['bulk_unit'],135+34)
        self.assertEqual(dict(budget.snapshot().weighted_counts)['bulk_unit'],3+1)
        budget,_=self.budget(limit=None)
        with activate_budget(budget): self.assertEqual(_decode('甲'),'甲')
        self.assertEqual(dict(budget.snapshot().counts)['bulk_unit'],2)
        self.assertEqual(dict(budget.snapshot().weighted_counts)['bulk_unit'],2)

    def test_v2_string_identity_does_not_change_logical_comparison_fee(self):
        text='a😀'*40
        other=''.join([text[:-1],text[-1]])
        self.assertEqual(text,other);self.assertIsNot(text,other)
        vm=self.vm();node=parse('显 真.')[0]
        fees=[]
        for right in (text,other):
            budget,_=self.budget(limit=None)
            with activate_budget(budget): self.assertTrue(vm.equals(node,text,right))
            snapshot=budget.snapshot()
            fees.append((dict(snapshot.counts)['bulk_unit'],dict(snapshot.weighted_counts)['bulk_unit']))
        self.assertEqual(fees,[(160,3),(160,3)])
        for value in ([],list(range(1000))):
            budget,_=self.budget(limit=None)
            with activate_budget(budget): self.assertTrue(vm.equals(node,value,value))
            self.assertEqual(dict(budget.snapshot().counts)['bulk_unit'],0)
            self.assertEqual(dict(budget.snapshot().weighted_counts)['bulk_unit'],0)

    def test_v2_production_default_and_historical_raw_model_are_not_confused(self):
        from rulang.execution_budget import DEFAULT_BUDGET_POLICY
        self.assertEqual((DEFAULT_BUDGET_POLICY.work_limit,DEFAULT_BUDGET_POLICY.sample_every),(262144,256))
        self.assertFalse(DEFAULT_BUDGET_POLICY.calibration_only)
        self.assertEqual(DEFAULT_BUDGET_POLICY.model_version,'logical-work-v2')
        vm=self.vm();host=GraphicsHost(vm,lambda event:None)
        self.addCleanup(host.close)
        self.assertIs(host.budget_policy,DEFAULT_BUDGET_POLICY)
        raw=Budget(BudgetPolicy(None,256,model_version='raw-v1'),clock=lambda:0.,memory=lambda:0,started=0.,memory_start=0)
        raw.charge('bulk_unit',65)
        self.assertEqual((raw.snapshot().raw_total,raw.snapshot().charged_units),(65,65))
        with self.assertRaises(ValueError): BudgetPolicy(None,256,calibration_only=False)
        with self.assertRaises(ValueError): BudgetPolicy(262144,256,calibration_only=False,model_version='raw-v1')

    def test_exact_work_boundary_and_bulk_precharge_are_sticky(self):
        budget,_=self.budget(limit=4)
        budget.charge('expr',4)
        self.assertEqual(budget.total,4)
        touched=[]
        with self.assertRaises(BudgetExceeded) as first:
            budget.charge('bulk_unit',1)
            touched.append('must not run')
        self.assertEqual(touched,[])
        self.assertEqual(first.exception.kind,'work')
        self.assertEqual((budget.total,budget.attempted_total),(4,5))
        with self.assertRaises(BudgetExceeded) as again:
            budget.charge('expr',0)
        self.assertIs(first.exception,again.exception)

    def test_zero_bulk_checks_time_and_never_revives_exhaustion(self):
        budget,samples=self.budget()
        with activate_budget(budget):
            samples['time']=math.nextafter(1.0,math.inf)
            with self.assertRaises(BudgetExceeded) as caught:
                bulk(0)
            self.assertEqual(caught.exception.kind,'time')
            samples['time']=0.0
            with self.assertRaises(BudgetExceeded) as again:
                bulk(0)
            self.assertIs(caught.exception,again.exception)

    def test_strict_wall_and_net_memory_limits_unchanged(self):
        self.assertEqual(MAX_CALLBACK_SECONDS,1.0)
        self.assertEqual(MAX_GRAPHICS_MEMORY,64*1024*1024)
        for kind in ('time','memory'):
            with self.subTest(kind=kind):
                budget,samples=self.budget()
                samples.update(time=1.0,memory=100+64*1024*1024)
                budget.check()
                if kind=='time': samples['time']=math.nextafter(1.0,math.inf)
                else: samples['memory']+=1
                with self.assertRaises(BudgetExceeded) as caught:
                    budget.check()
                self.assertEqual(caught.exception.kind,kind)

    def test_business_exception_identity_does_not_trigger_new_post_samples(self):
        calls=[0,0];clock=[0.0]
        def now(): calls[0]+=1;return clock[0]
        def memory(): calls[1]+=1;return 0
        budget=Budget(BudgetPolicy(None,256),clock=now,memory=memory,started=0.0,memory_start=0)
        original=RuntimeError('business failure')
        @checked_operation
        def operation():
            clock[0]=2.0
            raise original
        with activate_budget(budget):
            with self.assertRaises(RuntimeError) as caught: operation()
            self.assertIs(caught.exception,original)
            self.assertEqual(calls,[1,1])
            # The host may catch the business error, but the next semantic safe
            # point must still enforce the elapsed deadline.
            with self.assertRaises(BudgetExceeded) as exhausted: bulk(0)
            self.assertEqual(exhausted.exception.kind,'time')

    def test_ru_rescue_cannot_repeatedly_hide_elapsed_deadline(self):
        vm=self.vm();budget,samples=self.budget(limit=None,cadence=1)
        vm.execute(parse("算 坏: 卒 'business'. 法"))
        original=Panic.__init__
        panics=[]
        def panic(error,*args,**kwargs):
            original(error,*args,**kwargs)
            panics.append(error)
            samples['time']=2.0
        with patch.object(Panic,'__init__',panic):
            with self.assertRaises(BudgetExceeded) as caught:
                with activate_budget(budget):
                    vm.execute(parse("循 100 次 试 坏. 救 原因 1. 终. 环"))
        self.assertEqual(len(panics),1)
        self.assertEqual(caught.exception.kind,'time')
        self.assert_idle(vm)

    def test_snapshot_is_immutable_and_counts_sum_to_total(self):
        budget,_=self.budget()
        budget.charge('stmt',2);budget.charge('helper_item',3);budget.charge('bulk_unit',5)
        budget.close()
        snapshot=budget.snapshot()
        self.assertEqual(snapshot.total,sum(dict(snapshot.counts).values()))
        self.assertEqual(snapshot.total,10)
        self.assertTrue(snapshot.closed)
        with self.assertRaises(FrozenInstanceError): snapshot.total=0

    def test_nested_context_inherits_outer_budget_not_child_allowance(self):
        outer,_=self.budget(limit=4)
        inner,_=self.budget(limit=10000)
        with activate_budget(outer):
            charge('expr',3)
            with activate_budget(inner) as active:
                self.assertIs(active,outer)
                self.assertIs(current_budget(),outer)
                with self.assertRaises(BudgetExceeded): charge('expr',2)
            self.assertEqual(inner.total,0)
        self.assertTrue(outer.closed)
        self.assertIsNone(current_budget())

    def test_closed_copied_context_rejects_public_invoke_before_body(self):
        vm=self.vm()
        vm.execute(parse('痕 取 []. 算 回: 痕 其 增 1. 得 7. 法'))
        fn=vm.function_values['回']
        node=parse('显 1.')[0]
        budget,_=self.budget()
        with activate_budget(budget): context=copy_context()
        with self.assertRaises(BudgetExceeded) as caught:
            context.run(vm.invoke_value,node,fn,[])
        self.assertEqual(caught.exception.kind,'closed')
        self.assertEqual(vm.global_scope.values['痕'],[])
        self.assert_idle(vm)
        fresh,_=self.budget()
        with activate_budget(fresh): self.assertEqual(vm.invoke_value(node,fn,[]),7.0)
        self.assertEqual(vm.global_scope.values['痕'],[1.0])
        self.assert_idle(vm)

    def test_empty_loop_consumes_budget_and_ru_rescue_cannot_swallow_it(self):
        vm=self.vm();budget,_=self.budget(limit=300)
        with self.assertRaises(BudgetExceeded) as caught:
            with activate_budget(budget):
                vm.execute(parse("试 循 环 救 原因 显 'wrong rescue'. 终."))
        self.assertNotIsInstance(caught.exception,Panic)
        self.assertEqual(vm.stdout.getvalue(),'')
        self.assertGreater(dict(budget.snapshot().counts)['loop'],0)
        self.assert_idle(vm)

    def finalizer_fixture(self):
        import threading
        from types import SimpleNamespace
        budget,_=self.budget(limit=0)
        context=SimpleNamespace(thread=threading.current_thread(),handling_failure=True)
        function=object();values=[object()]
        class Callback:
            def context(self): return context
        callback=Callback();callback.failure_hook=(function,values)
        return budget,context,callback,function,values

    def test_native_finalizer_ticket_rejects_function_argument_context_transfer(self):
        from rulang.execution_budget import _registered_native_finalizer,_enter_registered_native_finalizer
        for altered in ('function','arguments','context','reenter'):
            with self.subTest(altered=altered):
                budget,context,callback,function,values=self.finalizer_fixture()
                with activate_budget(budget):
                    with self.assertRaises(BudgetExceeded): charge('expr')
                    first=budget.error
                    with _registered_native_finalizer(budget,context,callback,function,values) as frozen:
                        if altered=='reenter': _enter_registered_native_finalizer(context,function,list(frozen))
                        with self.assertRaises(BudgetExceeded) as caught:
                            _enter_registered_native_finalizer(object() if altered=='context' else context,
                                object() if altered=='function' else function,
                                [object()] if altered=='arguments' else list(frozen))
                        self.assertIs(caught.exception,first)

    def test_native_finalizer_failed_action_is_consumed_and_ru_guard_stays_sticky(self):
        from rulang.execution_budget import _registered_native_finalizer,_enter_registered_native_finalizer,guard_budget
        budget,context,callback,function,values=self.finalizer_fixture()
        with activate_budget(budget):
            with self.assertRaises(BudgetExceeded): charge('expr')
            first=budget.error
            with self.assertRaisesRegex(RuntimeError,'marshal failed'):
                with _registered_native_finalizer(budget,context,callback,function,values) as frozen:
                    _enter_registered_native_finalizer(context,function,list(frozen))
                    charge('helper_item',99);check_budget()
                    with self.assertRaises(BudgetExceeded) as guard: guard_budget()
                    self.assertIs(guard.exception,first)
                    raise RuntimeError('marshal failed')
            with self.assertRaises(BudgetExceeded) as reused:
                with _registered_native_finalizer(budget,context,callback,function,values): pass
            self.assertIs(reused.exception,first)
            self.assertEqual(budget.total,0)

    def test_native_finalizer_copied_context_revoked_on_exit(self):
        from rulang.execution_budget import _registered_native_finalizer,_enter_registered_native_finalizer
        budget,context,callback,function,values=self.finalizer_fixture()
        with activate_budget(budget):
            with self.assertRaises(BudgetExceeded): charge('expr')
            with _registered_native_finalizer(budget,context,callback,function,values) as frozen:
                _enter_registered_native_finalizer(context,function,list(frozen))
                escaped=copy_context()
            for operation in (lambda:charge('expr'),check_budget,lambda:bulk(0),
                              lambda:_enter_registered_native_finalizer(context,function,list(values))):
                with self.subTest(operation=operation),self.assertRaises(BudgetExceeded) as caught:
                    escaped.run(operation)
                self.assertIs(caught.exception,budget.error)
        with self.assertRaises(BudgetExceeded) as closed: escaped.run(check_budget)
        self.assertIs(closed.exception,budget.error)

    def test_short_circuit_cost_matches_unvisited_rhs_and_no_side_effect(self):
        counts=[]
        for source in ("显 假 且 真.","显 假 且 (算: 卒 'not evaluated'. 法)()."):
            vm=self.vm();budget,_=self.budget()
            expression=parse(source)[0].data['expr']
            with activate_budget(budget): value=vm.expr(expression,vm.global_scope)
            self.assertIs(value,False)
            self.assertEqual(vm.stdout.getvalue(),'')
            counts.append(budget.snapshot().counts)
            self.assert_idle(vm)
        self.assertEqual(counts[0],counts[1])

    def test_public_and_ast_call_wrapper_do_not_double_count_ru_call(self):
        counts=[]
        for direct in (True,False):
            vm=self.vm();vm.execute(parse('算 回: 得 7. 法'))
            budget,_=self.budget()
            with activate_budget(budget):
                if direct: vm.invoke_value(parse('显 1.')[0],vm.function_values['回'],[])
                else: vm.execute(parse('回.'))
            counts.append(dict(budget.snapshot().counts)['call'])
            self.assert_idle(vm)
        self.assertEqual(counts,[1,1])

    def test_cross_module_owner_shares_outer_work_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            (path/'owner.ru').write_text('算 回: 循 1000 次 环 得 7. 法',encoding='utf-8')
            vm=self.vm();vm.execute(parse("库 取 外言 'owner.ru'."),source_path=path/'main.ru')
            budget,_=self.budget(limit=300)
            with self.assertRaises(BudgetExceeded):
                with activate_budget(budget): vm.execute(parse('库 其 回.'))
            self.assertGreater(dict(budget.snapshot().counts)['loop'],0)
            self.assert_idle(vm)
            for module in vm.module_cache.values():
                self.assertEqual((module.interpreter.structure_depth,module.interpreter.depth),(0,0))

    def test_hash_equality_and_sort_callbacks_consume_same_budget(self):
        for source in (
            "物 取 {}. 形 键: 算 印: 循 1000 次 环 得 0. 法 算 同 另一: 得 真. 法 象 物 其 增 (新 键) 1.",
            "显 [2,1] 其 排序 (算 左 右: 循 1000 次 环 得 左 < 右. 法).",
        ):
            with self.subTest(source=source):
                vm=self.vm();budget,_=self.budget(limit=500)
                with self.assertRaises(BudgetExceeded):
                    with activate_budget(budget): vm.execute(parse(source))
                self.assertGreater(dict(budget.snapshot().counts)['call'],0)
                self.assert_idle(vm)

    def test_helper_input_growth_has_nonconstant_work(self):
        counts=[]
        for n in (0,1,16,256):
            vm=self.vm();vm.execute(parse('原 取 '+str(list(range(n)))+'.'))
            budget,_=self.budget(limit=None)
            with activate_budget(budget): vm.execute(parse(f'原[0:{n}].'))
            counts.append(dict(budget.snapshot().counts)['bulk_unit'])
        self.assertEqual(counts,sorted(set(counts)))

    def host(self,source='图 其 每帧 (作 帧: 为).',limit=None,cadence=256):
        vm=self.vm();events=[]
        host=GraphicsHost(vm,events.append,budget_policy=BudgetPolicy(limit,cadence),now_seconds=lambda:0.)
        self.addCleanup(host.close)
        vm.execute(parse("观 取 外言 '如:观'. 图 取 观 其 画布 64 64. "+source))
        return vm,host

    def test_next_event_starts_new_budget_and_old_snapshot_stays_frozen(self):
        vm,host=self.host()
        host.handle({'type':'frame'});first=host.budget_snapshot
        host.handle({'type':'frame'});second=host.budget_snapshot
        self.assertEqual(first.counts,second.counts)
        self.assertEqual(second.event_sequence,first.event_sequence+1)
        self.assertTrue(first.closed and second.closed)
        self.assert_idle(vm)

    def test_external_trace_is_not_installed_or_removed_by_logical_host(self):
        seen=[]
        def trace(frame,event,arg):
            if event=='call' and frame.f_code.co_name=='handle': seen.append(event)
            return trace
        old=sys.gettrace()
        for failed in (False,True):
            with self.subTest(failed=failed):
                vm,host=self.host("图 其 每帧 (作 帧: 卒 'business'. 为)." if failed else '图 其 每帧 (作 帧: 为).')
                try:
                    sys.settrace(trace)
                    if failed:
                        with self.assertRaises(Panic): host.handle({'type':'frame'})
                    else: host.handle({'type':'frame'})
                    self.assertIs(sys.gettrace(),trace)
                finally: sys.settrace(old)
                self.assert_idle(vm)
        self.assertTrue(seen)

    def test_final_check_catches_short_callback_deadline_after_last_charge(self):
        vm,host=self.host(cadence=1024)
        clock=[0.0]
        original=vm.invoke_value
        def invoke(*args,**kwargs):
            result=original(*args,**kwargs)
            clock[0]=1.01
            return result
        with patch('rulang.graphics_runtime.time.monotonic',side_effect=lambda:clock[0]), \
             patch.object(vm,'invoke_value',side_effect=invoke):
            with self.assertRaises(BudgetExceeded) as caught:
                host.handle({'type':'frame'})
        self.assertEqual(caught.exception.kind,'time')
        self.assertIsNone(host.canvas)
        self.assert_idle(vm)
        fresh_vm,fresh_host=self.host()
        fresh_host.handle({'type':'frame'})
        self.assertIsNone(fresh_host.budget_snapshot.first_exhaustion_kind)
        self.assertTrue(fresh_host.budget_snapshot.closed)
        self.assert_idle(fresh_vm)



# Native Python FFI is supported on Windows x64 only. This class is absent from
# Linux discovery (not a skip), and mandatory on each supported CI Python.
if sys.platform == 'win32':
    class WindowsNativeLogicalBudgetTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            import ctypes
            import hashlib
            import json
            import os
            import platform
            import shutil
            import subprocess
            if ctypes.sizeof(ctypes.c_void_p)!=8 or platform.machine().lower() not in ('amd64','x86_64'):
                raise AssertionError('Native budget acceptance requires Windows x64')
            compiler=shutil.which(os.environ.get('CC','gcc'))
            if compiler is None: raise AssertionError('Required C compiler missing; no skip allowed')
            cls.directory=tempfile.TemporaryDirectory(prefix='logical-native-')
            cls.library=Path(cls.directory.name)/'bridge.dll'
            source=Path(__file__).resolve().parents[1]/'tests/fixtures/native/logical_budget_bridge.c'
            built=subprocess.run([compiler,'-shared','-O2',str(source),'-o',str(cls.library)],capture_output=True,timeout=60)
            if built.returncode: raise AssertionError(repr((built.returncode,built.stdout,built.stderr)))
            print(json.dumps({'native_budget_fixture_sha256':hashlib.sha256(cls.library.read_bytes()).hexdigest(),
                              'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                              'compiler_sha256':hashlib.sha256(Path(compiler).read_bytes()).hexdigest(),
                              'compile_command':[compiler,'-shared','-O2',str(source),'-o',str(cls.library)]}))
            cls.counter_library=ctypes.CDLL(str(cls.library))
            cls.counter_library.cleanup_count.argtypes=[ctypes.c_uint64]
            cls.counter_library.cleanup_count.restype=ctypes.c_uint64

        @classmethod
        def tearDownClass(cls): cls.directory.cleanup()

        def setUp(self): self.counter_library.cleanup_count(1)

        def setup_callback(self,body,limit=None,hook=False,twice=False):
            import json
            vm=Interpreter(stdout=io.StringIO(),allow_native=True)
            host=GraphicsHost(vm,lambda event:None,budget_policy=BudgetPolicy(limit,64))
            self.addCleanup(host.close)
            source="密 取 外言 '如:密'. 观 取 外言 '如:观'. 图 取 观 其 画布 64 64. 库 取 密 其 动态库 "+json.dumps(str(self.library),ensure_ascii=False)+". 签 取 密 其 签名 (密 其 i64) ([(密 其 u64)]) 'cdecl'. 原生调 取 库 其 绑定 'invoke_callback' (密 其 签名 (密 其 i64) ([(密 其 指针),(密 其 u64)]) 'cdecl'). 次数 取 [0]. 结果 取 []. 回 取 密 其 回调 签 (算 值: 次数[0] 取 次数[0]+1. "+body+" 法) (-9). "
            if twice:
                source=source.replace("绑定 'invoke_callback'", "绑定 'invoke_twice'")
            if hook is True: source+='回 其 失败时 原生调 ([回,0]). '
            if hook=='increment':
                source+="唤醒 取 库 其 绑定 'cleanup_increment' (密 其 签名 (密 其 无值) ([(密 其 u64)]) 'cdecl'). 回 其 失败时 唤醒 ([1]). "
            if hook in ('reentry','invalid'):
                source+="旁库 取 密 其 动态库 "+json.dumps(str(self.library),ensure_ascii=False)+". 唤醒 取 旁库 其 绑定 'cleanup_then_callback' (密 其 签名 (密 其 i64) ([(密 其 指针),(密 其 u64)]) 'cdecl'). 回 其 失败时 唤醒 ([回,0]). "
                if hook=='invalid': source+='旁库 其 关闭. '

            source+='图 其 每帧 (作 帧: 结果 其 增 (((原生调 其 调用 [回,2]) 其 值) 其 数). 为).'
            vm.execute(parse(source))
            return vm,host

        def test_real_native_reentry_shares_event_budget(self):
            vm,host=self.setup_callback('若 值 其 数 == 0 则 得 1. 然 得 (((原生调 其 调用 [回,(值 其 数)-1]) 其 值) 其 数)+1.')
            host.handle({'type':'frame'})
            self.assertEqual(vm.global_scope.values['结果'],[3.0])
            self.assertEqual(vm.global_scope.values['次数'],[3.0])
            self.assertGreaterEqual(dict(host.budget_snapshot.counts)['call'],3)
            self.assertTrue(host.budget_snapshot.closed)
            self.assertIsNone(current_budget())

        def assert_native_exhaustion(self,hook):
            vm,host=self.setup_callback('循 10000 次 环 得 1.',limit=1000,hook=hook)
            from contextlib import redirect_stderr
            stderr=io.StringIO()
            with redirect_stderr(stderr):
                with self.assertRaises(BudgetExceeded) as caught: host.handle({'type':'frame'})
            self.assertNotIn('Exception ignored',stderr.getvalue())
            self.assertEqual(caught.exception.kind,'work')
            self.assertEqual(vm.global_scope.values['次数'],[1.0])
            self.assertEqual(vm.global_scope.values['结果'],[])
            self.assertEqual((vm.structure_depth,vm.depth,vm.call_state),(0,0,[0]))
            self.assertEqual(vm._native_context.callback_depth,0)
            self.assertIsNone(current_budget())
            self.assertIsNone(host.canvas)

        def test_native_fallback_cannot_swallow_sticky_budget(self):
            self.assert_native_exhaustion(False)

        def test_native_failure_hook_cannot_reenter_user_ru_after_exhaustion(self):
            self.assert_native_exhaustion(True)

        def test_sticky_cleanup_executes_once_even_if_native_calls_callback_twice(self):
            vm,host=self.setup_callback('循 10000 次 环 得 1.',limit=1000,hook='increment',twice=True)
            with self.assertRaises(BudgetExceeded): host.handle({'type':'frame'})
            self.assertEqual(self.counter_library.cleanup_count(0),1)
            self.assertEqual(vm.global_scope.values['次数'],[1.0])

        def test_sticky_cleanup_may_run_native_but_not_reenter_ru(self):
            vm,host=self.setup_callback('循 10000 次 环 得 1.',limit=1000,hook='reentry')
            with self.assertRaises(BudgetExceeded): host.handle({'type':'frame'})
            self.assertEqual(self.counter_library.cleanup_count(0),1)
            self.assertEqual(vm.global_scope.values['次数'],[1.0])
            self.assertEqual(vm._native_context.callback_depth,0)

        def test_invalid_cleanup_resource_cannot_replace_first_budget_error(self):
            from rulang.native_runtime import NativeCallback
            seen=[];original=NativeCallback.dispatch
            def dispatch(callback,*args):
                seen.append(current_budget())
                return original(callback,*args)
            vm,host=self.setup_callback('循 10000 次 环 得 1.',limit=1000,hook='invalid')
            with patch.object(NativeCallback,'dispatch',dispatch):
                with self.assertRaises(BudgetExceeded) as caught: host.handle({'type':'frame'})
            self.assertTrue(seen)
            self.assertIs(caught.exception,seen[0].error)
            self.assertEqual(self.counter_library.cleanup_count(0),0)
            self.assertEqual(vm._native_context.callback_depth,0)

        def test_ordinary_panic_keeps_existing_failure_hook_reentry_semantics(self):
            vm,host=self.setup_callback("卒 'ordinary panic'.",hook='reentry')
            host.handle({'type':'frame'})
            self.assertEqual(vm.global_scope.values['次数'],[2.0])
            self.assertEqual(vm.global_scope.values['结果'],[-9.0])
            self.assertEqual(self.counter_library.cleanup_count(0),1)
            self.assertIsNone(host.budget_snapshot.first_exhaustion_kind)


if __name__=='__main__': unittest.main()
