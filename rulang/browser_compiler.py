"""Explicit, self-contained browser target; never used by the Node CLI.

Only bundled standard modules are read. The generated ES module receives a
small message host, not JavaScript source, DOM objects or server credentials.
"""
from pathlib import Path
import re

from .c_runtime import walk_nodes
from .frontend import RuError, parse, validate
from .js_compiler import JSCompiler, js
from .modules import ModuleGraph, STANDARD_MODULES, import_nodes, reject_generation_document, reject_renamed_import

# ModuleGraph keys must have the same canonical form as Compiler.root. On
# Windows an absolute slash path gains a drive and native separators when
# resolved; keeping the slash spelling would collect the same root AST twice.
ROOT = str(Path('/__rushu_browser__/root.ru').resolve())
ALLOWED_MODULES = frozenset(STANDARD_MODULES)
FORBIDDEN_NAMES = frozenset({'读', '件', '录', '件作成果', '读取', '显出', '错误'})
MAX_NODES = 20000


def browser_graph(code):
    reject_generation_document(code)
    graph = ModuleGraph(ROOT)
    graph.sources[ROOT] = code

    def visit(path, source):
        if path in graph:
            return
        try:
            program = parse(source)
            validate(program)
        except RuError as error:
            error.source_name = path
            raise
        graph[path] = program
        graph.sources[path] = source
        for n in walk_nodes(program):
            if n.kind in ('name', 'call', 'new') and n.data.get('name') in FORBIDDEN_NAMES:
                error = RuError('浏览器 JS 模式不支持文件、终端输入或主机会话；请使用 Python 模式', n.token.line, n.token.col, '能力错误')
                error.source_name = path
                raise error
        for n in import_nodes(program):
            requested = n.data['path']
            try:
                reject_renamed_import(requested)
            except RuError as error:
                error.line, error.col = n.token.line, n.token.col
                error.source_name = path
                raise
            if requested not in ALLOWED_MODULES:
                error = RuError('浏览器 JS 模式只允许内置标准外言，不读取本地文件：' + requested, n.token.line, n.token.col, '能力错误')
                error.source_name = path
                raise error
            resolved = str((Path(__file__).parent / 'stdlib' / STANDARD_MODULES[requested]).resolve())
            n.data['resolved'] = resolved
            if resolved not in graph:
                visit(resolved, Path(resolved).read_text(encoding='utf-8'))
    visit(ROOT, code)
    if sum(1 for _ in walk_nodes(graph)) > MAX_NODES:
        raise RuError('浏览器 JS 编译超过 20000 个语法节点；请缩短此代码格', category='能力错误')
    return graph


