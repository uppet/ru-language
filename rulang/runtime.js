/* Standalone Ru JavaScript runtime. Generated programs contain direct JS
 * control flow; this file has no lexer, parser, AST walker, or evaluator. */
const R = (() => {
  'use strict';
  const fs = require('fs'), path = require('path');
  const {TextDecoder} = require('util');
  const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const dict = () => Object.create(null);
  const NO_RETURN = Symbol('no return'), MISSING = Symbol('missing');
  const reserved = new Set(['读','件','录','件作成果','读取','显出','错误','__如竞','__实用']);
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
  class RuMap {
    constructor() { this.buckets = new Map(); this.size = 0; this.version = 0; }
  }
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
  function valueTypeName(value) {
    if (value === null) return '空';
    if (typeof value === 'boolean') return '事实';
    if (value instanceof RuMap) return '典';
    if (typeof value === 'number') return '数';
    if (typeof value === 'string') return '句';
    if (Array.isArray(value)) return '阵';
    if (value instanceof Pair) return '对';
    if (value instanceof Instance) return value.type.name;
    if (value instanceof Fn) return value.procedure ? '作' : '算';
    if (value instanceof Module) return '外言';
    if (value instanceof Type) return '形声明';
    throw new Error('unknown 如 value');
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
  for (const [kind, name] of [['helpers','如竞工具'],['scanner','如竞读流'],['writer','如竞出流']])
    contestTypes[kind] = builtin(name, [], kind, 'contestKind');
  builtins.values.__如竞 = new Instance(contestTypes.helpers, dict());

  // Binary64, Python .15g rounding and exponent spelling.
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
      else if (typeof v === 'boolean') out.push(v ? '真' : '假');
      else if (typeof v === 'number') out.push(numberText(v));
      else if (typeof v === 'string') out.push(v);
      else if (v instanceof Instance) out.push('<形 ' + v.type.name + '>');
      else if (v instanceof Type) out.push('<形 ' + v.name + '>');
      else if (v instanceof Module) out.push('<外言>');
      else if (v instanceof Fn) out.push('<' + (v.procedure ? '作' : '算') + ' ' + v.name + '>');
      else if (v instanceof Pair || v instanceof RuMap || Array.isArray(v)) {
        if (active.has(v)) { out.push('<循环>'); continue; }
        active.add(v); stack.push([2, v]);
        if (v instanceof RuMap) {
          out.push('{'); stack.push([1,'}']);
          const entries = Array.from(v.buckets.values()).flat();
          for (let i = entries.length - 1; i >= 0; i--) {
            stack.push([0,entries[i][1]],[1,': '],[0,entries[i][0]]);
            if (i) stack.push([1,', ']);
          }
        } else if (v instanceof Pair) {
          out.push('('); stack.push([1, ')'], [0, v.right], [1, ' 对 '], [0, v.left]);
        } else {
          out.push('['); stack.push([1, ']']);
          for (let i = v.length - 1; i >= 0; i--) { stack.push([0, v[i]]); if (i) stack.push([1, ', ']); }
        }
      } else throw new Error('unknown Ru value');
    }
    return out.join('');
  }
  function truth(v) { return v !== null && v !== false; }
  function keyMethod(m,value,name,arity,loc) {
    const f = value.type.methods[name];
    if (!(f instanceof Fn) || f.procedure || f.params.length !== arity)
      fail(m,'典键的「'+name+'」须为 '+arity+' 个参数的算',loc);
    return boundMethod(f,value);
  }
  function sameInstance(m,a,b,loc) {
    if (a.type !== b.type) return false;
    const f = a.type.methods.同;
    if (!f) return a === b;
    const result = call(m,keyMethod(m,a,'同',1,loc),[[null,b]],loc);
    if (typeof result !== 'boolean') fail(m,'「同」须返回事实',loc);
    return result;
  }
  function equal(a,b,m = null,loc = null) {
    const todo = [[a,b]], visited = new Map();
    while (todo.length) {
      const [x,y] = todo.pop();
      if (x instanceof Instance && y instanceof Instance) {
        if (!sameInstance(m,x,y,loc)) return false;
      } else if (x === y) continue;
      else if (x instanceof Pair && y instanceof Pair) {
        let seen = visited.get(x); if (!seen) visited.set(x,seen = new Set());
        if (seen.has(y)) continue; seen.add(y); todo.push([x.right,y.right],[x.left,y.left]);
      } else return false;
    }
    return true;
  }
  /* RU_OPTIONAL_MAP_BEGIN */
  const typeIds = new WeakMap(); let nextTypeId = 0;
  function keyHash(m,key,loc) {
    if (typeof key === 'boolean') return key ? 'b1' : 'b0';
    if (typeof key === 'number' && Number.isFinite(key)) return 'n'+String(key);
    if (typeof key === 'string') return 's'+key;
    if (key instanceof Instance) {
      keyMethod(m,key,'同',1,loc);
      const result = call(m,keyMethod(m,key,'印',0,loc),[],loc);
      if (typeof result !== 'number' || !Number.isSafeInteger(result))
        fail(m,'「印」须返回有限安全整数',loc);
      if (!typeIds.has(key.type)) typeIds.set(key.type,++nextTypeId);
      return 'o'+typeIds.get(key.type)+':'+String(result);
    }
    fail(m,'典键须为数、句、事实或具备同与印的形',loc);
  }
  function mapFind(m,map,key,loc) {
    const version = map.version, hash = keyHash(m,key,loc);
    const unchanged = () => { if (map.version !== version) fail(m,'典键的同／印调用期间不能修改该典',loc); };
    unchanged();
    const bucket = map.buckets.get(hash);
    if (bucket) for (let i = 0; i < bucket.length; i++) {
      const found = equal(bucket[i][0],key,m,loc); unchanged();
      if (found) return [hash,bucket,i];
    }
    return [hash,bucket,-1];
  }
  function mapPut(m,map,key,value,loc) {
    const [hash,bucket,index] = mapFind(m,map,key,loc);
    if (index >= 0) bucket[index][1] = value;
    else {
      if (bucket) bucket.push([key,value]); else map.buckets.set(hash,[[key,value]]);
      map.size++;
    }
    map.version++; return map;
  }
  function map(m,entries,loc) {
    const result = new RuMap();
    for (const [key,value] of entries) { const k = key(), v = value(); mapPut(m,result,k,v,loc); }
    return result;
  }
  function mapMember(m,receiver,name,args,loc) {
    if (name === '量') { argsBind(m,name,args,[],loc); return receiver.size; }
    if (name === '增') {
      const a = argsBind(m,name,args,['目','相'],loc); return mapPut(m,receiver,a.目,a.相,loc);
    }
    if (name === '查' || name === '除') {
      const a = argsBind(m,name,args,['目'],loc), [hash,bucket,index] = mapFind(m,receiver,a.目,loc);
      if (name === '查') return index < 0 ? null : bucket[index][1];
      if (index < 0) return false;
      bucket.splice(index,1); if (!bucket.length) receiver.buckets.delete(hash);
      receiver.size--; receiver.version++; return true;
    }
    if (name === '列') fail(m,'典的「列」已改名为「逐目」；请改用「其 逐目」',loc);
    if (name === '逐目') {
      const a = argsBind(m,name,args,['回调'],loc), callback = a.回调;
      if (!(callback instanceof Fn) || callback.params.length !== 2) fail(m,'典的逐目回调须为接受两个参数的算或作',loc);
      const snapshot = [];
      for (const bucket of receiver.buckets.values()) for (const [key,value] of bucket) snapshot.push([key,value]);
      for (const [key,value] of snapshot) {
        /* RU_ARRAY_TICK */
        call(m,callback,[[null,key],[null,value]],loc);
      }
      m.lastMemberProcedure = false; return null;
    }
    fail(m,'未知成员：'+name,loc);
  }
  /* RU_OPTIONAL_MAP_END */
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
    const result = dict(), count = params.length, argc = args.length;
    const positional = args.some(x => x[0] === null);
    let detail = '';
    if (positional) {
      if (args.some(x => x[0] !== null)) fail(m, '不能混用位置实参与命名实参', loc);
      if (argc === count) {
        args.forEach((x,i) => { result[params[i]] = x[1]; }); return result;
      }
    } else {
      for (const [key,value] of args) {
        if (own(result,key)) fail(m, '重复的实参：'+key, loc); result[key] = value;
      }
      if (optional && !argc) return result;
      for (const [label, keys] of [
        ['缺少', params.filter(k => !own(result,k))],
        ['未知', Object.keys(result).filter(k => !params.includes(k))]
      ]) if (keys.length) detail += label+'「'+keys.join('、')+'」；';
      if (!detail) return result;
    }
    fail(m, `函数「${name}」${detail}需要 ${count} 个${positional ? '位置' : ''}实参，收到 ${argc} 个`+
      (positional && argc > count ? '；若并列阵元素，请括起调用' : ''), loc);
  }
  function ordinary(m,value,loc) {
    if (value instanceof Type) fail(m,'形名「'+value.name+'」不能作为普通值；创建实例请用「新 '+value.name+'」，类型注解请直接使用形名',loc);
    return value;
  }
  function typeIdentity(m,annotation,loc) {
    if (annotation.endsWith(' 阵')) return ['array',typeIdentity(m,annotation.slice(0,-2),loc)];
    if (['','数','句','空','阵','对','算','作','事实','典'].includes(annotation)) return annotation;
    const t = m.types[annotation] || builtinTypes[annotation];
    if (!(t instanceof Type)) fail(m,'未定义类型：'+annotation+'；类型注解须使用已声明或已尽取导入的形名',loc);
    return t;
  }
  function sameType(a,b) {
    return a === b || (Array.isArray(a) && Array.isArray(b) && a[0] === b[0] && sameType(a[1],b[1]));
  }
  function get(m,s,name,loc,raw = false) {
    if (name === '读') {
      if (raw) fail(m, '当前仅支持用户定义算／作的引用；内置「读」不能取引用', loc);
      return read(m,[],loc);
    }
    const [value,declared] = s.find(name);
    if (value !== MISSING) return ordinary(m,!raw && declared ? call(m,value,[],loc) : value,loc);
    if (own(m.types,name)) return ordinary(m,m.types[name],loc);
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
        typeIdentity(t.owner,typ,t.loc);
        t.fields[name] = [typ,t.owner];
      }
      for (const method of t.ownMethods) {
        const f = method instanceof Fn ? method : fn(t.owner,t.owner.scope,...method);
        if (own(t.fields,f.name)) fail(t.owner,'方法与字段重名：'+f.name,f.loc);
        f.parameterTypes = f.params.map(([key,typ]) => typeIdentity(f.owner,typ,f.loc));
        if (own(t.methods,f.name)) {
          const old = t.methods[f.name];
          if (old.procedure !== f.procedure || old.params.length !== f.params.length || old.params.some(([key,typ],i) => key !== f.params[i][0] || !sameType(old.parameterTypes ? old.parameterTypes[i] : typeIdentity(old.owner,typ,f.loc),f.parameterTypes[i])))
            fail(t.owner,'覆写方法「'+f.name+'」须保持参数名称、类型及算／作种类',f.loc);
        }
        t.methods[f.name] = f;
      }
      t.state = 2; return t;
    } catch (e) { t.state = 0; throw e; }
  }
  function matches(m,value,typ) {
    if (Array.isArray(typ)) return Array.isArray(value) && value.every(x => matches(m,x,typ[1]));
    if (typ instanceof Type) {
      if (!(value instanceof Instance)) return false;
      for (let t = value.type; t; t = t.parent) if (t === typ) return true;
      return false;
    }
    if (typ === '') return true;
    if (typ.endsWith(' 阵')) return Array.isArray(value) && value.every(x => matches(m,x,typ.slice(0,-2)));
    if (typ === '事实') return typeof value === 'boolean';
    if (typ === '典') return value instanceof RuMap;
    if (typ === '数') return typeof value === 'number';
    if (typ === '句') return typeof value === 'string';
    if (typ === '空') return value === null;
    if (typ === '阵') return Array.isArray(value);
    if (typ === '对') return value instanceof Pair;
    if (typ === '算' || typ === '作') return value instanceof Fn && value.procedure === (typ === '作');
    const expected = m && m.types[typ] || builtinTypes[typ];
    if (!(expected instanceof Type) || !(value instanceof Instance)) return false;
    for (let t = value.type; t; t = t.parent) if (t === expected) return true;
    return false;
  }
