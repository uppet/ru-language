/* Opt-in host primitives. Guest semantics are in the Ru sources under rushu/native. */
#include <errno.h>
#include <locale.h>
#include <time.h>
/* Intern the finite set of host program literals and primitive type names.
 * Strings are immutable. The rooted ordinary map and all of its strings use
 * the existing GC and shutdown path; no unmanaged cache entries can leak.
 * Guest-created strings are not interned here. */
static Val ru_interpreter_literals;
static int ru_interpreter_literals_initialized;
static void ru_interpreter_literals_clear(void)
{
    if(ru_interpreter_literals_initialized) {
        v_drop(ru_interpreter_literals);ru_interpreter_literals=v_null();
        ru_interpreter_literals_initialized=0;
    }
}
static Val ru_interpreter_literal(const char *text)
{
    size_t i,length=strlen(text),at;
    uint64_t bits=UINT64_C(1469598103934665603),hash;
    RuMap *map;
    Val value,inserted;
    if(!ru_interpreter_literals_initialized) {
        ru_interpreter_literals=v_map_new(0);ru_interpreter_literals_initialized=1;
    }
    map=(RuMap *)ru_interpreter_literals.heap;
    for(i=0;i<length;++i){bits^=(unsigned char)text[i];bits*=UINT64_C(1099511628211);}
    hash=ru_hash_mix(bits^UINT64_C(0x3456));
    if(map->capacity) {
        at=(size_t)hash&(map->capacity-1);
        while(map->entries[at].state) {
            RuMapEntry *entry=&map->entries[at];
            if(entry->hash==hash&&entry->key.s->len==length&&!memcmp(entry->key.s->data,text,length))
                return v_copy(entry->value);
            at=(at+1)&(map->capacity-1);
        }
    }
    value=v_str(text);inserted=v_map_put(ru_interpreter_literals,value,value,0);v_drop(inserted);return value;
}
static RuClass ru_interpreter_service = {"解释宿主", NULL, NULL, 0, NULL, NULL, 0, NULL};
static void ru_interpreter_install(Env *env)
{
    Val value;
    ru_interpreter_service.global=env;
    value=ru_object_new(&ru_interpreter_service,0);
    env_declare(env,"__如释",value);v_drop(value);
    setlocale(LC_NUMERIC,"C");
#ifdef _WIN32
    _setmode(_fileno(stdin),_O_BINARY);
    _setmode(_fileno(stdout),_O_BINARY);
#endif
}
/* A checked operation is [success, value, message]. No ru_fail/longjmp for
 * guest arithmetic errors: all roots and frames unwind through ordinary calls. */
