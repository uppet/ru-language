"""Current cache teaching contract and clean two-host nine-body notebook."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from rulang.frontend import parse, validate
from rulang.graphics_runtime import GraphicsHost
from rulang.interpreter import Interpreter
from rulang.prompts import export_prompt
import test_browser_js
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'rushu/examples/ruguan/cached-solar-system.ru'
class CacheExamplesTests(unittest.TestCase):
    def test_clean_notebook_and_python_example(self):
        source=SOURCE.read_text();book=json.loads((ROOT/'rushu/examples/cached-solar-system.rushu.json').read_text());code=[c for c in book['cells'] if c['type']=='code'];self.assertEqual(code[0]['source'],source)
        for cell in book['cells']:self.assertIsNone(cell['execution_count']);self.assertEqual(cell['outputs'],[])
        validate(parse(source));events=[];interpreter=Interpreter(stdout=io.StringIO());host=GraphicsHost(interpreter,events.append);self.addCleanup(host.close);interpreter.execute(parse(source));host.flush()
        first=events[-1];self.assertEqual(len(first['resources'][0]['commands']),515)
        host.handle({'type':'frame'});latest=events[-1];self.assertEqual(len(latest['commands']),28);self.assertEqual(latest['resources'],first['resources']);self.assertEqual(latest['commands'][0]['op'],'image')
        host.handle({'type':'mouse_move','x':370,'y':390});self.assertFalse(events[-1]['running']);host.handle({'type':'mouse_move','x':1,'y':1});self.assertTrue(events[-1]['running'])
    def test_both_exports_and_both_runtime_targets_include_same_cache_contract(self):
        for target in ('rushu','ruguan'):
            for backend in ('python','browser-js'):
                with self.subTest(target=target,backend=backend),tempfile.TemporaryDirectory() as tmp:
                    path=Path(tmp)/'prompt.txt';export_prompt(target,path,runtime_target=backend);prompt=path.read_text()
                    for fragment in ('随附规范版本：0.19.8','缓存 宽 高 绘制','贴图 图像 横 纵','2047','128 KiB','每帧内嵌定义的方案 A','不是跨机器冻结的像素'):
                        self.assertIn(fragment,prompt)
    @unittest.skipUnless(test_browser_js.NODE,'Node required')
    def test_browser_example_static_recipe_and_animation(self):
        events=test_browser_js.BrowserCompilerTests.run_js(self,SOURCE.read_text(),"const canvas_id=events.at(-1).canvas_id;runtime.dispatch({canvas_id,event:{type:'frame'}});")
        self.assertFalse([e for e in events if e['type']=='error'],events);scenes=[e for e in events if e['type']=='graphics'];self.assertEqual(scenes[0]['resources'],scenes[-1]['resources']);self.assertEqual(len(scenes[-1]['commands']),28)