/* RU_OPTIONAL_DIAGNOSTIC_DETAIL_BEGIN */
  function typeDetail(m,value,annotation,identity = annotation) {
    let indices = '';
    while (annotation.endsWith(' 阵') && Array.isArray(value)) {
      const itemAnnotation = annotation.slice(0,-2);
      const itemType = Array.isArray(identity) ? identity[1] : itemAnnotation;
      const i = value.findIndex(x => !matches(m,x,itemType));
      if (i < 0) break;
      indices += '['+i+']'; value = value[i]; annotation = itemAnnotation; identity = itemType;
    }
    let detail = indices ? '；元素'+indices+'须为'+annotation+'，实际收到'+valueTypeName(value) : '';
    if (value instanceof Instance && value.type.name === annotation)
      detail += '；同名但不同形身份：期望形与实际形来自不同声明；请核对所用形声明，若曾重定义，请按需重建相关实例或函数';
    return detail;
  }
  function callHint(value,args) { return ((Array.isArray(value) || typeof value === 'string' || value instanceof RuMap) && args.length === 1 && Array.isArray(args[0][1]) ? '；若要索引，请让方括号紧邻接收者，如 列[0]；列 [0] 会被解析为调用' : ''); }
  function comparisonHint(left,right) { return (typeof left === 'boolean' || typeof right === 'boolean' ? '；比较结果为事实，若要连续比较，请拆成两个比较并用「且」连接' : ''); }
