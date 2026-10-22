# Native entry point. The service/transport does not evaluate source code.
解释 取 外言 'interpreter.ru'.
前端 取 外言 '../../bootstrap/compiler.ru'.

算 JSON错 错:
    得 '{"type":"error","category":'+(前端 其 JSON句 错['category'])+
        ',"message":'+(前端 其 JSON句 错['message'])+',"source_name":'+(前端 其 JSON句 错['source_name'])+
        ',"line":'+(错['line'] 为 句)+',"col":'+(错['col'] 为 句)+'}'.
法.
算 元初 参数 为 句 阵:
    若 (参数 其 量) < 1 则
        错误 其 写 内容:'用法：native-kernel SOURCE [STDLIB [ARGS...]] 或 native-kernel --stdio STDLIB\n'. 得 2.
    然.
    标准库 取 'rulang/stdlib'. 若 (参数 其 量) > 1 则 标准库 取 参数[1]. 然.
    若 参数[0] == '--stdio' 则
        状 取 解释 其 创建 标准库 作 流 文 截断:
            末 取 '}'. 若 截断 则 末 取 ',"truncated":true}'. 然.
            __如释 其 发 ('{"type":"output","stream":'+(前端 其 JSON句 流)+',"text":'+(前端 其 JSON句 文)+末).
        为.
        解释 其 设 状 '协议' 真.
        __如释 其 发 '{"type":"ready","protocol":2,"engine":"ru-ast"}'.
        循
            信 取 __如释 其 接. 若 信 == 空 则 破. 然.
            若 信['kind'] == 'graphics_rejected' 则 解释 其 图拒 状 信['source'].
            另 若 信['kind'] == 'graphics' 则
                错 取 解释 其 图事 状 信. 态 取 'ok'. 若 错 != 空 则 __如释 其 发 (JSON错 错). 态 取 'error'. 然.
                __如释 其 发 ('{"type":"graphics_done","canvas_id":'+(前端 其 JSON句 信['source'])+',"status":"'+态+'"}').
            另
            若 信['kind'] != 'execute' 则 得 2. 然.
            错 取 空.
            若 信['invalid'] 则 错 取 {'category':'语法错误','message':'源码及来源不能含 NUL，且须为有效 UTF-8','source_name':信['source'],'line':1,'col':1}.
            另 错 取 解释 其 执行 状 信['text'] 信['source'] 真. 然.
            若 错 != 空 则 __如释 其 发 (JSON错 错). __如释 其 发 '{"type":"done","status":"error"}'.
            另 __如释 其 发 '{"type":"done","status":"ok"}'. 然.
            然. 然.
        环. 得 0.
    然.
    状 取 解释 其 创建 标准库 作 流 文 截断:
        若 流 == 'stderr' 则 错误 其 写 内容:文. 另 显出 其 写 内容:文. 然.
    为.
    路果 取 __如释 其 实路 参数[0].
    若 非 路果[0] 则 错误 其 写 内容:(路果[2]+'\n'). 得 1. 然.
    文件 取 路果[1].
    试:
        错 取 解释 其 执行 状 (前端 其 读文 文件) 文件 假.
        若 错 != 空 则 错误 其 写 内容:(错['source_name']+':'+(错['line'] 为 句)+':'+(错['col'] 为 句)+': error: '+错['category']+'：'+错['message']+'\n'). 得 1. 然.
        外参 取 []. 若 (参数 其 量) > 2 则 外参 取 参数[2:]. 然.
        果 取 解释 其 入口 状 外参.
        若 果['错误'] != 空 则
            错 取 果['错误']. 错误 其 写 内容:(错['source_name']+':'+(错['line'] 为 句)+':'+(错['col'] 为 句)+': error: '+错['category']+'：'+错['message']+'\n').
        然. 得 果['退出'].
    救 原因: 错误 其 写 内容:原因+'\n'. 得 1. 终.
法.
