#!/usr/bin/env python3
"""Reproduce the native frontend's frozen Unicode 13.0.0 classifier data."""
from pathlib import Path
import unicodedata

ROOT = Path(__file__).resolve().parents[1]


def boundaries(predicate):
    points, inside = [], False
    for value in range(0x110000):
        matched = predicate(chr(value))
        if matched and not inside:
            points.append(chr(value))
            inside = True
        elif inside and not matched:
            points.append(chr(value-1))
            inside = False
    if inside:
        points.append(chr(0x10ffff))
    return ''.join(points)


def prefix():
    if unicodedata.unidata_version != '13.0.0':
        raise RuntimeError('Use Python with Unicode 13.0.0 (e.g. Python 3.10); do not silently change identifier rules.')
    text = '# 如言编译器：词法、语法、语义准备和直接 LLVM 发射均由如源码实现。\n'
    text += '# Unicode 13.0.0；边界由 Python Unicode 字母/字母数字属性冻结生成，运行不调用 Python。\n'
    for name, predicate in (('字母边界', str.isalpha), ('名称边界', str.isalnum)):
        text += name+" 取 __如竞 其 字列 '"+boundaries(predicate)+"'.\n"
    space = ''.join(chr(i) for i in range(0x110000) if chr(i).isspace())
    space = space.replace('\\','\\\\').replace("'","\\'").replace('\n','\\n').replace('\r','\\r').replace('\t','\\t')
    return text+"空白字 取 __如竞 其 字列 '"+space+"'.\n"


def main():
    source = ROOT/'bootstrap/compiler.ru'
    text = source.read_text(encoding='utf-8')
    updated = prefix()+text[text.index('关键词 取'):]
    source.write_text(updated, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
