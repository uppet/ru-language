# 如见：用如编写的 Win32 试验库

如见随工具链一起发布，但属于第三方库，暂不成为如语言本身的一部分。精确导入名是 `外言 '如见'`，没有冒号。它使用通用标准库 `如:密`；不使用 `ffi.ru`，也没有 Python GUI 专用运行时。

首版只支持 **Windows x64 的本地 Python 解释器**。需要可用的 Windows 桌面；未显示的真实窗口仍需要窗口站/桌面。32 位 Windows、Windows ARM64、其他操作系统、C、Node.js、浏览器及如书执行均不支持。源码检查不执行 DLL 或创建窗口，不能代替 Windows 上的运行验证。

## 运行

在仓库根目录执行：

```sh
python ru check --target python examples/native/rujian_window_button.ru
python ru run --allow-native examples/native/rujian_window_button.ru
python ru run --allow-native examples/native/rujian_hidden.ru
python -m unittest discover -s tests -p 'test_rujian*.py' -v
```

第一个例子显示原生窗口和 BUTTON，点击会更新 Unicode 标题。第二个实际创建隐藏窗口与按钮，发送 `BM_CLICK`，核对标题，投递 `WM_CLOSE` 并运行消息循环。它不是 GUI 模拟。非 Windows x64 上，集成测试明确跳过，仅检查如源码。

原生能力默认关闭。`--allow-native` 表示信任本程序及其整个导入图。错误的 ABI、地址、生命周期或任意 DLL 都可能破坏或终止进程；如:密 **不是沙箱**。只运行自己检查并信任的源码及 DLL。不要对下载的未知程序直接开启原生能力。

## 最小接口

```ru
见 取 外言 '如见'.
窗 取 见 其 窗口 'MyApp.UniqueClass' '你好' 480 240.
试
    窗 其 按钮 '点我' 24 28 180 48 100 (算:
        窗 其 标题 '你好，如见 🌸'.
        得 空.
    法).
    窗 其 显示.
    窗 其 循环.
救 原因
    窗 其 释放.
    卒 原因.
终
```

- `见 其 窗口 类名 标题 宽 高`：注册独有窗口类并创建隐藏的主窗口，返回窗体。类名不能为空且不能占用已有类；宽高是正的 i32。宽高包含窗口外框，按钮位置使用客户区坐标。
- `窗 其 句柄`：取得原生 HWND。不转换成如的浮点数；关闭后报错。
- `窗 其 按钮 文字 横 纵 宽 高 编号 点击`：创建标准 BUTTON，返回其原生 HWND。编号为不重复的 1–65535 整数；点击是无参数的 `算`，返回值忽略。
- `窗 其 标题 新句` / `窗 其 取标题`：设置/读取真实 Win32 Unicode 标题。空标题允许；内嵌 NUL 不允许。
- `窗 其 显示`：显示并更新窗口。`ShowWindow` 返回零仅表示此前隐藏。
- `窗 其 关闭`：销毁主窗口及其子窗口，重复调用安全；`WM_DESTROY` 投递退出消息。还须运行 `循环` 或调用 `释放`。
- `窗 其 循环`：执行 GetMessage / TranslateMessage / DispatchMessage，返回退出码，并释放类与原生回调。Win32 失败或回调错误会先尝试清理，再以 `卒` 报告。GetMessage 的 -1 与 0 分开处理。
- `窗 其 释放`：销毁尚活着的窗口，再注销类并关闭回调和类名内存；成功后重复调用安全。失败可重试。直接释放保留唤醒进行中 GetMessage 所需的 WM_QUIT；循环栈退出后或下一个主窗口创建前清除本生命周期的退出消息。

首版**同一解释器只允许一个如见主窗口同时存在**。一个主窗口可以有多个按钮；可顺序创建、运行、释放，再创建下一个。处理器内可以释放，但必须等当前处理器和消息循环返回后才能创建下一主窗口；任何原生回调内创建主窗口或启动消息循环都会明确报错。不要与另一个 GUI 框架、其他线程、嵌套消息循环或独立拥有的 WM_QUIT 共用线程。底层 `Win32` 导出不自动施加高层限制；混用底层改变所有权后，必须自行维护约定。

## 两层边界

`win32.ru` 用如声明所有 DLL 名、符号、Win64 调用签名、消息常量和结构布局，包含 `WNDCLASSEXW`、`MSG`、嵌套的 `POINT`、`WNDPROC` 及本例所需的 user32/kernel32 入口。高层通过 `见 其 Win32` 导出这个模块，方便检查和低层试验：

