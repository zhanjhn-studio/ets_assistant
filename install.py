# -*- coding: utf-8 -*-
# =============================================================================
#  install.py  ——  E听说助手 图形化安装 / 卸载程序
#
#  ⚠️ 免责声明：本工具仅供个人技术研究与逆向工程教学用途。
#  严禁用于考试作弊或侵犯软件权益。使用者须自行承担一切法律与纪律责任，
#  作者不对任何使用后果负责。若不同意，请立即删除本项目。
#
#  功能：
#    1) 图形化向导（PyQt5 + QWebEngineView 渲染内嵌 HTML，无边框毛玻璃界面；
#       若环境缺少 WebEngine，自动回退为原生 Qt 界面，功能完全一致）
#    2) 用户自选安装位置 -> 把本文件同目录的 ets_assistant / 启动器 / ps1 等
#       全部复制到该位置
#    3) 创建桌面快捷方式 + 开始菜单快捷方式（可选）
#    4) 可选自动安装 Python 依赖（pip install -r requirements.txt）
#    5) 写注册表 HKCU\...\Uninstall\ETSAssistant（可在「添加或删除程序」里卸载）
#    6) 已安装时再次运行 -> 直接进入「卸载 / 修复 / 启动」界面
#
#  使用：
#    python install.py          （与 ets_assistant 目录放在一起）
#    或打包成 install.exe 后双击（需把 ets_assistant 等文件放在 exe 同目录）
# =============================================================================

import os
import re
import sys
import traceback
import json
import stat
import time
import shutil
import random
import tempfile
import threading
import subprocess
import urllib.parse
from datetime import datetime

APP_NAME = "E听说助手"
APP_ID = "ETSAssistant"
APP_VERSION = "1.0.0"
PUBLISHER = "ETS Assistant"

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _safe_print(*a):
    try:
        print(*a, flush=True)
    except Exception:
        pass


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
except Exception:
    pass


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def dlog(msg: str):
    """仅打包 + ETS_DEBUG=1 时写入临时日志，便于排查无控制台崩溃。"""
    if is_frozen() and os.environ.get("ETS_DEBUG"):
        try:
            p = os.path.join(tempfile.gettempdir(), "ets_install.log")
            with open(p, "a", encoding="utf-8") as f:
                f.write("%s %s\n" % (datetime.now().strftime("%H:%M:%S"), msg))
        except Exception:
            pass


def source_dir() -> str:
    """安装源目录：打包后指向 _MEIPASS/payload（仅含待安装数据，避免把
    PyQt5/Qt 运行时也复制进安装目录）；未打包时指向本脚本所在目录。"""
    if is_frozen():
        for base in (getattr(sys, "_MEIPASS", ""),
                     os.path.dirname(os.path.abspath(sys.executable))):
            if base:
                payload = os.path.join(base, "payload")
                if os.path.isdir(payload):
                    return payload
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


SOURCE_DIR = source_dir()

# 复制时需要排除的条目
EXCLUDE_NAMES = {
    "install.py", "install.exe", "install.spec", "install_ui.html",
    "卸载E听说助手.py", "卸载E听说助手.exe",
    "__pycache__", ".git", ".gitignore", ".github", ".codebuddy",
    "build", "dist", ".idea", ".vscode",
    "ets-automation.zip",
}
EXCLUDE_EXTS = {".pyc", ".pyo", ".tmp", ".log"}
EXCLUDE_PREFIX = (".", "_internal")


def _excluded(name: str) -> bool:
    if name in EXCLUDE_NAMES:
        return True
    if os.path.splitext(name)[1].lower() in EXCLUDE_EXTS:
        return True
    return name.startswith(EXCLUDE_PREFIX)


def human_size(n) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


# ---------------------------------------------------------------------------
# PowerShell / 快捷方式 / 注册表
# ---------------------------------------------------------------------------

def ps_quote(s) -> str:
    """把字符串安全地包成 PowerShell 单引号字面量。"""
    return "'" + str(s).replace("'", "''") + "'"


def _si():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return si


def run_ps(script: str, timeout: int = 120):
    """执行一段 PowerShell 脚本，返回 (ok, stdout)。"""
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, encoding="utf-8",
            errors="ignore", timeout=timeout, startupinfo=_si(),
        )
        return p.returncode == 0, (p.stdout or "").strip()
    except Exception as e:
        return False, str(e)


def special_folder(name: str) -> str:
    """读取 Windows 特殊文件夹（Desktop / StartMenu / LocalAppData …）。"""
    ok, out = run_ps(f"[Environment]::GetFolderPath([Environment+SpecialFolder]::{name})", 30)
    if ok and out and os.path.isdir(out):
        return out
    home = os.path.expanduser("~")
    fallback = {
        "Desktop": os.path.join(home, "Desktop"),
        "StartMenu": os.path.join(home, "AppData", "Roaming", "Microsoft",
                                  "Windows", "Start Menu", "Programs"),
        "LocalApplicationData": os.path.join(home, "AppData", "Local"),
    }.get(name, home)
    os.makedirs(fallback, exist_ok=True)
    return fallback


def create_shortcut(lnk: str, target: str, args: str = "", workdir: str = "",
                    icon: str = "", desc: str = "") -> bool:
    try:
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
    except Exception:
        pass
    script = (
        "$ws = New-Object -ComObject WScript.Shell\n"
        f"$s = $ws.CreateShortcut({ps_quote(lnk)})\n"
        f"$s.TargetPath = {ps_quote(target)}\n"
        f"$s.Arguments = {ps_quote(args)}\n"
        f"$s.WorkingDirectory = {ps_quote(workdir)}\n"
        f"$s.Description = {ps_quote(desc)}\n"
        f"if ({ps_quote(icon)}) {{ $s.IconLocation = {ps_quote(icon)} }}\n"
        "$s.Save()\n"
    )
    ok, _ = run_ps(script, 60)
    return ok and os.path.exists(lnk)


def remove_file(path: str) -> bool:
    try:
        if os.path.exists(path):
            os.remove(path)
        return True
    except Exception:
        return False


REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + APP_ID


def reg_write(install_dir: str, version: str = APP_VERSION):
    try:
        import winreg
        launch = resolve_launch_target(install_dir)
        uninst = os.path.join(install_dir, f"卸载{APP_NAME}.py")
        if not os.path.isfile(uninst):
            uninst = os.path.join(install_dir, f"卸载{APP_NAME}.exe")
        if not os.path.isfile(uninst):
            uninst = os.path.abspath(__file__)

        py = pythonw_exe() or python_exe() or "pythonw"
        if uninst.lower().endswith(".exe"):
            uninst_cmd = f'"{uninst}"'
            icon = uninst + ",0"
        else:
            uninst_cmd = f'"{py}" "{uninst}"'
            icon = launch[0] if launch else ""

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REG_PATH, 0,
                                winreg.KEY_WRITE) as k:
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, version)
            winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
            winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, install_dir)
            winreg.SetValueEx(k, "InstallDate", 0, winreg.REG_SZ,
                              datetime.now().strftime("%Y%m%d"))
            winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ, uninst_cmd)
            winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ, icon)
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD,
                              int(dir_size(install_dir) / 1024))
        return True
    except Exception as e:
        _safe_print("[注册] 写入失败:", e)
        return False


def reg_read():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0,
                            winreg.KEY_READ) as k:
            info = {}
            i = 0
            while True:
                try:
                    n, v, _ = winreg.EnumValue(k, i)
                    info[n] = v
                    i += 1
                except OSError:
                    break
            return info
    except Exception:
        return None


def reg_remove():
    try:
        import winreg
        winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, REG_PATH)
        return True
    except Exception:
        try:
            import winreg
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_PATH)
            return True
        except Exception:
            return False


def dir_size(path: str) -> int:
    total = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not _excluded(d)]
        for f in files:
            if _excluded(f):
                continue
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


# ---------------------------------------------------------------------------
# Python 解释器 / 启动目标解析
# ---------------------------------------------------------------------------

GENERIC_EXE = {
    "python.exe", "pythonw.exe", "uninstall.exe", "install.exe",
    "卸载e听说助手.exe", "卸载e听说助手.py",
}


