"""Reproducible independent oracle + C/JS semantic tests, standard library only."""
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest
import generate
from rulang.cli import compiler_command
from rulang.llvm_toolchain import find_clang
from rulang.toolchain_environment import llvm_environment

HERE=Path(__file__).resolve().parent
MAX=2**32-1
EXE=".exe" if os.name == "nt" else ""
UBSAN=os.name != "nt"
def compile_kernel(args):
    selected = os.environ.get('CC') or shutil.which('gcc') or find_clang()
    if not selected: raise AssertionError('需要 C 编译器或本地 LLVM 14')
    defines = ['-D_CRT_SECURE_NO_WARNINGS'] if os.name == 'nt' else []
    subprocess.run(compiler_command(selected) + defines + args, env=llvm_environment(), check=True)
def executable(directory, name):
    return directory / (name + EXE)
def sanitize_flags():
    return ["-fsanitize=undefined", "-fno-sanitize-recover=all"] if UBSAN else []
C_HARNESS=r'''
#include "kernel.h"
#include <stdio.h>
#include <stdlib.h>
#include <inttypes.h>
int main(void) {
    char hex[8194]; int64_t off,n,seed; int closed;
    MiOwner empty={NULL,0,0,0};
    if(mi_scan(&empty,0,0,0).status || !mi_truth_u32(0)) return 21;
    empty.borrows=1;
    if(mi_close(&empty)!=MI_BORROWED || empty.closed) return 22;
    empty.borrows=0;
    if(mi_close(&empty)!=MI_OK || !empty.closed) return 23;
    MiOwner saturated={NULL,0,UINT32_MAX,0};
    if(mi_scan(&saturated,0,0,0).status!=MI_RANGE || saturated.borrows!=UINT32_MAX) return 24;
    MiOwner invalid={NULL,1,0,0};
    if(mi_scan(&invalid,0,1,0).status!=MI_RANGE || invalid.borrows) return 25;
    while(scanf("%8193s %" SCNd64 " %" SCNd64 " %" SCNd64 " %d",hex,&off,&n,&seed,&closed)==5) {
        uint8_t data[4096]; uint32_t size=0;
        if(hex[0]!='-') {
            for(char *p=hex;*p;p+=2) {
                unsigned byte;
                if(size==4096 || !p[1] || sscanf(p,"%2x",&byte)!=1) return 26;
                data[size++]=(uint8_t)byte;
            }
        }
        MiOwner owner={data,size,0,closed};
        MiResult r=mi_scan_checked(&owner,off,n,seed);
        printf("%d %" PRIu32 " %" PRIu32 "\n",r.status,r.count,owner.borrows);
        if(mi_close(&owner)!=MI_OK) return 27;
    }
    return 0;
}
'''
JS_HARNESS=r'''
const fs=require('fs'); const {Owner,scan,truthU32}=require(process.argv[2]);
if(!truthU32(0)) throw Error('zero false');
const source=new Uint8Array([13,10]); const isolated=new Owner(source); source.fill(0);
if(scan(isolated,0,2).count!==1) throw Error('external alias mutated owner');
for(const [hex,offset,length,seed,closed] of JSON.parse(fs.readFileSync(0,'utf8'))) {
 const owner=new Owner(new Uint8Array(Buffer.from(hex,'hex')));
 if(closed) owner.close();
 const r=scan(owner,offset,length,seed);
 console.log(`${r.status} ${r.count} ${owner.borrows}`);
 if(owner.close()!==0) throw Error('borrow not released');
}
'''

def oracle(row):
    text, off,n,seed,closed=row
    if not 0<=seed<=MAX:return (5,0,0)
    if not 0<=off<=MAX or not 0<=n<=MAX:return (5,seed,0)
    if closed:return (3,seed,0)
    data=bytes.fromhex(text)
    if off>len(data) or n>len(data)-off:return (1,seed,0)
    # Independent chunk tokenization, not the generator's previous-byte loop.
    parts=data[off:off+n].replace(b'\r\n',b'\n').replace(b'\r',b'\n').split(b'\n')
    amount=len(parts)-1
    if amount>MAX-seed:return (2,MAX,0)
    return (0,seed+amount,0)


