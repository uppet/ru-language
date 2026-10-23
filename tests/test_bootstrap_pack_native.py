"""Real Win64 stage3 pack fastpath coverage on the unchanged slot FFI fixture.

The inherited production/probe test keeps the existing 12-callback, two-panic,
source/depth restoration and retry oracle. Only the labelled probe additionally
logs consumption of each of the two relevant owned array argument regions.
"""
import json
from pathlib import Path
import re
from unittest.mock import patch

import test_bootstrap_slot_reuse_native as slots

CALL_SOURCES = (
    '    果 取 原生调 其 调用 [内回,值].',
    '    果 取 原生调 其 调用 [外回,模式].',
)


def split_arguments(text):
    result, start, depth = [], 0, 0
    for index, char in enumerate(text):
        if char in '([': depth += 1
        elif char in ')]': depth -= 1
        elif char == ',' and depth == 0:
            result.append(text[start:index].strip()); start = index + 1
        if depth < 0: raise AssertionError('unbalanced IR arguments')
    if depth: raise AssertionError('unbalanced IR arguments')
    result.append(text[start:].strip())
    return result


def calls(body, name):
    output = []
    for match in re.finditer(r'^  call void @rul_'+name+r'\((.*)\)$', body, re.M):
        output.append((match.start(), match.end(), split_arguments(match.group(1))))
    return output


def argument_regions(ir, source):
    """Bind the actual fixture's two callsites to original owned array outputs."""
    lines = source.splitlines()
    expected = []
    for statement in CALL_SOURCES:
        if lines.count(statement) != 1:
            raise AssertionError('exact native pack callsite missing/duplicated')
        expected.append(lines.index(statement)+1)
    if expected != [26,39]:
        raise AssertionError('unchanged reviewed native fixture lines required')
    result = []
    for source_line in expected:
        hits = []
        for body in re.findall(r'define void @[^}]+}', ir):
            indices = {name:int(index) for name,index in re.findall(
                r'(%v\d+) = call i8\* @rul_slot\(i8\* %frame, i32 (\d+)\)', body)}
            for apos, aend, array in calls(body,'array'):
                if len(array) != 4 or array[1] != 'i32 2' or array[3] != 'i32 '+str(source_line):
                    continue
                for mpos, mend, member in calls(body,'member_finish'):
                    if (len(member) != 9 or member[3] != 'i32 1'
                            or member[6] != 'i32 '+str(source_line) or mpos <= apos):
                        continue
                    array_out = array[0].removeprefix('i8* ')
                    values = array[2].removeprefix('i8* ')
                    out, receiver, args, prepared = [member[i].removeprefix('i8* ') for i in (0,1,5,8)]
                    if args != array_out:
                        raise AssertionError('complex single argument copied instead of owned-result reuse')
                    if len({out,receiver,args,prepared}) != 4:
                        raise AssertionError('native input/output/receiver/prepared alias')
                    if not all(value in indices for value in (array_out,values,out,receiver,prepared)):
                        raise AssertionError('native inputs must be actual rooted frame slots')
                    between = body[aend:mpos]
                    if '@rul_clear(' in between or re.search(r'@rul_copy\(i8\* '+re.escape(args)+r',',between):
                        raise AssertionError('owned argument root released or replaced before native consumption')
                    if indices[out] <= indices[array_out] or indices[array_out] <= indices[values]+1:
                        raise AssertionError('array output/member output must follow input region')
                    # The array itself is the contiguous two-simple-name fastpath.
                    prior = body[:apos]
                    getters = calls(prior,'get')
                    last = [(p,a[0].removeprefix('i8* ')) for p,_,a in getters
                            if len(a)==4 and a[3]=='i32 '+str(source_line)]
                    if len(last)<2 or [indices.get(x[1]) for x in last[-2:]] != [indices[values],indices[values]+1]:
                        raise AssertionError('two simple array values not original contiguous result slots')
                    hits.append({'source_line':source_line,'array_result':args,
                        'array_input_indices':[indices[values],indices[values]+1],
                        'array_result_index':indices[args], 'consumer_output_index':indices[out],
                        'member_receiver_index':indices[receiver], 'prepared_index':indices[prepared],
                        'single_complex_fastpath':True,'two_simple_fastpath':True})
        if len(hits) != 1:
            raise AssertionError('exactly one attested native callsite required for source line '+str(source_line))
        result.extend(hits)
    return result


def consumption_probe(runtime, source):
    """Diagnostic only; production runtime and binary remain unmodified."""
    anchor = '{ rul_put(out,v_member_finish(*(Val *)receiver,name,(size_t)argc,keys,args,line,mode,*(Val *)prepared)); }'
    if runtime.count(anchor) != 1:
        raise AssertionError('exact member-finish boundary required')
    # Both are spellings of the exact generated owned main.ru, never arbitrary files.
    spellings = sorted({str(source),source.as_posix()})
    checks = ' || '.join('strcmp(ru_source,'+json.dumps(p,ensure_ascii=False)+') == 0' for p in spellings)
    injected = '{ if (argc == 1 && (line == 26 || line == 39) && ('+checks+') && strcmp(name,"调用") == 0) '
    injected += '{ uint32_t pack_probe_error = rn_platform_error(); int pack_probe_errno = errno; '
    injected += 'fprintf(stderr,"PACK_NATIVE_ARG_REGION line=%d\\n",line); '
    injected += 'errno = pack_probe_errno; rn_platform_set_error(pack_probe_error); } '
    injected += anchor[2:]
    return runtime.replace(anchor, injected)


class PackNativeCallbackTests(slots.SlotReuseNativeCallbackTests):
    def test_parent_temporaries_survive_nested_callback_panic_retry(self):
        original = slots.probe_runtime
        def labelled(runtime):
            return consumption_probe(original(runtime), self.directory/'probe/main.ru')
        with patch.object(slots,'probe_runtime',side_effect=labelled):
            super().test_parent_temporaries_survive_nested_callback_panic_retry()
        rows = []
        for label in ('production','probe'):
            directory = self.directory/label
            source = (directory/'main.ru').read_text(encoding='utf-8')
            irpath = directory/'program.exe.frontend.ll'
            regions = argument_regions(irpath.read_text(encoding='utf-8'),source)
            stderr = (directory/'stderr.txt').read_text(encoding='utf-8')
            counts = {str(line):stderr.count('PACK_NATIVE_ARG_REGION line='+str(line)+'\n') for line in (26,39)}
            self.assertEqual(counts, {'26':6,'39':6} if label=='probe' else {'26':0,'39':0})
            self.assertEqual(stderr.count('PACK_NATIVE_ARG_REGION'),12 if label=='probe' else 0)
            rows.append({'kind':label,'frontend_ir_sha256':slots.sha(irpath.read_bytes()),
                'source_sha256':slots.sha((directory/'main.ru').read_bytes()),
                'regions':regions,'dynamic_consumptions':counts,
                'diagnostic_only':label=='probe'})
        (self.directory/'pack-coverage.json').write_text(json.dumps({
            'schema':'ru-pack-native-coverage-v1','case':self.id(),'complete':True,
            'scope':'stage3 ordinary Win64 only; exact two original-owned argument regions; no Python-native/dense claims',
            'programs':rows},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
