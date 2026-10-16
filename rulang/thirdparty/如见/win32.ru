# 如见的 Windows x64 绑定。所有 ABI、常量及布局均在如源码中声明。
密 取 外言 '如:密'.
BOOL 取 密 其 i32.
UINT 取 密 其 u32.
DWORD 取 密 其 u32.
INT 取 密 其 i32.
ATOM 取 密 其 u16.
WPARAM 取 密 其 uintptr.
LPARAM 取 密 其 intptr.
LRESULT 取 密 其 intptr.
PTR 取 密 其 指针.
VOID 取 密 其 无值.

WM_DESTROY 取 2.
WM_CLOSE 取 16.
WM_QUIT 取 18.
WM_NCCREATE 取 129.
WM_NCDESTROY 取 130.
WM_COMMAND 取 273.
BM_CLICK 取 245.
BN_CLICKED 取 0.
WS_OVERLAPPEDWINDOW 取 13565952.
WS_CHILD 取 1073741824.
WS_VISIBLE 取 268435456.
BS_PUSHBUTTON 取 0.
SW_SHOW 取 5.
PM_REMOVE 取 1.
CW_USEDEFAULT 取 -2147483648.
IDC_ARROW 取 32512.
COLOR_WINDOW 取 5.

POINT 取 密 其 结构 [['x',INT],['y',INT]].
MSG 取 密 其 结构 [
    ['hwnd',PTR],['message',UINT],['wParam',WPARAM],['lParam',LPARAM],
    ['time',DWORD],['pt',POINT],['lPrivate',DWORD]
].
WNDCLASSEXW 取 密 其 结构 [
    ['cbSize',UINT],['style',UINT],['lpfnWndProc',PTR],
    ['cbClsExtra',INT],['cbWndExtra',INT],['hInstance',PTR],
    ['hIcon',PTR],['hCursor',PTR],['hbrBackground',PTR],
    ['lpszMenuName',PTR],['lpszClassName',PTR],['hIconSm',PTR]
].
WNDPROC 取 密 其 签名 LRESULT ([PTR,UINT,WPARAM,LPARAM]) 'win64'.

用户库 取 密 其 系统库 'user32.dll'.
内核库 取 密 其 系统库 'kernel32.dll'.
GetModuleHandleW 取 内核库 其 绑定 'GetModuleHandleW' (密 其 签名 PTR ([PTR]) 'win64').
RegisterClassExW 取 用户库 其 绑定 'RegisterClassExW' (密 其 签名 ATOM ([PTR]) 'win64').
UnregisterClassW 取 用户库 其 绑定 'UnregisterClassW' (密 其 签名 BOOL ([PTR,PTR]) 'win64').
CreateWindowExW 取 用户库 其 绑定 'CreateWindowExW' (密 其 签名 PTR ([DWORD,PTR,PTR,DWORD,INT,INT,INT,INT,PTR,PTR,PTR,PTR]) 'win64').
DefWindowProcW 取 用户库 其 绑定 'DefWindowProcW' (密 其 签名 LRESULT ([PTR,UINT,WPARAM,LPARAM]) 'win64').
ShowWindow 取 用户库 其 绑定 'ShowWindow' (密 其 签名 BOOL ([PTR,INT]) 'win64').
UpdateWindow 取 用户库 其 绑定 'UpdateWindow' (密 其 签名 BOOL ([PTR]) 'win64').
GetMessageW 取 用户库 其 绑定 'GetMessageW' (密 其 签名 BOOL ([PTR,PTR,UINT,UINT]) 'win64').
TranslateMessage 取 用户库 其 绑定 'TranslateMessage' (密 其 签名 BOOL ([PTR]) 'win64').
DispatchMessageW 取 用户库 其 绑定 'DispatchMessageW' (密 其 签名 LRESULT ([PTR]) 'win64').
PostQuitMessage 取 用户库 其 绑定 'PostQuitMessage' (密 其 签名 VOID ([INT]) 'win64').
DestroyWindow 取 用户库 其 绑定 'DestroyWindow' (密 其 签名 BOOL ([PTR]) 'win64').
SetWindowTextW 取 用户库 其 绑定 'SetWindowTextW' (密 其 签名 BOOL ([PTR,PTR]) 'win64').
GetWindowTextW 取 用户库 其 绑定 'GetWindowTextW' (密 其 签名 INT ([PTR,PTR,INT]) 'win64').
GetWindowTextLengthW 取 用户库 其 绑定 'GetWindowTextLengthW' (密 其 签名 INT ([PTR]) 'win64').
LoadCursorW 取 用户库 其 绑定 'LoadCursorW' (密 其 签名 PTR ([PTR,PTR]) 'win64').
GetSysColorBrush 取 用户库 其 绑定 'GetSysColorBrush' (密 其 签名 PTR ([INT]) 'win64').
SendMessageW 取 用户库 其 绑定 'SendMessageW' (密 其 签名 LRESULT ([PTR,UINT,WPARAM,LPARAM]) 'win64').
PostMessageW 取 用户库 其 绑定 'PostMessageW' (密 其 签名 BOOL ([PTR,UINT,WPARAM,LPARAM]) 'win64').
PeekMessageW 取 用户库 其 绑定 'PeekMessageW' (密 其 签名 BOOL ([PTR,PTR,UINT,UINT,UINT]) 'win64').
IsWindow 取 用户库 其 绑定 'IsWindow' (密 其 签名 BOOL ([PTR]) 'win64').