static Val ru_interpreter_result(Val value,const char *error)
{
    Val text=ru_interpreter_literal(error?error:"");
    Val values[]={v_fact(!error),value,text};
    Val result=v_array(3,values,0);v_drop(value);v_drop(text);return result;
}
static Val ru_interpreter_arithmetic(Val operation,Val a,Val b)
{
    double x=a.n,y=b.n,z=0;const char *op=operation.s->data;
    if(a.kind!=RU_NUM || b.kind!=RU_NUM)
        return ru_interpreter_result(v_null(),"算术运算需要两个数；「+」也可连接两个句");
    if(!strcmp(op,"+"))z=x+y;
    else if(!strcmp(op,"-"))z=x-y;
    else if(!strcmp(op,"*"))z=x*y;
    else if(!strcmp(op,"/")||!strcmp(op,"%")) {
        if(y==0)return ru_interpreter_result(v_null(),"除数不能为零");
        z=!strcmp(op,"/")?x/y:fmod(x,y);
    } else return ru_interpreter_result(v_null(),"未知算术运算符");
    if(!isfinite(z))return ru_interpreter_result(v_null(),"运算结果不是有限数");
    return ru_interpreter_result(v_num(z),NULL);
}
static Val ru_interpreter_number(Val value)
{
    const char *p,*end,*start;char *tail;double result;int digits=0;
    if(value.kind==RU_NUM)return ru_interpreter_result(value,NULL);
    if(value.kind!=RU_STR)return ru_interpreter_result(v_null(),"无法转为数字");
    p=value.s->data;end=p+value.s->len;
    while(p<end && ru_ascii_space((unsigned char)*p))++p;
    while(end>p && ru_ascii_space((unsigned char)end[-1]))--end;
    start=p;if(p<end && (*p=='+'||*p=='-'))++p;
    while(p<end && *p>='0'&&*p<='9'){++p;++digits;}
    if(p<end && *p=='.'){++p;while(p<end&&*p>='0'&&*p<='9'){++p;++digits;}}
    if(!digits)return ru_interpreter_result(v_null(),"无法转为数字");
    if(p<end&&(*p=='e'||*p=='E')) {
        int exponent=0;++p;if(p<end&&(*p=='+'||*p=='-'))++p;
        while(p<end&&*p>='0'&&*p<='9'){++p;++exponent;}
        if(!exponent)return ru_interpreter_result(v_null(),"无法转为数字");
    }
    if(p!=end)return ru_interpreter_result(v_null(),"无法转为数字");
    result=strtod(start,&tail);
    if(tail!=end||!isfinite(result))return ru_interpreter_result(v_null(),"无法转为有限数字");
    return ru_interpreter_result(v_num(result),NULL);
}
static Val ru_interpreter_math(Val operation,Val values)
{
    RuArray *args=(RuArray *)values.heap;const char *name=operation.s->data;
    double x,y=0,z;size_t i;
    if(args->len<1||args->len>2)return ru_interpreter_result(v_null(),"数学实参数量无效");
    for(i=0;i<args->len;++i)if(args->items[i].kind!=RU_NUM)
        return ru_interpreter_result(v_null(),"数学实参须为数");
    x=args->items[0].n;if(args->len==2)y=args->items[1].n;
    if(!strcmp(name,"平方根"))z=sqrt(x);
    else if(!strcmp(name,"幂"))z=y==0?1:pow(x,y);
    else if(!strcmp(name,"向下取整"))z=floor(x);
    else if(!strcmp(name,"向上取整"))z=ceil(x);
    else if(!strcmp(name,"四舍五入"))z=round(x);
    else if(!strcmp(name,"正弦"))z=sin(x);
    else if(!strcmp(name,"余弦"))z=cos(x);
    else if(!strcmp(name,"角度转弧度"))z=x*(3.141592653589793/180.0);
    else if(!strcmp(name,"弧度转角度"))z=x*(180.0/3.141592653589793);
    else if(!strcmp(name,"方向角"))z=atan2(x,y);
    else return ru_interpreter_result(v_null(),"未知数学接口");
    if(!isfinite(z))return ru_interpreter_result(v_null(),"数学运算的定义域无效或结果不是有限数");
    return ru_interpreter_result(v_num(z),NULL);
}
static Val ru_interpreter_path(Val path)
{
    Val result;
#ifdef _WIN32
    wchar_t *wide=ru_io_wide(path.s->data),*resolved;DWORD count,actual;HANDLE handle;int size;
    if(!wide)return ru_interpreter_result(v_null(),"外言路径不是有效 UTF-8");
    handle=CreateFileW(wide,FILE_READ_ATTRIBUTES,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,
                       NULL,OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS,NULL);free(wide);
    if(handle==INVALID_HANDLE_VALUE)return ru_interpreter_result(v_null(),"外言路径不存在或无法访问");
    count=GetFinalPathNameByHandleW(handle,NULL,0,FILE_NAME_NORMALIZED);
    if(!count){CloseHandle(handle);return ru_interpreter_result(v_null(),"无法规范化外言路径");}
    resolved=ru_alloc(((size_t)count+1)*sizeof(wchar_t),0);
    actual=GetFinalPathNameByHandleW(handle,resolved,count+1,FILE_NAME_NORMALIZED);
    if(!actual||actual>count) {
        CloseHandle(handle);free(resolved);return ru_interpreter_result(v_null(),"无法规范化外言路径");
    }
    CloseHandle(handle);
    size=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,resolved,-1,NULL,0,NULL,NULL);
    if(!size){free(resolved);return ru_interpreter_result(v_null(),"外言路径无法转换为 UTF-8");}
    result=ru_string_alloc((size_t)size-1,0);
    WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,resolved,-1,result.s->data,size,NULL,NULL);free(resolved);
    {
        Val clean;size_t i,skip=0;int unc=0;
        if(!strncmp(result.s->data,"\\\\?\\UNC\\",8)){skip=8;unc=1;}
        else if(!strncmp(result.s->data,"\\\\?\\",4))skip=4;
        clean=ru_string_alloc(result.s->len-skip+(unc?2:0),0);
        if(unc){clean.s->data[0]='/';clean.s->data[1]='/';}
        for(i=skip;i<result.s->len;++i)
            clean.s->data[i-skip+(unc?2:0)]=result.s->data[i]=='\\'?'/':result.s->data[i];
        v_drop(result);result=clean;
    }
