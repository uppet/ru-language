密 取 外言 '如:密'.
外 取 外言 'panic_module.ru'.
作 断言 条件 说明:
    若 非 条件 则 卒 说明. 然
为
库 取 密 其 动态库 '@DLL@'.
原生调 取 库 其 绑定 'invoke_callback' (密 其 签名 (密 其 i64) ([密 其 指针,密 其 u64]) 'win64').
签 取 密 其 签名 (密 其 i64) ([密 其 u64]) 'win64'.
算 造 文:
    循 12 次 垃圾 取 ['collect',文+'!', [1,2,3]]. 环
    得 [文+'-retained',['nested',文]].
法
算 合 左 中 右:
    断言 (左[0] == 'parent-retained') 'parent first arg lost'.
    断言 (右[0] == 'tail-retained') 'parent last arg lost'.
    得 [[左[0],右[0]],中].
法
算 内处理 值:
    堆 取 造 'inside'.
    断言 (堆[1][0] == 'nested') 'returned heap lost'.
    断言 (密 其 回调中) 'nested callback depth'.
    得 41.
法
内回 取 密 其 回调 签 (算 内处理) (-8).
算 内调 值:
    果 取 原生调 其 调用 [内回,值].
    断言 ((果 其 回调错误) == 空) 'inner callback failed'.
    得 (果 其 值) 其 数.
法
算 外处理 值:
    堆 取 合 左:(造 'parent') 右:(造 'tail') 中:(内调 值).
    断言 (堆[1] == 41) 'nested value lost'.
    断言 (密 其 回调中) 'outer callback depth lost'.
    若 (值 其 数) == 0 则 外 其 失败. 然
    得 堆[1].
法
外回 取 密 其 回调 签 (算 外处理) (-7).
算 触 模式:
    果 取 原生调 其 调用 [外回,模式].
    断言 (非 (密 其 回调中)) 'callback depth leaked'.
    若 模式 == 0 则
        断言 (((果 其 值) 其 数) == -7) 'panic fallback'.
        断言 ((果 其 回调错误) 其 含 'slot-panic') 'missing panic'.
        显 果 其 回调错误.
    另
        断言 ((果 其 回调错误) == 空) 'stale panic after retry'.
        断言 (((果 其 值) 其 数) == 41) 'retry failed'.
    然
    得 (果 其 值) 其 数.
法
算 词 模式:
    忽略 取 触 模式.
    得 'retain'+'ed'.
法
序列 取 [1,0,1]. 序 取 0.
循 3 次
    模 取 序列[序].
    堆 取 合 左:(造 'parent') 右:(造 'tail') 中:(触 模).
    断言 (堆[0][0] == 'parent-retained') 'returned parent heap'.
    若 模 == 0 则 断言 (堆[1] == -7) 'returned fallback heap'.
    另 断言 (堆[1] == 41) 'returned success heap'. 然
    断言 (((造 'receiver')[0]) 其 含 (词 模)) 'temporary receiver lost'.
    序 取 序+1.
环
外回 其 关闭. 内回 其 关闭.
显 'slot-native-ok'.
