# E听说自动化辅助工具 (ets_assistant)

> ## ⚠️ 免责声明（Disclaimer）
> 本项目（含 Python 自动化跟读模块与 C++ `winmm.dll` 劫持模块）**仅供个人技术学习、
> 研究与逆向工程教学用途**。
> - 作者不对任何人或组织因使用、修改或分发本代码所产生的任何直接或间接后果负责。
> - **DLL 劫持 / API Hook 模块（advanced/ 目录）通过劫持系统音频与计时 API 干预 E听说
>   评分与计时逻辑，可能违反《软件许可协议》、学校考试纪律及《计算机信息系统安全保护条例》
>   等相关规定，存在账号封禁、成绩作废乃至法律责任风险。**
> - 请勿在任何正式考试、测验或商业环境中使用劫持模块；请勿将本项目用于任何作弊或侵权目的。
> - 使用本项目即表示您已充分理解上述风险并**自负全部责任**。
> - 若您不同意以上条款，请立即删除本项目全部文件。

---

基于 GitHub 参考仓库（AutoETS、ETSAnsReader、ETS-Answer-Parser、ETSToolbox 等）
整合开发的 Windows 桌面应用，使用 PyQt5 实现图形界面。

提供两套方案：
1. **主方案 · Python 自动化跟读**（合规、无注入）：基于 OpenCV 模板匹配 + PyAutoGUI
   点击 + PyAudio 录音，自动完成跟读作业，并支持查看本地已下载试卷答案。
2. **高级方案 · `winmm.dll` 劫持**（可选、需自行编译、高风险）：参考
   [Howie114514/ETSToolbox](https://github.com/Howie114514/ETSToolbox)，通过导出表
   转发 + Detours 挂钩系统多媒体/计时 API，实现"免朗读高分""调整计时节流"等效果。
   **默认不启用，需用户显式编译并在理解风险后手动部署。**

> ⚠️ 本工具仅用于个人学习自动化技术，请遵守学校与软件使用规范，合理使用。

## 功能

1. **自动跟读**：基于 OpenCV 模板匹配定位按钮 + PyAutoGUI 自动点击 + PyAudio
   录音，循环完成「播放原文→录音→跟读→播放→停止」流程，自动检测「下一个」按钮
   并继续，直到作业结束。
2. **模板管理**：一键截取 E听说 界面按钮图片（播放原文 / 开始录音 / 停止录音 /
   下一个）保存到本地，适配不同分辨率与版本。
3. **答案查看**：读取系统 `%Appdata%\ETS` 目录下已下载的试卷，展示音频/图片
   资源，并尝试从 json 中提取答案相关字段。
4. **设置**：可调静默判定帧数、音量阈值、采样率、最大轮次等。

## 安装

需要 **Python 3.10**（因 `audioop` 在 3.13 被移除，3.11+ 不保证可用）。

```bash
cd ets_assistant
pip install -r requirements.txt
```

## 运行

```bash
python -m ets_assistant
# 或
python ets_assistant/__main__.py
```

## 使用步骤

1. 以**管理员身份**运行本程序（避免 PyAutoGUI 点击失败）。
2. 将系统默认**录音设备**设为「立体声混音」（控制面板 → 声音 → 录制）。
3. 打开 E听说 进入跟读作业界面，窗口不被遮挡、单显示器。
4. 在「模板管理」页依次截取四个按钮图片。
5. 回到「自动跟读」页点击「开始」。

## 参考仓库

- [deAlue/AutoETS](https://github.com/deAlue/AutoETS) —— 核心自动化思路
- [DMorest/ETSAnsReader](https://github.com/DMorest/ETSAnsReader) —— PyQt 答案读取
- [happycola233/ETS-Answer-Parser](https://github.com/happycola233/ETS-Answer-Parser) —— 试卷解析
- [15915996690/auto_ETS](https://github.com/15915996690/auto_ETS) —— 架构参考
- [Howie114514/ETSToolbox](https://github.com/Howie114514/ETSToolbox) —— 已评估，未采用（DLL注入改分，违法风险）

## 方案选择说明

最终采用 **AutoETS 的纯 Python 自动化方案**（OpenCV+PyAutoGUI+PyAudio）作为核心，
结合 PyQt5 做 GUI，而非 ETSToolbox 的 C++ DLL 注入改分方案。理由：

- 纯自动化无注入、无篡改，合规且对版本变化更鲁棒；
- PyQt5 架构清晰、易维护、可打包为 exe；
- DLL 注入方案已停更、编译复杂且涉及考试作弊风险。
