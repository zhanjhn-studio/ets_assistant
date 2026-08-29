# 高级模块：winmm.dll 劫持（实验性 / 高风险）

> ## ⚠️ 免责声明
> 本目录下的 C++ 代码参考 [Howie114514/ETSToolbox](https://github.com/Howie114514/ETSToolbox)
> 实现 **`winmm.dll` 导出表转发 + Detours API 挂钩** 技术，用于拦截 E听说 调用的系统
> 多媒体/计时 API。
>
> - **本模块仅供逆向工程教学与技术研究，严禁用于任何考试作弊或侵权用途。**
> - 部署本模块会修改 `C:\Program Files (x86)\ETS\` 目录、触发杀软拦截、可能违反软件协议。
> - 作者不对使用后果负责，使用即代表你已理解并自负全部责任。
> - 默认**不编译、不部署**；需用户自行用 Visual Studio + CMake + Detours 构建。

## 原理
Windows 的 DLL 搜索顺序会优先加载**应用程序所在目录**下同名 DLL。把本工程编译出的
`winmm.dll` 放到 `C:\Program Files (x86)\ETS\`，E听说 启动时会加载它而非系统
`C:\Windows\System32\winmm.dll`。本 DLL：
1. 通过 `#pragma comment(linker,"/EXPORT:...")` 转发所有 `winmm` 导出到真正的系统 DLL；
2. 在 `DllMain` 中用 Detours 挂钩关键音频播放/计时函数（如 `waveOutOpen`、`timeGetTime`
   等），实现"静音伪装成已朗读""延长/冻结计时"等效果。

## 构建
### 方式一：一键编译（推荐，通过 WebUI）
在 PyWebView 前端「DLL 编译」面板点击 **⚡ 一键编译 winmm.dll**，后端会：
1. 检测 MSVC(cl) + CMake + Detours；
2. 自动定位 VS2022 开发者命令环境（vswhere）；
3. 调用 `build_dll.py` 完成 cmake 配置 + 构建；
4. 自动把 `System32\winmm.dll` 拷贝为 `winmm_orig.dll`（转发目标）；
5. 产物 `advanced/winmm.dll` 就绪。

若环境缺失，面板会返回详细安装引导（VS2022 + Detours + `DETOURS_ROOT`）。

### 方式二：手动命令行
```bat
git clone https://github.com/microsoft/Detours  (或 vcpkg install detours)
:: 设置环境变量 DETOURS_ROOT 指向 Detours 根目录
cd advanced
cmake -B build -DDETOURS_ROOT=%DETOURS_ROOT%
cmake --build build --config Release
:: 产物 build/Release/winmm.dll + build/Release/winmm_orig.dll
```

> 注意：CMakeLists 已用 POST_BUILD 自动拷贝 `winmm_orig.dll`（转发目标）；
> 旧版 `real_winmm_minimal.def` 已弃用（导出转发改由 `winmm_hook.cpp` 的 `#pragma` 完成）。

## 部署（需管理员，风险自担）
在「DLL 编译」面板点击 **部署到 ETS 目录**，或手动把 `winmm.dll` + `winmm_orig.dll`
复制到 `C:\Program Files (x86)\ETS\` 即可劫持。删除这两个文件即恢复正常。

> 注意：ETSToolbox 原仓库 `main.cpp`/`dllmain.cpp` 含有具体改分逻辑，本工程仅提供
> **技术框架骨架**（转发 + Detours 挂钩示例），不内置任何具体作弊数值，使用者需自行
> 研究完善。请遵守法律法规与学校纪律。