/* RU_OPTIONAL_DIAGNOSTIC_DETAIL_END */
  let depth = 0;
  function call(m,value,args,loc) {
    if (!(value instanceof Fn)) fail(m, '值不是算／作'/* RU_DETAIL */+callHint(value,args)/* RU_END_DETAIL */,loc);
    const owner = value.owner;
    if (value.params.some(([name]) => value.env.protected(name) || own(owner.types,name)))
      fail(owner,'参数名不能与函数名、形名或内置名称重名',value.loc);
    const bound = argsBind(m,value.name,args,value.params.map(x => x[0]),loc);
    const s = new Scope(value.env,'function');
    if (value.receiver !== null) s.values.其 = value.receiver;
    for (const [i,[name,typ]] of value.params.entries()) {
      if (!matches(owner,bound[name],value.parameterTypes ? value.parameterTypes[i] : typeIdentity(owner,typ,value.loc))) fail(m,'函数「'+value.name+'」的实参「'+name+'」须为'+typ+'，实际收到'+valueTypeName(bound[name])/* RU_DETAIL */+typeDetail(owner,bound[name],typ,value.parameterTypes ? value.parameterTypes[i] : typeIdentity(owner,typ,value.loc))/* RU_END_DETAIL */,loc);
      s.values[name] = bound[name];
    }
    if (depth >= 128) fail(m,'函数调用层数超过 128',loc);
    depth++;
    try {
      const result = value.body(s,value.receiver);
      if (result === NO_RETURN || result === undefined) {
        if (!value.procedure) fail(m,'函数「'+value.name+'」没有执行「得」',loc);
        m.lastCallProcedure = true; return null;
      }
      m.lastCallProcedure = value.procedure; return result;
    } finally { depth--; }
  }
  function boundMethod(value,receiver) {
    const bound = new Fn(value.owner,value.env,value.name,value.params,value.procedure,value.body,value.loc,receiver);
    bound.parameterTypes = value.parameterTypes; return bound;
  }
  function functionRef(m,value,procedure,loc) {
    if (!(value instanceof Fn) || value.procedure !== procedure) fail(m,'引用的算／作种类不匹配',loc);
    return value;
  }
  function ref(m,receiver,name,loc) {
    if (receiver instanceof Module) {
      const values = receiver.exports(); if (own(values,name)) return ordinary(m,values[name],loc);
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
/* RU_OPTIONAL_MAP_INDEX_BEGIN */
    if (receiver instanceof RuMap) return mapMember(m,receiver,'查',[[null,i]],loc);
/* RU_OPTIONAL_MAP_INDEX_END */
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
    if (value !== null && !matches(owner,value,typ)) fail(m,'字段「'+name+'」须为'+typ+'，实际收到'+valueTypeName(value)/* RU_DETAIL */+typeDetail(owner,value,typ)/* RU_END_DETAIL */,loc);
    receiver.fields[name] = value; return value;
  }
  function construct(m,s,name,argsThunk,loc) {
    const t = m.types[name] || builtinTypes[name];
    if (!t) fail(m,'未定义形：'+name+'；新 后须使用已声明或已尽取导入的形名',loc);
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
      if (value !== null && !matches(owner,value,typ)) fail(m,'字段「'+key+'」须为'+typ+'，实际收到'+valueTypeName(value)/* RU_DETAIL */+typeDetail(owner,value,typ)/* RU_END_DETAIL */,loc);
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
  function convert(m,value,target,loc) { return target === '事实' ? truth(value) : target === '阵' ? [value] : target === '句' ? display(value) : number(m,value,loc); }
  function unary(m,op,value,loc) {
    if (op === '非') return !truth(value);
    if (typeof value !== 'number') fail(m,'正负号只能用于数',loc);
    return op === '+' ? value : -value;
  }
  function binary(m,op,left,right,loc) {
    if (op === '对') return new Pair(left,right);
    if (op === '==') return equal(left,right,m,loc);
    if (op === '!=') return !equal(left,right,m,loc);
    if (op === '含') {
      if (left instanceof Instance || left instanceof Module) return member(m,left,'含',()=>[[null,right]],loc);
      m.lastMemberProcedure = false;
      if (typeof left !== 'string' || typeof right !== 'string') fail(m,'「含」需要两个句',loc);
      return left.includes(right);
    }
    if (['<','<=','>','>='].includes(op)) {
      if (typeof left !== typeof right || !['number','string'].includes(typeof left)) fail(m,'大小比较需要两个数或两个句'/* RU_DETAIL */+comparisonHint(left,right)/* RU_END_DETAIL */,loc);
      const c = typeof left === 'string' ? compareText(left,right) : left === right ? 0 : left < right ? -1 : 1;
      return (op === '<' ? c < 0 : op === '<=' ? c <= 0 : op === '>' ? c > 0 : c >= 0);
    }
    if (op === '+' && typeof left === 'string' && typeof right === 'string') return left + right;
    if (typeof left !== 'number' || typeof right !== 'number') fail(m,'算术运算需要两个数；「+」也可连接两个句',loc);
    if ((op === '/' || op === '%') && right === 0) fail(m,'除数不能为零',loc);
    const v = op === '+' ? left+right : op === '-' ? left-right : op === '*' ? left*right : op === '/' ? left/right : left%right;
    if (!Number.isFinite(v)) fail(m,'运算结果不是有限数',loc); return v;
  }
  /* RU_OPTIONAL_ARRAY_ALGORITHM_BEGIN */
  function arrayAlgorithm(m,receiver,name,args,loc) {
    const a = argsBind(m,name,args,[name === '排序' ? '先于' : name === '逐位' ? '回调' : '算法'],loc,name === '排序');
    const snapshot = receiver.slice();
    const check = (f,count,label) => {
      if (!(f instanceof Fn) || f.procedure || f.params.length !== count)
        fail(m,label+'须为接受 '+count+' 个参数的算',loc);
      return f;
    };
    if (name === '逐位') {
      const callback = a.回调;
      if (!(callback instanceof Fn) || callback.params.length !== 2)
        fail(m,'阵的逐位回调须为接受两个参数的算或作',loc);
      for (let i = 0; i < snapshot.length; i++) {
        /* RU_ARRAY_TICK */
        call(m,callback,[[null,i],[null,snapshot[i]]],loc);
      }
      m.lastMemberProcedure = false; return null;
    }
    if (name === '另成') {
      const callback = check(a.算法,1,'「算法」'), result = [];
      for (const value of snapshot) {
        /* RU_ARRAY_TICK */
        result.push(call(m,callback,[[null,value]],loc));
      }
      m.lastMemberProcedure = false; return result;
    }
    let before;
    const fact = value => {
      if (typeof value !== 'boolean') fail(m,'「先于」须返回事实',loc);
      return value;
    };
    if (own(a,'先于')) {
      const callback = check(a.先于,2,'「先于」');
      before = (left,right) => fact(call(m,callback,[[null,left],[null,right]],loc));
    } else if (!snapshot.length) return snapshot;
    else {
      const first = snapshot[0];
      if (typeof first === 'number') {
        if (snapshot.some(value => typeof value !== 'number' || !Number.isFinite(value)))
          fail(m,'默认排序须为同类有限数、句或同一形且具有「先于」算的实例',loc);
        before = (left,right) => left < right;
      } else if (typeof first === 'string') {
        if (snapshot.some(value => typeof value !== 'string'))
          fail(m,'默认排序须为同类有限数、句或同一形且具有「先于」算的实例',loc);
        before = (left,right) => compareText(left,right) < 0;
      } else if (first instanceof Instance) {
        for (const value of snapshot) {
          if (!(value instanceof Instance) || value.type !== first.type)
            fail(m,'默认排序须为同类有限数、句或同一形且具有「先于」算的实例',loc);
          check(value.type.methods.先于,1,'形的「先于」');
        }
        before = (left,right) => fact(call(m,boundMethod(left.type.methods.先于,left),[[null,right]],loc));
      } else fail(m,'默认排序须为同类有限数、句或同一形且具有「先于」算的实例',loc);
    }
    // Stable iterative mergesort: ask only whether the right precedes the
    // left, so equivalent elements keep their input order. Both buffers hold
    // the original references, even if a callback changes the input array.
    let source = snapshot, target = new Array(snapshot.length);
    for (let width = 1; width < snapshot.length; width *= 2) {
      for (let start = 0; start < snapshot.length; start += 2*width) {
        const mid = Math.min(start+width,snapshot.length), end = Math.min(start+2*width,snapshot.length);
        let left = start, right = mid, out = start;
        while (left < mid && right < end) {
          /* RU_ARRAY_TICK */
          target[out++] = before(source[right],source[left]) ? source[right++] : source[left++];
        }
        while (left < mid) target[out++] = source[left++];
        while (right < end) target[out++] = source[right++];
      }
      [source,target] = [target,source];
    }
    m.lastMemberProcedure = false; return source;
  }
  /* RU_OPTIONAL_ARRAY_ALGORITHM_END */
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
        const value = ordinary(m,exports[name],loc), args = argsThunk();
        if (args.length || own(receiver.scope.declarations,name)) {
          const result = call(m,value,args,loc); m.lastMemberProcedure = value.procedure; return result;
        }
        return value;
      }
    }
    const args = argsThunk();
    if (receiver instanceof RuMap) return mapMember(m,receiver,name,args,loc);
    if (receiver instanceof Instance) {
      const a = contestMember(m,receiver,name,args,loc); if (a !== MISSING) return a;
      const b = ioMember(m,receiver,name,args,loc); if (b !== MISSING) return b;
      /* RU_PRACTICAL_DISPATCH_BEGIN */
      const c = practicalMember(m,receiver,name,args,loc); if (c !== MISSING) return c;
      /* RU_PRACTICAL_DISPATCH_END */
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
        return receiver.includes(a.句);
      }
      /* RU_OPTIONAL_ARRAY_ALGORITHM_DISPATCH_BEGIN */
      if (Array.isArray(receiver) && (name === '排序' || name === '另成' || name === '逐位')) return arrayAlgorithm(m,receiver,name,args,loc);
      /* RU_OPTIONAL_ARRAY_ALGORITHM_DISPATCH_END */
      /* RU_OPTIONAL_ARRAY_EDIT_BEGIN */
      if (Array.isArray(receiver) && ['删','弹','查'].includes(name)) {
        const a = argsBind(m,name,args,name === '删' ? ['位'] : name === '查' ? ['值'] : [],loc);
        if (name === '查') {
          // Equality may mutate the original array. Scan a shallow snapshot,
          // with each original element as the left operand of equality.
          const snapshot = receiver.slice();
          for (let i = 0; i < snapshot.length; i++) if (equal(snapshot[i],a.值,m,loc)) {
            m.lastMemberProcedure = false; return i;
          }
          m.lastMemberProcedure = false; return null;
        }
        const i = bounded(m,name === '删' ? a.位 : receiver.length-1,receiver.length,loc);
        return receiver.splice(i,1)[0];
      }
      /* RU_OPTIONAL_ARRAY_EDIT_END */
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
          try { return ioResult(fs.statSync(p).isFile()); }
          catch (e) { if (e.code === 'ENOENT' || e.code === 'ENOTDIR') return ioResult(false); throw e; }
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
  /* RU_OPTIONAL_PRACTICAL_BEGIN */
  // PCG32: Copyright 2014 Melissa O'Neill; Apache License 2.0.
  // https://www.apache.org/licenses/LICENSE-2.0 ; see docs/third-party-notices.md.
  const practicalTypes = dict();
  for (const [kind,name] of [['helpers','实用工具'],['random','随机源']])
    practicalTypes[kind] = builtin(name,[],kind,'practicalKind');
  builtins.values.__实用 = new Instance(practicalTypes.helpers,dict());
  const practicalParams = {
    '正弦':['弧度'],'余弦':['弧度'],'角度转弧度':['角度'],
    '弧度转角度':['弧度'],'方向角':['纵','横'],
    '拆分':['文','隔'],'替换':['文','旧','新文'],'去空白':['文'],
    '定点':['值','位数'],'平方根':['值'],'幂':['底数','指数'],
    '向下取整':['值'],'向上取整':['值'],'四舍五入':['值'],'造源':['种子'],
  };
  const randomParams = {'整数':['下','上'],'洗牌':['列']};
  function practicalNumber(m,value,label,loc) {
    if (typeof value !== 'number' || !Number.isFinite(value)) fail(m,label+'须为有限数',loc);
    return value;
  }
  function practicalInteger(m,value,label,low,high,loc) {
    practicalNumber(m,value,label,loc);
    if (!Number.isInteger(value) || value < low || value > high) fail(m,label+'须为范围内整数',loc);
    return value;
  }
  function fixedText(value,places) {
    // Scale the exact binary64 rational, never an already-rounded double
    // product. This also handles subnormals and the largest finite double.
    const negative = value < 0 || Object.is(value,-0);
    bits.setFloat64(0,Math.abs(value));
    const hi = bits.getUint32(0), lo = bits.getUint32(4), exponent = (hi >>> 20) & 2047;
    let numerator = (BigInt(hi & 1048575) << 32n) | BigInt(lo), denominator = 1n;
    if (exponent) numerator |= 1n << 52n;
    const binaryExponent = (exponent || 1)-1023-52;
    if (binaryExponent >= 0) numerator <<= BigInt(binaryExponent);
    else denominator <<= BigInt(-binaryExponent);
    numerator *= pow10(places);
    let quotient = numerator / denominator;
    if ((numerator % denominator)*2n >= denominator) quotient++;
    let text = quotient.toString().padStart(places+1,'0');
    if (places) text = text.slice(0,-places)+'.'+text.slice(-places);
    return (negative ? '-' : '')+text;
  }
  class PracticalRandom {
    constructor(seed) {
      this.state = 0n;
      this.next();
      this.state = (this.state+BigInt(seed)) & 0xffffffffffffffffn;
      this.next();
    }
    next() {
      // PCG32 XSH-RR, fixed initseq=54, state modulo 2^64. The
      // xorshifted value is truncated before the 32-bit rotation.
      const old = this.state;
      this.state = (old*6364136223846793005n+109n) & 0xffffffffffffffffn;
      const shifted = Number((((old >> 18n)^old) >> 27n) & 0xffffffffn);
      const rotation = Number(old >> 59n);
      return ((shifted >>> rotation) | (shifted << ((-rotation)&31))) >>> 0;
    }
    bounded(count) {
      if (count === 1) return 0;
      const threshold = 4294967296 % count;
      for (;;) {
        const value = this.next();
        if (value >= threshold) return value % count;
      }
    }
  }
  function practicalMember(m,receiver,name,args,loc) {
    if (!(receiver instanceof Instance) || !receiver.type.practicalKind) return MISSING;
    const kind = receiver.type.practicalKind, params = kind === 'random' ? randomParams : practicalParams;
    if (!own(params,name)) fail(m,(kind === 'random' ? '未知随机源成员：' : '未知实用库成员：')+name,loc);
    const b = argsBind(m,name,args,params[name],loc);
    if (kind === 'random') {
      if (name === '整数') {
        const low = practicalInteger(m,b.下,'下',-9007199254740991,9007199254740991,loc);
        const high = practicalInteger(m,b.上,'上',-9007199254740991,9007199254740991,loc);
        const width = BigInt(high)-BigInt(low)+1n;
        if (width < 1n || width > 4294967296n)
          fail(m,'随机整数须满足下不大于上且范围不超过 4294967296 项',loc);
        const result = low+receiver.practicalState.bounded(Number(width));
        return result === 0 ? 0 : result;
      }
      if (!Array.isArray(b.列)) fail(m,'洗牌的列须为阵',loc);
      if (b.列.length > 4294967296) fail(m,'洗牌的列超过随机范围限制',loc);
      const result = b.列.slice();
      for (let i = result.length-1; i > 0; i--) {
        const target = receiver.practicalState.bounded(i+1);
        [result[i],result[target]] = [result[target],result[i]];
      }
      return result;
    }
    if (['拆分','替换','去空白'].includes(name)) {
      for (const [label,value] of Object.entries(b)) if (typeof value !== 'string') fail(m,label+'须为句',loc);
      if (name === '去空白') return b.文.replace(/^[ \t\r\n\v\f]+|[ \t\r\n\v\f]+$/g,'');
      const separator = name === '拆分' ? b.隔 : b.旧;
      if (separator === '') fail(m,(name === '拆分' ? '隔' : '旧')+'不能为空句',loc);
      const pieces = b.文.split(separator);
      return name === '拆分' ? pieces : pieces.join(b.新文);
    }
    if (name === '造源') {
      const seed = practicalInteger(m,b.种子,'种子',0,4294967295,loc);
      const result = new Instance(practicalTypes.random,dict());
      result.practicalState = new PracticalRandom(seed); return result;
    }
    if (name === '定点') {
      const value = practicalNumber(m,b.值,'值',loc);
      const places = practicalInteger(m,b.位数,'位数',0,15,loc);
      return fixedText(value,places);
    }
    let result;
    if (name === '方向角') {
      result = Math.atan2(practicalNumber(m,b.纵,'纵',loc),practicalNumber(m,b.横,'横',loc));
    } else if (['正弦','余弦','角度转弧度','弧度转角度'].includes(name)) {
      const label = name === '角度转弧度' ? '角度' : '弧度';
      const value = practicalNumber(m,b[label],label,loc);
      if (name === '正弦') result = Math.sin(value);
      else if (name === '余弦') result = Math.cos(value);
      else if (name === '角度转弧度') result = value * (Math.PI / 180);
      else result = value * (180 / Math.PI);
    } else if (name === '幂') {
      const base = practicalNumber(m,b.底数,'底数',loc), exponent = practicalNumber(m,b.指数,'指数',loc);
      if (base < 0 && !Number.isInteger(exponent)) fail(m,'负底数的指数须为整数',loc);
      if (base === 0 && exponent < 0) fail(m,'零的指数不能为负数',loc);
      result = Math.pow(base,exponent);
    } else {
      const value = practicalNumber(m,b.值,'值',loc);
      if (name === '平方根') {
        if (value < 0) fail(m,'平方根的值不能为负数',loc);
        result = Math.sqrt(value);
      } else {
        if (name === '向下取整') result = Math.floor(value);
        else if (name === '向上取整') result = Math.ceil(value);
        else {
          const magnitude = Math.abs(value), integral = Math.floor(magnitude);
          result = integral+(magnitude-integral >= 0.5 ? 1 : 0);
          if (value < 0 || Object.is(value,-0)) result = -result;
        }
        if (result === 0) result = value < 0 || Object.is(value,-0) ? -0 : 0;
      }
    }
    if (!Number.isFinite(result)) fail(m,name+'的结果不是有限数',loc);
    return result;
  }
  /* RU_OPTIONAL_PRACTICAL_END */
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
    const text = error instanceof RuError ? error.source+':'+error.line+':'+error.col+': error: '+error.category+'：'+error.message : '<程序>: error: 运行错误：'+String(error && error.message || error);
    try { write(2,text+'\n'); } catch (_) {} process.exitCode = 1;
  }
  return {NO_RETURN,Panic,RuError,Pair,Fn,Type,Instance,Module,fail,
    module: source => new Module(source), scope: (parent,kind) => new Scope(parent,kind),
    get,bind,fn,declare,type,resolve,call,member,ref,functionRef,new:construct,
    map,index,slice,setIndex,setField,binary,unary,convert,number,display,truth,equal,
    read,print,importAll,count,loopCount:count,panic,entry,finish};
})();
