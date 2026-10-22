# Only checked Val/borrow boundary metadata. Algorithm bodies are LLVM only.
算 密桥 记录 名 引句:
    约 取 记录['contract']. 参 取 约['params']. 原型 取 ['uint32_t *']. 实参 取 ['mi_out'].
    出 取 []. 名表 取 {}. 视 取 空. 序 取 0.
    循 (参 其 量) 次
        配 取 参[序]. 临 取 'mi_p'+(序 为 句). 名表 其 增 配[0] 临.
        若 配[1] == 'borrow_ro_utf8' 则
            原型 其 增 'const uint8_t *'. 原型 其 增 'uint32_t'.
            实参 其 增 'mi_view.data'. 实参 其 增 'mi_view.length'. 视 取 序.
        另 原型 其 增 'uint32_t'. 实参 其 增 临. 然. 序 取 序+1.
    环.
    出 其 增 ('extern void '+记录['symbol']+'_llvm('+(__如竞 其 合句 原型 ', ')+');').
    出 其 增 ('static Val '+名+'_bridge(Env *env, Val self, int call_line, Val *args) {').
    出 其 增 '    (void)env; (void)self; (void)call_line; (void)args;'.
    序 取 0.
    循 (参 其 量) 次
        配 取 参[序].
        若 配[1] != 'borrow_ro_utf8' 则
            上限 取 '4294967295u'. 若 配[1] == 'u8' 则 上限 取 '255u'. 然.
            出 其 增 ('    uint32_t '+名表[配[0]]+' = boot_dense_scalar(args['+(序 为 句)+'], call_line, '+上限+');').
        然. 序 取 序+1.
    环.
    若 视 != 空 则
        出 其 增 ('    BootDenseUtf8 mi_view = boot_dense_utf8(args['+(视 为 句)+'], call_line);').
        范 取 约['ranges']. 序 取 0.
        循 (范 其 量) 次
            配 取 范[序]. 始 取 名表[配['begin']]. 终 取 名表[配['end']].
            出 其 增 ('    if ('+始+' > '+终+' || '+终+' > mi_view.length) ru_fail(call_line, "密视图起止范围越界");'). 序 取 序+1.
        环.
        出 其 增 ('    Val mi_owner = v_copy(args['+(视 为 句)+']);').
    然.
    出 其 增 '    uint32_t mi_out[4];'.
    出 其 增 ('    '+记录['symbol']+'_llvm('+(__如竞 其 合句 实参 ', ')+');').
    若 视 != 空 则 出 其 增 '    v_drop(mi_owner);'. 然.
    # Native ru_fail trap restores source and callback state after longjmp.
    # The retained owner MUST be released before entering that trap.
    出 其 增 ('    if (mi_out[0] != 0) { ru_source = '+(引句 记录['module'])+'; ru_fail((int)mi_out[2], "密内核失败，列=%u，status=%d", mi_out[3], (int)mi_out[0]); }').
    出 其 增 '    return v_num((double)mi_out[1]);'. 出 其 增 '}'.
    得 (__如竞 其 合句 出 '\n')+'\n'.
法.
