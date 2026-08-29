"""
audio_control.py — Windows 录音设备控制（立体声混音）。

检测部分优先用 pyaudio 枚举 WaveIn 设备（可识别被截断/乱码的立体声混音名称），
不依赖 PowerShell/COM；设置默认设备时调用改进后的 enable_stereo_mix.ps1。

功能：
- 枚举录音设备，查找立体声混音
- 设为默认录音设备并备份原设备
- 恢复备份的默认设备
"""

import os
import sys
import json
import subprocess
import tempfile

STEREO_MIX_NAMES = ["立体声混音", "Stereo Mix", "立体声混合",
                    "What U Hear", "Wave Out Mix", "循环回放"]

BACKUP_FILE = os.path.join(os.environ.get("TEMP", "C:\\Windows\\Temp"),
                           "ets_stereo_mix_backup.json")


# -------------------- pyaudio 检测 --------------------
def _pyaudio_devices():
    """返回 [(index, name, is_default)] 所有输入设备。"""
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        devices = []
        default_index = p.get_default_input_device_info().get("index") if hasattr(p, "get_default_input_device_info") else -1
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                devices.append({
                    "index": i,
                    "name": info.get("name", ""),
                    "is_default": info.get("index") == default_index,
                })
        p.terminate()
        return devices
    except Exception:
        return []


def enum_capture_devices():
    """返回录音设备列表。"""
    return _pyaudio_devices()


def _match_stereo(name):
    # 仅匹配明确的立体声混音别名，避免把"麦克风/HD Audio Mixed capture"等误判为立体声混音
    lowered = name.lower()
    keys = ["立体声混音", "stereo mix", "立体声混合",
            "what u hear", "wave out mix", "循环回放"]
    if any(k in name for k in STEREO_MIX_NAMES):
        return True
    return any(k in lowered for k in keys)


def find_stereo_mix():
    """查找立体声混音设备。返回 (device_index, name) 或 (None, None)。"""
    for d in enum_capture_devices():
        if _match_stereo(d["name"]):
            return d["index"], d["name"]
    return None, None


def get_default_capture():
    """返回 (index, name) 当前默认录音设备。"""
    for d in enum_capture_devices():
        if d.get("is_default"):
            return d["index"], d["name"]
    return None, ""


# -------------------- PowerShell 操作 --------------------
def _ps1_path():
    """查找 enable_stereo_mix.ps1：依次检查 同目录 / 包上级(项目根) / 工作目录 / exe 目录。"""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "enable_stereo_mix.ps1"),
        os.path.join(os.path.dirname(here), "enable_stereo_mix.ps1"),
        os.path.join(os.getcwd(), "enable_stereo_mix.ps1"),
    ]
    if getattr(sys, "frozen", False):  # PyInstaller 打包
        candidates.append(os.path.join(os.path.dirname(sys.executable), "enable_stereo_mix.ps1"))
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[1]


def _is_admin():
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _looks_like_permission(detail):
    d = (detail or "").lower()
    keys = ["权限", "拒绝", "admin", "access is denied", "0x80070005",
            "uac", "elevated", "提升", "拒绝访问"]
    return any(k in d for k in keys)


def _parse_ps1_text(text):
    out = (text or "").strip()
    last_line = out.splitlines()[-1] if out else ""
    try:
        result = json.loads(last_line)
        return {"ok": bool(result.get("ok")), "detail": result.get("detail", last_line)}
    except Exception:
        return {"ok": False, "detail": f"输出无法解析: {out[:500]}"}


def _run_ps1(mode):
    """调用 enable_stereo_mix.ps1。普通运行失败且像权限问题时，自动以管理员(UAC)重试。"""
    ps1 = _ps1_path()
    if not os.path.exists(ps1):
        return {"ok": False,
                "detail": "未找到 enable_stereo_mix.ps1（应位于项目根目录）。请确认脚本存在或以管理员运行。"}

    # 1) 普通运行
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, mode],
            capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=60,
        )
        res = _parse_ps1_text(proc.stdout)
    except Exception as e:
        res = {"ok": False, "detail": f"调用 PowerShell 失败: {e}"}

    # 2) 失败且疑似权限不足，且当前非管理员 -> UAC 提权重试
    if (not res["ok"]) and (not _is_admin()) and _looks_like_permission(res.get("detail", "")):
        try:
            tmp = tempfile.gettempdir()
            result_file = os.path.join(tmp, f"ets_stereo_{mode}_result.txt")
            err_file = os.path.join(tmp, f"ets_stereo_{mode}_err.txt")
            for f in (result_file, err_file):
                try:
                    os.remove(f)
                except OSError:
                    pass
            cmd = [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                f'Start-Process -FilePath powershell -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File","{ps1}","{mode}" -Verb RunAs -Wait -RedirectStandardOutput "{result_file}" -RedirectStandardError "{err_file}"'
            ]
            subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="ignore", timeout=120)
            if os.path.exists(result_file):
                with open(result_file, "r", encoding="utf-8", errors="ignore") as fh:
                    res = _parse_ps1_text(fh.read())
        except Exception:
            pass
        if not res["ok"] and "管理员" not in res.get("detail", ""):
            res["detail"] = (res.get("detail", "") +
                             " 已尝试以管理员运行，若弹出 UAC 请允许；仍失败请手动以管理员身份启动本程序。")

    return res


def enable_stereo_mix():
    """启用立体声混音并设为默认录音设备。"""
    idx, name = find_stereo_mix()
    if idx is None:
        return {"ok": False, "detail": "未找到立体声混音设备（请在系统声音设置中确认已启用）"}
    return _run_ps1("enable")


def restore_default_capture():
    """恢复之前备份的默认录音设备。"""
    return _run_ps1("restore")


if __name__ == "__main__":
    print("默认录音设备:", get_default_capture())
    print("立体声混音:", find_stereo_mix())