def python_exe() -> str:
    if is_frozen():
        for c in ("python", "py"):
            p = shutil.which(c)
            if p:
                return p
        return ""
    return sys.executable


def pythonw_exe() -> str:
    """无控制台的解释器；过滤掉微软商店的 0 字节存根（点了没反应）。"""
    cands = []
    if is_frozen():
        p = shutil.which("pythonw")
        if p:
            cands.append(p)
    else:
        cands.append(os.path.join(os.path.dirname(sys.executable), "pythonw.exe"))
        cands.append(sys.executable)
    for c in cands:
        try:
            if os.path.isfile(c) and os.path.getsize(c) > 10000:
                return c
        except OSError:
            pass
    return ""


def resolve_launch_target(dest: str):
    """返回 (target, args, workdir) 或 None。"""
    # 1) 已知的 exe 启动器
    for name in (f"启动{APP_NAME}.exe", f"{APP_NAME}.exe", "ETSAssistant.exe"):
        p = os.path.join(dest, name)
        if os.path.isfile(p):
            return p, "", dest
    # 2) 安装目录下的其它 exe（排除通用名）
    try:
        for f in sorted(os.listdir(dest)):
            if f.lower().endswith(".exe") and f.lower() not in GENERIC_EXE:
                return os.path.join(dest, f), "", dest
    except OSError:
        pass
    # 3) Python 启动器脚本（无控制台，避免出现黑色命令行窗口）
    for name in (f"启动{APP_NAME}.pyw", f"启动{APP_NAME}.py", "main.pyw", "main.py"):
        p = os.path.join(dest, name)
        if os.path.isfile(p):
            py = pythonw_exe() or python_exe()
            return py, f'"{p}"', dest
    return None


def resolve_icon(dest: str, target: str) -> str:
    if target.lower().endswith(".exe"):
        return target + ",0"
    for cand in (os.path.join(dest, "ets_assistant", "pic", "logo.ico"),
                 os.path.join(dest, "logo.ico")):
        if os.path.isfile(cand):
            return cand
    return ""


# ---------------------------------------------------------------------------
# 安装 / 卸载 核心
# ---------------------------------------------------------------------------

class Installer:
    """纯逻辑层：通过 log(msg) / progress(pct, text) 回调向 UI 汇报。"""

    def __init__(self, log=None, progress=None):
        self.log = log or _safe_print
        self.progress = progress or (lambda p, t: None)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    # ---------------- 扫描待复制文件 ----------------
    def collect(self, src: str):
        items = []
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if not _excluded(d)]
            for f in files:
                if _excluded(f):
                    continue
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, src)
                if os.path.abspath(fp) == os.path.abspath(__file__):
                    continue
                items.append((fp, rel))
        return items

    # ---------------- 安装 ----------------
    def install(self, dest: str, opts: dict) -> bool:
        src = SOURCE_DIR
        dest = os.path.abspath(dest)
        src = os.path.abspath(src)

        if os.path.normcase(dest) == os.path.normcase(src):
            self.log("错误：安装位置不能与安装源目录相同。")
            return False
        nd, ns = os.path.normcase(dest), os.path.normcase(src)
        if nd.startswith(ns + os.sep):
            self.log("错误：安装位置不能位于安装源目录内部。")
            return False
        if ns.startswith(nd + os.sep):
            self.log("错误：安装位置不能是安装源的父目录（会把整个源目录复制进去）。")
            return False

        try:
            os.makedirs(dest, exist_ok=True)
        except Exception as e:
            self.log(f"错误：无法创建目录 {dest} -> {e}")
            return False

        items = self.collect(src)
        total = len(items)
        if total == 0:
            self.log("错误：安装源为空，未找到可复制的文件。")
            return False

        total_bytes = 0
        for fp, _ in items:
            try:
                total_bytes += os.path.getsize(fp)
            except OSError:
                pass

        self.progress(2, "准备安装…")
        self.log(f"安装源：{src}")
        self.log(f"安装位置：{dest}")
        self.log(f"共 {total} 个文件（{human_size(total_bytes)}）")

        # --- 复制文件 ---
        done = 0
        for fp, rel in items:
            if self._cancel:
                self.log("已取消。")
                return False
            out = os.path.join(dest, rel)
            try:
                os.makedirs(os.path.dirname(out), exist_ok=True)
                shutil.copy2(fp, out)
            except Exception as e:
                self.log(f"跳过 {rel} -> {e}")
            done += 1
            pct = 5 + int(done / total * 65)
            if done % 5 == 0 or done == total:
                self.progress(pct, f"复制文件 {done}/{total}")
                self.log(f"  {rel}")

        # --- 复制卸载器（install.py 自身） ---
        self.progress(72, "写入卸载程序…")
        self._copy_self(dest)

        # --- 快捷方式 ---
        self.progress(76, "创建快捷方式…")
        target = self.make_shortcuts(dest, opts)

        # --- 依赖 ---
        if opts.get("deps", True):
            self.progress(82, "检查 Python 依赖…")
            self._ensure_deps(dest)

        # --- 注册表 ---
        self.progress(96, "写入安装信息…")
        if reg_write(dest):
            self.log("已写入卸载信息（可在「添加或删除程序」中卸载）。")
        else:
            self.log("警告：写入卸载信息失败（不影响使用）。")

        self.progress(100, "安装完成")
        if target:
            self.log(f"启动入口：{target[0]}")
        self.log("全部完成。")
        return True

    def _copy_self(self, dest: str):
        """把安装器自身复制一份到安装目录，作为卸载入口。"""
        try:
            if is_frozen():
                # exe 无法单独复制（缺依赖），优先复制源码版 install.py
                src = os.path.join(SOURCE_DIR, "install.py")
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(dest, f"卸载{APP_NAME}.py"))
                    self.log("已写入 卸载入口：卸载%s.py" % APP_NAME)
                else:
                    self.log("提示：打包版未附带 install.py 源码，"
                             "卸载请再次运行本安装程序。")
            else:
                shutil.copy2(os.path.abspath(__file__),
                             os.path.join(dest, f"卸载{APP_NAME}.py"))
                self.log("已写入 卸载入口：卸载%s.py" % APP_NAME)
        except Exception as e:
            self.log(f"警告：写入卸载入口失败 -> {e}")

    def make_shortcuts(self, dest: str, opts: dict):
        target = resolve_launch_target(dest)
        if not target:
            self.log("警告：未找到可启动的程序，跳过创建快捷方式。")
            return None
        exe, args, workdir = target
        icon = resolve_icon(dest, exe)
        made = []
        if opts.get("desk", True):
            lnk = os.path.join(special_folder("Desktop"), f"{APP_NAME}.lnk")
            if create_shortcut(lnk, exe, args, workdir, icon, APP_NAME):
                made.append(lnk)
                self.log(f"桌面快捷方式：{lnk}")
            else:
                self.log("警告：桌面快捷方式创建失败。")
        if opts.get("menu", True):
            lnk = os.path.join(special_folder("StartMenu"), "Programs",
                               APP_NAME, f"{APP_NAME}.lnk")
            if create_shortcut(lnk, exe, args, workdir, icon, APP_NAME):
                made.append(lnk)
                self.log(f"开始菜单快捷方式：{lnk}")
            else:
                self.log("警告：开始菜单快捷方式创建失败。")
        return (made[0] if made else None) or target

    def _ensure_deps(self, dest: str):
        req = os.path.join(dest, "ets_assistant", "requirements.txt")
        py = python_exe()
        if not py:
            self.log("警告：未找到 Python 解释器，跳过依赖安装。")
            return
        if not os.path.isfile(req):
            self.log("未找到 requirements.txt，跳过依赖安装。")
            return

        mods = ["cv2", "numpy", "pyautogui", "pyaudio", "PyQt5", "webview"]
        missing = []
        for m in mods:
            try:
                if subprocess.run([py, "-c", f"import {m}"], capture_output=True,
                                  startupinfo=_si(), timeout=120).returncode != 0:
                    missing.append(m)
            except Exception:
                missing.append(m)
        if not missing:
            self.log("依赖已就绪，无需安装。")
            return

        self.log(f"缺少依赖：{', '.join(missing)}，正在 pip 安装（需要几分钟）…")
        try:
            p = subprocess.Popen([py, "-m", "pip", "install", "-r", req],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="ignore",
                                 startupinfo=_si())
            for line in iter(p.stdout.readline, ""):
                line = line.rstrip()
                if line:
                    self.log("  " + line)
                if self._cancel:
                    p.terminate()
                    break
            p.wait()
            self.log(f"pip 结束，code={p.returncode}")
        except Exception as e:
            self.log(f"依赖安装失败：{e}")

    # ---------------- 卸载 ----------------
    def uninstall(self, info: dict) -> bool:
        dest = (info or {}).get("InstallLocation") or ""
        if not dest or not os.path.isdir(dest):
            self.log("未找到安装目录，仅清理注册信息。")
            reg_remove()
            self.progress(100, "已完成")
            return True

        self.progress(5, "正在停止运行中的程序…")
        self._kill_running(dest)

        self.progress(15, "删除快捷方式…")
        for lnk in (os.path.join(special_folder("Desktop"), f"{APP_NAME}.lnk"),
                    os.path.join(special_folder("StartMenu"), "Programs",
                                 APP_NAME, f"{APP_NAME}.lnk")):
            if os.path.exists(lnk):
                self.log(f"删除 {lnk}")
                remove_file(lnk)
        try:
            shutil.rmtree(os.path.join(special_folder("StartMenu"), "Programs",
                                       APP_NAME), ignore_errors=True)
        except Exception:
            pass

        self.progress(30, "删除程序文件…")
        ok = self._remove_tree(dest)

        self.progress(95, "清理安装信息…")
        if reg_remove():
            self.log("已删除卸载注册项。")

        if ok:
            self.progress(100, "卸载完成")
            self.log("已卸载完成，感谢使用。")
        else:
            self.progress(100, "部分文件需重启后删除")
            self.log("部分文件被占用，已安排重启后自动删除。")
        return ok

    def _kill_running(self, dest: str):
        names = set()
        try:
            for f in os.listdir(dest):
                if f.lower().endswith(".exe") and f.lower() not in GENERIC_EXE:
                    names.add(f)
        except OSError:
            pass
        for n in names:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/IM", n],
                               capture_output=True, startupinfo=_si(), timeout=30)
                self.log(f"已结束进程 {n}")
            except Exception:
                pass

    def _remove_tree(self, dest: str) -> bool:
        def _on_error(func, path, exc):
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception:
                pass

        try:
            shutil.rmtree(dest, onerror=_on_error)
            if not os.path.exists(dest):
                self.log(f"已删除 {dest}")
                return True
        except Exception as e:
            self.log(f"删除失败：{e}")

        # 文件被占用 -> 交给延迟清理脚本
        bat = os.path.join(os.environ.get("TEMP", "."),
                           f"{APP_ID}_cleanup_{int(time.time())}.bat")
        try:
            with open(bat, "w", encoding="gbk", errors="ignore") as f:
                f.write("@echo off\n")
                f.write("ping -n 3 127.0.0.1 >nul\n")
                f.write(f'rmdir /s /q "{dest}"\n')
                f.write('(goto) 2>nul & del "%~f0"\n')
            subprocess.Popen(["cmd", "/c", bat], close_fds=True,
                             creationflags=0x00000008 | 0x00000200,
                             startupinfo=_si())
            self.log(f"已创建延迟清理脚本：{bat}")
            return False
        except Exception as e:
            self.log(f"创建清理脚本失败：{e}")
            return False


