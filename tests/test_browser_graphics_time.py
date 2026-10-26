"""Deterministic browser timing, compiled Ru semantics and host-clock safety."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import test_browser_js
from test_graphics_time import PREFIX, READ, FRAME, KEY, MOUSE

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(test_browser_js.NODE, 'Node required for browser canvas time')
class BrowserGraphicsTimeTests(unittest.TestCase):
    def run_timed(self, source, tail='', setup='', host='emit,nowSeconds'):
        result = test_browser_js.request(source)
        self.assertNotIn('error', result, result)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / 'program.mjs').write_text(result['javascript'], encoding='utf-8')
            (target / 'run.mjs').write_text(
                "import create from './program.mjs';import assert from 'node:assert/strict';"
                "const events=[];let now=100,calls=0,runtime;"
                "const emit=e=>events.push(e);"
                "const nowSeconds=()=>{calls++;if(now instanceof Error)throw now;return now;};"
                + setup + "try{runtime=create({" + host + "});"
                "const canvas_id=events.findLast(e=>e.type==='graphics')?.canvas_id;"
                "const send=(type,extra={})=>runtime.dispatch({canvas_id,event:{type,...extra}});"
                + tail + "}catch(error){events.push({type:'error',message:error.message,diagnostic:error.diagnostic});}"
                "console.log(JSON.stringify({events,calls}));", encoding='utf-8')
            proc = subprocess.run([test_browser_js.NODE, str(target / 'run.mjs')],
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def output(self, result):
        self.assertFalse([e for e in result['events'] if e['type'] == 'error'], result)
        return ''.join(e['text'] for e in result['events'] if e['type'] == 'output')

    def test_zero_initial_and_one_frozen_sample_per_callback(self):
        result = self.run_timed(PREFIX + f'显 {READ}. 显 {READ}. ' + FRAME,
                                "now=102.5;send('frame');now=103.25;send('frame');")
        self.assertEqual(self.output(result), '[0, 0, 0, 0, 0]\n' * 2 +
                         '[2.5, 0, 2.5, 0, 1]\n[3.25, 0.75, 3.25, 0.75, 2]\n')
        self.assertEqual(result['calls'], 3)

    def test_input_interleaving_and_uncapped_hidden_gap(self):
        result = self.run_timed(PREFIX + FRAME + KEY + MOUSE, """
now=101;send('frame');now=102;send('key_down',{key:'A'});
now=103;send('mouse_move',{x:2,y:3});now=110;send('frame');now=1210;send('frame');
""")
        self.assertEqual(self.output(result), '[1, 0, 1, 0, 1]\n[2, 0, 2, 0, 1]\n'
                         '[3, 0, 3, 0, 1]\n[10, 9, 10, 9, 2]\n[1110, 1100, 1110, 1100, 3]\n')
        self.assertEqual(result['calls'], 6)

    def test_static_input_canvas(self):
        result = self.run_timed(PREFIX + KEY,
                                "now=102;send('key_down',{key:'A'});now=200;send('key_down',{key:'A'});")
        self.assertEqual(self.output(result), '[2, 0, 2, 0, 0]\n[100, 0, 100, 0, 0]\n')
        self.assertEqual(result['calls'], 3)

    def test_running_controls_replace_callback_and_stop_resume(self):
        source = PREFIX + FRAME + f"""
图 其 按键 (作 键:
 若 键 == 'continue' 则 图 其 继续. 图 其 继续. 然
 若 键 == 'replace' 则 {FRAME} 然
 若 键 == 'stop' 则 图 其 停. 然
 显 {READ}.
为).
"""
        result = self.run_timed(source, """
now=101;send('frame');now=102;send('key_down',{key:'continue'});
now=103;send('key_down',{key:'replace'});now=110;send('frame');
now=111;send('key_down',{key:'stop'});now=112;send('key_down',{key:'continue'});
now=120;send('frame');now=121;send('frame');
now=122;send('key_down',{key:'stop'});now=130;send('key_down',{key:'replace'});
now=150;send('frame');
""")
        lines = self.output(result).splitlines()
        self.assertEqual(lines[0], '[1, 0, 1, 0, 1]')
        self.assertEqual(lines[3], '[10, 9, 10, 9, 2]')
        self.assertEqual(lines[6:8], ['[20, 0, 20, 0, 3]', '[21, 1, 21, 1, 4]'])
        self.assertEqual(lines[-1], '[50, 0, 50, 0, 5]')
        self.assertEqual(result['calls'], 12)

    def test_in_callback_resume_keeps_current_snapshot_and_resets_next(self):
        result = self.run_timed(PREFIX + f'''
图 其 每帧 (作 帧: 显 {READ}. 图 其 停. 图 其 继续. 显 {READ}. 为).
''', "now=101;send('frame');now=120;send('frame');")
        self.assertEqual(self.output(result), '[1, 0, 1, 0, 1]\n' * 2 + '[20, 0, 20, 0, 2]\n' * 2)
        self.assertEqual(result['calls'], 3)

    def test_new_canvas_resets_origin_and_rejects_old_id(self):
        result = self.run_timed(PREFIX + FRAME + f"""