#else
    char *resolved=realpath(path.s->data,NULL);
    if(!resolved)return ru_interpreter_result(v_null(),"外言路径不存在或无法访问");
    result=v_str(resolved);free(resolved);
#endif
    return ru_interpreter_result(result,NULL);
}
static Val ru_interpreter_field(Val map,const char *key,Val value)
{
    Val name=v_str(key),result=v_map_put(map,name,value,0);
    v_drop(result);v_drop(name);v_drop(value);return map;
}
/* Bytes owned by the dynamic value heap, including backing buffers and Env
 * bindings. This excludes the allocator's metadata, OS handles and C stack.
 * It is sampled only during graphics callback budget checks. */
static double ru_interpreter_heap_bytes(void)
{
    RuHeap *heap;double total=0;
    for(heap=ru_heap;heap;heap=heap->next) {
        switch(heap->kind) {
        case RU_STR: total+=sizeof(RuString)+((RuString *)heap)->len+1;break;
        case RU_ARRAY: total+=sizeof(RuArray)+((RuArray *)heap)->capacity*sizeof(Val);break;
        case RU_MAP: total+=sizeof(RuMap)+((RuMap *)heap)->capacity*sizeof(RuMapEntry);break;
        case RU_OBJECT: total+=sizeof(RuObject)+((RuObject *)heap)->len*sizeof(Val);break;
        case RU_PAIR: total+=sizeof(RuPair);break;
        case RU_FUNCTION: total+=sizeof(RuCallable);break;
        case RU_ENV: {
            RuBinding *binding;total+=sizeof(Env);
            for(binding=((Env *)heap)->bindings;binding;binding=binding->next)
                total+=sizeof(*binding)+strlen(binding->name)+1;
            break;
        }
        }
    }
    return total;
}
/* RU2 header followed by exact byte payloads. Source and user input never
 * become protocol syntax. JSON event records travel in the opposite direction. */