# ---------------------------------------------------------------------------
# 界面（HTML，内嵌，无需外部文件）
# ---------------------------------------------------------------------------

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>E听说助手 · 安装</title>
<style>
:root{
  --bg:#0a0a0a; --bg2:#141414;
  --card:rgba(255,255,255,.05); --card2:rgba(255,255,255,.03);
  --line:rgba(255,255,255,.12); --line2:rgba(255,255,255,.08);
  --text:#f2f2f2; --muted:#8b8b8b;
  --btn:#ffffff; --btnT:#0a0a0a;
  --ghost:rgba(255,255,255,.08);
  --danger:#e5484d; --ok:#30a46c;
  --grid:rgba(255,255,255,.05); --stripe:rgba(0,0,0,.20);
  --shine:rgba(255,255,255,.32); --sweep:rgba(255,255,255,.30);
  --face:rgba(255,255,255,.10);
  --logbg:rgba(0,0,0,.30);
}
body.light{
  --bg:#f2f2f3; --bg2:#e9e9ec;
  --card:rgba(0,0,0,.035); --card2:rgba(0,0,0,.02);
  --line:rgba(0,0,0,.12); --line2:rgba(0,0,0,.07);
  --text:#101010; --muted:#6b6b6b;
  --btn:#111111; --btnT:#ffffff;
  --ghost:rgba(0,0,0,.06);
  --danger:#d13438; --ok:#1a7f4b;
  --grid:rgba(0,0,0,.05); --stripe:rgba(255,255,255,.32);
  --shine:rgba(255,255,255,.45); --sweep:rgba(0,0,0,.14);
  --face:rgba(0,0,0,.08);
  --logbg:rgba(0,0,0,.04);
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{
  font-family:"Microsoft YaHei UI","Microsoft YaHei",-apple-system,"Segoe UI",sans-serif;
  color:var(--text); background:var(--bg);
  background-image:radial-gradient(900px 500px at 15% -10%,rgba(255,255,255,.07),transparent 60%),
                   radial-gradient(700px 400px at 110% 110%,rgba(255,255,255,.05),transparent 60%);
  overflow:hidden; user-select:none;
}
/* 背景网格 + 缓慢呼吸 */
body::before{
  content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:linear-gradient(var(--grid) 1px,transparent 1px),
                   linear-gradient(90deg,var(--grid) 1px,transparent 1px);
  background-size:55px 55px;
  -webkit-mask-image:radial-gradient(circle at 50% 25%,#000 10%,transparent 78%);
          mask-image:radial-gradient(circle at 50% 25%,#000 10%,transparent 78%);
  animation:gridBreath 9s ease-in-out infinite;
}
@keyframes gridBreath{0%,100%{opacity:.55}50%{opacity:.95}}
.wrap{height:100%;display:flex;flex-direction:column;padding:4px 22px 14px;position:relative;z-index:1}
.spacer{flex:1}
/* ---- 卡片 ---- */
.card{
  flex:1 1 auto;min-height:0;margin-top:2px;border-radius:18px;
  background:var(--card);border:1px solid var(--line);
  backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
  box-shadow:0 24px 60px rgba(0,0,0,.35);
  padding:24px 26px;display:flex;flex-direction:column;overflow:hidden;position:relative;
}
.card::after{ /* 顶部高光边 */
  content:"";position:absolute;left:16px;right:16px;top:0;height:1px;pointer-events:none;
  background:linear-gradient(90deg,transparent,var(--shine),transparent);opacity:.5}
body.light .card{box-shadow:0 18px 44px rgba(0,0,0,.10)}
.page{display:none;flex:1 1 auto;min-height:0;flex-direction:column}
.page.on{display:flex;animation:fade .3s ease}
@keyframes fade{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
/* 内容错峰入场 */
.page.on>*{animation:rise .42s cubic-bezier(.2,.7,.3,1) backwards}
.page.on>*:nth-child(1){animation-delay:.02s}
.page.on>*:nth-child(2){animation-delay:.07s}
.page.on>*:nth-child(3){animation-delay:.12s}
.page.on>*:nth-child(4){animation-delay:.17s}
.page.on>*:nth-child(5){animation-delay:.22s}
@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
h1.big{font-size:23px;font-weight:700;letter-spacing:.5px}
h1.big .dot{display:inline-block;width:9px;height:9px;border-radius:2px;
  background:var(--btn);margin-right:10px;vertical-align:middle;
  box-shadow:0 0 12px var(--line);animation:blink 2.6s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1;transform:rotate(0)}
  50%{opacity:.45;transform:rotate(45deg)}}
/* ---- 启动检测页 ---- */
.boot{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:16px}
.boot-t{font-size:19px;font-weight:700;letter-spacing:.5px;margin-top:4px;
  animation:fade .3s ease}
.boot-s{font-size:12px;color:var(--muted);letter-spacing:.2px;
  animation:fade .3s ease}
p.lead{font-size:12.5px;color:var(--muted);margin-top:6px;line-height:1.7}
.sect{margin-top:20px}
.lab{font-size:11.5px;color:var(--muted);margin-bottom:7px;letter-spacing:.3px}
.row{display:flex;gap:8px}
input[type=text]{
  flex:1;height:36px;padding:0 12px;border-radius:10px;
  border:1px solid var(--line);background:var(--card2);color:var(--text);
  font-size:12.5px;font-family:inherit;outline:none}
input[type=text]{transition:border-color .2s,box-shadow .2s}
input[type=text]:focus{border-color:var(--line);
  box-shadow:0 0 0 3px var(--card2),0 0 0 4px var(--line2)}
.chk{display:flex;align-items:flex-start;gap:10px;padding:10px 12px;border-radius:12px;
  border:1px solid var(--line2);background:var(--card2);cursor:pointer;margin-bottom:8px;
  transition:border-color .2s,background .2s,transform .12s}
.chk:hover{border-color:var(--line);background:var(--ghost)}
.chk:active{transform:scale(.995)}
.chk input{
  appearance:none;-webkit-appearance:none;flex:0 0 auto;
  width:16px;height:16px;margin-top:2px;border-radius:5px;cursor:pointer;
  border:1px solid var(--line);background:var(--card2);
  display:grid;place-items:center;transition:background .18s,border-color .18s}
.chk input:checked{background:var(--btn);border-color:var(--btn)}
.chk input:checked::after{
  content:"";width:4px;height:8px;margin-top:-2px;
  border:solid var(--btnT);border-width:0 2px 2px 0;transform:rotate(45deg)}
.chk .t{font-size:12.5px}
.chk .d{font-size:11px;color:var(--muted);margin-top:3px;line-height:1.5}
.info{font-size:11.5px;color:var(--muted);margin-top:10px;display:flex;gap:14px;flex-wrap:wrap}
.info b{color:var(--text);font-weight:600}
/* ---- 按钮 ---- */
.actions{margin-top:auto;padding-top:18px;display:flex;gap:10px;align-items:center}
.btn{height:38px;padding:0 22px;border-radius:11px;border:1px solid transparent;
  font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;position:relative;
  background:var(--btn);color:var(--btnT);overflow:hidden;
  transition:transform .12s,filter .2s,box-shadow .2s}
.btn:hover{filter:brightness(1.06);box-shadow:0 6px 18px rgba(0,0,0,.30)}
.btn:active{transform:scale(.98)}
.btn[disabled]{opacity:.45;cursor:not-allowed;transform:none;box-shadow:none}
.btn.ghost{background:var(--ghost);color:var(--text);border-color:var(--line);font-weight:500}
.btn.danger{background:var(--danger);color:#fff}
.btn.ok{background:var(--ok);color:#fff}
/* 流光扫过 */
.btn::after{
  content:"";position:absolute;top:0;left:-70%;width:45%;height:100%;pointer-events:none;
  background:linear-gradient(90deg,transparent,var(--shine),transparent);transform:skewX(-18deg)}
.btn:hover::after{animation:shine .75s ease}
@keyframes shine{to{left:130%}}
/* ---- 3D 立方体加载动画 ---- */
.cube-stage{display:flex;align-items:center;gap:16px}
.cube{width:44px;height:44px;flex:0 0 auto;position:relative;
  transform-style:preserve-3d;animation:spinCube 3.4s linear infinite}
.cube i{position:absolute;inset:0;border:1px solid var(--line);background:var(--face);
  box-shadow:inset 0 0 14px var(--line2)}
.cube i:nth-child(1){transform:translateZ(22px)}
.cube i:nth-child(2){transform:rotateY(180deg) translateZ(22px)}
.cube i:nth-child(3){transform:rotateY(90deg) translateZ(22px)}
.cube i:nth-child(4){transform:rotateY(-90deg) translateZ(22px)}
.cube i:nth-child(5){transform:rotateX(90deg) translateZ(22px)}
.cube i:nth-child(6){transform:rotateX(-90deg) translateZ(22px)}
@keyframes spinCube{
  0%{transform:rotateX(-22deg) rotateY(0deg)}
  100%{transform:rotateX(-22deg) rotateY(360deg)}}
.cube-shadow{width:44px;height:8px;margin-top:10px;border-radius:50%;
  background:radial-gradient(ellipse at center,var(--line),transparent 70%);
  animation:cs 3.4s ease-in-out infinite}
@keyframes cs{0%,100%{transform:scaleX(.9);opacity:.5}50%{transform:scaleX(1.05);opacity:.85}}
.cube-cell{display:flex;flex-direction:column;align-items:center;flex:0 0 auto}
/* ---- 进度 ---- */
.bar{height:10px;border-radius:99px;background:var(--card2);
  border:1px solid var(--line2);overflow:hidden;margin-top:18px;position:relative}
.bar>i{position:relative;display:block;height:100%;width:0%;border-radius:99px;
  background:linear-gradient(90deg,#fff,#b0b0b0);transition:width .3s ease;overflow:hidden}
body.light .bar>i{background:linear-gradient(90deg,#1c1c1c,#6a6a6a)}
.bar>i::after{
  content:"";position:absolute;inset:0;
  background-image:repeating-linear-gradient(115deg,var(--stripe) 0 7px,transparent 7px 15px);
  background-size:30px 100%;animation:stripes .8s linear infinite}
@keyframes stripes{to{background-position:30px 0}}
.bar::after{ /* 未填充部分的微光扫过 */
  content:"";position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(90deg,transparent,var(--sweep),transparent);
  width:35%;animation:sweep 2.4s ease-in-out infinite}
@keyframes sweep{0%{left:-35%}60%,100%{left:105%}}
.ptext{margin-top:9px;font-size:12px;color:var(--muted);display:flex;justify-content:space-between;gap:10px}
.ptext .el{font-variant-numeric:tabular-nums;opacity:.75}
/* ---- 日志（终端风）---- */
.term{flex:1 1 auto;min-height:0;margin-top:14px;border-radius:12px;overflow:hidden;
  border:1px solid var(--line2);display:flex;flex-direction:column;background:var(--logbg)}
.term-bar{height:26px;flex:0 0 auto;display:flex;align-items:center;gap:6px;padding:0 11px;
  border-bottom:1px solid var(--line2);background:var(--card2)}
.term-bar i{width:8px;height:8px;border-radius:50%;background:var(--line);display:block}
.term-bar i:first-child{background:var(--danger);opacity:.75}
.term-bar span{margin-left:6px;font-size:10.5px;color:var(--muted);letter-spacing:.4px}
.log{flex:1 1 auto;min-height:0;padding:9px 12px;overflow:auto;
  font:11.5px/1.75 Consolas,"Cascadia Mono",monospace;color:#cfcfcf;white-space:pre-wrap;
  word-break:break-all;user-select:text}
body.light .log{background:rgba(0,0,0,.04);color:#333}
.log::-webkit-scrollbar{width:7px}
.log::-webkit-scrollbar-thumb{background:rgba(255,255,255,.18);border-radius:99px}
body.light .log::-webkit-scrollbar-thumb{background:rgba(0,0,0,.2)}
/* ---- 完成 ---- */
.done{width:56px;height:56px;border-radius:50%;display:grid;place-items:center;
  font-size:26px;font-weight:700;background:rgba(48,164,108,.14);color:var(--ok);
  border:1px solid rgba(48,164,108,.42);animation:pop .45s cubic-bezier(.2,.9,.3,1.2)}
.done.bad{background:rgba(229,72,77,.14);color:var(--danger);border-color:rgba(229,72,77,.42);
  animation:shake .45s ease}
@keyframes pop{0%{transform:scale(.6);opacity:0}100%{transform:scale(1);opacity:1}}
@keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-4px)}
  75%{transform:translateX(4px)}}
.done svg{width:34px;height:34px;overflow:visible}
.done .ring{fill:none;stroke:var(--ok);stroke-width:2.4;stroke-linecap:round;
  stroke-dasharray:145;stroke-dashoffset:145;transform:rotate(-90deg);transform-origin:center;
  animation:draw .65s ease forwards}
.done .tick{fill:none;stroke:var(--ok);stroke-width:3.2;stroke-linecap:round;stroke-linejoin:round;
  stroke-dasharray:44;stroke-dashoffset:44;animation:draw .35s .5s ease forwards}
@keyframes draw{to{stroke-dashoffset:0}}
.kv{margin-top:14px;font-size:12px;color:var(--muted);line-height:1.9}
.kv b{color:var(--text);font-weight:600}
/* ---- 底部 ---- */
.disc{margin-top:10px;font-size:10.5px;color:var(--muted);line-height:1.6;flex:0 0 auto}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <!-- 启动检测 -->
    <section class="page on" id="p-boot">
      <div class="boot">
        <div class="cube-cell">
          <div class="cube"><i></i><i></i><i></i><i></i><i></i><i></i></div>
          <div class="cube-shadow"></div>
        </div>
        <div class="boot-t" id="bootTitle">正在检测依赖</div>
        <div class="boot-s" id="bootSub">准备运行环境…</div>
      </div>
    </section>
    <!-- 欢迎 / 选位置 -->
    <section class="page" id="p-welcome">
      <h1 class="big"><span class="dot"></span>安装 E听说助手</h1>
      <p class="lead">选择安装位置，安装程序会把所有文件复制到该目录，并在桌面创建快捷方式。<br>已安装过的目录可直接覆盖升级。</p>

      <div class="sect">
        <div class="lab">安装位置</div>
        <div class="row">
          <input type="text" id="path" spellcheck="false">
          <button class="btn ghost" onclick="cmd('browse')">浏览…</button>
        </div>
        <div class="info" id="info"></div>
      </div>

      <div class="sect">
        <label class="chk"><input type="checkbox" id="optDesk" checked>
          <span><span class="t">创建桌面快捷方式</span>
          <span class="d">安装完成后在桌面生成「E听说助手」图标。</span></span></label>
        <label class="chk"><input type="checkbox" id="optMenu" checked>
          <span><span class="t">创建开始菜单快捷方式</span>
          <span class="d">在「开始 → 所有程序」中加入入口。</span></span></label>
        <label class="chk"><input type="checkbox" id="optDeps" checked>
          <span><span class="t">安装 Python 依赖</span>
          <span class="d">自动执行 pip install -r requirements.txt（首次运行必需，约几分钟）。</span></span></label>
      </div>

      <div class="actions">
        <button class="btn" id="btnInstall" onclick="doInstall()">立即安装</button>
        <button class="btn ghost" id="btnUninstOld" style="display:none" onclick="cmd('uninstall')">卸载旧版本</button>
        <div class="spacer"></div>
      </div>
    </section>

    <!-- 进度 -->
    <section class="page" id="p-run">
      <div class="cube-stage">
        <div class="cube-cell">
          <div class="cube"><i></i><i></i><i></i><i></i><i></i><i></i></div>
          <div class="cube-shadow"></div>
        </div>
        <div>
          <h1 class="big" id="runTitle">正在安装…</h1>
          <p class="lead" id="runLead">请不要关闭本窗口。</p>
        </div>
      </div>
      <div class="bar"><i id="bar"></i></div>
      <div class="ptext"><span id="pmsg">准备中…</span><span id="ppct">0%</span></div>
      <div class="term">
        <div class="term-bar"><i></i><i></i><i></i><span>安装日志</span>
          <div class="spacer"></div><span class="el" id="elapsed">00:00</span></div>
        <div class="log" id="log"></div>
      </div>
      <div class="actions">
        <button class="btn" id="btnRunDone" style="display:none" onclick="cmd('finish')">完成</button>
      </div>
    </section>

    <!-- 完成 -->
    <section class="page" id="p-done">
      <div class="done" id="doneIcon"></div>
      <h1 class="big" id="doneTitle" style="margin-top:16px">安装完成</h1>
      <p class="lead" id="doneText">现在可以从桌面快捷方式启动 E听说助手。</p>
      <div class="kv" id="doneKv"></div>
      <div class="actions">
        <button class="btn ok" id="btnLaunch" onclick="cmd('launch')">立即启动</button>
        <button class="btn ghost" id="btnOpen" onclick="cmd('open')">打开安装目录</button>
        <div class="spacer"></div>
        <button class="btn" onclick="cmd('exit')">完成</button>
      </div>
    </section>

    <!-- 已安装 -->
    <section class="page" id="p-installed">
      <h1 class="big"><span class="dot"></span>已安装 E听说助手</h1>
      <p class="lead">检测到本机已经安装过本程序，你可以启动、修复或卸载它。</p>
      <div class="kv" id="insKv"></div>
      <div class="actions">
        <button class="btn ok" onclick="cmd('launch')">启动</button>
        <button class="btn ghost" onclick="cmd('open')">打开安装目录</button>
        <button class="btn ghost" onclick="cmd('repair')">修复 / 覆盖安装</button>
        <div class="spacer"></div>
        <button class="btn danger" onclick="cmd('uninstall')">卸载</button>
      </div>
    </section>

    <!-- 卸载确认 -->
    <section class="page" id="p-uninst">
      <div class="done bad">!</div>
      <h1 class="big" style="margin-top:16px"><span class="dot"></span>确认卸载？</h1>
      <p class="lead">将删除安装目录中的全部文件、桌面与开始菜单快捷方式，并移除卸载注册项。<br>此操作不可撤销。</p>
      <div class="kv" id="unKv"></div>
      <div class="actions">
        <button class="btn danger" onclick="cmd('doUninstall')">确认卸载</button>
        <div class="spacer"></div>
        <button class="btn ghost" onclick="cmd('back')">取消</button>
      </div>
    </section>
  </div>

  <p class="disc">注意：本工具仅供个人技术研究与逆向工程教学用途，严禁用于考试作弊或侵犯软件权益；使用者须自行承担全部责任。</p>
</div>

<script>
var curPath = "";
/* 命令通道：Chromium 会静默丢弃未注册的 app:// scheme 导航，
   因此改用 console.log 把命令送回 Python（QWebEnginePage.javaScriptConsoleMessage）。 */
function cmd(u){
  var sep = (u.indexOf("?") >= 0) ? "&" : "?";
  console.log("ETS_CMD::" + u + sep + "_t=" + Date.now());
}
function doInstall(){
  var p = document.getElementById("path").value;
  var o = function(id){ return document.getElementById(id).checked ? 1 : 0; };
  cmd("install?path=" + encodeURIComponent(p)
      + "&desk=" + o("optDesk") + "&menu=" + o("optMenu") + "&deps=" + o("optDeps"));
}
function setTheme(light){ document.body.classList.toggle("light", light); }
function show(id){
  document.querySelectorAll(".page").forEach(function(e){ e.classList.remove("on"); });
  document.getElementById(id).classList.add("on");
}
function boot(t, s){
  if(t != null) document.getElementById("bootTitle").textContent = t;
  if(s != null) document.getElementById("bootSub").textContent = s;
}
function setPath(p){ curPath = p; document.getElementById("path").value = p; }
function setInfo(html){ document.getElementById("info").innerHTML = html; }
function setRunTitle(t){ document.getElementById("runTitle").textContent = t; }
function setRunLead(t){ document.getElementById("runLead").textContent = t; }
function progress(pct, msg){
  document.getElementById("bar").style.width = pct + "%";
  document.getElementById("ppct").textContent = pct + "%";
  document.getElementById("pmsg").textContent = msg;
  if(pct > 0 && !timerId) startTimer();
  if(pct >= 100) stopTimer();
}
/* 耗时计时器 */
var timerId = null, t0 = 0;
function startTimer(){ t0 = Date.now(); stopTimer(); timerId = setInterval(tickTimer, 500); tickTimer(); }
function stopTimer(){ if(timerId){ clearInterval(timerId); timerId = null; } }
function tickTimer(){
  var s = Math.floor((Date.now() - t0) / 1000);
  var m = Math.floor(s / 60), r = s % 60;
  var e = document.getElementById("elapsed");
  if(e) e.textContent = (m < 10 ? "0" : "") + m + ":" + (r < 10 ? "0" : "") + r;
}
function log(msg, clear){
  var el = document.getElementById("log");
  if(clear) el.textContent = "";
  el.textContent += msg + "\n";
  el.scrollTop = el.scrollHeight;
}
function clearLog(){
  document.getElementById("log").textContent = "";
  document.getElementById("bar").style.width = "0%";
  document.getElementById("ppct").textContent = "0%";
  stopTimer();
  tickTimer();
}
function runDone(show){
  document.getElementById("btnRunDone").style.display = show ? "" : "none";
}
var TICK_SVG = '<svg viewBox="0 0 52 52">'
  + '<circle class="ring" cx="26" cy="26" r="23"></circle>'
  + '<path class="tick" d="M15 27 l7.5 7.5 L37 19.5"></path></svg>';
function setDone(kind, title, text, kv, canLaunch, showOpen){
  stopTimer();
  var ic = document.getElementById("doneIcon");
  /* 重置动画：清空 -> 强制重排 -> 重设内容 */
  ic.style.animation = "none";
  ic.innerHTML = "";
  void ic.offsetWidth;
  ic.style.animation = "";
  ic.className = "done" + (kind === "ok" ? "" : " bad");
  ic.innerHTML = (kind === "ok") ? TICK_SVG : "!";
  document.getElementById("doneTitle").textContent = title;
  document.getElementById("doneText").textContent = text;
  document.getElementById("doneKv").innerHTML = kv;
  document.getElementById("btnLaunch").style.display = canLaunch ? "" : "none";
  document.getElementById("btnOpen").style.display = showOpen ? "" : "none";
  show("p-done");
}
function setInstalled(kv){ document.getElementById("insKv").innerHTML = kv; show("p-installed"); }
function setInstalledKv(kv){ document.getElementById("insKv").innerHTML = kv; }
function setUninstKv(kv){ document.getElementById("unKv").innerHTML = kv; show("p-uninst"); }
function busy(on){
  document.getElementById("btnInstall").disabled = on;
}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Qt 界面（WebEngine 版）
# ---------------------------------------------------------------------------

QT_OK = False
try:
    from PyQt5.QtCore import (Qt, QUrl, QUrlQuery, QObject, pyqtSignal, QTimer)
    from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                 QHBoxLayout, QLabel, QPushButton, QLineEdit,
                                 QFileDialog, QTextEdit, QProgressBar, QCheckBox,
                                 QMessageBox, QFrame)
    from PyQt5.QtGui import QFont, QCursor, QMouseEvent
    QT_OK = True
except Exception as e:
    _safe_print("[警告] 未找到 PyQt5，将使用控制台模式：", e)

WEBENGINE_OK = False
if QT_OK:
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
        WEBENGINE_OK = True
    except Exception as e:
        _safe_print("[警告] 未找到 PyQtWebEngine，回退原生界面：", e)
dlog("WEBENGINE_OK=%s frozen=%s" % (WEBENGINE_OK, is_frozen()))


CMD_PREFIX = "ETS_CMD::"


class Bridge(QObject):
    """工作线程 -> UI 线程 的信号桥（跨线程 emit 是安全的）。"""
    log = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    done = pyqtSignal(bool, str)
    invoke = pyqtSignal(object)   # 在 UI 线程执行一段回调


class CommandPage(QWebEnginePage if WEBENGINE_OK else object):
    """JS -> Python 命令通道（走 console.log，避免自定义 scheme 被丢弃）。"""

    command = pyqtSignal(str) if WEBENGINE_OK else None

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if isinstance(message, str) and message.startswith(CMD_PREFIX):
            self.command.emit(message[len(CMD_PREFIX):])
            return
        return super().javaScriptConsoleMessage(level, message,
                                                lineNumber, sourceID)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        # 兜底：拦掉 app:// 命令导航（首页 base 导航 path 为空，需放行）
        try:
            if url.scheme() == "app" and url.path().strip("/"):
                return False
        except Exception:
            pass
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class TitleBar(QWidget):
    """自绘标题栏：品牌区 + 主题切换 + 最小化 / 关闭 + 可拖动。"""

    def __init__(self, win):
        super().__init__(win)
        self._win = win
        self._off = None
        self.setFixedHeight(46)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 0, 8, 0)
        lay.setSpacing(10)

        self.mark = QLabel("ET")
        self.mark.setFixedSize(28, 28)
        self.mark.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.mark)

        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = QLabel("E听说助手 · 安装程序")
        self.sub = QLabel("v" + APP_VERSION)
        col.addWidget(self.title)
        col.addWidget(self.sub)
        lay.addLayout(col)
        lay.addStretch(1)

        self.theme_btn = QPushButton("深 / 浅")
        self.theme_btn.setFixedHeight(26)
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.theme_btn)

        self.btn_min = QPushButton("—")
        self.btn_close = QPushButton("✕")
        for b in (self.btn_min, self.btn_close):
            b.setFixedSize(32, 26)
            b.setCursor(Qt.PointingHandCursor)
            lay.addWidget(b)
        self.btn_min.clicked.connect(win.showMinimized)
        self.btn_close.clicked.connect(win.close)
        self.apply_theme(False)

    def apply_theme(self, light: bool):
        fg = "#101010" if light else "#f2f2f2"
        sub = "#6b6b6b" if light else "#8b8b8b"
        hover = "rgba(0,0,0,.08)" if light else "rgba(255,255,255,.12)"
        mark = ("background:linear-gradient(145deg,#222,#555);color:#fff"
                if light else
                "background:linear-gradient(145deg,#fff,#b9b9b9);color:#111")
        self.setStyleSheet(f"TitleBar{{background:{'#f2f2f3' if light else '#0a0a0a'}}}")
        self.mark.setStyleSheet(
            mark + ";border-radius:8px;font:700 11px 'Segoe UI';"
                   "qproperty-alignment:AlignCenter")
        self.title.setStyleSheet(f"color:{fg};font-size:12.5px;font-weight:600")
        self.sub.setStyleSheet(f"color:{sub};font-size:10.5px")
        self.theme_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:1px solid "
            f"{'rgba(0,0,0,.14)' if light else 'rgba(255,255,255,.16)'};"
            f"color:{fg};border-radius:8px;font-size:11px;padding:0 10px}}"
            f"QPushButton:hover{{background:{hover}}}")
        self.btn_min.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;color:{fg};font-size:12px}}"
            f"QPushButton:hover{{background:{hover};border-radius:6px}}")
        self.btn_close.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;color:{fg};font-size:13px}}"
            "QPushButton:hover{background:#e5484d;color:#fff;border-radius:6px}")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._off = e.globalPos() - self._win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._off is not None and e.buttons() & Qt.LeftButton:
            self._win.move(e.globalPos() - self._off)

    def mouseReleaseEvent(self, e):
        self._off = None


