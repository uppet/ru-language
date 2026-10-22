"""PureRu helper development gates; NOT real LLVM/stage3 acceptance.

The C-seeded driver parses application text only with bootstrap/compiler.ru.
Python frontend/Mi lowering is used solely for independent expected output.
"""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/dense'
EFFECTS = ['borrow-read', 'no-escape', 'no-callback', 'no-gc', 'may-fail']


def literal(value):
    if value is None: return '空'
    if isinstance(value, bool): return '真' if value else '假'
    if isinstance(value, str): return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float)): return str(value)
    if isinstance(value, list): return '['+','.join(map(literal, value))+']'
    if isinstance(value, dict): return '{'+','.join(literal(k)+':'+literal(v) for k,v in value.items())+'}'
    raise TypeError(value)


def spec(params, result='u32', **extra):
    return dict(params=params, result=result, effects=EFFECTS, **extra)


@unittest.skipUnless(shutil.which('cc'), 'C seed needed for helper development test')
class BootstrapDenseHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='ru-dense-helper-')
        cls.directory = Path(cls.tmp.name).resolve()
        cls.contracts = json.loads((FIXTURE/'markdown-dense-manifest.json').read_text(encoding='utf-8'))['functions']
        cls.contracts += [spec({'字节':'borrow_ro_utf8','始':'u32','终':'u32'}),
                          spec({'值':'u8'}, 'u8'), spec({'值':'u32'}),
                          spec({'字节':'borrow_ro_utf8','另字节':'borrow_ro_utf8'}),
                          spec({'字节':'borrow_ro_u8'}),
                          spec({'值':'u32'}, effects_override=True)]
        cls.contracts[-1]['effects'] = ['no-gc']
        cls.contracts += [spec({'值':'u32'},locals={'未知':'u8'}),
                          spec({'值':'u32'},ranges=[{'view':'值','begin':'值','end':'值'}]),
                          spec({'值':'u32'},'void'),
                          spec({'值':'u32'},locals={'量':'u32'})]
        converted=[]
        for contract in cls.contracts:
            c=copy.deepcopy(contract)
            c['params']=list(map(list,c['params'].items()))
            c['locals']=list(map(list,c.get('locals',{}).items()))
            converted.append(c)
        harness=cls.directory/'driver.ru'
        harness.write_text("前端 取 外言 "+literal(str(ROOT/'bootstrap/compiler.ru'))+".\n"
            +"密核 取 外言 "+literal(str(ROOT/'bootstrap/dense_emit.ru'))+".\n"
            +"约列 取 "+literal(converted)+".\n"+'''算 元初 参数 为 句 阵:
    文件 取 参数[0]. 源 取 前端 其 读文 文件.
    状 取 {'词':(前端 其 词法 源 文件),'位':0,'深':0,'文件':文件,'函数':[],'类':[],'模块':0,'父':空}.
    体 取 前端 其 语块 状 ([]).
    约 取 约列[参数[1] 为 数].
    IR 取 密核 其 密降型 体[参数[2] 为 数] 约 文件.
    显 密核 其 密LLVM IR 参数[3]. 得 0.
法.
''',encoding='utf-8')
        cls.driver=cls.directory/'driver'
        built=subprocess.run([sys.executable,'-m','rulang','build',str(harness),'-o',str(cls.driver)],
                             cwd=ROOT,capture_output=True,text=True,timeout=180, encoding='utf-8')
        if built.returncode: raise AssertionError(built.stdout+built.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_helper(self,source,contract=5,function=0,symbol='ru_mi_kernel_0'):
        path=self.directory/'input.ru';path.write_text(source,encoding='utf-8')
        return subprocess.run([str(self.driver),str(path),str(contract),str(function),symbol],
                              capture_output=True,text=True,timeout=30, encoding='utf-8')

    def compare(self,source,contract=5,function=0):
        result=self.run_helper(source,contract,function)
        self.assertEqual(result.returncode,0,result.stderr)
        from rulang.frontend import parse
        from rulang.mi_source import SourceLowerer
        from rulang.mi_llvm import lower
        c=copy.deepcopy(self.contracts[contract])
        c['params']={n:'borrow_ro_u8' if t=='borrow_ro_utf8' else t for n,t in c['params'].items()}
        ir=SourceLowerer(parse(source)[function],c,str(self.directory/'input.ru')).run()
        expected=lower(ir,'ru_mi_kernel_0')
        # Blank lines only: all opcodes, CFG, spans, names and ABI must match.
        normalize=lambda text:'\n'.join(line for line in text.splitlines() if line.strip())
        self.assertEqual(normalize(result.stdout),normalize(expected))
        self.assertNotIn('@rul_',result.stdout)
        self.assertNotIn('call ',result.stdout)
        return result.stdout

    def test_exact_five_wij_algorithms(self):
        source=(FIXTURE/'markdown_ascii_kernel.ru').read_text(encoding='utf-8')
        for i in range(5):
            with self.subTest(kernel=i): self.compare(source,i,i)

    def test_names_are_not_special_cased(self):
        self.compare('算 改名后 字节 始 终: 得 字节 其 量. 法')
        self.compare('算 又改名 字节 始 终: 得 终-始. 法')

    def test_short_circuit_truth_and_checked_reads(self):
        self.compare('算 工 字节 始 终: 若 0 或 字节[始] == 0 则 得 终. 然 得 始. 法')
        self.compare('算 工 字节 始 终: 若 非 (字节[始]) 且 真 则 得 终. 然 得 始. 法')

    def test_u8_overflow_and_subtraction(self):
        self.compare('算 工 值: 得 值+1. 法',6)
        self.compare('算 工 值: 得 值-1. 法',6)

    def test_nested_loop_break_return_and_elif(self):
        self.compare('算 工 字节 始 终: 循 (终-始) 次 循 (终-始) 次 若 始 == 终 则 得 始. 另若 终 == 0 则 破. 另 得 终. 然 环 破. 环 得 始. 法')

    def test_bad_source_effects_types_and_initialization_fail_closed(self):
        cases=[('作 工 值: 完. 为',7),('算 工 值: 得 读. 法',7),
               ('算 工 值: 得 值*2. 法',7),('算 工 值: 得 256. 法',6),
               ('算 工 值: 得 4294967296. 法',7),('算 工 值: 得 1.0. 法',7),
               ('算 工 值: 若 值 == 0 则 量 取 值. 然 得 量. 法',7),
               ('算 工 值: 循 值 次 量 取 值. 环 得 量. 法',7),
               ('算 工 值: 值 取 0. 得 值. 法',7),
               ('算 工 字节 始 终: 保存 取 字节. 得 始. 法',5),
               ('算 工 字节 始 终: 得 字节. 法',5),
               ('算 工 值: 循 破. 环 得 值. 法',7)]
        for source,contract in cases:
            with self.subTest(source=source):
                result=self.run_helper(source,contract)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(result.stdout,'')
                self.assertIn('自举密编译错误',result.stderr)

    def test_bad_contracts_fail_closed(self):
        cases=[('算 工 字节 另字节: 得 0. 法',8),('算 工 字节: 得 0. 法',9)]
        cases += [('算 工 值: 得 值. 法',i) for i in (10,11,12,13)]
        cases += [('算 工 别名: 得 别名. 法',7),('算 工 值 为 数: 得 值. 法',7)]
        for source,contract in cases:
            with self.subTest(contract=contract):
                result=self.run_helper(source,contract)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(result.stdout,'')
                self.assertIn('自举密编译错误',result.stderr)

    def test_symbol_injection_rejected(self):
        for symbol in ('','0bad','bad) {','汉字','bad\nret void'):
            result=self.run_helper('算 工 值: 得 值. 法',7,symbol=symbol)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(result.stdout,'')
            self.assertIn('无效密符号',result.stderr)

if __name__=='__main__': unittest.main()
