"""Text-anchor styles: interpreter state, backend parity and IPC boundaries."""
import io
import json
from pathlib import Path
import subprocess
import time
import unittest
from unittest.mock import patch

import test_browser_js
import test_graphics_state_parity
from rulang.frontend import RuError, parse
from rulang.graphics_runtime import GraphicsHost
from rulang.interpreter import Interpreter
from rushu.kernel import Session

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "观 取 外言 '如:观'. 图 取 观 其 画布 160 100. "
HORIZONTAL = {'左': 'left', '中': 'center', '右': 'right'}
VERTICAL = {'上': 'top', '中': 'middle', '下': 'bottom', '基线': 'alphabetic'}


def anchors(command):
    return command.get('align', 'left'), command.get('baseline', 'top')


class GraphicsTextAlignTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.interpreter = Interpreter(stdout=io.StringIO())
        self.host = GraphicsHost(self.interpreter, self.events.append)
        self.addCleanup(self.host.close)
        self.run_ru(PREFIX)

    def run_ru(self, source):
        self.interpreter.execute(parse(source))
        self.host.flush()

    def test_default_and_every_named_anchor_pair_are_frozen(self):
        self.run_ru("图 其 文字 '旧' 1 2.")
        self.assertEqual(self.events[-1]['commands'][0], {
            'op': 'text', 'x': 1, 'y': 2, 'text': '旧', 'color': '#4677ff', 'size': 16})
        for horizontal, align in HORIZONTAL.items():
            for vertical, baseline in VERTICAL.items():
                self.run_ru(f"图 其 文字对齐 纵向: '{vertical}' 横向: '{horizontal}'. 图 其 文字 '锚' 3 4.")
                self.assertEqual(anchors(self.events[-1]['commands'][-1]), (align, baseline))
        frozen = json.loads(json.dumps(self.events[-1]['commands']))
        self.run_ru("图 其 文字对齐 '左' '上'. 图 其 填色 '#11223380'. 图 其 字号 32.")
        self.assertEqual(self.events[-1]['commands'], frozen)

    def test_invalid_enums_are_atomic_and_do_not_change_commands_or_bytes(self):
        self.run_ru("图 其 文字对齐 '右' '基线'. 图 其 文字 '保留' 10 20.")
        canvas = self.host.canvas
        commands, size = list(canvas.commands), canvas.command_bytes
        invalid = [None, True, False, 0., 1., float('nan'), float('inf'), [], {}, '', 'left', 'top', '居中',
                   '中 ', ' 中', '中\n', '中\0', '__proto__', 'constructor', 'toString']
        for value in invalid:
            self.interpreter.global_scope.values['坏'] = value
            for args, axis in (("坏 '中'", '横向'), ("'中' 坏", '纵向')):
                with self.subTest(value=value, axis=axis), self.assertRaisesRegex(RuError, axis):
                    self.run_ru('图 其 文字对齐 ' + args + '.')
                self.assertEqual((canvas.text_align, canvas.text_baseline), ('right', 'alphabetic'))
                self.assertEqual(canvas.commands, commands)
                self.assertEqual(canvas.command_bytes, size)
        for args in ("'上' '中'", "'下' '中'", "'基线' '中'", "'中' '左'", "'中' '右'"):
            with self.subTest(args=args), self.assertRaises(RuError):
                self.run_ru('图 其 文字对齐 ' + args + '.')
            self.assertEqual((canvas.text_align, canvas.text_baseline), ('right', 'alphabetic'))
        self.run_ru("图 其 文字 '仍然' 10 20.")
        self.assertEqual(anchors(canvas.commands[-1]), ('right', 'alphabetic'))

    def test_exact_required_names_and_arity(self):
        for args in ('', "'中'", "'中' '中' '中'", "横向: '中'", "纵向: '中'",
                     "横: '中' 纵: '中'", "横向: '中' 基线: '中'",
                     "横向: '中' 纵向: '中' 多: '中'", "横向: '中' 横向: '右' 纵向: '上'"):
            with self.subTest(args=args), self.assertRaises(RuError):
                self.run_ru('图 其 文字对齐 ' + args + '.')
        self.assertEqual((self.host.canvas.text_align, self.host.canvas.text_baseline), ('left', 'top'))

    def test_nested_save_restore_keeps_style_geometry_and_alpha(self):
        self.run_ru("""
图 其 文字对齐 '右' '基线'. 图 其 填色 '#11223380'. 图 其 字号 24.
图 其 平移 5 6. 图 其 裁剪 0 0 20 30. 图 其 保存.
图 其 文字对齐 '中' '中'. 图 其 填色 空. 图 其 字号 30. 图 其 保存.
图 其 文字对齐 '左' '下'. 图 其 平移 7 8. 图 其 文字 '一' 0 0.
图 其 恢复. 图 其 文字 '二' 0 0.
图 其 恢复. 图 其 文字 '三' 0 0.
图 其 取消裁剪. 图 其 重置变换. 图 其 文字 '四' 0 0.
""")
        commands = self.events[-1]['commands']
        self.assertEqual([anchors(c) for c in commands], [
            ('left', 'bottom'), ('center', 'middle'), ('right', 'alphabetic'), ('right', 'alphabetic')])
        self.assertEqual([c['color'] for c in commands], ['', '', '#11223380', '#11223380'])
        self.assertEqual([c['size'] for c in commands], [30, 30, 24, 24])
        self.assertEqual(commands[0]['transform'], [1, 0, 0, 1, 12, 14])
        self.assertEqual(commands[2]['transform'], [1, 0, 0, 1, 5, 6])
        self.assertNotIn('transform', commands[3])
        self.assertNotIn('clips', commands[3])

    def test_canvas_replacement_resets_alignment(self):
        self.run_ru("图 其 文字对齐 '右' '下'. 图 取 观 其 画布 20 20. 图 其 文字 '新' 0 0.")
        command = self.events[-1]['commands'][0]
        self.assertNotIn('align', command)
        self.assertNotIn('baseline', command)