def cases():
    rows=[]
    for b in (b'',b'a',b'\n',b'\r',b'\r\n',b'\r\r\n',b'\n\r',b'a\r\nb\rc\n', b'\x00\xff\r\n\x80', '如\n言'.encode()):
        rows.append((b.hex(),0,len(b),0,0))
        rows.append((b.hex(),0,len(b),MAX,0))
        rows.append((b.hex(),0,len(b),MAX-1,0))
    rng=random.Random(649)
    for _ in range(600):
        b=bytes(rng.choice([0,10,13,65,255,rng.randrange(256)]) for _ in range(rng.randrange(150)))
        off=rng.randrange(len(b)+1); n=rng.randrange(len(b)-off+1)
        rows.append((b.hex(),off,n,rng.choice([0,MAX,MAX-1,MAX-4]),0))
    for off,n,seed,closed in [(0,0,0,0),(3,0,0,0),(4,0,0,0),(0,4,0,0),(MAX,2,0,0),(0,MAX,0,0),(-1,1,0,0),(0,-1,0,0),(MAX+1,0,0,0),(0,MAX+1,0,0),(0,0,-1,0),(0,0,MAX+1,0),(0,1,0,1),(0,-1,0,1)]:
        rows.append(('0d0a0a',off,n,seed,closed))
    return rows

