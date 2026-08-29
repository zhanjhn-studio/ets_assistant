# =============================================================================
#  api.py  ——  PyWebView 前端 <-> Python 后端 桥接 API
#
#  ⚠️ 免责声明：本工具仅供个人技术研究与逆向工程教学用途。
#  严禁用于考试作弊或侵犯软件权益。使用者须自行承担一切法律与纪律责任，
#  作者不对任何使用后果负责。若不同意，请立即删除本项目。
#
#  所有供 JS 调用的后端方法都集中在本类的静态/实例方法里。
#  PyWebView 会把本类实例暴露为 window.pywebview.api.<method>(...)
# =============================================================================

import os
import sys
import time
import threading
import subprocess
import shutil
import importlib.util
from typing import Any

# 确保无论以脚本还是模块方式启动，都能找到 ets_assistant 包
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.dirname(BASE_DIR)
ROOT_DIR = os.path.dirname(PKG_DIR)
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, PKG_DIR)  # 兼容内部模块的旧式绝对导入

from ets_assistant.env_check import run_all_checks
from ets_assistant.audio_control import enable_stereo_mix, restore_default_capture
from ets_assistant.answer_reader import get_ets_dir, list_papers, read_paper_info, search_papers

ETS_DIR = r"C:\Program Files (x86)\ETS"
ADVANCED_DIR = os.path.join(PKG_DIR, "advanced")