class InstallerWindow(QMainWindow):
    WIDTH, HEIGHT = 760, 620

    def __init__(self):
        super().__init__()
        self.setWindowTitle("E听说助手 · 安装程序")
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet("QMainWindow{background:#0a0a0a}")
        self.resize(self.WIDTH, self.HEIGHT)

        self.bridge = Bridge()
        self.bridge.log.connect(self.ui_log)
        self.bridge.progress.connect(self.ui_progress)
        self.bridge.done.connect(self.on_finish)
        self.bridge.invoke.connect(self.run_in_ui)

        # 回调全部走信号：Installer 在工作线程运行，禁止跨线程调用 runJavaScript
        self.installer = Installer(log=self.bridge.log.emit,
                                   progress=self.bridge.progress.emit)

        self.installed = self.detect_install()
        self.ready = False
        self._pending = []
        self._mode = "install"
        self._last_dir = ""
        self._last_path = (self.installed or {}).get("InstallLocation", "")

        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.light = False
        self.bar = TitleBar(self)
        self.bar.theme_btn.clicked.connect(self.toggle_theme)
        lay.addWidget(self.bar)

        self.view = QWebEngineView()
        self.page = CommandPage(self.view)
        self.page.command.connect(self.handle_command)
        self.view.setPage(self.page)
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        self.view.page().setBackgroundColor(Qt.transparent)
        self.view.loadFinished.connect(self.on_loaded)
        self.view.setHtml(HTML, QUrl("app://local/"))
        lay.addWidget(self.view, 1)

    # ---------------- JS 调用 ----------------
    def js(self, code: str):
        if self.ready:
            self.view.page().runJavaScript(code)
        else:
            self._pending.append(code)

    def call(self, fn: str, *args):
        params = ", ".join(json.dumps(a, ensure_ascii=False) for a in args)
        self.js(f"{fn}({params});")

    def toggle_theme(self):
        self.light = not self.light
        self.bar.apply_theme(self.light)
        self.setStyleSheet("QMainWindow{background:%s}"
                           % ("#f2f2f3" if self.light else "#0a0a0a"))
        self.call("setTheme", self.light)

    def on_loaded(self, ok=True):
        self.ready = True
        default = self.installed.get("InstallLocation") if self.installed else \
            os.path.join(special_folder("LocalApplicationData"), APP_ID)
        self.call("setPath", default)
        self.refresh_info(default)
        if self.installed:
            info = self.installed
            kv = (f"安装位置：<b>{info.get('InstallLocation','')}</b><br>"
                  f"版本：<b>{info.get('DisplayVersion','-')}</b>　"
                  f"安装日期：<b>{info.get('InstallDate','-')}</b><br>"
                  f"占用空间：<b>{human_size(dir_size(info.get('InstallLocation','')))}</b>")
            self.call("setInstalledKv", kv)
        for code in self._pending:
            self.view.page().runJavaScript(code)
        self._pending = []
        try:
            _lst = ", ".join(sorted(os.listdir(SOURCE_DIR)))
        except Exception:
            _lst = "(list fail)"
        dlog("on_loaded ready; installed=%s SOURCE_DIR=%s payload=[%s]"
             % (bool(self.installed), SOURCE_DIR, _lst))
        self.start_boot()

    # ---------------- 启动检测动画（5~9 秒）----------------
    def start_boot(self):
        steps = [
            (0,    "正在检测依赖", "准备运行环境…"),
            (1200, "正在检测依赖", "检查 Python 运行环境…"),
            (2600, "正在检测依赖", "验证界面组件 (PyQt5)…"),
            (4000, "正在检测依赖", "检查桌面组件 (pywin32)…"),
        ]
        self._boot_timers = []
        for dt, t, s in steps:
            tm = QTimer(self)
            tm.setSingleShot(True)
            tm.timeout.connect(lambda t=t, s=s: self.call("boot", t, s))
            tm.start(dt)
            self._boot_timers.append(tm)
        self._boot_timer = QTimer(self)
        self._boot_timer.setSingleShot(True)
        self._boot_timer.timeout.connect(self.finish_boot)
        self._boot_timer.start(5000 + random.randint(0, 4000))  # 5~9 秒
        dlog("start_boot scheduled")

    def finish_boot(self):
        if not self.isVisible():
            return
        try:
            if self.installed:
                self.call("setInstalledKv", self.installed_kv())
                self.call("show", "p-installed")
                dlog("finish_boot -> p-installed")
            else:
                self.call("show", "p-welcome")
                dlog("finish_boot -> p-welcome")
        except Exception:
            pass

    # ---------------- UI 回调 ----------------
    def ui_log(self, msg: str):
        self.call("log", str(msg), False)

    def ui_progress(self, pct: int, text: str):
        self.call("progress", int(pct), str(text))

    def on_finish(self, ok: bool, msg: str):
        self.call("runDone", True)

    # ---------------- 命令派发 ----------------
    def run_in_ui(self, fn):
        """在 UI 线程执行回调（供工作线程通过 bridge.invoke 使用）。"""
        try:
            fn()
        except Exception as e:
            _safe_print("[UI] 回调出错:", e)

    def handle_command(self, cmd: str):
        url = QUrl("app://local/" + cmd)
        path = url.path().strip("/")
        q = QUrlQuery(url)

        def arg(k, default=""):
            v = q.queryItemValue(k)
            return urllib.parse.unquote(v) if v else default

        def flag(k):
            return q.queryItemValue(k) == "1"

        if path == "browse":
            start = arg("path") or self._last_dir or \
                os.path.join(special_folder("LocalApplicationData"), APP_ID)
            d = QFileDialog.getExistingDirectory(self, "选择安装位置", start)
            if d:
                self.call("setPath", d)
                self.refresh_info(d)
        elif path == "install":
            dest = arg("path").strip()
            self.do_install(dest, {"desk": flag("desk"), "menu": flag("menu"),
                                   "deps": flag("deps")})
        elif path == "uninstall":
            self.show_uninstall_confirm()
        elif path == "doUninstall":
            self.do_uninstall()
        elif path == "repair":
            dest = (self.installed or {}).get("InstallLocation", "")
            self.do_install(dest, {"desk": True, "menu": True, "deps": False})
        elif path == "launch":
            self.launch()
        elif path == "open":
            self.open_dir((self.installed or {}).get("InstallLocation", "")
                          or arg("path") or self._last_path)
        elif path == "back":
            if self.installed:
                self.call("setInstalled", self.installed_kv())
            else:
                self.call("show", "p-welcome")
        elif path == "finish":
            self.call("show", "p-done")
        elif path == "exit":
            self.close()

    # ---------------- 业务逻辑 ----------------
    def detect_install(self):
        info = reg_read()
        if not info:
            return None
        loc = info.get("InstallLocation", "")
        if loc and os.path.isdir(os.path.join(loc, "ets_assistant")):
            return info
        # 记录存在但文件已不在 -> 清理残留
        reg_remove()
        return None

    def installed_kv(self) -> str:
        info = self.installed or {}
        return (f"安装位置：<b>{info.get('InstallLocation','')}</b><br>"
                f"版本：<b>{info.get('DisplayVersion','-')}</b>　"
                f"安装日期：<b>{info.get('InstallDate','-')}</b>")

    def refresh_info(self, path: str):
        need = dir_size(SOURCE_DIR)
        try:
            drive = os.path.splitdrive(os.path.abspath(path))[0] or "C:"
            free = shutil.disk_usage(drive + os.sep).free
            free_txt = human_size(free)
        except Exception:
            free_txt = "未知"
        self.call("setInfo", f"所需空间 <b>{human_size(need)}</b>　"
                             f"可用空间 <b>{free_txt}</b>")

    def do_install(self, dest: str, opts: dict):
        if not dest:
            QMessageBox.warning(self, "提示", "请先选择安装位置。")
            return
        self._mode = "install"
        self._last_path = os.path.abspath(dest)
        self.call("busy", True)
        self.call("setRunTitle", "正在安装…")
        self.call("setRunLead", "正在复制文件，请不要关闭本窗口。")
        self.call("clearLog")
        self.call("progress", 0, "准备中…")
        self.call("runDone", False)
        self.call("show", "p-run")
        threading.Thread(target=self._worker_install, args=(dest, opts),
                         daemon=True).start()

    def _worker_install(self, dest, opts):
        ok = self.installer.install(dest, opts)
        self.installed = self.detect_install()

        def done():
            self.call("busy", False)
            if ok:
                kv = (f"安装位置：<b>{os.path.abspath(dest)}</b><br>"
                      f"快捷方式：<b>桌面「{APP_NAME}」</b>")
                self.call("setDone", "ok", "安装完成",
                          "现在可以从桌面快捷方式启动 E听说助手。", kv, True, True)
            else:
                self.call("setDone", "bad", "安装失败",
                          "请查看日志中的错误信息后重试。", "", False, False)

        self.bridge.invoke.emit(done)

    def show_uninstall_confirm(self):
        info = self.installed or {}
        if not info:
            self.call("setDone", "bad", "未检测到安装",
                      "本机没有找到已安装的 E听说助手。", "", False, False)
            return
        kv = (f"安装位置：<b>{info.get('InstallLocation','')}</b><br>"
              f"占用空间：<b>{human_size(dir_size(info.get('InstallLocation','')))}</b>")
        self.call("setUninstKv", kv)

    def do_uninstall(self):
        self._mode = "uninstall"
        self.call("setRunTitle", "正在卸载…")
        self.call("setRunLead", "正在删除文件，请不要关闭本窗口。")
        self.call("clearLog")
        self.call("progress", 0, "准备中…")
        self.call("runDone", False)
        self.call("show", "p-run")
        threading.Thread(target=self._worker_uninstall, daemon=True).start()

    def _worker_uninstall(self):
        ok = self.installer.uninstall(self.installed or {})
        self.installed = None

        def done():
            if ok:
                self.call("setDone", "ok", "卸载完成",
                          "E听说助手已从本机移除，感谢使用。", "", False, False)
            else:
                self.call("setDone", "bad", "卸载基本完成",
                          "部分文件被占用，重启后将自动删除。", "", False, False)

        self.bridge.invoke.emit(done)

    def launch(self):
        dest = (self.installed or {}).get("InstallLocation", "")
        t = resolve_launch_target(dest) if dest else None
        if not t:
            QMessageBox.information(self, "提示", "未找到可启动的程序。")
            return
        exe, args, workdir = t
        try:
            subprocess.Popen(f'"{exe}" {args}'.strip(), cwd=workdir,
                             shell=True, startupinfo=_si(), close_fds=True)
        except Exception as e:
            QMessageBox.warning(self, "启动失败", str(e))

    def open_dir(self, path: str):
        if path and os.path.isdir(path):
            try:
                subprocess.Popen(["explorer", os.path.normpath(path)],
                                 startupinfo=_si(), close_fds=True)
            except Exception:
                pass

    def closeEvent(self, e):
        for tm in getattr(self, "_boot_timers", []):
            tm.stop()
        getattr(self, "_boot_timer", None) and self._boot_timer.stop()
        self.installer.cancel()
        super().closeEvent(e)