```ru
W 取 见 其 Win32.
成果 取 (W 其 SendMessageW) 其 调用 [钮,W 其 BM_CLICK,0,0].
若 (成果 其 回调错误) != 空 则 卒 (成果 其 回调错误). 然
```

每次低层调用返回成果：`值` 是原生标量（void 为 `空`），`错误码` 是调用刚返回时的 Win32 错误快照，`回调错误` 是空或错误文本。非零错误码并不意味着本次调用失败：须按每个 Win32 函数自己的返回值约定判断。尤其不能用“返回零即失败”处理 ShowWindow、TranslateMessage、SendMessageW 或 DispatchMessageW。

低层句柄、WPARAM、LPARAM、LRESULT 保持精确原生值。只在明确安全时用 `其 数`；用 `其 句` 查看完整十进制值。按钮分派用 `其 位段 0 16` 和 `其 位段 16 16` 提取编号/通知，并将 LPARAM 重释为指针核对真实子控件 HWND。菜单、加速键、错误编号、错误通知和其他控件不能被当作同一个按钮的点击。

## 所有权与故障

- 类名 UTF-16 缓冲、如回调与原生回调在创建窗口之前准备好；CreateWindowExW 可同步回入如。WM_NCCREATE 交给 DefWindowProcW，所有未处理消息也交给系统默认过程。
- 窗体拥有主/子窗口。`GetModuleHandleW`、共享系统游标与系统画刷是借用资源，不调用 FreeLibrary / DestroyCursor / DeleteObject。
- 注册的类在如模块中保持强引用。销毁完成且 UnregisterClassW **成功之后**才能关闭回调与类名缓冲；注销失败会保留引用，避免悬空 WNDPROC，可稍后重试。
- 销毁窗口与注销类不依赖垃圾回收。用户丢失窗体引用不会自动销毁 Windows 资源；务必显式结束生命周期。
- 点击处理器可调用 `释放`；已进入的 WNDPROC 可完成标量返回，后续循环检查已释放状态，不再等待下一条消息。退出消息清理延后到安全边界，避免吃掉正在等待的 GetMessage 唤醒消息。
- 如:密只支持拥有者线程上、原生调用期间的同步回调。回调中的 `卒` 和普通运行错误都被隔离在 C 边界内，返回安全的 0，并记录在调用成果中。如见声明通用失败动作 `PostQuitMessage(1)`，使正在 GetMessage 内等待的调用能返回。
- `循环` 在成果错误后清理并重新报告主错误；清理失败附在主错误之后。回调不能自行保留原生临时指针、跨线程调用窗体或依赖回调参数的外部存储继续存活。
- 如的 `试/救` 只捕获 `卒`。调用高层方法前应满足其类型、范围与文本契约；普通参数错误不是可恢复的 `卒`。错误的低层声明仍可能直接崩溃，无法保证清理。
- 如:密会保留已关闭回调的安全占位，防止外部陈旧地址变成已释放代码。单进程有 1024 个累计回调上限；反复创建大量窗口时应启动新进程。

## 验证范围与待办

Windows 集成测试使用独立子进程与 45 秒超时，断言结构大小/对齐/每个字段偏移、真实 BM_CLICK、Unicode 和非 BMP 字符标题、错误 WM_COMMAND 路由、重复创建/注销、父子销毁、GetMessage 的 -1、回调 `卒` 与普通错误、队列回调失败清理、过期 WM_QUIT 隔离。跳过不算通过真实 Windows 验证。

人工验收还须运行可见例子，鼠标连续点击，调整大小，最小化/恢复，点 X 或 Alt+F4 退出。当前没有布局系统、DPI 自适应、对话框 Tab 键导航、菜单、自绘、资源编辑器、复杂控件、辅助功能承诺或跨平台抽象。

布局和消息语义依据 Microsoft 文档：[WNDCLASSEXW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-wndclassexw)、[MSG](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-msg)、[WM_NCCREATE](https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-nccreate)、[WM_COMMAND](https://learn.microsoft.com/en-us/windows/win32/menurc/wm-command)、[BM_CLICK](https://learn.microsoft.com/en-us/windows/win32/controls/bm-click)、[GetMessageW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getmessagew)、[UnregisterClassW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-unregisterclassw)。
