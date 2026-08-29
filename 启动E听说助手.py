# -*- coding: utf-8 -*-
# =============================================================================
#  启动E听说助手.py  ——  PyWebView（WebEngine 渲染）图形化一键启动器
#
#  ⚠️ 免责声明：本工具仅供个人技术研究与逆向工程教学用途。
#  严禁用于考试作弊或侵犯软件权益。使用者须自行承担一切法律与纪律责任，
#  作者不对任何使用后果负责。若不同意，请立即删除本项目。
#
#  流程：
#    1) 最前面 UAC 提权（非管理员则用 PowerShell RunAs 重启自身）
#    2) 用 PyWebView 打开 webui/launcher.html（黑白毛玻璃 UI + 3D 加载动画，
#       与主程序同一套渲染与深浅色主题）
#    3) 点击「开始启动」后：检查依赖 -> 启用立体声混音 -> 启动主程序
#       -> 退出后恢复设备。后端日志通过 window.__appendLog 实时推回前端。
# =============================================================================

import os
import sys
import ctypes
import json
import threading
import subprocess

import webview  # PyWebView（WebEngine 渲染）

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(ROOT, "ets_assistant")
PS1 = os.path.join(ROOT, "enable_stereo_mix.ps1")
REQ = os.path.join(APP_DIR, "requirements.txt")
LAUNCHER_HTML = os.path.join(APP_DIR, "webui", "launcher.html")


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def relaunch_as_admin():
    params = (f'Start-Process -FilePath "{sys.executable}" '
              f'-ArgumentList "{os.path.abspath(__file__)}" -Verb RunAs')
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-Command", params], check=False)
    except Exception:
        pass
    sys.exit(0)


# -------------------- 后端 API（暴露给前端 JS） --------------------
class LauncherAPI:
    def __init__(self):
        self._running = False
        self._proc = None

    # ---- 把指令推到前端 JS ----
    def _js(self, code: str):
        try:
            if webview.windows:
                webview.windows[0].evaluate_js(code)
        except Exception:
            pass

    def _log(self, msg: str):
        self._js("window.__appendLog(" + json.dumps(msg, ensure_ascii=False) + ");")

    def _set_state(self, cls: str, txt: str):
        self._js("window.__setState(" + json.dumps(cls, ensure_ascii=False) + "," +
                 json.dumps(txt, ensure_ascii=False) + ");")

    def _set_running(self, running: bool):
        self._js("window.__setRunning(" + ("true" if running else "false") + ");")

    # ---- 前端点击「开始启动」时调用 ----
    def start(self):
        if self._running:
            return {"ok": False, "error": "已在运行"}
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()
        return {"ok": True}

    def stop(self):
        """停止正在运行的主程序（终止其进程）。"""
        if not self._running or self._proc is None:
            return {"ok": False, "error": "主程序未在运行"}
        try:
            self._proc.terminate()
        except Exception as e:
            return {"ok": False, "error": str(e)}
        self._log("[停止] 已向主程序发送停止信号。")
        return {"ok": True}

    # -------------------- 内部流程 --------------------
    def _ensure_deps(self) -> bool:
        required = ["PyQt5", "cv2", "pyautogui", "numpy", "pyaudio"]
        missing = []
        for mod in required:
            if subprocess.run([sys.executable, "-c", f"import {mod}"],
                              capture_output=True).returncode != 0:
                missing.append(mod)
        if not missing:
            self._log("[OK] 依赖已就绪。")
            return True
        self._log(f"[安装] 缺少依赖 {missing}，正在安装...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", REQ])
            self._log("[OK] 依赖安装完成。")
            return True
        except Exception as e:
            self._log(f"[错误] 依赖安装失败: {e}")
            return False

    def _run_powershell(self, mode: str):
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", PS1, mode]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  encoding="utf-8", errors="ignore", timeout=60)
            for line in (proc.stdout or "").strip().splitlines():
                if line.strip():
                    self._log(f"[音频] {line.strip()}")
        except Exception as e:
            self._log(f"[音频] 调用失败: {e}")

    def _run(self):
        # 1) 依赖
        if not self._ensure_deps():
            self._set_state("err", "依赖缺失")
            self._running = False
            return

        # 2) 启用立体声混音（并备份原设备）
        if os.path.exists(PS1):
            self._log("[音频] 正在启用立体声混音并备份原设备...")
            self._run_powershell("enable")
        else:
            self._log("[警告] 未找到 enable_stereo_mix.ps1，跳过音频设置。")

        # 3) 启动主程序（以项目根目录 ROOT 为工作目录，保证 ets_assistant 包可被找到）
        self._log("[启动] 正在打开主界面，可最小化本窗口等待…")
        self._set_state("wait", "主程序运行中")
        self._set_running(True)
        try:
            self._proc = subprocess.Popen([sys.executable, "-m", "ets_assistant"], cwd=ROOT)
            self._proc.wait()
            self._log(f"[信息] 主程序已退出 (code={self._proc.returncode})。")
        except Exception as e:
            self._log(f"[错误] 启动主程序失败: {e}")
        finally:
            self._proc = None
            self._set_running(False)

        # 4) 恢复立体声混音
        if os.path.exists(PS1):
            self._log("[音频] 正在恢复你原来的默认录音设备...")
            self._run_powershell("restore")

        self._set_state("ok", "已完成")
        self._running = False
        self._log("[完成] 所有步骤结束，感谢使用。可关闭本窗口。")


# -------------------- 入口 --------------------
def main():
    # ---- 最前面直接 UAC 提权 ----
    if not is_admin():
        relaunch_as_admin()
        return
    print("[提权] 已获得管理员权限。", flush=True)

    api = LauncherAPI()
    webview.create_window(
        "E听说助手 · 启动器",
        url=LAUNCHER_HTML,
        js_api=api,
        background_color="#0a0a0a",   # 黑色背景，避免 WebView 初始化时白屏
        width=620,
        height=720,
    )
    webview.start()


if __name__ == "__main__":
    main()
