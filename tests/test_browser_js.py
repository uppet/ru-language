"""Explicit browser compilation, host semantics and authenticated transport."""
import hashlib
import http.client
import importlib.util
import json
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from rulang.browser_compiler import BrowserJSCompiler, compile_browser
from rulang.diagnostics import SourceOrigin
from rulang.frontend import RuError, parse
from rulang.js_compiler import JSCompiler
from rushu.browser_compile import compile_request
from rushu.kernel import KernelError
from rushu.server import MAX_BODY, make_server

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


def run_source(source, timeout=10):
    """以临时文件运行 JS 源码（Windows 命令行 ~8k 上限会截断 node -e 长参数）。"""
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / 'source.js'
        target.write_text(source, encoding='utf-8')
        return subprocess.run([NODE, str(target)], capture_output=True, text=True, timeout=timeout)


def request(code, **extra):
    return compile_request(dict(code=code, cell_id='格/一', execution_count=3, generation=7, **extra))


class BrowserCompilerTests(unittest.TestCase):
    @unittest.skipUnless(NODE, 'Node required')
    def test_windows_root_is_collected_once_and_runs_as_esm(self):
        # Model Windows resolving a slash-rooted synthetic filename to a drive
        # path even when this regression runs on a POSIX CI host. Load an
        # isolated compiler module so its ROOT initialization is tested too.
        from rulang import browser_compiler
        windows_root = PureWindowsPath('C:/__rushu_browser__/root.ru')
        slash_root = str(Path('/__rushu_browser__/root.ru'))
        resolve = Path.resolve

        def windows_resolve(path, *args, **kwargs):
            if str(path) in (slash_root, str(windows_root)):
                return windows_root
            return resolve(path, *args, **kwargs)

        spec = importlib.util.spec_from_file_location(
            'rulang._browser_compiler_windows_test', browser_compiler.__file__)
        isolated = importlib.util.module_from_spec(spec)
        code = """数学 取 外言 '如:数学'.
再取 取 外言 '如:数学'.
随机 取 外言 '如:随机'.
算 制 起 为 数:
    算 加 步 为 数: 得 起 + 步. 法
    得 算 值 为 数: 得 加 值. 法.
法
回调 取 制 40.
显 回调 2.
显 数学 其 正弦 0.
显 再取 其 余弦 0.
"""
        with patch.object(Path, 'resolve', windows_resolve):
            spec.loader.exec_module(isolated)
            self.assertEqual(isolated.ROOT, str(windows_root))
            graph = isolated.browser_graph(code)
            compiler = isolated.BrowserJSCompiler(graph[isolated.ROOT], isolated.ROOT, modules=graph)
            self.assertEqual(list(compiler.modules), list(graph))
            identities = [id(fn) for _, fn in compiler.all_functions]
            self.assertEqual(len(identities), len(set(identities)))
            javascript = compiler.compile()
            origin = SourceOrigin('rushu-js://independent/7/test/3.ru', 'cell', 'test', 3, 7, 'test-hash')
            error_javascript = isolated.compile_browser('显 1.\n显 1 / 0.', origin)
        symbols = re.findall(r'^function (ru_function_\d+)\(', javascript, re.M)
        self.assertEqual(len(symbols), len(set(symbols)))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target/'program.mjs').write_text(javascript, encoding='utf-8')
            (target/'error.mjs').write_text(error_javascript, encoding='utf-8')
            (target/'run.mjs').write_text(
                "import create from './program.mjs';import fail from './error.mjs';"
                "const events=[];create({emit:e=>events.push(e)});"
                "try{fail({emit:()=>{}});}catch(error){events.push({diagnostic:error.diagnostic});}"
                "console.log(JSON.stringify(events));", encoding='utf-8')
            proc = subprocess.run([NODE, str(target/'run.mjs')],
                capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        events = json.loads(proc.stdout)
        self.assertEqual(''.join(e.get('text', '') for e in events), '42\n0\n1\n')
        detail = events[-1]['diagnostic']
        self.assertEqual(detail['source_name'], origin.source_name)
        self.assertEqual(detail['source'], origin.metadata())
        self.assertEqual(detail['line'], 2)

    def test_module_boundary_before_any_file_read(self):
        for code in ("库 取 外言 '/etc/passwd'.", "若 不实 则 库 取 外言 '../private.ru'. 然"):
            with self.subTest(code=code), patch.object(Path, 'read_text', side_effect=AssertionError('must not read')):
                result = request(code)
                self.assertIn('error', result)
                self.assertNotIn('javascript', result)

    def test_default_cli_still_rejects_graphics(self):
        with self.assertRaisesRegex(RuError, '仅支持如书 Python'):
            JSCompiler(parse("观 取 外言 '如:观'."), '<test>')

    def test_browser_constructor_requires_safe_graph(self):
        with self.assertRaises(ValueError):
            BrowserJSCompiler(parse("库 取 外言 '/private.ru'."))

    def test_forbidden_capabilities(self):
        for code in ("显 读.", "件造 取 件 新 路径 为 '/tmp/x'.", "显 显出."):
            result=request(code)
            self.assertIn('error', result, code)

    def test_compile_diagnostic_identity(self):
        code='显 不存在.'
        result=request(code)
        # Unknown plain values are runtime errors, so use a syntax error.
        result=request('显 (.')
        detail=result['diagnostic']
        self.assertEqual(detail['source']['cell_id'], '格/一')
        self.assertEqual(detail['source']['execution_count'], 3)
        self.assertEqual(detail['source']['generation'], 7)
        self.assertEqual(detail['source']['source_version'], hashlib.sha256('显 (.'.encode()).hexdigest())
        self.assertTrue(detail['source_name'].startswith('rushu-js://'))
        self.assertNotIn('/workspace/', result['error'])

    def test_invalid_requests(self):
        for data in ({},dict(code='显 1.',cell_id='a',execution_count=True,generation=1),dict(code='显 1.',cell_id='a',execution_count=1,generation=0),dict(code='x'*200001,cell_id='a',execution_count=1,generation=1)):
            with self.subTest(data=str(data)[:80]), self.assertRaises(KernelError):compile_request(data)

    def test_slots_release_and_busy(self):
        with patch('rushu.browser_compile._COMPILE_SLOTS') as slots:
            slots.acquire.return_value=False
            with self.assertRaises(KernelError) as caught:request('显 1.')
            self.assertEqual(caught.exception.status,429)
            slots.release.assert_not_called()

    def test_no_node_or_evaluator_in_output(self):
        result=request("观 取 外言 '如:观'.\n数库 取 外言 '如:数学'.\n随机 取 外言 '如:随机'.\n显 数库 其 正弦 0.")
        self.assertNotRegex(result['javascript'], r'\brequire\s*\(|\bprocess\.|\bBuffer\.|\bfs\.|\beval\s*\(|new Function')
        self.assertTrue(result['javascript'].startswith('export default function'))

    @unittest.skipUnless(NODE, 'Node required')
    def run_js(self, code, tail=''):
        result=request(code)
        self.assertNotIn('error', result, result)
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'program.mjs';target.write_text(result['javascript'],encoding='utf-8')
            runner=Path(directory)/'run.mjs'
            runner.write_text("import create from './program.mjs';const events=[];let runtime;try {runtime=create({emit:e=>events.push(e)});"+tail+"}catch(error){events.push({type:'error',diagnostic:error.diagnostic,message:error.message});}console.log(JSON.stringify(events));",encoding='utf-8')
            proc=subprocess.run([NODE,str(runner)],capture_output=True,text=True,timeout=10)
            self.assertEqual(proc.returncode,0,proc.stderr)
            return json.loads(proc.stdout)

    def test_solar_animation_pause_resume_60fps(self):
        code=json.loads((ROOT/'rushu/examples/solar-system-math.rushu.json').read_text())['cells'][1]['source'].replace('图 其 帧率 20.','图 其 帧率 60.')
        events=self.run_js(code,"const canvas_id=events.at(-1).canvas_id;runtime.dispatch({canvas_id,event:{type:'frame'}});runtime.dispatch({canvas_id,event:{type:'mouse_move',x:370,y:390}});runtime.dispatch({canvas_id,event:{type:'mouse_move',x:0,y:0}});")
        self.assertTrue(all(e['type']=='graphics' for e in events),events[-1])
        self.assertEqual([e['running'] for e in events],[True,True,False,True])
        self.assertTrue(all(e['fps']==60 for e in events))
        self.assertNotEqual(events[0]['commands'],events[1]['commands'])
        self.assertTrue(any(c.get('text')=='太阳' for c in events[2]['commands']))

    def test_math_random_closures_maps(self):
        code="""数学 取 外言 '如:数学'.
随机 取 外言 '如:随机'.
源 取 随机 其 造源 42.
显 数学 其 正弦 0.
显 数学 其 余弦 0.
状态 取 [0].
加 取 作: 状态[0] 取 状态[0] + 1. 为.
加(). 加().
显 状态[0].
"""
        events=self.run_js(code)
        self.assertEqual(''.join(e.get('text','') for e in events),'0\n1\n2\n')

    def test_existing_examples_match_python(self):
        for name in ('closures.ru','objects.ru','maps_facts.ru','practical_libraries.ru'):
            with self.subTest(name=name):
                path=ROOT/'examples'/name
                events=self.run_js(path.read_text(encoding='utf-8'))
                self.assertFalse(any(e['type']=='error' for e in events),events[-1])
                native=subprocess.run([sys.executable,'-m','rulang','run',str(path)],cwd=ROOT,capture_output=True,text=True,timeout=10)
                self.assertEqual(native.returncode,0,native.stderr)
                self.assertEqual(''.join(e.get('text','') for e in events),native.stdout)

    def test_canvas_ids_unique_across_runtime_instances(self):
        events=self.run_js("观 取 外言 '如:观'. 图 取 观 其 画布 100 100.","create({emit:e=>events.push(e)});")
        self.assertNotEqual(events[0]['canvas_id'],events[1]['canvas_id'])

    def test_formatted_errors_escape_controls(self):
        events=self.run_js('卒 "line\\nnext".')
        self.assertIn('\\n',events[-1]['diagnostic']['formatted'])
        self.assertNotIn('\n',events[-1]['diagnostic']['formatted'])

    def test_runtime_source_line_preserved(self):
        events=self.run_js('值 取 1.\n显 值 / 0.')
        detail=events[-1]['diagnostic'];self.assertEqual(detail['line'],2)
        self.assertEqual(detail['source']['cell_id'],'格/一')

    def test_callback_error_identity(self):
        code="观 取 外言 '如:观'.\n图 取 观 其 画布 100 100.\n图 其 每帧 (作 帧: 显 1 / 0. 为)."
        events=self.run_js(code,"runtime.dispatch({canvas_id:events.at(-1).canvas_id,event:{type:'frame'}});")
        self.assertEqual(events[-2]['type'],'graphics_closed')
        self.assertEqual(events[-1]['diagnostic']['line'],3)
        self.assertEqual(events[-1]['diagnostic']['source']['execution_count'],3)

    def test_empty_loop_budget_and_line(self):
        events=self.run_js('显 1.\n循\n环')
        self.assertIn('500000',events[-1]['message'])
        self.assertEqual(events[-1]['diagnostic']['line'],2)

    def test_exact_step_budget_boundary_and_observed_count(self):
        # One loop-statement tick plus one tick per iteration. Use the real
        # generated counter and production threshold, with no clock claims.
        for iterations in (499998, 499999):
            with self.subTest(iterations=iterations):
                self.assertEqual(self.run_js(f'循 {iterations} 次\n环'), [])
        events = self.run_js('循 500000 次\n环')
        error = events[-1]
        self.assertEqual(error['message'],
                         '浏览器 JS 执行超过 500000 步预算（实际 500001 步，阈值 500000 步）；请简化代码后重跑')
        self.assertEqual(error['diagnostic']['line'], 1)
        self.assertEqual(error['diagnostic']['col'], 1)
        self.assertEqual(error['diagnostic']['source']['cell_id'], '格/一')
        self.assertNotIn('秒', error['message'])
        self.assertNotIn('内存', error['message'])

    def test_callback_step_diagnostic_still_closes_canvas(self):
        code = "观 取 外言 '如:观'.\n图 取 观 其 画布 100 100.\n图 其 每帧 (作 帧: 循 环 为)."
        events = self.run_js(code, "runtime.dispatch({canvas_id:events.at(-1).canvas_id,event:{type:'frame'}});")
        self.assertEqual(events[-2]['type'], 'graphics_closed')
        self.assertIn('实际 500001 步，阈值 500000 步', events[-1]['message'])
        self.assertEqual(events[-1]['diagnostic']['line'], 3)

    def test_empty_frame_clears_previous(self):
        code="观 取 外言 '如:观'. 图 取 观 其 画布 100 100. 图 其 背景 '#112233'. 图 其 每帧 (作 帧: 完. 为)."
        events=self.run_js(code,"runtime.dispatch({canvas_id:events.at(-1).canvas_id,event:{type:'frame'}});")
        self.assertEqual(len(events[0]['commands']),1)
        self.assertEqual(events[-1]['commands'],[])

    def test_command_budget_closes_canvas(self):
        code="观 取 外言 '如:观'. 图 取 观 其 画布 100 100. 图 其 每帧 (作 帧: 循 2049 次 图 其 矩形 0 0 1 1. 环 为)."
        events=self.run_js(code,"runtime.dispatch({canvas_id:events.at(-1).canvas_id,event:{type:'frame'}});")
        self.assertIn('2048',events[-1]['message']);self.assertEqual(events[-2]['type'],'graphics_closed')

    def test_invalid_fps_and_prototype_not_exposed(self):
        for suffix in ('图 其 帧率 61.', '显 图 其 constructor.', '显 图 其 __proto__.'):
            events=self.run_js("观 取 外言 '如:观'. 图 取 观 其 画布 100 100. "+suffix)
            self.assertEqual(events[-1]['type'],'error')


class BrowserCompileHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        for name in ('index.html','js-worker.mjs'):(Path(self.directory.name)/name).write_text('// test')
        self.server=make_server(token='browser-compile-test-abcdefghijklmnop',static_dir=self.directory.name)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.thread.join();self.server.server_close();self.directory.cleanup()

    def send(self,path='/api/compile',method='POST',headers=None,raw=None):
        connection=http.client.HTTPConnection(*self.server.server_address,timeout=5)
        body=json.dumps(dict(code='显 1.',cell_id='test',execution_count=1,generation=1)) if raw is None else raw
        hs={'Content-Type':'application/json','X-Rushu-Token':self.server.token,'Origin':self.server.origin};hs.update(headers or {})
        connection.request(method,path,body=body if method=='POST' else None,headers=hs)
        response=connection.getresponse();result=response.status,dict(response.getheaders()),response.read();connection.close();return result

    def test_authenticated_compilation_and_no_session(self):
        status,headers,body=self.send();self.assertEqual(status,200)
        self.assertIn('javascript',json.loads(body));self.assertNotIn(self.server.token,body.decode())
        self.assertEqual(self.server.sessions.sessions,{})

    def test_auth_origin_method_query_body_limits(self):
        self.assertEqual(self.send(headers={'X-Rushu-Token':'wrong'})[0],401)
        self.assertEqual(self.send(headers={'Origin':'http://evil.example'})[0],403)
        self.assertEqual(self.send(method='GET')[0],405)
        self.assertEqual(self.send(path='/api/compile?x=1')[0],400)
        self.assertEqual(self.send(raw='',headers={'Content-Length':str(MAX_BODY+1)})[0],413)

    def test_worker_csp_separate_from_page(self):
        _,headers,_=self.send(path='/js-worker.mjs',method='GET')
        csp=headers['Content-Security-Policy'];self.assertIn("script-src blob:",csp);self.assertIn("connect-src 'none'",csp);self.assertIn("worker-src 'none'",csp)
        _,headers,_=self.send(path='/',method='GET');csp=headers['Content-Security-Policy']
        self.assertIn("worker-src 'self'",csp);self.assertNotIn('blob:',csp);self.assertNotIn('unsafe-eval',csp)
