#!/usr/bin/env python3
"""Compare every sorted field to independent Python stable sorted oracle."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from sort_benchmark import build, expected, MAX_COUNT, source


def main():
    results = []
    cases = [(0,'mixed'),(1,'mixed'),(2,'reverse'),(17,'mixed'),
             (31,'equal'),(32,'sorted'),(33,'reverse'),(256,'mixed'),
             (257,'mixed'),(258,'mixed'),(4097,'mixed')]
    with tempfile.TemporaryDirectory(prefix='ru-record-sort-') as tmp:
        for count, pattern in cases:
            directory = Path(tmp)/f'{count}-{pattern}'
            directory.mkdir()
            oracle = expected(count,pattern,True)
            for kind in ('dynamic','packed'):
                artifact = build(kind,count,pattern,True,directory)
                # Untimed correctness process: no RSS runner or phase results retained.
                result = subprocess.run([str(directory/kind)],capture_output=True,text=True,
                                        check=False,timeout=180,
                                        env={k:v for k,v in os.environ.items() if k not in ('RU_GC_THRESHOLD','RU_GC_STATS')})
                if result.returncode:
                    raise AssertionError((count,pattern,kind,result.returncode,result.stderr))
                if result.stdout != oracle:
                    raise AssertionError((count,pattern,kind,result.stdout[:1000],oracle[:1000]))
                results.append({'count':count,'pattern':pattern,'kind':kind,
                                'all_fields_match_python_stable_sort':True,
                                'output_sha256':hashlib.sha256(result.stdout.encode()).hexdigest(),
                                'source_sha256':artifact['source_sha256']})
    for bad in (-1,MAX_COUNT+1):
        try:
            source('packed',bad)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid count accepted')
    print(json.dumps({'schema':1,'passed':len(results),'full_output_comparison':True,
                      'range_guards_passed':True,'cases':results},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
