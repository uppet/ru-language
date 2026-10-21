#!/usr/bin/env python3
"""Reproduce ordinary Ru C/JS semantic baseline against an independent oracle."""
import json
import os
from pathlib import Path
import random
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=HERE/'benchmark-output'

def main():
    OUT.mkdir(exist_ok=True)
    rng=random.Random(649)
    cases=[[],[13],[10],[13,10],[13,13,10],[10,13],
           [0,10,0,13,10,255],[65,66]]
    cases += [[rng.choice([0,10,13,65,255]) for _ in range(rng.randrange(128))] for _ in range(64)]
    # Independent bytes splitting oracle: normalize CRLF, then CR to LF.
    expected=[bytes(v).replace(b'\r\n',b'\n').replace(b'\r',b'\n').count(b'\n') for v in cases]
    source=OUT/'ordinary-correctness.ru'
    source.write_text((HERE/'baseline.ru').read_text()+''.join('显 (数行界 字节:'+str(v)+').\n' for v in cases))
    for target in ('c','js'):
        artifact=OUT/('ordinary-correctness'+('.js' if target=='js' else ('.exe' if os.name=='nt' else '')))
        subprocess.run([sys.executable,str(ROOT/'ru'),'build',str(source),'--target',target,'-o',str(artifact)],cwd=ROOT,check=True,capture_output=True)
        command=['node',str(artifact)] if target=='js' else [str(artifact)]
        got=list(map(int,subprocess.check_output(command,text=True).split()))
        if got!=expected:raise AssertionError((target,got,expected))
    (OUT/'ordinary-correctness.json').write_text(json.dumps({'cases':len(cases),'random_seed':649,'random_cases':64,'c':'pass','js':'pass','fixtures':cases,'expected':expected},indent=2)+'\n')
    print('ordinary baseline C/JS: 72 fixtures passed, including 64 seeded random inputs')

if __name__=='__main__':main()