def _load_advanced_module(name: str) -> Any:
    """从 advanced 目录动态加载 build_dll / deploy_dll 等模块。"""
    path = os.path.join(ADVANCED_DIR, f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -------------------- 简易日志广播 --------------------
class LogHub:
    """把后端日志推送给前端（JS 通过 poll_logs 拉取）。"""
    _lock: threading.Lock = threading.Lock()
    _buffer: list[dict[str, str]] = []

    @classmethod
    def push(cls, msg: str):
        with cls._lock:
            cls._buffer.append({"t": time.strftime("%H:%M:%S"), "msg": msg})
            # 最多保留 500 条
            if len(cls._buffer) > 500:
                cls._buffer = cls._buffer[-500:]

    @classmethod
    def drain(cls):
        with cls._lock:
            data = cls._buffer[:]
            cls._buffer.clear()
        return data


# -------------------- 后端 API --------------------
class BackendAPI:
    """暴露给前端的 Python 接口集合。"""

    def __init__(self):
        self._auto_helper: Any = None
        self._auto_thread: Any = None

    # ---------------- 自动跟读 ----------------
    def start_automation(self) -> dict[str, Any]:
        """在后台线程启动自动跟读（操控 E听说窗口）。"""
        if self._auto_thread and self._auto_thread.is_alive():
            return {"ok": False, "error": "自动跟读已在运行中"}
        try:
            from ets_assistant.automation import ETSHelper
            pic_dir = os.path.join(PKG_DIR, "pic")
            helper = ETSHelper(pic_dir, log_callback=lambda m: LogHub.push(m))
            self._auto_helper = helper

            def _run():
                try:
                    helper.run()
                except Exception as e:
                    LogHub.push(f"[自动跟读] 运行异常: {e}")
                finally:
                    LogHub.push("[自动跟读] 已结束")
                    self._auto_thread = None
                    self._auto_helper = None

            self._auto_thread = threading.Thread(target=_run, daemon=True)
            self._auto_thread.start()
            LogHub.push("[自动跟读] 已启动，请在 E听说 窗口中进行跟读操作")
            return {"ok": True}
        except Exception as e:
            LogHub.push(f"[自动跟读] 启动失败: {e}")
            return {"ok": False, "error": str(e)}

    def stop_automation(self) -> dict[str, Any]:
        """停止正在运行的自动跟读。"""
        if self._auto_helper is None:
            return {"ok": False, "error": "当前没有运行中的自动跟读"}
        self._auto_helper.stop()
        LogHub.push("[自动跟读] 已发送停止信号，将在下一轮结束")
        return {"ok": True}

    # ---------------- 环境检测 ----------------
    def env_check(self) -> dict[str, Any]:
        """返回环境检测汇总（含本地模板状态）。"""
        res: dict[str, Any] = {}
        try:
            res = run_all_checks()
            if "error" in res:
                return res
            # 补充本地模板状态（前端卡片 tpl 使用）
            try:
                from ets_assistant.automation import ETSHelper
                pic_dir = os.path.join(PKG_DIR, "pic")
                helper = ETSHelper(pic_dir)
                tpl_ok = all(
                    os.path.exists(os.path.join(pic_dir, f))
                    for f in helper.templates.values()
                )
                res["tpl"] = {
                    "ok": tpl_ok,
                    "detail": "四个按钮模板均已就绪" if tpl_ok
                    else "未找到 pic/yuan.png,luyin.png,stop.png,next.png；请手动截取这四个按钮",
                }
            except Exception:
                res["tpl"] = {"ok": False, "detail": "模板状态未知"}
        except Exception as e:
            res = {"error": str(e)}
        LogHub.push("[环境] 检测完成")
        return res

    def open_ets(self) -> dict[str, Any]:
        """尝试启动 E听说。"""
        candidates = ["ETS.exe", "ETSStudent.exe", "ETSClient.exe"]
        for c in candidates:
            path = os.path.join(ETS_DIR, c)
            if os.path.exists(path):
                try:
                    _ = subprocess.Popen(path)
                    LogHub.push(f"[环境] 已启动 {path}")
                    return {"ok": True, "path": path}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
        LogHub.push("[环境] 未找到 E听说 主程序")
        return {"ok": False, "error": "未找到主程序"}

    # ---------------- 答案/试卷查看 ----------------
    def list_papers(self, keyword: str = "") -> dict[str, Any]:
        try:
            papers = search_papers(keyword) if keyword else list_papers()
            return {"ok": True, "papers": papers}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def paper_info(self, name: str) -> dict[str, Any]:
        try:
            ets_dir = get_ets_dir()
            papers = list_papers(ets_dir)
            target = next((p for p in papers if p["name"] == name), None)
            if not target:
                return {"ok": False, "error": "未找到试卷"}
            info = read_paper_info(target["path"])
            try:
                info["created"] = time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(os.path.getctime(target["path"])))
                info["modified"] = time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(target["mtime"]))
            except Exception:
                info["created"] = info["modified"] = ""
            return {"ok": True, "info": info}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------------- 立体声混音 ----------------
    def enable_stereo_mix(self) -> dict[str, Any]:
        """启用立体声混音并设为默认录音设备。"""
        LogHub.push("[音频] 尝试启用立体声混音...")
        try:
            res = enable_stereo_mix()
            if res.get("ok"):
                LogHub.push(f"[音频] {res.get('detail', '')}")
            else:
                LogHub.push(f"[音频] 启用失败: {res.get('detail', '')}")
            return res
        except Exception as e:
            LogHub.push(f"[音频] 启用异常: {e}")
            return {"ok": False, "error": str(e)}

    def restore_stereo_mix(self) -> dict[str, Any]:
        """恢复之前备份的默认录音设备。"""
        LogHub.push("[音频] 尝试恢复默认录音设备...")
        try:
            res = restore_default_capture()
            if res.get("ok"):
                LogHub.push(f"[音频] {res.get('detail', '')}")
            else:
                LogHub.push(f"[音频] 恢复失败: {res.get('detail', '')}")
            return res
        except Exception as e:
            LogHub.push(f"[音频] 恢复异常: {e}")
            return {"ok": False, "error": str(e)}

    # ---------------- DLL 编译（一键） ----------------
    def dll_build_status(self) -> dict[str, bool]:
        """检测编译器、Detours、产物与部署状态。"""
        status: dict[str, bool] = {
            "msvc": False,
            "clang": False,
            "cmake": False,
            "detours": False,
            "output_exists": os.path.exists(os.path.join(ADVANCED_DIR, "winmm.dll")),
            "deployed": os.path.exists(os.path.join(ETS_DIR, "winmm.dll")),
        }
        # MSVC cl
        try:
            r = subprocess.run(["where", "cl"], capture_output=True, text=True, shell=True)
            status["msvc"] = r.returncode == 0
        except Exception:
            pass
        # clang
        status["clang"] = shutil.which("clang") is not None
        # cmake
        try:
            r = subprocess.run(["cmake", "--version"], capture_output=True, text=True)
            status["cmake"] = r.returncode == 0
        except Exception:
            pass
        # detours 头文件
        detours_root = os.environ.get("DETOURS_ROOT", "")
        if detours_root and os.path.exists(os.path.join(detours_root, "include", "detours", "detours.h")):
            status["detours"] = True
        return status

    def dll_build(self) -> dict[str, Any]:
        """
        一键编译 winmm.dll。
        需要 MSVC(cl)+cmake+Detours。若不可用则返回引导信息。
        """
        st = self.dll_build_status()
        if not (st["msvc"] or st["clang"]) or not st["cmake"] or not st["detours"]:
            LogHub.push("[DLL] 编译环境不完整，已返回安装引导")
            return {
                "ok": False,
                "need_setup": True,
                "status": st,
                "guide": (
                    "缺少编译依赖，请按以下步骤准备：\n"
                    "1) 安装 Visual Studio 2022（勾选『使用 C++ 的桌面开发』，含 MSVC + CMake）。\n"
                    "2) 安装 Detours：\n"
                    "   git clone https://github.com/microsoft/Detours && cd Detours\n"
                    "   mkdir build && cd build && cmake .. && cmake --build . --config Release\n"
                    "   设置环境变量 DETOURS_ROOT 指向 Detours 根目录。\n"
                    "3) 重新打开本程序（需从 VS 的『Developer Command Prompt』启动）。\n"
                    "完成后点击『一键编译』即可生成 advanced/winmm.dll。"
                ),
            }
        # 调用 build_dll.py 实际编译（已处理 MSVC 开发者环境）
        try:
            build_dll = _load_advanced_module("build_dll")
            LogHub.push("[DLL] 开始编译（MSVC + CMake + Detours）...")
            ok: bool = build_dll.build()  # type: ignore[attr-defined]
            if ok and os.path.exists(os.path.join(ADVANCED_DIR, "winmm.dll")):
                LogHub.push("[DLL] 编译成功 -> advanced/winmm.dll")
                return {"ok": True, "path": os.path.join(ADVANCED_DIR, "winmm.dll")}
            return {"ok": False, "stage": "build", "error": "编译未成功，请查看运行日志"}
        except Exception as e:
            LogHub.push(f"[DLL] 编译异常: {e}")
            return {"ok": False, "error": str(e)}

    def dll_deploy(self, dll_path: str = "__auto__") -> dict[str, Any]:
        """部署（写入 ETS 目录）。前端已做风险确认，后端跳过交互输入。"""
        if dll_path in ("__auto__", "", None):
            dll_path = os.path.join(ADVANCED_DIR, "winmm.dll")
        if not os.path.isfile(dll_path):
            return {"ok": False, "error": "找不到 advanced/winmm.dll，请先编译"}
        if not os.path.isfile(os.path.join(os.path.dirname(dll_path), "winmm_orig.dll")):
            return {"ok": False, "error": "找不到 winmm_orig.dll（转发目标），请先完整编译"}
        try:
            deploy_dll = _load_advanced_module("deploy_dll")
            deploy_dll.deploy(dll_path, auto_confirm=True)  # type: ignore[attr-defined]
            LogHub.push("[DLL] 部署完成")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_ets_dir(self) -> dict[str, Any]:
        """在资源管理器中打开 ETS 目录。"""
        os.makedirs(ETS_DIR, exist_ok=True)
        try:
            _ = subprocess.Popen(["explorer", ETS_DIR])
            LogHub.push("[环境] 已打开 ETS 目录")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def dll_uninstall(self) -> dict[str, Any]:
        try:
            deploy_dll = _load_advanced_module("deploy_dll")
            deploy_dll.uninstall()  # type: ignore[attr-defined]
            LogHub.push("[DLL] 卸载完成")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------------- 日志 ----------------
    def poll_logs(self) -> list[dict[str, str]]:
        """前端轮询后端日志。"""
        return LogHub.drain()


# -------------------- 启动 WebUI --------------------
def start_webui() -> None:
    """由 __main__ 调用，启动 PyWebView 窗口。"""
    import webview

    api = BackendAPI()
    # 让 automation 等模块的日志也能进 LogHub
    html_path = os.path.join(BASE_DIR, "index.html")
    LogHub.push("[WebUI] 正在加载前端界面...")

    _ = webview.create_window(
        "E听说自动化辅助工具",
        url=html_path,
        js_api=api,
        width=1180,
        height=760,
        min_size=(980, 640),
    )
    webview.start(debug=False)


if __name__ == "__main__":
    start_webui()
