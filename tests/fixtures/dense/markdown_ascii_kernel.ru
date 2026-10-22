# Ordinary Ru source is the only algorithm definition. Explicit build manifest
# may lower this function's AST to typed readonly-u8 IR; no handwritten C kernel.
# Without opt-in this is an ordinary number-array oracle, not NativeMemory access.
算 ASCII段 字节 始 终:
    位 取 始.
    循 (终-始) 次
        值 取 字节[位].
        若 值 >= 128 或 值 == 13 或 值 == 10 或 值 == 62 则 破. 然
        位 取 位+1.
    环
    得 位-始.
法

# A general same-byte ASCII run. Backticks, HTML-closer terminators and physical
# line endings stay on the exact scalar path; no text or Markdown state escapes.
算 重复ASCII段 字节 始 终:
    若 始 == 终 则 得 0. 然
    首 取 字节[始].
    若 首 >= 128 或 首 == 13 或 首 == 10 或 首 == 62 或 首 == 96 则 得 0. 然
    位 取 始.
    循 (终-始) 次
        若 字节[位] != 首 则 破. 然
        位 取 位+1.
    环
    得 位-始.
法

算 字节量 字节:
    得 字节 其 量.
法

# Return a complete LF-terminated ASCII prefix whose lines cannot close a fence.
# CR, non-ASCII, HTML closer markers and a potential fence closer stop BEFORE
# the current line. No assumption about a particular word or benchmark input.
算 安全围栏段 字节 始 终 围栏:
    位 取 始. 末 取 始. 缩进 取 0. 安全 取 0.
    循 (终-始) 次
        值 取 字节[位].
        若 值 >= 128 或 值 == 13 或 值 == 62 则 破. 然
        若 值 == 10 则
            位 取 位+1. 末 取 位. 缩进 取 0. 安全 取 0.
        另
            若 安全 == 0 则
                若 值 == 32 则
                    缩进 取 缩进+1.
                    若 缩进 >= 4 则 安全 取 1. 然
                另若 值 == 9 则
                    安全 取 1.
                另
                    若 值 == 围栏 则 破. 然
                    安全 取 1.
                然
            然
            位 取 位+1.
        然
    环
    得 末-始.
法
算 计换行 字节 始 终:
    位 取 始. 数量 取 0.
    循 (终-始) 次
        若 字节[位] == 10 则 数量 取 数量+1. 然
        位 取 位+1.
    环
    得 数量.
法