图 其 按键 (作 键:
 新图 取 观 其 画布 20 20. 显 [新图 其 经过秒, 新图 其 间隔秒].
 新图 其 每帧 (作 帧: 显 [新图 其 经过秒, 新图 其 间隔秒, 帧]. 为).
为).
""", """
now=101;send('frame');now=110;send('key_down',{key:'A'});
assert.throws(()=>send('frame'),/失效/);assert.equal(calls,4);
now=112;runtime.dispatch({canvas_id:events.findLast(e=>e.type==='graphics').canvas_id,event:{type:'frame'}});
""")
        self.assertEqual(self.output(result), '[1, 0, 1, 0, 1]\n[0, 0]\n[2, 0, 1]\n')
        self.assertEqual(result['calls'], 5)

    def test_zero_argument_numeric_read_only_and_canvas_only(self):
        result = self.run_timed(PREFIX + '显 (图 其 经过秒) + (图 其 间隔秒) + 1.')
        self.assertEqual(self.output(result), '1\n')
        for name in ('经过秒', '间隔秒'):
            for call in (f'图 其 {name} 1.', f'图 其 {name} 秒: 1.',
                         f'图 其 {name} 取 1.', f'观 其 {name}.'):
                with self.subTest(call=call):
                    result = self.run_timed(PREFIX + call)
                    self.assertEqual(result['events'][-1]['type'], 'error', result)
                    self.assertIn('diagnostic', result['events'][-1])

    def test_rejected_events_do_not_sample_or_mutate_current_frame(self):
        result = self.run_timed(PREFIX + FRAME + KEY + MOUSE, """
for(const event of [null,[],{}, {type:'unknown'},{type:[]},{type:'key_down'},
 {type:'key_down',key:3},{type:'key_down',key:'a'.repeat(65)},
 {type:'mouse_move',x:NaN,y:0},{type:'mouse_move',x:true,y:0},
 {type:'mouse_move',x:0,y:0,button:true},{type:'mouse_up',x:0,y:0,button:0}]){
 assert.throws(()=>runtime.dispatch({canvas_id,event}));assert.equal(calls,1);
}
for(const key of ['time','timestamp','elapsed','delta','nowSeconds','经过秒','间隔秒']){
 assert.throws(()=>send('frame',{[key]:123}),/未知字段/);
 assert.throws(()=>runtime.dispatch({canvas_id,event:{type:'frame'},[key]:123}),/未知字段/);
 assert.equal(calls,1);
}
assert.throws(()=>runtime.dispatch({canvas_id:'old',event:{type:'frame'}}),/失效/);
now=101;send('frame');send('close');assert.throws(()=>send('frame'),/失效/);
""")
        self.assertEqual(self.output(result), '[1, 0, 1, 0, 1]\n')
        self.assertEqual(result['calls'], 2)

    def test_disabled_frame_and_close_do_not_sample(self):
        result = self.run_timed(PREFIX + FRAME + '图 其 停.', """
assert.throws(()=>send('frame'),/未启用/);send('close');assert.equal(calls,1);
""")
        self.assertEqual(self.output(result), '')
        self.assertEqual(result['calls'], 1)

    def test_invalid_host_samples_close_without_publishing_partial_frame(self):
        for bad in ('true', 'null', "'101'", '[]', '{}', 'NaN', 'Infinity', '-Infinity',
                    '-1', '99', "new Error('secret clock detail')"):
            with self.subTest(bad=bad):
                result = self.run_timed(PREFIX + FRAME, f'now={bad};send("frame");')
                self.assertEqual(result['calls'], 2)
                self.assertEqual([e['type'] for e in result['events']], ['graphics', 'graphics_closed', 'error'])
                error = result['events'][-1]
                self.assertIn('宿主单调时钟无效', error['message'])
                self.assertNotIn('secret', error['message'])
                self.assertIsNotNone(error['diagnostic']['line'])

    def test_backward_samples_after_input_are_rejected(self):
        for kind in ('frame', 'key_down'):
            result = self.run_timed(PREFIX + FRAME + KEY,
                                    "now=101;send('frame');now=120;send('key_down',{key:'A'});"
                                    f"now=119;send('{kind}'," + ("{key:'A'}" if kind == 'key_down' else '{}') + ');')
            self.assertEqual(result['events'][-2]['type'], 'graphics_closed')
            self.assertIn('宿主单调时钟无效', result['events'][-1]['message'])
            self.assertEqual(result['calls'], 4)

    def test_invalid_initial_clock_and_unavailable_fallback_report_cleanly(self):
        result = self.run_timed(PREFIX, setup='now=NaN;')
        self.assertEqual(result['calls'], 1)
        self.assertEqual(len(result['events']), 1)
        self.assertIn('宿主单调时钟无效', result['events'][0]['message'])
        for host in ('emit,nowSeconds:3', 'emit,nowSeconds:null', 'emit,nowSeconds:undefined'):
            result = self.run_timed(PREFIX, host=host)
            self.assertIn('宿主单调时钟无效', result['events'][0]['message'])
        result = self.run_timed(PREFIX, host='emit', setup="Object.defineProperty(globalThis,'performance',{value:undefined,configurable:true});")
        self.assertIn('宿主单调时钟无效', result['events'][0]['message'])

    def test_failed_replacement_clock_preserves_existing_canvas_atomically(self):
        runtime = (ROOT / 'rulang/browser_runtime.js').read_text(encoding='utf-8')
        prelude = """