static Val ru_interpreter_receive(void)
{
    char header[96],kind,extra;unsigned long long first,second;
    size_t sizes[2],i;Val payloads[2],result;int invalid=0;
    if(!fgets(header,sizeof(header),stdin))return v_null();
    if(!strchr(header,'\n')||sscanf(header,"RU2 %c %llu %llu %c",&kind,&first,&second,&extra)!=3)
        return v_null();
    if(kind=='Q'&&first==0&&second==0)return v_null();
    if(kind!='E'&&kind!='I'&&kind!='G'&&kind!='R')return v_null();
    if(first>800000||second>(kind=='I'?1:16384))return v_null();
    sizes[0]=(size_t)first;sizes[1]=kind=='I'?0:(size_t)second;
    for(i=0;i<2;++i) {
        size_t count=0;payloads[i]=ru_string_alloc(sizes[i],0);
        while(count<sizes[i]) {
            size_t got=fread(payloads[i].s->data+count,1,sizes[i]-count,stdin);
            if(!got){v_drop(payloads[i]);if(i)v_drop(payloads[0]);return v_null();}
            count+=got;
        }
        if(memchr(payloads[i].s->data,0,sizes[i]) || !ru_valid_utf8(payloads[i].s->data,sizes[i])) {
            v_drop(payloads[i]);payloads[i]=v_str("");invalid=1;
        }
    }
    result=v_map_new(0);
    ru_interpreter_field(result,"kind",v_str(kind=='E'?"execute":kind=='I'?"input":kind=='G'?"graphics":"graphics_rejected"));
    ru_interpreter_field(result,"text",payloads[0]);
    ru_interpreter_field(result,"source",payloads[1]);
    ru_interpreter_field(result,"eof",v_fact(kind=='I'&&second));
    ru_interpreter_field(result,"invalid",v_fact(invalid));
    return result;
}
static int ru_interpreter_member(Val receiver,const char *name,size_t argc,
                                 const char **keys,Val *args,int line,Val *out)
{
    (void)keys;
    if(receiver.kind!=RU_OBJECT || ((RuObject *)receiver.heap)->klass!=&ru_interpreter_service)return 0;
    if(!strcmp(name,"种")&&argc==1)*out=ru_interpreter_literal(v_type_name(args[0]));
    else if(!strcmp(name,"同一")&&argc==2) {
        int same=args[0].kind==args[1].kind;
        if(same) {
            if(args[0].heap||args[1].heap)same=args[0].heap==args[1].heap;
            else if(args[0].kind==RU_NUM||args[0].kind==RU_FACT)same=args[0].n==args[1].n;
            else if(args[0].kind==RU_CLASS)same=args[0].klass==args[1].klass;
            else if(args[0].kind==RU_MODULE)same=args[0].module==args[1].module;
        }
        *out=v_fact(same);
    }
    else if(!strcmp(name,"深")&&!argc)*out=v_num(ru_call_depth);
    else if(!strcmp(name,"存")&&!argc)*out=v_num(ru_interpreter_heap_bytes());
    else if(!strcmp(name,"时")&&!argc) {
#ifdef _WIN32
        LARGE_INTEGER now,frequency;
        *out=v_num(QueryPerformanceCounter(&now)&&QueryPerformanceFrequency(&frequency)&&frequency.QuadPart>0
                   ?(double)now.QuadPart/(double)frequency.QuadPart:-1);
#else
        struct timespec now;
        *out=v_num(clock_gettime(CLOCK_MONOTONIC,&now)==0?(double)now.tv_sec+(double)now.tv_nsec/1e9:-1);
#endif
    }
    else if(!strcmp(name,"字节")&&argc==1&&args[0].kind==RU_STR)*out=v_num((double)args[0].s->len);
    else if(!strcmp(name,"JSON数")&&argc==1&&args[0].kind==RU_NUM&&isfinite(args[0].n)) {
        char buffer[32];snprintf(buffer,sizeof(buffer),"%.17g",args[0].n);*out=v_str(buffer);
    }
    else if(!strcmp(name,"空白")&&argc==1&&args[0].kind==RU_STR)
        *out=v_fact(args[0].s->len==1&&ru_ascii_space((unsigned char)args[0].s->data[0]));
    else if(!strcmp(name,"限字")&&argc==2&&args[0].kind==RU_STR&&args[1].kind==RU_NUM&&args[1].n>=0) {
        size_t length=args[0].s->len,limit=args[1].n>=(double)length?length:(size_t)args[1].n;
        while(limit && (((unsigned char)args[0].s->data[limit]&0xc0)==0x80))--limit;
        *out=ru_string_alloc(limit,line);memcpy(out->s->data,args[0].s->data,limit);
    }
    else if(!strcmp(name,"有目")&&argc==2&&args[0].kind==RU_MAP) {
        RuMap *map=(RuMap *)args[0].heap;int found=0;
        if(map->capacity)ru_map_find(map,args[1],ru_key_hash(args[1],line),map->version,line,&found);
        *out=v_fact(found);
    }
    else if(!strcmp(name,"运算")&&argc==3&&args[0].kind==RU_STR)
        *out=ru_interpreter_arithmetic(args[0],args[1],args[2]);
    else if(!strcmp(name,"数")&&argc==1)*out=ru_interpreter_number(args[0]);
    else if(!strcmp(name,"数学")&&argc==2&&args[0].kind==RU_STR&&args[1].kind==RU_ARRAY)
        *out=ru_interpreter_math(args[0],args[1]);
    else if(!strcmp(name,"实路")&&argc==1&&args[0].kind==RU_STR)*out=ru_interpreter_path(args[0]);
    else if(!strcmp(name,"接")&&!argc)*out=ru_interpreter_receive();
    else if(!strcmp(name,"发")&&argc==1&&args[0].kind==RU_STR) {
        if(fwrite(args[0].s->data,1,args[0].s->len,stdout)!=args[0].s->len||fputc('\n',stdout)==EOF||fflush(stdout))
            ru_fail(line,"解释内核协议输出失败");
        *out=v_null();
    } else ru_fail(line,"无效解释宿主调用：%s",name);
    return 1;
}
