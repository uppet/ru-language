#!/usr/bin/env python3
"""Deterministic output checks across record count and repeated scan boundaries."""
import json
from pathlib import Path
import tempfile
from benchmark import build, run, expected


def main():
    results=[]
    with tempfile.TemporaryDirectory(prefix='ru-record-layout-') as tmp:
        root=Path(tmp)
        for count, scans in ((1,1),(17,3),(250,1),(251,2),(252,3),(4097,2)):
            directory=root/f'{count}-{scans}'
            directory.mkdir()
            for kind in ('dynamic','packed'):
                build(kind,count,scans,directory)
                result=run(directory/kind,expected(count,scans),directory/'rss.txt')
                results.append({'count':count,'scans':scans,'kind':kind,'output':result['stdout']})
    print(json.dumps({'schema':1,'passed':len(results),'cases':results},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
