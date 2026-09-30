/* Standalone Ru JavaScript runtime. Generated programs contain direct JS
 * control flow; this file has no lexer, parser, AST walker, or evaluator. */
const R = (() => {
  'use strict';
  const fs = require('fs'), path = require('path');
  const {TextDecoder} = require('util');
  const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const dict = () => Object.create(null);
  const NO_RETURN = Symbol('no return'), MISSING = Symbol('missing');
  const reserved = new Set(['读','件','录','件作成果','读取','显出','错误','__竞赛']);
  class RuError extends Error {
    constructor(m, message, loc, category = '运行错误') {
      super(message); this.category = category;
      this.source = m ? m.path : '<源码>';
      this.line = loc && loc[0] || 1; this.col = loc && loc[1] || 1;
    }
  }
  class Panic extends RuError {
    constructor(m, reason, loc) { super(m, reason, loc, '未救之卒'); this.reason = reason; }
  }
  function fail(m, message, loc) { throw new RuError(m, message, loc); }
  class Scope {
    constructor(parent = null, kind = 'module') {
      this.parent = parent; this.kind = kind; this.values = dict(); this.declarations = dict();
    }
    find(name) {
      for (let s = this; s; s = s.parent) {
        if (own(s.values, name)) return [s.values[name], false];
        if (own(s.declarations, name)) return [s.declarations[name], true];
      }
      return [MISSING, false];
    }
    protected(name) {
      for (let s = this; s; s = s.parent) if (own(s.declarations, name)) return true;
      return false;
    }
    bind(name, value) {
      if (!own(this.values, name) && this.kind === 'function') {
        for (let s = this.parent; s && s.kind !== 'module'; s = s.parent) {
          if (own(s.values, name)) { s.values[name] = value; return value; }
        }
      }
      this.values[name] = value; return value;
    }
  }
  class Fn {
    constructor(owner, env, name, params, procedure, body, loc, receiver = null) {
      Object.assign(this, {owner, env, name, params, procedure, body, loc, receiver});
    }
  }
  class Type {
    constructor(owner, name, parentName, fields, methods, loc) {
      Object.assign(this, {owner, name, parentName, ownFields: fields, ownMethods: methods, loc});
      this.parent = null; this.fields = dict(); this.methods = dict(); this.state = 0;
    }
  }
  class Instance { constructor(type, fields) { this.type = type; this.fields = fields; } }
  class Pair { constructor(left, right) { this.left = left; this.right = right; } }
  class Module {
    constructor(source) {
      this.path = source; this.types = dict();
      const globals = new Scope();
      for (const name of Object.keys(builtins.values)) {
        const value = builtins.values[name];
        if (value instanceof Instance) {
          const copy = new Instance(value.type,dict());
          if (own(value,'fd')) copy.fd = value.fd;
          globals.values[name] = copy;
        } else globals.values[name] = value;
      }
      this.scope = new Scope(globals);
      this.lastCallProcedure = false; this.lastMemberProcedure = false;
    }
    exports() { return Object.assign(dict(), this.scope.values, this.types, this.scope.declarations); }
  }
  const builtinTypes = dict(), builtins = new Scope();
  function builtin(name, fields, kind, property) {
    const t = new Type(null, name, null, fields, [], [0,0]); t.state = 2;
    for (const [key, typ] of fields) t.fields[key] = [typ, null];
    t[property] = kind; return t;
  }
  for (const [name, fields] of [['件', [['路径','句']]], ['录', [['路径','句']]],
    ['件作成果', [['结果','句'],['值',''],['错误信息','句']]], ['输入流',[]], ['输出流',[]]]) {
    builtinTypes[name] = builtin(name, fields, name, 'ioKind');
    if (!name.endsWith('流')) builtins.values[name] = builtinTypes[name];
  }
  for (const [name, kind, fd] of [['读取','输入流',0],['显出','输出流',1],['错误','输出流',2]]) {
    const value = new Instance(builtinTypes[kind], dict()); value.fd = fd; builtins.values[name] = value;
  }
  const contestTypes = dict();
  for (const [kind, name] of [['helpers','竞赛工具'],['scanner','竞赛读流'],['writer','竞赛出流']])
    contestTypes[kind] = builtin(name, [], kind, 'contestKind');
  builtins.values.__竞赛 = new Instance(contestTypes.helpers, dict());

  // Format binary64 using 15 significant digits and round-to-even, matching
  // Python .15g (including halfway cases, exponent spelling, and negative zero).
  const bits = new DataView(new ArrayBuffer(8));
  const pow10 = n => 10n ** BigInt(n);
  function numberText(value) {
    if (Object.is(value, -0)) return '-0';
    if (Number.isInteger(value) && Math.abs(value) < 1e15) return String(value);
    const sign = value < 0 ? '-' : ''; value = Math.abs(value);
    if (!Number.isFinite(value)) return sign + (Number.isNaN(value) ? 'nan' : 'inf');
    bits.setFloat64(0, value); const hi = bits.getUint32(0), lo = bits.getUint32(4);
    const exp = (hi >>> 20) & 2047;
    let num = (BigInt(hi & 1048575) << 32n) | BigInt(lo), den = 1n;
    if (exp) num |= 1n << 52n;
    const binaryExp = (exp || 1) - 1023 - 52;
    if (binaryExp >= 0) num <<= BigInt(binaryExp); else den <<= BigInt(-binaryExp);
    let e = Math.floor(Math.log10(value));
    const atLeast = n => n >= 0 ? num >= den * pow10(n) : num * pow10(-n) >= den;
    while (!atLeast(e)) e--;
    while (atLeast(e + 1)) e++;
    const scale = 14 - e;
    let n = num, d = den;
    if (scale >= 0) n *= pow10(scale); else d *= pow10(-scale);
    let q = n / d, rem = n % d;
    if (rem * 2n > d || (rem * 2n === d && (q & 1n))) q++;
    if (q === 1000000000000000n) { q /= 10n; e++; }
    const digits = q.toString().replace(/0+$/, '');
    if (e < -4 || e >= 15) {
      const mantissa = digits[0] + (digits.length > 1 ? '.' + digits.slice(1) : '');
      return sign + mantissa + 'e' + (e < 0 ? '-' : '+') + String(Math.abs(e)).padStart(2, '0');
    }
    if (e < 0) return sign + '0.' + '0'.repeat(-e - 1) + digits;
    return sign + (digits.length <= e + 1 ? digits + '0'.repeat(e + 1 - digits.length) :
      digits.slice(0, e + 1) + '.' + digits.slice(e + 1));
  }
  function display(value) {
    const out = [], active = new Set(), stack = [[0, value]];
    while (stack.length) {
      const [op, v] = stack.pop();
      if (op === 1) { out.push(v); continue; }
      if (op === 2) { active.delete(v); continue; }
      if (v === null) out.push('空');
      else if (typeof v === 'number') out.push(numberText(v));
      else if (typeof v === 'string') out.push(v);
      else if (v instanceof Instance) out.push('<形 ' + v.type.name + '>');
      else if (v instanceof Type) out.push('<形 ' + v.name + '>');
      else if (v instanceof Module) out.push('<外言>');
      else if (v instanceof Fn) out.push('<' + (v.procedure ? '作' : '算') + ' ' + v.name + '>');
      else if (v instanceof Pair || Array.isArray(v)) {
        if (active.has(v)) { out.push('<循环>'); continue; }
        active.add(v); stack.push([2, v]);
        if (v instanceof Pair) {
          out.push('('); stack.push([1, ')'], [0, v.right], [1, ' 对 '], [0, v.left]);
        } else {
          out.push('['); stack.push([1, ']']);
          for (let i = v.length - 1; i >= 0; i--) { stack.push([0, v[i]]); if (i) stack.push([1, ', ']); }
        }
      } else throw new Error('unknown Ru value');
    }
    return out.join('');
  }
  function truth(v) {
    return v !== null && (typeof v === 'number' ? v !== 0 :
      (typeof v === 'string' || Array.isArray(v)) ? v.length !== 0 : true);
  }
  function equal(a, b) {
    const todo = [[a,b]], visited = new Map();
    while (todo.length) {
      const [x,y] = todo.pop(); if (x === y) continue;
      if (x instanceof Pair && y instanceof Pair) {
        let seen = visited.get(x); if (!seen) visited.set(x, seen = new Set());
        if (seen.has(y)) continue; seen.add(y); todo.push([x.left,y.left], [x.right,y.right]);
      } else return false;
    }
    return true;
  }
  // Cache only a bounded number of strings. Indices count Unicode codepoints.
  const strings = new Map();
  function chars(s) {
    let value = strings.get(s);
    if (!value) { value = Array.from(s); if (strings.size >= 16) strings.delete(strings.keys().next().value); strings.set(s,value); }
    return value;
  }
  function compareText(a,b) {
    const x = a[Symbol.iterator](), y = b[Symbol.iterator]();
    for (;;) { const p = x.next(), q = y.next();
      if (p.done || q.done) return p.done === q.done ? 0 : p.done ? -1 : 1;
      const d = p.value.codePointAt(0) - q.value.codePointAt(0); if (d) return d;
    }
  }
  function argsBind(m, name, args, params, loc, optional = false) {
    const result = dict();
    if (args.some(x => x[0] === null)) {
      if (args.some(x => x[0] !== null)) fail(m, '同一次调用不能混用位置实参与命名实参', loc);
      if (args.length !== params.length)
        fail(m, '函数「'+name+'」需要 '+params.length+' 个位置实参（'+params.join('、')+'），收到 '+args.length+' 个', loc);
      args.forEach((x,i) => { result[params[i]] = x[1]; }); return result;
    }
    for (const [key,value] of args) {
      if (own(result,key)) fail(m, '重复的实参：'+key, loc); result[key] = value;
    }
    if (optional && !args.length) return result;
    const missing = params.filter(k => !own(result,k)), unknown = Object.keys(result).filter(k => !params.includes(k));
    if (missing.length || unknown.length) {
      const detail = [];
      if (missing.length) detail.push('缺少「'+missing.join('、')+'」');
      if (unknown.length) detail.push('未知「'+unknown.join('、')+'」');
      fail(m, '函数「'+name+'」实参不匹配：'+detail.join('；'), loc);
    }
    return result;
  }
  function get(m,s,name,loc,raw = false) {
    if (name === '读') {
      if (raw) fail(m, '当前仅支持用户定义算／作的引用；内置「读」不能取引用', loc);
      return read(m,[],loc);
    }
    const [value,declared] = s.find(name);
    if (value !== MISSING) return !raw && declared ? call(m,value,[],loc) : value;
    if (own(m.types,name)) return m.types[name];
    fail(m, '未定义名称：'+name, loc);
  }
  function bind(m,s,name,value,loc) {
    if (s.protected(name) || own(m.types,name) || reserved.has(name))
      fail(m, '变量名不能与函数名、形名或内置名称重名', loc);
    return s.bind(name,value);
  }
  function fn(m,s,name,params,procedure,body,loc) { return new Fn(m,s,name,params,procedure,body,loc); }
  function declare(m,s,value,loc) {
    const name = value.name;
    if (own(s.values,name) || own(s.declarations,name) || own(m.types,name) || reserved.has(name))
      fail(m, '重复或保留的函数名称：'+name, loc || value.loc);
    s.declarations[name] = value; return value;
  }
  function type(m,name,parentName,fields,methods,loc) {
    if (own(m.types,name) || own(m.scope.values,name) || own(m.scope.declarations,name) || reserved.has(name))
      fail(m, '名称冲突：'+name,loc);
    return m.types[name] = new Type(m,name,parentName,fields,methods,loc);
  }
  function resolve(t) {
    if (t.state === 2) return t;
    if (t.state === 1) fail(t.owner, '形的继承形成循环', t.loc);
    t.state = 1;
    try {
      if (t.parentName) {
        const p = t.owner.types[t.parentName];
        if (!(p instanceof Type)) fail(t.owner, '未定义父形：'+t.parentName,t.loc);
        resolve(p); t.parent = p; t.fields = Object.assign(dict(),p.fields); t.methods = Object.assign(dict(),p.methods);
      } else { t.fields = dict(); t.methods = dict(); }
      for (const [name,typ] of t.ownFields) {
        if (own(t.fields,name) || own(t.methods,name)) fail(t.owner, '继承字段／方法重名：'+name,t.loc);
        t.fields[name] = [typ,t.owner];
      }
      for (const method of t.ownMethods) {
        const f = method instanceof Fn ? method : fn(t.owner,t.owner.scope,...method);
        if (own(t.fields,f.name)) fail(t.owner,'方法与字段重名：'+f.name,f.loc);
        if (own(t.methods,f.name)) {
          const old = t.methods[f.name];
          if (old.procedure !== f.procedure || JSON.stringify(old.params) !== JSON.stringify(f.params))
            fail(t.owner,'覆写方法「'+f.name+'」须保持参数名称、类型及算／作种类',f.loc);
        }
        t.methods[f.name] = f;
      }
      t.state = 2; return t;
    } catch (e) { t.state = 0; throw e; }
  }
  function matches(m,value,typ) {
    if (typ === '') return true;
    if (typ.endsWith(' 阵')) return Array.isArray(value) && value.every(x => matches(m,x,typ.slice(0,-2)));
    if (typ === '数') return typeof value === 'number';
    if (typ === '句') return typeof value === 'string';
    if (typ === '空') return value === null;
    if (typ === '阵') return Array.isArray(value);
    if (typ === '对') return value instanceof Pair;
    if (typ === '算' || typ === '作') return value instanceof Fn && value.procedure === (typ === '作');
    const expected = m && (m.types[typ] || m.scope.values[typ]) || builtinTypes[typ];
    if (!(expected instanceof Type) || !(value instanceof Instance)) return false;
    for (let t = value.type; t; t = t.parent) if (t === expected) return true;
    return false;
  }
  let depth = 0;
  function call(m,value,args,loc) {
    if (!(value instanceof Fn)) fail(m, '值不是算／作',loc);
    const owner = value.owner;
    if (value.params.some(([name]) => value.env.protected(name) || own(owner.types,name)))
      fail(owner,'参数名不能与函数名、形名或内置名称重名',value.loc);
    const bound = argsBind(m,value.name,args,value.params.map(x => x[0]),loc);
    const s = new Scope(value.env,'function');
    if (value.receiver !== null) s.values.其 = value.receiver;
    for (const [name,typ] of value.params) {
      if (!matches(owner,bound[name],typ)) fail(m,'实参「'+name+'」须为'+typ+'，请显式使用「为 '+typ+'」转换',loc);
      s.values[name] = bound[name];
    }
    if (depth >= 128) fail(m,'函数调用层数超过 128',loc);
    depth++;
    try {
      const result = value.body(s,value.receiver);
      if (result === NO_RETURN || result === undefined) {
        if (!value.procedure) fail(m,'函数「'+value.name+'」没有执行「得」',loc);
        m.lastCallProcedure = true; return '';
      }
      m.lastCallProcedure = value.procedure; return result;
    } finally { depth--; }
  }
  function boundMethod(value,receiver) {
    return new Fn(value.owner,value.env,value.name,value.params,value.procedure,value.body,value.loc,receiver);
  }
  function functionRef(m,value,procedure,loc) {
    if (!(value instanceof Fn) || value.procedure !== procedure) fail(m,'引用的算／作种类不匹配',loc);
    return value;
  }
  function ref(m,receiver,name,loc) {
    if (receiver instanceof Module) {
      const values = receiver.exports(); if (own(values,name)) return values[name];
    } else if (receiver instanceof Instance) {
      if (own(receiver.type.fields,name)) return receiver.fields[name];
      if (own(receiver.type.methods,name)) return boundMethod(receiver.type.methods[name],receiver);
    } else if (receiver instanceof Pair && (name === '囫' || name === '囵')) return name === '囫' ? receiver.left : receiver.right;
    else if ((Array.isArray(receiver) || typeof receiver === 'string') && name === '量') return typeof receiver === 'string' ? chars(receiver).length : receiver.length;
    fail(m,'无法取得用户定义算／作成员引用：'+name,loc);
  }
  function bounded(m,index,size,loc,endpoint = false) {
    if (typeof index !== 'number' || !Number.isFinite(index) || !Number.isInteger(index)) fail(m,'索引须为整数',loc);
    if (index < 0 || index > size - (endpoint ? 0 : 1)) fail(m,'索引越界：'+display(index)+'（长度 '+size+'）',loc);
    return index;
  }
  function index(m,receiver,i,loc) {
    if (typeof receiver === 'string') receiver = chars(receiver);
    if (!Array.isArray(receiver)) fail(m,'「位」／索引只适用于阵或句',loc);
    return receiver[bounded(m,i,receiver.length,loc)];
  }
  function slice(m,receiver,start,end,loc) {
    const string = typeof receiver === 'string'; if (string) receiver = chars(receiver);
    if (!Array.isArray(receiver)) fail(m,'「段」／切片只适用于阵或句',loc);
    const a = start === null ? 0 : bounded(m,start,receiver.length,loc,true);
    const b = end === null ? receiver.length : bounded(m,end,receiver.length,loc,true);
    if (a > b) fail(m,'切片起点不能大于终点',loc);
    const value = receiver.slice(a,b); return string ? value.join('') : value;
  }
  function setIndex(m,receiver,i,rhs,loc) {
    if (!Array.isArray(receiver)) fail(m,'只有阵元素可赋值；句不可变',loc);
    const offset = bounded(m,i,receiver.length,loc); return receiver[offset] = rhs();
  }
  function setField(m,receiver,name,rhs,loc) {
    if (!(receiver instanceof Instance) || !own(receiver.type.fields,name)) fail(m,'不可赋值的字段：'+name,loc);
    const value = rhs(), [typ,owner] = receiver.type.fields[name];
    if (value !== null && !matches(owner,value,typ)) fail(m,'字段「'+name+'」须为'+typ,loc);
    receiver.fields[name] = value; return value;
  }
  function construct(m,s,name,argsThunk,loc) {
    let t = m.types[name] || s.values[name];
    if (!t) { const found = s.find(name)[0]; if (found === MISSING) fail(m,'未定义形：'+name,loc); t = found; }
    if (!(t instanceof Type)) fail(m,'「'+name+'」不是形',loc);
    resolve(t); const fields = dict();
    for (const key of Object.keys(t.fields)) fields[key] = null;
    if (t.ioKind === '件') fields.路径 = '';
    if (t.ioKind === '录') fields.路径 = '.';
    if (t.ioKind === '件作成果') Object.assign(fields,{'结果':'成功','值':null,'错误信息':''});
    const provided = new Set();
    for (const [key,expression] of argsThunk()) {
      if (provided.has(key)) fail(m,'重复的字段实参：'+key,loc);
      if (!own(fields,key)) fail(m,'未知字段：'+key,loc);
      const value = typeof expression === 'function' ? expression() : expression;
      const [typ,owner] = t.fields[key];
      if (value !== null && !matches(owner,value,typ)) fail(m,'字段「'+key+'」须为'+typ,loc);
      fields[key] = value; provided.add(key);
    }
    return new Instance(t,fields);
  }
  function number(m,value,loc) {
    if (typeof value === 'number') return value;
    if (typeof value !== 'string') fail(m,'只有数或句可转换为数',loc);
    const v = value.replace(/^[ \t\r\n\v\f]+|[ \t\r\n\v\f]+$/g,'');
    if (!/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(v)) fail(m,'无法转换为数：'+value,loc);
    const result = Number(v); if (!Number.isFinite(result)) fail(m,'转换结果不是有限数',loc);
    return result;
  }
  function convert(m,value,target,loc) { return target === '阵' ? [value] : target === '句' ? display(value) : number(m,value,loc); }
  function unary(m,op,value,loc) {
    if (op === '非') return truth(value) ? 0 : 1;
    if (typeof value !== 'number') fail(m,'正负号只能用于数',loc);
    return op === '+' ? value : -value;
  }
  function binary(m,op,left,right,loc) {
    if (op === '对') return new Pair(left,right);
    if (op === '==') return equal(left,right) ? 1 : 0;
    if (op === '!=') return equal(left,right) ? 0 : 1;
    if (op === '含') {
      if (left instanceof Instance || left instanceof Module) return member(m,left,'含',()=>[[null,right]],loc);
      m.lastMemberProcedure = false;
      if (typeof left !== 'string' || typeof right !== 'string') fail(m,'「含」需要两个句',loc);
      return left.includes(right) ? 1 : 0;
    }
    if (['<','<=','>','>='].includes(op)) {
      if (typeof left !== typeof right || !['number','string'].includes(typeof left)) fail(m,'大小比较需要两个数或两个句',loc);
      const c = typeof left === 'string' ? compareText(left,right) : left === right ? 0 : left < right ? -1 : 1;
      return (op === '<' ? c < 0 : op === '<=' ? c <= 0 : op === '>' ? c > 0 : c >= 0) ? 1 : 0;
    }
    if (op === '+' && typeof left === 'string' && typeof right === 'string') return left + right;
    if (typeof left !== 'number' || typeof right !== 'number') fail(m,'算术运算需要两个数；「+」也可连接两个句',loc);
    if ((op === '/' || op === '%') && right === 0) fail(m,'除数不能为零',loc);
    const v = op === '+' ? left+right : op === '-' ? left-right : op === '*' ? left*right : op === '/' ? left/right : left%right;
    if (!Number.isFinite(v)) fail(m,'运算结果不是有限数',loc); return v;
  }
  function member(m,receiver,name,argsThunk,loc) {
    m.lastMemberProcedure = false;
    // Capture methods and callable fields before argument side effects.
    if (receiver instanceof Instance) {
      if (own(receiver.type.methods,name)) {
        const f = boundMethod(receiver.type.methods[name],receiver), args = argsThunk();
        const result = call(m,f,args,loc); m.lastMemberProcedure = f.procedure; return result;
      }
      if (own(receiver.type.fields,name)) {
        const value = receiver.fields[name], args = argsThunk();
        if (!args.length) return value;
        const result = call(m,value,args,loc); m.lastMemberProcedure = value.procedure; return result;
      }
    } else if (receiver instanceof Module) {
      const exports = receiver.exports();
      if (own(exports,name)) {
        const value = exports[name], args = argsThunk();
        if (args.length || own(receiver.scope.declarations,name)) {
          const result = call(m,value,args,loc); m.lastMemberProcedure = value.procedure; return result;
        }
        return value;
      }
    }
    const args = argsThunk();
    if (receiver instanceof Instance) {
      const a = contestMember(m,receiver,name,args,loc); if (a !== MISSING) return a;
      const b = ioMember(m,receiver,name,args,loc); if (b !== MISSING) return b;
    }
    if (receiver instanceof Pair && (name === '囫' || name === '囵')) {
      argsBind(m,name,args,[],loc); return name === '囫' ? receiver.left : receiver.right;
    }
    if (typeof receiver === 'string' || Array.isArray(receiver)) {
      if (name === '量') { argsBind(m,name,args,[],loc); return typeof receiver === 'string' ? chars(receiver).length : receiver.length; }
      if (name === '位') { const a = argsBind(m,name,args,['位'],loc); return index(m,receiver,a.位,loc); }
      if (name === '段') { const a = argsBind(m,name,args,['始','终'],loc); return slice(m,receiver,a.始,a.终,loc); }
      if (name === '含' && typeof receiver === 'string') {
        const a = argsBind(m,name,args,['句'],loc); if (typeof a.句 !== 'string') fail(m,'「含」需要两个句',loc);
        return receiver.includes(a.句) ? 1 : 0;
      }
      if (name === '增' && Array.isArray(receiver)) { const a = argsBind(m,name,args,['值'],loc); receiver.push(a.值); return receiver; }
    }
    fail(m,'未知成员：'+name,loc);
  }

  // Synchronous descriptor I/O preserves read-ahead across all input APIs and
  // validates each line independently, so a bad UTF-8 line cannot lose the next.
  const decoder = new TextDecoder('utf-8',{fatal:true,ignoreBOM:true});
  function invalid(message,errno = 22) { const e = new Error(message); e.errno = errno; return e; }
  function validText(value,label) {
    if (typeof value !== 'string') throw invalid(label+'须为句');
    if (value.includes('\0')) throw invalid(label+'不能含 NUL');
    for (let i = 0; i < value.length; i++) {
      const c = value.charCodeAt(i);
      if (c >= 0xd800 && c <= 0xdbff) {
        const next = value.charCodeAt(++i); if (!(next >= 0xdc00 && next <= 0xdfff)) throw invalid('文本不是有效的 UTF-8',84);
      } else if (c >= 0xdc00 && c <= 0xdfff) throw invalid('文本不是有效的 UTF-8',84);
    }
    return value;
  }
  function decode(buffer) {
    let result;
    try { result = decoder.decode(buffer); } catch (_) { throw invalid('文本不是有效的 UTF-8',84); }
    return validText(result,'文本');
  }
  let input = Buffer.alloc(0), inputOffset = 0, inputEOF = false;
  function inputLine() {
    const pieces = [];
    for (;;) {
      const end = input.indexOf(10,inputOffset);
      if (end >= 0) {
        pieces.push(input.subarray(inputOffset,end+1)); inputOffset = end+1;
        return decode(pieces.length === 1 ? pieces[0] : Buffer.concat(pieces));
      }
      if (inputOffset < input.length) pieces.push(input.subarray(inputOffset));
      inputOffset = 0; input = Buffer.alloc(0);
      if (inputEOF) return decode(Buffer.concat(pieces));
      const next = Buffer.allocUnsafe(65536); const count = fs.readSync(0,next,0,next.length,null);
      if (!count) inputEOF = true; else input = next.subarray(0,count);
    }
  }
  function inputAll() {
    const pieces = [input.subarray(inputOffset)]; input = Buffer.alloc(0); inputOffset = 0;
    if (!inputEOF) pieces.push(fs.readFileSync(0)); inputEOF = true;
    return decode(Buffer.concat(pieces));
  }
  function write(fd,text) {
    const data = Buffer.from(text,'utf8'); if (fs.writeSync(fd,data,0,data.length,null) !== data.length) throw invalid('写入不完整',5);
  }
  /* RU_OPTIONAL_IO_BEGIN */
  function ioResult(value = null,error = null,operation = 'I/O') {
    return new Instance(builtinTypes.件作成果, Object.assign(dict(), {
      '结果': error ? '失败' : '成功', '值': error ? null : value,
      '错误信息': error ? operation+': [errno '+(Math.abs(error.errno) || 5)+'] '+(error.message || 'I/O 失败') : ''
    }));
  }
  function ioBind(m,name,args,params,loc,optional = 0) {
    const minimum = params.length - optional, b = dict();
    if (args.some(x => x[0] === null)) {
      if (args.some(x => x[0] !== null)) fail(m,'同一次调用不能混用位置实参与命名实参',loc);
      if (args.length < minimum || args.length > params.length) fail(m,'方法「'+name+'」需要 '+minimum+' 至 '+params.length+' 个实参',loc);
      args.forEach((x,i) => { b[params[i]] = x[1]; }); return b;
    }
    for (const [key,value] of args) {
      if (!params.includes(key)) fail(m,'方法「'+name+'」未知实参：'+key,loc);
      if (own(b,key)) fail(m,'重复的实参：'+key,loc); b[key] = value;
    }
    for (const key of params.slice(0,minimum)) if (!own(b,key)) fail(m,'方法「'+name+'」缺少实参：'+key,loc);
    return b;
  }
  function filePath(receiver) {
    const p = validText(receiver.fields.路径,'路径'); if (!p) throw invalid('路径不能为空'); return p;
  }
  function fileIO(p,operation,content,append) {
    let fd = null, value = null, error = null;
    try {
      const c = fs.constants;
      fd = fs.openSync(p, (operation === '读' ? c.O_RDONLY : c.O_WRONLY | c.O_CREAT) |
        (append ? c.O_APPEND : 0) | (c.O_NONBLOCK || 0), 0o666);
      if (!fs.fstatSync(fd).isFile()) throw invalid('路径不是普通文件');
      if (operation === '读') value = decode(fs.readFileSync(fd));
      else { if (!append) fs.ftruncateSync(fd,0); write(fd,content); }
    } catch (e) { error = e; }
    finally { if (fd !== null) try { fs.closeSync(fd); } catch (e) { if (!error) error = e; } }
    return ioResult(value,error,operation);
  }
  const ioMethods = {'件':['读','写','在','除'],'录':['列'],'输入流':['读'],'输出流':['写']};
  function ioMember(m,receiver,name,args,loc) {
    const kind = receiver.type.ioKind;
    if (!ioMethods[kind] || !ioMethods[kind].includes(name)) return MISSING;
    const params = kind === '件' && name === '写' ? ['内容','追加'] : name === '写' ? ['内容'] : [];
    const b = ioBind(m,name,args,params,loc,kind === '件' && name === '写' ? 1 : 0);
    try {
      let content,append = 0;
      if (name === '写') {
        content = validText(b.内容,'内容'); if (own(b,'追加')) append = b.追加;
        if (typeof append !== 'number' || (append !== 0 && append !== 1)) throw invalid('追加须为数 0 或 1');
      }
      if (kind === '件') {
        const p = filePath(receiver);
        if (name === '读' || name === '写') return fileIO(p,name,content,!!append);
        if (name === '在') {
          try { return ioResult(fs.statSync(p).isFile() ? 1 : 0); }
          catch (e) { if (e.code === 'ENOENT' || e.code === 'ENOTDIR') return ioResult(0); throw e; }
        }
        const st = fs.lstatSync(p); if (!st.isFile() && !st.isSymbolicLink()) throw invalid('路径不是普通文件');
        fs.unlinkSync(p); return ioResult();
      }
      if (kind === '录') {
        const p = filePath(receiver), entries = [];
        const join = name => p + (p.endsWith(path.sep) || (path.sep === '\\' && p.endsWith('/')) ? '' : path.sep) + name;
        for (const raw of fs.readdirSync(p,{encoding:'buffer'})) {
          const name = decode(raw);
          try { if (fs.statSync(join(name)).isFile()) entries.push(name); }
          catch (e) { if (e.code !== 'ENOENT' && e.code !== 'ENOTDIR') throw e; }
        }
        entries.sort(compareText);
        return ioResult(entries.map(name => new Instance(builtinTypes.件,Object.assign(dict(),{'路径':join(name)}))));
      }
      if (name === '读') {
        const value = inputLine(); return ioResult(value === '' ? null : value.replace(/\n$/,'').replace(/\r$/,''));
      }
      write(receiver.fd,content); return ioResult();
    } catch (e) { return ioResult(null,e,name); }
  }
  /* RU_OPTIONAL_IO_END */
  function read(m,args,loc) {
    const b = argsBind(m,'读',args,['提示'],loc,true), prompt = own(b,'提示') ? b.提示 : '';
    if (typeof prompt !== 'string') fail(m,'输入提示须为句',loc);
    try { write(1,prompt); } catch (e) { fail(m,'输出失败：'+e.message,loc); }
    let value;
    try { value = inputLine(); } catch (e) { fail(m,'读取输入失败：'+e.message,loc); }
    if (value === '') fail(m,'输入结束（EOF）',loc);
    m.lastCallProcedure = false; return value.replace(/\n$/,'').replace(/\r$/,'');
  }
  function print(m,value,loc) {
    try { write(1,display(value)+'\n'); } catch (e) { if (e instanceof RuError) throw e; fail(m,'输出失败：'+e.message,loc); }
  }

  /* RU_OPTIONAL_CONTEST_BEGIN */
  class Scanner {
    constructor(text) { this.text = text; this.cursor = 0; }
    token() {
      const s = this.text; let p = this.cursor;
      while (p < s.length && ' \t\r\n\v\f'.includes(s[p])) p++;
      const start = p;
      while (p < s.length && !' \t\r\n\v\f'.includes(s[p])) p++;
      this.cursor = p; return start === s.length ? null : s.slice(start,p);
    }
    line() {
      const start = this.cursor; if (start === this.text.length) return null;
      let end = this.text.indexOf('\n',start);
      if (end < 0) { this.cursor = this.text.length; return this.text.slice(start); }
      this.cursor = end + 1; if (end > start && this.text[end-1] === '\r') end--;
      return this.text.slice(start,end);
    }
  }
  function scanner(text) { const value = new Instance(contestTypes.scanner,dict()); value.state = new Scanner(text); return value; }
  class Writer {
    constructor() { this.pending = Buffer.allocUnsafe(65536); this.size = 0; }
    flush() { if (this.size) { if (fs.writeSync(1,this.pending,0,this.size,null) !== this.size) throw invalid('写入不完整',5); this.size = 0; } }
    write(text) {
      // Bounded encoding chunks and complete codepoints at every flush.
      for (let start = 0; start < text.length;) {
        let end = Math.min(start + 16384,text.length);
        if (end < text.length && text.charCodeAt(end-1) >= 0xd800 && text.charCodeAt(end-1) <= 0xdbff) end--;
        const data = Buffer.from(text.slice(start,end),'utf8'); start = end;
        for (let offset = 0; offset < data.length;) {
          let limit = Math.min(data.length,offset + 65536 - this.size);
          while (limit < data.length && limit > offset && (data[limit] & 0xc0) === 0x80) limit--;
          if (limit === offset) { this.flush(); continue; }
          data.copy(this.pending,this.size,offset,limit); this.size += limit-offset; offset = limit;
          if (this.size === 65536) this.flush();
        }
      }
    }
  }
  const helperParams = {'读入':[],'扫句':['文'],'拆词':['文'],'拆行':['文'],'字列':['文'],'合句':['列','隔'],'排序':['列','比较'],'取整':['值'],'蓄出':[]};
  const scannerParams = {'词':[],'数':[],'行':[]}, writerParams = {'写':['内容'],'行':['值'],'清':[]};
  function contestText(m,value,label,loc) { try { return validText(value,label); } catch (e) { fail(m,e.message,loc); } }
  function contestMember(m,receiver,name,args,loc) {
    const kind = receiver.type.contestKind;
    const params = kind === 'helpers' ? helperParams : kind === 'scanner' ? scannerParams : kind === 'writer' ? writerParams : null;
    if (!params || !own(params,name)) return MISSING;
    const b = argsBind(m,name,args,params[name],loc);
    if (kind === 'scanner') {
      if (name === '行') return receiver.state.line();
      const token = receiver.state.token(); return name === '数' && token !== null ? number(m,token,loc) : token;
    }
    if (kind === 'writer') {
      let text;
      if (name === '写') text = contestText(m,b.内容,'内容',loc);
      else if (name === '行') {
        if (typeof b.值 === 'string') text = contestText(m,b.值,'值',loc);
        else if (typeof b.值 === 'number' && Number.isFinite(b.值)) text = numberText(b.值);
        else fail(m,'值须为句或有限数',loc);
      }
      try {
        if (name === '清') receiver.state.flush();
        else { receiver.state.write(text); if (name === '行') receiver.state.write('\n'); }
      } catch (e) { fail(m,'输出失败：'+e.message,loc); }
      m.lastMemberProcedure = true; return null;
    }
    if (name === '读入') {
      try { return scanner(inputAll()); } catch (e) { fail(m,'读取输入失败：'+e.message,loc); }
    }
    if (['扫句','拆词','拆行','字列'].includes(name)) {
      const text = contestText(m,b.文,'文',loc);
      if (name === '扫句') return scanner(text);
      if (name === '字列') return Array.from(text);
      const s = new Scanner(text), result = [];
      for (;;) { const item = name === '拆词' ? s.token() : s.line(); if (item === null) return result; result.push(item); }
    }
    if (name === '合句') {
      if (!Array.isArray(b.列) || b.列.some(x => typeof x !== 'string')) fail(m,'列须为句 阵',loc);
      const sep = contestText(m,b.隔,'隔',loc); for (const value of b.列) contestText(m,value,'列中元素',loc);
      return b.列.join(sep);
    }
    if (name === '取整') {
      if (typeof b.值 !== 'number' || !Number.isFinite(b.值)) fail(m,'值须为有限数',loc); return Math.trunc(b.值);
    }
    if (name === '排序') {
      if (!Array.isArray(b.列)) fail(m,'列须为阵',loc);
      if (!(b.比较 instanceof Fn) || b.比较.procedure) fail(m,'比较须为算',loc);
      const result = b.列.slice();
      // Iterative stable mergesort guarantees O(n log n) comparisons without
      // relying on a particular Node/V8 sort implementation.
      let source = result, target = new Array(result.length);
      for (let width = 1; width < result.length; width *= 2) {
        for (let start = 0; start < result.length; start += 2*width) {
          const mid = Math.min(start+width,result.length), end = Math.min(start+2*width,result.length);
          let left = start, right = mid, out = start;
          while (left < mid && right < end) {
            const value = call(m,b.比较,[[null,source[left]],[null,source[right]]],loc);
            if (typeof value !== 'number' || !Number.isFinite(value)) fail(m,'比较结果须为有限数',loc);
            target[out++] = value <= 0 ? source[left++] : source[right++];
          }
          while (left < mid) target[out++] = source[left++];
          while (right < end) target[out++] = source[right++];
        }
        [source,target] = [target,source];
      }
      m.lastMemberProcedure = false; return source;
    }
    if (name === '蓄出') { const value = new Instance(contestTypes.writer,dict()); value.state = new Writer(); return value; }
    throw new Error('unknown contest helper');
  }
  /* RU_OPTIONAL_CONTEST_END */
  function importAll(m,s,module,loc) {
    if (!(module instanceof Module)) fail(m,'尽取需要外言',loc);
    const values = module.exports();
    const conflicts = Object.keys(values).filter(k => own(s.values,k) || own(m.scope.declarations,k) || own(m.types,k) || reserved.has(k));
    if (conflicts.length) fail(m,'导入名称冲突：'+conflicts.sort(compareText).join('、'),loc);
    for (const name of Object.keys(values)) {
      if (own(module.scope.declarations,name)) m.scope.declarations[name] = values[name];
      else if (own(module.types,name)) m.types[name] = values[name];
      else s.values[name] = values[name];
    }
  }
  function count(m,value,loc) {
    if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) fail(m,'循环次数须为 0 至 9007199254740991 之间的整数',loc);
    return value;
  }
  function panic(m,value,loc) {
    if (typeof value !== 'string') fail(m,'「卒」的原因须为句',loc); throw new Panic(m,value,loc);
  }
  function entry(m,args) {
    const value = m.scope.declarations.元初;
    if (!value || value.owner !== m) return 0;
    if (value.procedure || value.params.length !== 1 || value.params[0][1] !== '句 阵') fail(m,'入口须声明为「算 元初 外参 为 句 阵」',value.loc);
    const result = call(m,value,[[null,args]],value.loc);
    if (typeof result !== 'number' || !Number.isInteger(result) || result < 0 || result > 255) fail(m,'元初须返回 0 至 255 的整数退出码',value.loc);
    return result;
  }
  function finish(error) {
    const text = error instanceof RuError ? error.source+':'+error.line+':'+error.col+': '+error.category+'：'+error.message : '运行错误：'+String(error && error.message || error);
    try { write(2,text+'\n'); } catch (_) {} process.exitCode = 1;
  }
  return {NO_RETURN,Panic,RuError,Pair,Fn,Type,Instance,Module,fail,
    module: source => new Module(source), scope: (parent,kind) => new Scope(parent,kind),
    get,bind,fn,declare,type,resolve,call,member,ref,functionRef,new:construct,
    index,slice,setIndex,setField,binary,unary,convert,number,display,truth,equal,
    read,print,importAll,count,loopCount:count,panic,entry,finish};
})();