@unittest.skipUnless(test_browser_js.NODE, 'Node required for browser/Python text alignment parity')
class BrowserGraphicsTextAlignTests(unittest.TestCase):
    run_js = test_browser_js.BrowserCompilerTests.run_js
    compare = test_graphics_state_parity.GraphicsStateParityTests.compare

    def test_defaults_and_all_twelve_anchor_pairs_match_python(self):
        source = PREFIX + "图 其 文字 '默认' 1 2.\n"
        expected = [('left', 'top')]
        for horizontal, align in HORIZONTAL.items():
            for vertical, baseline in VERTICAL.items():
                source += f"图 其 文字对齐 纵向: '{vertical}' 横向: '{horizontal}'. 图 其 文字 '锚' 3 4.\n"
                expected.append((align, baseline))
        source += "图 其 文字对齐 '右' '基线'."
        commands = self.compare(source)[0]['commands']
        self.assertEqual([anchors(c) for c in commands], expected)
        self.assertNotIn('align', commands[0])
        self.assertNotIn('baseline', commands[0])

    def test_callback_style_persists_and_geometry_resets_without_rewriting_old_text(self):
        scenes = self.compare(PREFIX + """
图 其 填色 '#AABBCC80'. 图 其 文字对齐 '右' '基线'.
图 其 平移 5 6. 图 其 裁剪 0 0 20 20. 图 其 文字 '初' 0 0.
图 其 鼠标移动 (作 横 纵: 图 其 文字对齐 '中' '中'. 为).
图 其 每帧 (作 帧:
 图 其 背景 '#00000000'. 图 其 文字 '帧' 帧 20.
 图 其 保存. 图 其 文字对齐 '左' '下'. 图 其 填色 空.
 图 其 平移 7 8. 图 其 裁剪 0 0 1 1. 图 其 文字 '藏' 0 0.
 图 其 恢复. 图 其 文字 '复' 0 0.
为).
""", [{'type': 'mouse_move', 'x': 8, 'y': 9}, {'type': 'frame'}, {'type': 'frame'}])
        self.assertEqual(scenes[0]['commands'], scenes[1]['commands'])
        self.assertEqual(anchors(scenes[1]['commands'][0]), ('right', 'alphabetic'))
        for scene in scenes[2:]:
            background, first, hidden, restored = scene['commands']
            self.assertEqual(background, {'op': 'background', 'color': '#00000000'})
            self.assertEqual(anchors(first), ('center', 'middle'))
            self.assertEqual(anchors(hidden), ('left', 'bottom'))
            self.assertEqual(anchors(restored), ('center', 'middle'))
            self.assertEqual(first['color'], '#aabbcc80')
            self.assertEqual(hidden['color'], '')
            self.assertNotIn('transform', first)
            self.assertNotIn('clips', first)
            self.assertNotIn('transform', restored)
            self.assertNotIn('clips', restored)

    def test_alignment_stays_off_other_primitives(self):
        commands = self.compare(PREFIX + """
图 其 文字对齐 '右' '基线'. 图 其 背景 '#ffffff80'.
图 其 矩形 0 0 1 1. 图 其 椭圆 0 0 1 1. 图 其 线 0 0 1 1.
图 其 三角形 0 0 1 0 0 1. 图 其 多边形 [[0,0],[1,0],[0,1]].
""")[0]['commands']
        for command in commands:
            self.assertNotIn('align', command)
            self.assertNotIn('baseline', command)

    def test_wrong_types_unknown_enums_and_prototype_keys_fail_with_diagnostics(self):
        invalid = ['空', '真', '假', '0', '([])', "''", "'left'", "'top'", "'居中'",
                   "' 中'", "'中 '", '"中\\n"', "'constructor'", "'__proto__'", "'toString'"]
        for value in invalid:
            for args, axis in ((value + " '中'", '横向'), ("'中' " + value, '纵向')):
                with self.subTest(args=args):
                    events = self.run_js(PREFIX + '\n图 其 文字对齐 ' + args + '.')
                    self.assertEqual(events[-1]['type'], 'error', events)
                    self.assertIn(axis, events[-1]['message'])
                    self.assertEqual(events[-1]['diagnostic']['line'], 2)

    def test_exact_argument_names_arity_and_canvas_only_member(self):
        for call in ("图 其 文字对齐.", "图 其 文字对齐 '中'.", "图 其 文字对齐 '中' '上' '左'.",
                     "图 其 文字对齐 横向: '中'.", "图 其 文字对齐 纵向: '中'.",
                     "图 其 文字对齐 横: '中' 纵: '中'.", "图 其 文字对齐 横向: '中' 基线: '中'.",
                     "图 其 文字对齐 横向: '中' 横向: '右' 纵向: '上'.",
                     "图 其 文字对齐 横向: '中' 纵向: '上' 多: '右'.", "观 其 文字对齐 '中' '中'.",
                     "图 其 文字对齐 '上' '中'.", "图 其 文字对齐 '下' '中'.",
                     "图 其 文字对齐 '基线' '中'.", "图 其 文字对齐 '中' '左'.", "图 其 文字对齐 '中' '右'."):
            with self.subTest(call=call):
                events = self.run_js(PREFIX + call)
                self.assertEqual(events[-1]['type'], 'error', events)
                self.assertIn('diagnostic', events[-1])

    def test_browser_invalid_second_argument_is_atomic_in_the_real_member_implementation(self):
        # A small host harness retains the canvas after a member error so its
        # internal state can be checked; normal compiled execution is covered above.
        runtime = (ROOT / 'rulang/browser_runtime.js').read_text(encoding='utf-8')
        prelude = """
const assert=require('node:assert/strict');
const dict=()=>Object.create(null),own=(o,k)=>Object.hasOwn(o,k),MISSING=Symbol();
const builtins={values:dict()},__ruHost={emit:()=>{}};
const builtin=(name,fields,kind,key)=>({[key]:kind});
class Instance{constructor(type,fields){this.type=type;this.fields=fields;}} class Fn{}
const fail=(m,message)=>{throw new Error(message);};
const argsBind=(m,name,args,params)=>Object.fromEntries(params.map((key,i)=>[key,args[i][1]]));
"""
        checks = """
const m={},call=(receiver,name,...args)=>browserMember(m,receiver,name,args.map(x=>[null,x]),[1,1]);
const canvas=call(builtins.values.__如观,'画布',100,80),c=canvas.graphicsCanvas;
call(canvas,'文字对齐','右','基线');call(canvas,'文字','保留',1,2);
const commands=JSON.stringify(c.commands),bytes=c.bytes;
for(const bad of [null,true,false,0,NaN,Infinity,[],{},'', 'left','top','中 ','constructor','__proto__','toString']){
 for(const args of [[bad,'中'],['中',bad]]){
  assert.throws(()=>call(canvas,'文字对齐',...args),/文字对齐/);
  assert.equal(c.textAlign,'right');assert.equal(c.textBaseline,'alphabetic');
  assert.equal(JSON.stringify(c.commands),commands);assert.equal(c.bytes,bytes);
 }
}
console.log('atomic');
"""
        result = test_browser_js.run_source(prelude + runtime + checks)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'atomic\n')


