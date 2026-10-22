# Markdown 双撤销的密核实验

应用基线固定为 `uppet/ru_notepad@d964ea9f7e27065aa5bbcced8d6c7526a6224dd1`。本目录的 `notepad.patch` 只改变五份应用文件；原来的普通 `喂入` 和所有辅助函数保留，构建时通过一个显式事实值选择候选路径。当前应用隔离副本在 `.git/bs-local/ru-notepad-mi` 的本地 `bs-mi-undo` 分支。

本实验保留 C 应用／动态值路径，选中的 u8/u32 扫描核直接发射 LLVM 14，随后与 C 调用方链接。普通和密模式两份产物使用相同源码、清单、编译器与 DLL；生成的 LLVM 核完全相同，C 文本只有一个 `v_fact(0)` → `v_fact(1)` 差异。

## 复现

先准备一个固定基线的应用检出，在其中应用本目录的补丁。不要改原安装目录：

```sh
git clone https://github.com/uppet/ru_notepad.git ../ru-notepad-mi-undo
git -C ../ru-notepad-mi-undo switch -c bs-mi-undo d964ea9f7e27065aa5bbcced8d6c7526a6224dd1
git -C ../ru-notepad-mi-undo apply /absolute/path/to/ru-toy/experiments/notepad_undo/notepad.patch
```

在如言仓库根目录、真实 Windows 上构建。`--runtime` 指向原 d964 预览包，构建器会核验三份复用 DLL 和原生辅助源码；LLVM 14 使用本项目既有工具选择，资源编译器默认来自本机 `C:/msys64/mingw64/bin/windres.exe`。

```sh
python3 experiments/notepad_undo/build.py --app-root ../ru-notepad-mi-undo --runtime S:/Apps/ru_notepad --output bin/notepad-mi-dense --arm dense --target c-llvm
python3 experiments/notepad_undo/build.py --app-root ../ru-notepad-mi-undo --runtime S:/Apps/ru_notepad --output bin/notepad-mi-ordinary --arm ordinary --target c-llvm
```

输出目录必须尚不存在。构建器记录当前编译器工作树的源码哈希，接受本地实验改动；没有修改应用原来的编译器 pin 或正式打包验收。

运行原应用的完整 Markdown GUI 检查，每个阶段仍用原 30 秒门槛；`run_gui.py` 核验原脚本字节未改，只启动和清理自己创建的独立进程，测试文件均为新建合成样本。

```sh
python3 experiments/notepad_undo/run_gui.py --app-root ../ru-notepad-mi-undo --binary-dir bin/notepad-mi-ordinary --output bin/notepad-measure-ordinary
python3 experiments/notepad_undo/run_gui.py --app-root ../ru-notepad-mi-undo --binary-dir bin/notepad-mi-dense --output bin/notepad-measure-dense
```

逐块语义对照可在 WSL/Linux 或 Windows 运行，包含全部 24 个状态槽、压缩折叠区间、保留别名、Unicode／CRLF、接近队列上限和两个 Undo 文本修订：

```sh
python3 experiments/notepad_undo/check_policy.py --app-root ../ru-notepad-mi-undo --output bin/notepad-policy-check --target c-llvm
```

`--target c` 可验证密 IR 的 C 后端；Linux 在该命令前设置 `MI_UBSAN=1` 可插桩 C 路径。检查中的调用计数仅存在于测试生成物，未注入 GUI 候选程序。每次使用新的输出目录。

结果、算法约束与本地／远端验收边界见[实验报告](../../docs/notepad-mi-undo-2026-10-22.md)。

## 增量算法实验

`notepad-incremental.patch` 是对同一个 d964 基线的完整六文件补丁，包含原密核改动；和 `notepad.patch` 二选一应用，不要叠加。构建时保留 `--arm dense --target c-llvm`，通过 `--incremental` 单独启用有界检查点和后缀复用。未启用时仍执行全量扫描；旧五文件补丁也继续受构建工具支持。

```sh
python3 experiments/notepad_undo/build.py --app-root ../ru-notepad-mi-undo --runtime S:/Apps/ru_notepad --output bin/notepad-full --arm dense --target c-llvm
python3 experiments/notepad_undo/build.py --app-root ../ru-notepad-mi-undo --runtime S:/Apps/ru_notepad --output bin/notepad-incremental --arm dense --target c-llvm --incremental
python3 experiments/notepad_undo/benchmark_incremental.py --app-root ../ru-notepad-mi-undo --control bin/notepad-full --incremental bin/notepad-incremental --output bin/notepad-incremental-results
```

计时器依次运行六个完整 GUI 进程，顺序为增量开关关闭、开启、开启、关闭、关闭、开启；每个版本三轮，全部沿用原门槛。这里“关闭”仍然启用原密核优化。生成的 C 代码须仅有一个事实值差异，LLVM 密核、输入源码和三份 DLL 须完全一致。

语义对照另行运行，不与 GUI 计时并行：

```sh
python3 experiments/notepad_undo/check_incremental.py --app-root ../ru-notepad-mi-undo --output bin/notepad-incremental-policy
python3 experiments/notepad_undo/check_incremental_native.py --app-root ../ru-notepad-mi-undo --runtime S:/Apps/ru_notepad --output bin/notepad-incremental-native
```

第一个检查在 Linux／Windows 均可运行，以固定 d964 原策略全量计算作 oracle。第二个要求真实 Windows，使用原生 Scintilla／Lexilla 控件逐行比较折叠、可见性与文本，并实际调用 Undo。