# ---------------------------------------------------------------------------
# 回退：原生 Qt 界面（无 WebEngine 时）
# ---------------------------------------------------------------------------

class SimpleWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("E听说助手 · 安装程序")
        self.resize(620, 480)
        self.setStyleSheet("""
          QMainWindow{background:#121212}
          QWidget{color:#f2f2f2;font-family:"Microsoft YaHei UI";font-size:12px}
          QLineEdit{background:#1c1c1c;border:1px solid #333;border-radius:8px;
                    padding:7px 10px;color:#f2f2f2}
          QPushButton{background:#ffffff;color:#111;border:none;border-radius:8px;
                      padding:8px 18px;font-weight:600}
          QPushButton[flat="true"]{background:#2a2a2a;color:#f2f2f2;font-weight:400}
          QTextEdit{background:#0d0d0d;border:1px solid #2a2a2a;border-radius:8px;
                    color:#cfcfcf;font-family:Consolas;font-size:11px}
          QProgressBar{background:#1c1c1c;border:1px solid #2a2a2a;border-radius:6px;
                       height:10px;color:transparent}
          QProgressBar::chunk{background:#ffffff;border-radius:6px}
        """)
        self.bridge = Bridge()
        self.bridge.log.connect(self.ui_log)
        self.bridge.progress.connect(self.ui_progress)
        self.bridge.invoke.connect(self.run_in_ui)
        self.installer = Installer(log=self.bridge.log.emit,
                                   progress=self.bridge.progress.emit)
        self.installed = None
        try:
            info = reg_read()
            if info and os.path.isdir(os.path.join(
                    info.get("InstallLocation", ""), "ets_assistant")):
                self.installed = info
        except Exception:
            pass

        c = QWidget()
        self.setCentralWidget(c)
        lay = QVBoxLayout(c)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        lay.addWidget(QLabel("<h2 style='margin:0'>E听说助手 · 安装程序</h2>"))
        row = QHBoxLayout()
        self.edit = QLineEdit(os.path.join(
            special_folder("LocalApplicationData"), APP_ID))
        b = QPushButton("浏览…")
        b.setFlat(True)
        b.clicked.connect(self.browse)
        row.addWidget(self.edit, 1)
        row.addWidget(b)
        lay.addLayout(row)

        opts = QHBoxLayout()
        self.cb_desk, self.cb_menu, self.cb_deps = QCheckBox("桌面快捷方式"), \
            QCheckBox("开始菜单"), QCheckBox("安装依赖")
        for cb, v in ((self.cb_desk, True), (self.cb_menu, True), (self.cb_deps, True)):
            cb.setChecked(v)
            opts.addWidget(cb)
        opts.addStretch(1)
        lay.addLayout(opts)

        self.bar = QProgressBar()
        self.bar.setValue(0)
        lay.addWidget(self.bar)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        lay.addWidget(self.log_view, 1)

        brow = QHBoxLayout()
        self.btn_main = QPushButton("安装")
        self.btn_main.clicked.connect(self.on_main)
        self.btn_uninst = QPushButton("卸载")
        self.btn_uninst.setStyleSheet("background:#e5484d;color:#fff")
        self.btn_uninst.clicked.connect(self.on_uninstall)
        self.btn_open = QPushButton("打开目录")
        self.btn_open.setFlat(True)
        self.btn_open.clicked.connect(lambda: self.open_dir(self.edit.text()))
        brow.addWidget(self.btn_main)
        brow.addWidget(self.btn_uninst)
        brow.addWidget(self.btn_open)
        brow.addStretch(1)
        lay.addLayout(brow)

        if self.installed:
            self.edit.setText(self.installed.get("InstallLocation", ""))
            self.btn_main.setText("修复 / 覆盖安装")
            self.ui_log(f"检测到已安装：{self.installed.get('InstallLocation','')}")

    def browse(self):
        d = QFileDialog.getExistingDirectory(self, "选择安装位置", self.edit.text())
        if d:
            self.edit.setText(d)

    def ui_log(self, msg):
        self.log_view.append(str(msg))

    def ui_progress(self, pct, text=""):
        self.bar.setValue(int(pct))

    def on_main(self):
        dest = self.edit.text().strip()
        if not dest:
            return
        self.btn_main.setEnabled(False)
        opts = {"desk": self.cb_desk.isChecked(), "menu": self.cb_menu.isChecked(),
                "deps": self.cb_deps.isChecked()}
        threading.Thread(target=self._run, args=(dest, opts), daemon=True).start()

    def run_in_ui(self, fn):
        try:
            fn()
        except Exception as e:
            _safe_print("[UI] 回调出错:", e)

    def _run(self, dest, opts):
        self.installer.install(dest, opts)

        def done():
            self.btn_main.setEnabled(True)
            self.ui_log("完成。")

        self.bridge.invoke.emit(done)

    def on_uninstall(self):
        if QMessageBox.question(self, "确认", "确定要卸载 E听说助手吗？") != QMessageBox.Yes:
            return
        info = self.installed or {"InstallLocation": self.edit.text()}
        self.btn_uninst.setEnabled(False)

        def work():
            self.installer.uninstall(info)

            def done():
                self.installed = None
                self.btn_uninst.setEnabled(True)
                self.btn_main.setText("安装")
                self.ui_log("卸载完成。")

            self.bridge.invoke.emit(done)

        threading.Thread(target=work, daemon=True).start()

    def open_dir(self, path):
        if os.path.isdir(path):
            subprocess.Popen(["explorer", os.path.normpath(path)],
                             startupinfo=_si(), close_fds=True)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    if not QT_OK:
        # 极简控制台模式
        print("=" * 60)
        print(f"{APP_NAME} 安装程序（控制台模式）")
        print("=" * 60)
        info = reg_read()
        if info and os.path.isdir(os.path.join(info.get("InstallLocation", ""),
                                               "ets_assistant")):
            loc = info["InstallLocation"]
            ans = input(f"检测到已安装于 {loc}，输入 y 卸载，其它键覆盖安装：")
            ins = Installer()
            if ans.strip().lower() == "y":
                ins.uninstall(info)
            else:
                ins.install(loc, {"desk": True, "menu": True, "deps": True})
        else:
            default = os.path.join(special_folder("LocalApplicationData"), APP_ID)
            dest = input(f"安装位置（回车使用 {default}）：").strip() or default
            Installer().install(dest, {"desk": True, "menu": True, "deps": True})
        input("按回车键退出…")
        return

    try:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    win = InstallerWindow() if WEBENGINE_OK else SimpleWindow()
    win.show()
    dlog("window shown; entering event loop")
    sys.exit(app.exec_())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        dlog("FATAL: " + traceback.format_exc())
        raise