class KernelTests(unittest.TestCase):
    def test_generated_raw_bytes_are_reproducible(self):
        # Git normalizes CRLF: compare raw bytes, not just git diff text.
        expected = {
            'kernel.h': '00b73730803725dc361df8f18a507b78fee84a9dcf391346f35f60182df3a6c4',
            'kernel.js': '9f772e42c3ce3cc911d1b1962080f1cd710a9bc8b38c0cff58956a4c357cb1c0',
            'metadata.json': '73eeaad8026c733e27bba82f0d74db9bd9ac1280f4877304b32e677b6af12ac5',
        }
        generate.generate()
        for name, digest in expected.items():
            data = (HERE/'generated'/name).read_bytes()
            with self.subTest(name=name):
                data.decode('utf-8', errors='strict')
                self.assertNotIn(b'\r', data)
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)

    def test_legacy_types_and_signature_reused(self):
        new=generate.signature('非负32',['非负8','非负32'])
        old=generate.NativeCSignature('u32',('u8','u32'))
        self.assertEqual(new,old)
        self.assertEqual(generate.PRIMITIVES['u32'].size,4)
        self.assertEqual(generate.PRIMITIVES['u8'].size,1)
        self.assertEqual(generate.C_TYPES['u32'],'uint32_t')

    def test_ir_rejects_undecided_and_escape(self):
        original=json.loads((HERE/'scan.ir.json').read_text())
        bad=[]
        for ret in [['var','data'],['div',['const','u32',3],['const','u32',2]],['const','u32',MAX+1],['const','u32',-1],['const','u32',1.0],['const','f32',0]]:
            ir=copy.deepcopy(original);ir['return']=ret;bad.append(ir)
        for stmt in [['box',['var','data']],['global','saved',['var','data']],['set','data',['var','data']],['set','count',['const','u8',1]],['set','seed',['const','u32',0]],['set','current',['load',['const','u8',0]]]]:
            ir=copy.deepcopy(original);ir['body'].append(stmt);bad.append(ir)
        for ir in bad:
            with self.subTest(ir=ir), self.assertRaises(ValueError):generate.validate(ir)

    def test_local_names_are_mangled(self):
        source=(HERE/'scan.ir.json').read_text()
        cbodies=[]; jsbodies=[]
        for i,(old,name) in enumerate((('current','byte_1'),('current','local_0'),('current','return'),('current','class'),('current','UINT32_MAX'),('i','payload'))):
            ir=json.loads(source.replace(json.dumps(old),json.dumps(name)))
            cbodies.append(f'static MiResult p{i}(const uint8_t *data,uint32_t length,uint32_t seed) {{\n'+generate.lower(ir,'c')+'\n}')
            jsbodies.append(f'function p{i}(data,length,seed) {{\n'+generate.lower(ir,'js')+'\n}')
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            c='#include "kernel.h"\n'+'\n'.join(cbodies)+'\nint main(void) { const uint8_t b[]={10,13,10};\n'+''.join(f'if(p{i}(b,3,0).count!=2) return 1;\n' for i in range(6))+'return 0; }'
            (d/'p.c').write_text(c)
            compile_kernel(['-std=c11','-O2','-I',str(HERE/'generated'),str(d/'p.c'),'-o',str(executable(d,'p'))])
            subprocess.run([str(executable(d,'p'))],check=True)
            js='const MI_OK=0,MI_BOUNDS=1,MI_OVERFLOW=2;\n'+'\n'.join(jsbodies)+'\n'+''.join(f'if(p{i}(new Uint8Array([10,13,10]),3,0).count!==2) process.exit(1);' for i in range(6))
            subprocess.run(['node','-e',js],check=True)

    def test_checked_load_and_partial_internal_effect(self):
        ir=json.loads((HERE/'scan.ir.json').read_text())
        ir['body']=[['add_checked','count',['const','u32',1]], ['set','current',['load',['var','length']]]]
        cbody=generate.lower(ir,'c'); jsbody=generate.lower(ir,'js')
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            c='#include "kernel.h"\nstatic MiResult probe(const uint8_t *data,uint32_t length,uint32_t seed) {\n'+cbody+'\n}\nint main(void) { MiResult r=probe(NULL,0,40); return !(r.status==MI_BOUNDS && r.count==41); }\n'
            (d/'p.c').write_text(c)
            compile_kernel(['-std=c11','-O1',*sanitize_flags(),'-I',str(HERE/'generated'),str(d/'p.c'),'-o',str(executable(d,'p'))])
            subprocess.run([str(executable(d,'p'))],check=True)
            js='const MI_OK=0,MI_BOUNDS=1,MI_OVERFLOW=2; function probe(data,length,seed) {\n'+jsbody+'\n}\nconst r=probe(new Uint8Array(),0,40); if(r.status!==1 || r.count!==41) process.exit(1);'
            subprocess.run(['node','-e',js],check=True)

    def test_differential(self):
        generate.generate()
        rows=cases();expected=[oracle(r) for r in rows]
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);(d/'h.c').write_text(C_HARNESS);(d/'h.js').write_text(JS_HARNESS)
            compile_kernel(['-std=c11','-O2','-Wall','-Wextra','-Werror','-I',str(HERE/'generated'),str(d/'h.c'),'-o',str(executable(d,'h'))])
            cinput=''.join(f'{h or "-"} {o} {n} {s} {closed}\n' for h,o,n,s,closed in rows)
            c=subprocess.run([str(executable(d,'h'))],input=cinput,text=True,capture_output=True,check=True)
            js=subprocess.run(['node',str(d/'h.js'),str(HERE/'generated/kernel.js')],input=json.dumps(rows),text=True,capture_output=True,check=True)
            for backend,out in [('C',c.stdout),('JS',js.stdout)]:
                actual=[tuple(map(int,line.split())) for line in out.splitlines()]
                self.assertEqual(len(actual),len(expected))
                for i,(got,want) in enumerate(zip(actual,expected)):
                    with self.subTest(backend=backend,index=i,case=rows[i]):self.assertEqual(got,want)
            # Windows MinGW does not ship a usable UBSan runtime. All semantic
            # cases still run above; Linux CI requires this additional backend.
            if UBSAN:
                compile_kernel(['-std=c11','-O1','-g',*sanitize_flags(),'-I',str(HERE/'generated'),str(d/'h.c'),'-o',str(executable(d,'h-ubsan'))])
                u=subprocess.run([str(executable(d,'h-ubsan'))],input=cinput,text=True,capture_output=True,check=True)
                self.assertEqual(u.stdout,c.stdout);self.assertEqual(u.stderr,'')
        (HERE/'semantic-results.json').write_text(json.dumps({'cases_per_backend':len(rows),'backends':['C O2','JS Node'] + (['C UBSan'] if UBSAN else []),'ubsan_required_on_this_platform':UBSAN,'oracle':'independent CRLF token normalization','random_seed':649,'partial_count_on_overflow':'UINT32_MAX (previous increments retained; internal result only)','no_external_output_buffer':True},indent=2)+'\n')

if __name__=='__main__':unittest.main(verbosity=2)