class BrowserJSCompiler(JSCompiler):
    supports_browser_graphics = True

    def __init__(self, program, source_name=ROOT, modules=None, full_runtime=True, *, origin=None):
        if modules is None:
            raise ValueError('BrowserJSCompiler requires a prevalidated browser module graph')
        self.origin = origin
        # Retain the shared runtime for predictable standard-library support.
        super().__init__(program, source_name, modules=modules, full_runtime=True)

    def source_label(self, path):
        if path == self.root:
            return self.origin.source_name if self.origin else '<如书 JS>'
        return 'ru-stdlib://' + Path(path).name

    def line(self, text):
        # Every loop iteration, including an empty infinite loop, is metered.
        super().line(text)
        if text.startswith('for') and text.endswith('{'):
            super().line('R.browserTick(m,' + getattr(self, '_budget_loc', '[1,1]') + ');')

    def block(self, statements, function=False):
        for statement in statements:
            if statement.kind != 'function':
                self.line(f'R.browserTick(m,{self.loc(statement)});')
            previous = getattr(self, '_budget_loc', '[1,1]')
            self._budget_loc = self.loc(statement)
            super().block([statement], function)
            self._budget_loc = previous

    def runtime(self):
        runtime = super().runtime()
        runtime = runtime.replace('/* RU_ARRAY_TICK */', 'browserTick(m,loc);')
        runtime = runtime.replace("  const fs = require('fs'), path = require('path');\n  const {TextDecoder} = require('util');\n", '')
        # Remove actual host I/O, not just its exported names.
        start = runtime.index('  let input = Buffer.alloc(0)')
        end = runtime.index('  /* RU_OPTIONAL_CONTEST_BEGIN */', start)
        runtime = runtime[:start] + '''  function inputAll(){throw new Error('浏览器 JS 模式不支持终端输入');}
  function ioMember(){return MISSING;}
  function read(m,args,loc){fail(m,'浏览器 JS 模式不支持读；请使用 Python 模式',loc);}
  function print(m,value,loc){browserOutput(m,display(value)+'\\n',loc);}
''' + runtime[end:]
        start = runtime.index('  class Writer {')
        end = runtime.index('  const helperParams', start)
        runtime = runtime[:start] + '  class Writer { flush(){} write(text){browserOutput(null,text,[1,1]);} }\n' + runtime[end:]
        runtime = re.sub(r'  function finish\(error\) \{.*?\n  \}', '  function finish(error){throw error;}', runtime, count=1, flags=re.S)
        # No file/stream capabilities are installed in browser module scopes.
        start = runtime.index("  for (const [name, fields] of [['件'")
        end = runtime.index('  const contestTypes', start)
        runtime = runtime[:start] + runtime[end:]
        runtime = runtime.replace("'__实用']);", "'__实用','__如观']);")
        runtime = runtime.replace('      const a = contestMember', '      const g = browserMember(m,receiver,name,args,loc); if (g !== MISSING) return g;\n      const a = contestMember')
        insertion = Path(__file__).with_name('browser_runtime.js').read_text(encoding='utf-8')
        runtime = runtime.replace('  return {NO_RETURN,', insertion + '\n  return {browserTick,browserDispatch,browserFlush,browserReset,NO_RETURN,')
        if re.search(r'\brequire\s*\(|\bprocess\.|\bBuffer\.|\bfs\.', runtime):
            raise RuntimeError('Browser runtime unexpectedly retained Node capabilities')
        return runtime

    def emit_entry(self):
        self.line('R.browserReset();')
        self.line(f'{self.module_ids[self.root]}();')
        # Notebook execution, like Python, does not implicitly call 元初.
        self.line('R.browserFlush();')
        self.line('return {dispatch(request){try{return R.browserDispatch(request);}catch(error){throw decorate(error);}},flush:R.browserFlush};')

    def compile(self):
        body = super().compile()
        origin = self.origin.metadata() if self.origin else {'kind': 'cell'}
        root = self.source_label(self.root)
        decorate = r'''function decorate(error) {
  const source_name=error.source || ROOT_SOURCE;
  const known=Number.isInteger(error.line)&&Number.isInteger(error.col);
  error.diagnostic={source_name,line:known?error.line:null,col:known?error.col:null,severity:'error',category:error.category||'运行错误',message:String(error.message||error),source:known&&source_name===ROOT_SOURCE?ROOT_META:{kind:'module'}};
  const escape=value=>String(value).replace(/[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028-\u202e\u2066-\u2069]/g,c=>({'\r':'\\r','\n':'\\n','\t':'\\t'}[c]||'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0')));
  const d=error.diagnostic; d.formatted=escape(d.source_name)+(known?':'+d.line+':'+d.col:'')+': error: '+escape(d.category)+'：'+escape(d.message);
  return error;
}'''.replace('ROOT_SOURCE', js(root)).replace('ROOT_META', js(origin))
        return 'export default function createRuntime(__ruHost) {\n' + decorate + '\ntry {\n' + body + '\n} catch(error) {throw decorate(error);}\n}\n'


def compile_browser(code, origin=None):
    graph = browser_graph(code)
    return BrowserJSCompiler(graph[ROOT], ROOT, modules=graph, origin=origin).compile()