class GraphicsTextAlignIPCTests(unittest.TestCase):
    def setUp(self):
        with patch.object(Session, '_start'):
            self.session = Session()
        self.scene = {'type': 'graphics', 'canvas_id': 'canvas', 'width': 20, 'height': 20,
                      'fps': 30, 'running': False, 'handlers': [], 'commands': []}
        self.text = {'op': 'text', 'x': 1, 'y': 2, 'text': '锚', 'color': '#12345680', 'size': 16}

    def test_ipc_accepts_missing_defaults_and_all_native_enums(self):
        for align in (None, 'left', 'center', 'right'):
            for baseline in (None, 'top', 'middle', 'bottom', 'alphabetic'):
                command = dict(self.text)
                if align is not None:
                    command['align'] = align
                if baseline is not None:
                    command['baseline'] = baseline
                self.session._accept_graphics(dict(self.scene, commands=[command]))

    def test_ipc_rejects_explicit_invalid_enums_and_nontext_fields_atomically(self):
        self.session._accept_graphics(self.scene)
        previous = self.session.graphics
        invalid = [None, True, 0, [], {}, '', '中', 'left ', 'middle\n', 'start', 'end',
                   'hanging', 'ideographic', 'constructor', '__proto__', 'toString']
        for key in ('align', 'baseline'):
            for value in invalid:
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'text alignment'):
                    self.session._accept_graphics(dict(self.scene, commands=[dict(self.text, **{key: value})]))
                self.assertIs(self.session.graphics, previous)
        for op in ('background', 'line', 'rect', 'ellipse', 'polygon'):
            for key, value in (('align', 'left'), ('baseline', 'top')):
                with self.subTest(op=op, key=key), self.assertRaisesRegex(ValueError, 'text alignment'):
                    self.session._accept_graphics(dict(self.scene, commands=[dict(self.text, op=op, **{key: value})]))


