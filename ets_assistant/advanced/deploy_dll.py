# =============================================================================
#  deploy_dll.py  ——  winmm.dll 劫持部署 / 卸载工具（实验性 / 高风险）
#
#  ⚠️ 免责声明：
#  本脚本用于协助部署 / 卸载 winmm.dll 劫持模块，仅供个人技术研究与逆向教学。
#  严禁用于考试作弊、侵犯软件权益或任何违法违规用途。使用者须自行承担一切
#  法律与纪律责任。运行本脚本即表示你已充分理解并同意上述免责条款。
#
#  使用：
#    python deploy_dll.py deploy   <编译好的 winmm.dll 路径>
#    python deploy_dll.py uninstall
#  需以管理员身份运行（要写入 C:\Program Files (x86)\ETS\）。
# =============================================================================

import sys
import os
import shutil
import ctypes

ETS_DIR = r"C:\Program Files (x86)\ETS"
BACKUP_NAME = "winmm_orig_backup.dll"


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def confirm_risk() -> bool:
    print("=" * 60)
    print("⚠️  高风险操作警告")
    print("本操作将部署/修改 E听说 目录下的 winmm.dll（DLL 劫持）。")
    print("可能造成：杀软拦截、软件异常、违反软件协议、成绩/账号风险。")
    print("仅限个人技术研究，严禁作弊用途。作者不承担责任。")
    print("=" * 60)
    ans = input("输入 'YES_I_UNDERSTAND' 以确认你已阅读并承担全部风险：").strip()
    return ans == "YES_I_UNDERSTAND"


def deploy(dll_path: str, auto_confirm: bool = False):
    if not os.path.isfile(dll_path):
        print(f"[错误] 找不到 DLL: {dll_path}")
        return
    if not is_admin():
        print("[错误] 请以管理员身份运行本脚本。")
        return
    if not auto_confirm and not confirm_risk():
        print("[取消] 未确认风险，已退出。")
        return
    os.makedirs(ETS_DIR, exist_ok=True)

    # 劫持 DLL
    target = os.path.join(ETS_DIR, "winmm.dll")
    # 如果 ETS 目录里原本就存在 winmm.dll（极罕见），先备份
    if os.path.isfile(target):
        backup = os.path.join(ETS_DIR, BACKUP_NAME)
        if not os.path.isfile(backup):
            shutil.copy2(target, backup)
            print(f"[备份] 原 winmm 已备份为 {backup}")
    shutil.copy2(dll_path, target)

    # 转发目标：System32 的 winmm.dll -> ETS 目录的 winmm_orig.dll
    orig_target = os.path.join(ETS_DIR, "winmm_orig.dll")
    sys_winmm = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "winmm.dll")
    sys_winmm_syswow = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "SysWOW64", "winmm.dll")
    src_orig = sys_winmm_syswow if os.path.exists(sys_winmm_syswow) else sys_winmm
    if os.path.exists(src_orig):
        shutil.copy2(src_orig, orig_target)
        print(f"[转发目标] 已拷贝 {src_orig} -> {orig_target}")
    else:
        print(f"[警告] 未找到系统 winmm.dll，转发目标可能缺失: {src_orig}")

    print(f"[完成] 已部署劫持 DLL 到 {target}")
    print("重启 E听说 后生效。如需恢复，运行本脚本 uninstall。")


def uninstall():
    if not is_admin():
        print("[错误] 请以管理员身份运行本脚本。")
        return
    target = os.path.join(ETS_DIR, "winmm.dll")
    orig_target = os.path.join(ETS_DIR, "winmm_orig.dll")
    backup = os.path.join(ETS_DIR, BACKUP_NAME)

    restored = False
    if os.path.isfile(backup):
        shutil.move(backup, target)
        restored = True
        print("[完成] 已从备份恢复原始 winmm.dll。")

    # 删除劫持 DLL 与转发目标
    if os.path.isfile(target) and not restored:
        os.remove(target)
        print(f"[完成] 已删除劫持 DLL: {target}")
    if os.path.isfile(orig_target):
        os.remove(orig_target)
        print(f"[完成] 已删除转发目标: {orig_target}")

    if not os.path.isfile(target) and not os.path.isfile(orig_target):
        print("[提示] 已清理 ETS 目录下的 winmm.dll / winmm_orig.dll。")
    else:
        print("[提示] 部分文件仍在，请检查权限。")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1].lower()
    if cmd == "deploy":
        if len(sys.argv) < 3:
            print("[错误] 需提供编译好的 winmm.dll 路径。")
            return
        deploy(sys.argv[2])
    elif cmd == "uninstall":
        uninstall()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
