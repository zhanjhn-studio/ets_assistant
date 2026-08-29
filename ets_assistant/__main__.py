"""
E听说自动化辅助工具 - 启动入口

⚠️ 免责声明：本项目仅供个人技术研究与逆向工程教学。其中的 Python 自动化模块与
C++ winmm.dll 劫持模块（advanced/）可能干预 E听说 评分/计时逻辑，存在违反软件
协议、学校纪律及法律法规的风险。使用者须自行承担全部责任，严禁用于考试作弊。
作者不对任何使用后果负责。若不同意，请立即删除本项目。
"""
import sys
import os

# 确保能 import 同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ⚠️ 默认使用 PyWebView 超级前端（WebEngine 渲染 + 前后端分离）。
# 如需退回原 PyQt5 界面，运行：python -m ets_assistant --qt
if "--qt" in sys.argv:
    from main_window import main
else:
    from webui.api import start_webui as main


if __name__ == "__main__":
    main()
