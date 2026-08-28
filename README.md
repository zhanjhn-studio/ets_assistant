# ets_assistant E听说辅助工具

[CN] ets_assistant 一个关于 e听说的辅助工具，详见 `ets_assistant/README.md`。

> [!WARNING]
> 1. 英语听说非常重要，请在使用本软件时保持应有的练习！！！
> 2. 此软件仅限个人探索使用，禁止用于考试等场景！
> 3. 关于 ets_assistant 项目的所有反馈请提交至[仓库](https://github.com/zhanjhn-studio/ets_assistant/)的 issue（提交 issue 等将截图上传时请注意保护您的个人隐私）进行反馈。
> 4. 此软件完全开源，下载软件请前往[此处](https://github.com/zhanjhn-studio/ets_assistant/release)下载。
> 5. 使用本软件默认已知晓其[隐私协议](https://zhanjhn.github.io/etsassistant/pravaYS.html)与其[使用须知](https://zhanjhn.github.io/etsassistant/pravaXZ.html)。
> 6. 我们的[免责条款](https://zhanjhn.github.io/etsassistant/MZTK.html)。
> 7. 附使用说明，请点击[这里](https://zhanjhn.github.io/etsassistant/index.html)，此仓库可 git 到本地进行其他探究，但必须遵循其许可证。

**什么是 ets_assistant?**

> ets_assistant 是一个用于 E听说 的辅助 / 自动化工具，支持自动跟读、试卷答案查看、立体声混音管理与 DLL 一键编译，详见下文。

---

## 功能
- 自动跟读（OpenCV 模板匹配 + PyAutoGUI + PyAudio 录音）
- 试卷 / 答案查看（读取 `%Appdata%\ETS`）
- 立体声混音自动启用与恢复（用于系统声音回录）
- 高级模块：winmm.dll 搜索顺序劫持框架（Detours Hook，实验性 / 高风险）

## 界面
提供两套前端：
1. **PyWebView 超级前端（默认）**：基于 WebEngine 渲染的现代 HTML/CSS/JS 界面，前后端分离，
   后端为 Python 类（`ets_assistant/webui/api.py`）。支持环境仪表盘、答案查看、立体声混音、
   **DLL 一键编译**等面板。
2. 原 PyQt5 界面：运行 `python -m ets_assistant --qt` 启用。

## 启动
双击运行根目录 `启动E听说助手.py`（PyQt5 图形启动器，自动提权 + 启用立体声混音 +
启动主程序，退出后恢复设备）。主程序默认进入 PyWebView 前端。
我们会准备二进制文件（exe）,请前往请前往[此处](https://github.com/zhanjhn-studio/ets_assistant/release)下载。

## 依赖
```bash
pip install -r ets_assistant/requirements.txt
```
(详见项目源码)
其中 WebUI 需要 `pywebview`（会自动选用系统 Edge/Chromium 内核）。

## DLL 一键编译（敏感！）
见 `ets_assistant/advanced/README.md`。需要：
- Visual Studio 2022（含 MSVC + CMake）
- [Microsoft Detours](https://github.com/microsoft/Detours)，并设置 `DETOURS_ROOT` 环境变量

在前端「DLL 编译」面板点击一键编译即可（后端自动定位 VS 开发者命令环境并构建）。



#此软件持续更新！
