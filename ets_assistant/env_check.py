"""
环境检测模块：检查运行 E听说 自动化所需的前置条件。
返回结构化结果供 GUI 展示。所有检测都不阻塞，纯查询。
"""
import os
import sys
import ctypes
import importlib.util


# E听说 可能的进程名（不同版本/渠道略有差异）
ETS_PROCESS_NAMES = [
    "ETS.exe", "ETSStudent.exe", "e_ting_shuo.exe",
    "EtingtingShuo.exe", "ETSCloud.exe", "ETSClient.exe",
]

# 立体声混音相关设备名（中英文）
STEREO_MIX_NAMES = [
    "立体声混音", "Stereo Mix", "立体声混合",
    "What U Hear", "Wave Out Mix", "循环回放",
]


def is_admin() -> bool:
    """是否以管理员身份运行。"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def check_ets_process() -> dict:
    """检测 E听说 进程是否在运行。"""
    try:
        import psutil
    except Exception:
        # 没有 psutil 时退回 wmic / tasklist
        return _check_ets_process_fallback()
    running = []
    for p in psutil.process_iter(["name"]):
        try:
            name = (p.info.get("name") or "").lower()
        except Exception:
            continue
        for cand in ETS_PROCESS_NAMES:
            if name == cand.lower():
                running.append(cand)
    return {
        "ok": len(running) > 0,
        "detail": f"检测到进程: {', '.join(running)}" if running
                  else "未检测到 E听说 进程（请先启动 E听说）",
        "processes": running,
    }


def _check_ets_process_fallback() -> dict:
    try:
        import subprocess
        out = subprocess.run(
            ["tasklist", "/FO", "CSV"], capture_output=True, text=True,
            encoding="gbk", errors="ignore", timeout=10,
        ).stdout.lower()
        running = [c for c in ETS_PROCESS_NAMES if c.lower() in out]
        return {
            "ok": len(running) > 0,
            "detail": f"检测到进程: {', '.join(running)}" if running
                      else "未检测到 E听说 进程（请先启动 E听说）",
            "processes": running,
        }
    except Exception as e:
        return {"ok": False, "detail": f"进程检测失败: {e}", "processes": []}


def check_stereo_mix() -> dict:
    """
    检测立体声混音是否可用且为默认录音设备。
    优先用 audio_control（pycaw 纯 Python），失败时退回 PowerShell。
    """
    try:
        try:
            from .audio_control import find_stereo_mix, get_default_capture
        except ImportError:
            from audio_control import find_stereo_mix, get_default_capture
        dev_id, stereo_name = find_stereo_mix()
        default_id, default_name = get_default_capture()
        if dev_id is None:
            return {
                "ok": False,
                "detail": "未找到立体声混音设备（声卡可能不支持，或需在声音设置中先启用）",
            }
        is_default = default_id is not None and default_id == dev_id
        if is_default:
            return {
                "ok": True,
                "detail": f"立体声混音已启用且为默认录音设备（{stereo_name}）",
            }
        return {
            "ok": False,
            "detail": f"立体声混音已存在但非默认（当前默认: {default_name or '未知'}），点击启用切换",
        }
    except Exception as e:
        return {"ok": False, "detail": f"立体声混音检测失败: {e}"}


def check_dependencies() -> dict:
    """检测 Python 关键依赖是否安装。"""
    required = {
        "PyQt5": "PyQt5",
        "OpenCV": "cv2",
        "PyAutoGUI": "pyautogui",
        "NumPy": "numpy",
        "PyAudio": "pyaudio",
        "python-docx": "docx",
    }
    missing = []
    present = []
    for label, mod in required.items():
        if importlib.util.find_spec(mod) is None:
            missing.append(label)
        else:
            present.append(label)
    return {
        "ok": len(missing) == 0,
        "detail": "全部依赖已安装" if not missing
                  else f"缺少依赖: {', '.join(missing)}（请运行 pip install -r requirements.txt）",
        "missing": missing,
        "present": present,
    }


def check_screen() -> dict:
    """检测屏幕尺寸（单屏更稳）。"""
    try:
        import screeninfo  # 可选
        monitors = screeninfo.get_monitors()
        n = len(monitors)
    except Exception:
        try:
            import tkinter as tk
            root = tk.Tk()
            n = 1 if root.winfo_screenwidth() > 0 else 0
            root.destroy()
        except Exception:
            n = 1
    return {
        "ok": n <= 1,
        "detail": f"检测到 {n} 个显示器（单屏更稳定，多屏可能定位偏移）" if n else "无法检测显示器",
        "count": n,
    }


def run_all_checks() -> dict:
    """汇总所有检测项。"""
    return {
        "admin": is_admin(),
        "ets": check_ets_process(),
        "stereo": check_stereo_mix(),
        "deps": check_dependencies(),
        "screen": check_screen(),
    }
