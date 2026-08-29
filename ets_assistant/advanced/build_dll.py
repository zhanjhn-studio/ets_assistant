# =============================================================================
#  build_dll.py  ——  winmm.dll 一键编译执行器（供 WebUI 后端调用）
#
#  ⚠️ 免责声明：本脚本仅用于编译「DLL 搜索顺序劫持」技术演示框架，
#  严禁用于考试作弊或侵犯软件权益。使用者自负一切责任。
#
#  流程：
#   1) 定位 MSVC 开发者命令环境（vswhere）
#   2) 校验 Detours（DETOURS_ROOT）
#   3) cmake 配置 + 构建（Release）
#   4) 产物 advanced/winmm.dll 与 winmm_orig.dll 已就绪
#
#  也可单独运行：python build_dll.py
# =============================================================================

import os
import sys
import subprocess
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))


def log(msg):
    print(msg, flush=True)


def find_vs_dev_bat():
    """用 vswhere 找 VS 2022 的 vcvars64.bat。"""
    try:
        out = subprocess.check_output(
            [r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe",
             "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
             "-property", "installationPath"],
            text=True,
        ).strip()
    except Exception:
        return None
    if not out:
        return None
    cand = os.path.join(out, "VC", "Auxiliary", "Build", "vcvars64.bat")
    return cand if os.path.exists(cand) else None


def build():
    # --- 环境校验 ---
    detours = os.environ.get("DETOURS_ROOT", "")
    if not detours or not os.path.exists(os.path.join(detours, "include", "detours", "detours.h")):
        log("[错误] 未设置有效的 DETOURS_ROOT（指向 Detours 根目录，含 include/detours/detours.h）。")
        log("安装：git clone https://github.com/microsoft/Detours && cd Detours && "
            "mkdir build && cd build && cmake .. && cmake --build . --config Release")
        return False

    dev_bat = find_vs_dev_bat()
    if not dev_bat:
        log("[错误] 未找到 VS2022 vcvars64.bat，请安装『使用 C++ 的桌面开发』工作负载。")
        return False

    build_dir = os.path.join(HERE, "build")
    os.makedirs(build_dir, exist_ok=True)

    # 用开发者命令提示符运行 cmake（确保 cl / link 在 PATH）
    cmd = (
        f'call "{dev_bat}" >nul && '
        f'cd /d "{build_dir}" && '
        f'cmake -S "{HERE}" -B "{build_dir}" && '
        f'cmake --build "{build_dir}" --config Release'
    )
    log("[构建] 启动 MSVC 开发者环境并编译...")
    ret = subprocess.run(cmd, shell=True)
    if ret.returncode != 0:
        log(f"[错误] 编译失败 (code={ret.returncode})")
        return False

    # 拷贝产物到 advanced/
    for name in ("winmm.dll", "winmm_orig.dll"):
        src = os.path.join(build_dir, "Release", name)
        if not os.path.exists(src):
            src = os.path.join(build_dir, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(HERE, name))
            log(f"[OK] 已生成 {name}")

    log("[完成] 编译成功。可回到界面点击『部署到 ETS 目录』。")
    return True


if __name__ == "__main__":
    sys.exit(0 if build() else 1)