const assert=require('node:assert/strict');
const dict=()=>Object.create(null),own=(o,k)=>Object.hasOwn(o,k),MISSING=Symbol();
const builtins={values:dict()},events=[];let now=100,calls=0;
const __ruHost={emit:e=>events.push(e),nowSeconds:()=>{calls++;if(now instanceof Error)throw now;return now;}};
const builtin=(name,fields,kind,key)=>({[key]:kind});
class Instance{constructor(type,fields){this.type=type;this.fields=fields;}} class Fn{}
const fail=(m,message)=>{throw new Error(message);};
const argsBind=(m,name,args,params)=>Object.fromEntries(params.map((key,i)=>[key,args[i][1]]));
"""
        checks = """
const m={},call=(receiver,name,...args)=>browserMember(m,receiver,name,args.map(x=>[null,x]),[1,1]);
const old=call(builtins.values.__如观,'画布',100,80),c=old.graphicsCanvas;
call(old,'文字','保留',1,2);browserFlush();
const commands=JSON.stringify(c.commands),bytes=c.bytes,emitted=events.length;
for(const invalid of [NaN,Infinity,-1,99,new Error('secret')]){
 now=invalid;
 assert.throws(()=>call(builtins.values.__如观,'画布',20,20),/^Error: 如观宿主单调时钟无效；请重新运行$/);
 assert.equal(browserCanvas,c);assert.equal(c.closed,false);assert.equal(c.frame,0);
 assert.equal(JSON.stringify(c.commands),commands);assert.equal(c.bytes,bytes);
 assert.equal(events.length,emitted);assert.equal(call(old,'经过秒'),0);assert.equal(call(old,'间隔秒'),0);
}
now=110;const next=call(builtins.values.__如观,'画布',20,20);
assert.equal(c.closed,true);assert.equal(next.graphicsCanvas.origin,110);
assert.equal(call(next,'经过秒'),0);assert.equal(call(next,'间隔秒'),0);assert.equal(calls,7);
console.log('atomic');
"""
        result = test_browser_js.run_source(prelude + runtime + checks)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'atomic\n')

    def test_direct_create_emit_only_uses_real_monotonic_fallback(self):
        result = self.run_timed(PREFIX + FRAME, "send('frame');", host='emit')
        line = json.loads(self.output(result))
        self.assertGreaterEqual(line[0], 0)
        self.assertEqual(line[0], line[2])
        self.assertEqual(line[1:], [0, line[0], 0, 1])
        self.assertEqual(result['calls'], 0)

    def test_zero_equal_and_large_finite_clock_samples(self):
        result = self.run_timed(PREFIX + FRAME, "send('frame');now=1e308;send('frame');send('frame');", setup='now=0;')
        lines = [json.loads(line) for line in self.output(result).splitlines()]
        self.assertEqual(lines, [[0, 0, 0, 0, 1], [1e308, 1e308, 1e308, 1e308, 2], [1e308, 0, 1e308, 0, 3]])
        self.assertEqual(result['calls'], 4)

    def test_frozen_time_does_not_bypass_step_budget(self):
        result = self.run_timed(PREFIX + '''图 其 每帧 (作 帧:
循 若 (图 其 经过秒) > 0 则 破. 然 环 为).''', "send('frame');")
        self.assertEqual(result['calls'], 2)
        self.assertEqual(result['events'][-2]['type'], 'graphics_closed')
        self.assertIn('500000 步预算', result['events'][-1]['message'])

    def test_worker_provides_private_monotonic_clock(self):
        worker = (ROOT / 'rushu/static/js-worker.mjs').read_text(encoding='utf-8')
        self.assertIn('Object.freeze({emit,nowSeconds:()=>performance.now()/1000})', worker)
        self.assertNotIn('Date.now', worker)