class GraphicsTextAlignSpawnTests(unittest.TestCase):
    def test_text_alignment_survives_spawn_frames_and_fresh_execution(self):
        session = Session()
        self.addCleanup(session.close)
        def ready():
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                result = session.poll()
                self.assertFalse([e for e in result['events'] if e['type'] == 'error'], result)
                self.assertNotEqual(result['state'], 'dead', result)
                if result['state'] == 'idle' and not result['graphics_busy']:
                    return result
                time.sleep(.01)
            self.fail('text alignment graphics did not become ready')
        session.execute(PREFIX + "图 其 文字对齐 '右' '基线'. 图 其 填色 '#11223380'. "
                        "图 其 文字 '初' 10 20. "
                        "图 其 每帧 (作 帧: 图 其 文字 '帧' 帧 20. 为).", 'alignment')
        result = ready()
        canvas_id = result['graphics']['canvas_id']
        for _ in range(2):
            scene = next(e for e in reversed(result['events']) if e['type'] == 'graphics')
            self.assertEqual(anchors(scene['commands'][0]), ('right', 'alphabetic'))
            self.assertEqual(scene['commands'][0]['color'], '#11223380')
            time.sleep(.05)
            session.dispatch_graphics(canvas_id, 'alignment', 1, 1, {'type': 'frame'})
            result = ready()
        scene = next(e for e in reversed(result['events']) if e['type'] == 'graphics')
        self.assertEqual(anchors(scene['commands'][0]), ('right', 'alphabetic'))
        session.execute("图 取 观 其 画布 20 20. 图 其 文字 '新' 0 0.", 'replacement')
        scene = next(e for e in reversed(ready()['events']) if e['type'] == 'graphics')
        self.assertNotIn('align', scene['commands'][0])
        self.assertNotIn('baseline', scene['commands'][0])
