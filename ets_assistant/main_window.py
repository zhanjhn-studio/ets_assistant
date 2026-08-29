r"""
E听说自动化辅助工具 - PyQt5 主界面（精美版）
功能：
  0. 环境检测 Dashboard（E听说进程 / 立体声混音 / 依赖 / 管理员 / 显示器）
  1. 自动跟读（OpenCV 模板匹配 + PyAutoGUI + PyAudio）
  2. 模板管理（截图按钮图片）
  3. 答案/试卷查看（读取 %Appdata%\ETS）
  4. 设置（静默阈值、采样率等）
  5. 高级模块说明（winmm.dll 劫持）
"""
import os
import sys
import time
import threading
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox,
    QFileDialog, QMessageBox, QListWidget, QProgressBar, QGroupBox, QFormLayout,
    QComboBox, QCheckBox, QFrame, QSizePolicy,
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QPixmap, QImage, QFont, QIcon

from automation import ETSHelper
from answer_reader import (
    get_ets_dir, list_papers, read_paper_info, search_papers,
)
from env_check import run_all_checks, check_ets_process, check_stereo_mix

# ====================== 样式（现代深色主题） ======================
STYLE = """
QMainWindow, QWidget {
    background-color: #1e1f2b;
    color: #e6e6e6;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
}
QTabWidget::pane {
    border: none;
    background: #1e1f2b;
}
QTabBar::tab {
    background: #2a2c3a;
    color: #9aa0b4;
    padding: 10px 18px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #3a3d52;
    color: #ffffff;
    font-weight: bold;
}
QTabBar::tab:hover { background: #34374a; }

QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #4f7cff, stop:1 #3b5bdb);
    color: white;
    border: none;
    border-radius: 8px;
    padding: 9px 18px;
    font-weight: bold;
}
QPushButton:hover { background: #5c8bff; }
QPushButton:pressed { background: #2f4bb0; }
QPushButton:disabled { background: #3a3d52; color: #6b7088; }

QPushButton#danger {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #ff6b6b, stop:1 #e03131);
}
QPushButton#danger:hover { background: #ff8787; }
QPushButton#ghost {
    background: transparent;
    border: 1px solid #4f7cff;
    color: #8fb0ff;
}
QPushButton#ghost:hover { background: #2a2c3a; }

QGroupBox {
    border: 1px solid #3a3d52;
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 10px;
    font-weight: bold;
    color: #b8c0e0;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }

QTextEdit, QLineEdit, QListWidget {
    background: #15161f;
    border: 1px solid #3a3d52;
    border-radius: 8px;
    color: #d6d9e6;
    padding: 6px;
}
QTextEdit { font-family: "Consolas", "Courier New", monospace; font-size: 12px; }

QSpinBox, QDoubleSpinBox, QComboBox {
    background: #15161f;
    border: 1px solid #3a3d52;
    border-radius: 6px;
    color: #e6e6e6;
    padding: 4px;
}
QComboBox QAbstractItemView { background: #15161f; selection-background-color: #4f7cff; }

QLabel#title { font-size: 22px; font-weight: bold; color: #ffffff; }
QLabel#subtitle { font-size: 12px; color: #8a90a8; }
QLabel#cardlabel { font-size: 13px; color: #b8c0e0; }
QLabel#cardval { font-size: 12px; color: #d6d9e6; }

QProgressBar {
    border: 1px solid #3a3d52;
    border-radius: 6px;
    background: #15161f;
    text-align: center;
    color: #ffffff;
}
QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #4f7cff,stop:1 #51cf66); border-radius: 5px; }

QFrame#card {
    background: #262838;
    border: 1px solid #3a3d52;
    border-radius: 12px;
}
QCheckBox { color: #b8c0e0; spacing: 6px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; background: #15161f; }
QCheckBox::indicator:checked { background: #4f7cff; }
"""


# -------------------- 工作线程 --------------------
class AutomationWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal()

    def __init__(self, helper: ETSHelper):
        super().__init__()
        self.helper = helper

    def run(self):
        self.helper.log = self.log_signal.emit
        self.helper.progress = self.progress_signal.emit
        try:
            self.helper.run()
        except Exception as e:
            self.log_signal.emit(f"[异常] {e}")
        finally:
            self.finished_signal.emit()


class EnvCheckWorker(QThread):
    """后台执行环境检测，避免 PowerShell 调用阻塞界面。"""
    result_signal = pyqtSignal(dict)

    def run(self):
        try:
            res = run_all_checks()
        except Exception as e:
            res = {"error": str(e)}
        self.result_signal.emit(res)


# -------------------- 状态指示灯 --------------------
def make_status_dot(color: str) -> QLabel:
    dot = QLabel()
    dot.setFixedSize(14, 14)
    dot.setStyleSheet(
        f"background:{color};border-radius:7px;"
        f"border:1px solid rgba(255,255,255,0.2);"
    )
    return dot


# -------------------- 主窗口 --------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("E听说自动化辅助工具")
        self.setMinimumSize(900, 640)
        self.resize(960, 680)

        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.pic_dir = os.path.join(self.base_dir, "pic")
        os.makedirs(self.pic_dir, exist_ok=True)

        self.helper = ETSHelper(self.pic_dir, log_callback=self._log)
        self.worker = None
        self.env_worker = None
        self.env_cards = {}   # key -> (dot, value_label)

        self._build_ui()
        self._refresh_template_status()
        self._refresh_papers()
        self._start_env_check()

    # ---------------- UI 构建 ----------------
    def _build_ui(self):
        tabs = QTabWidget()
        tabs.addTab(self._build_dashboard_tab(), " 环境检测 ")
        tabs.addTab(self._build_automation_tab(), " 自动跟读 ")
        tabs.addTab(self._build_template_tab(), " 模板管理 ")
        tabs.addTab(self._build_answer_tab(), " 答案查看 ")
        tabs.addTab(self._build_settings_tab(), " 设置 ")
        tabs.addTab(self._build_advanced_tab(), " 高级(劫持) ")
        self.setCentralWidget(tabs)

    # ---------------- Dashboard（环境检测首页） ----------------
    def _build_dashboard_tab(self):
        w = QWidget()
        outer = QVBoxLayout()
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(14)

        # 头部
        head = QHBoxLayout()
        title = QLabel("运行环境检测")
        title.setObjectName("title")
        subtitle = QLabel("启动前请确认以下项目均为绿色，方可流畅运行自动跟读")
        subtitle.setObjectName("subtitle")
        head.addWidget(title)
        head.addStretch()
        self.env_refresh_btn = QPushButton("重新检测")
        self.env_refresh_btn.setObjectName("ghost")
        self.env_refresh_btn.clicked.connect(self._start_env_check)
        head.addWidget(self.env_refresh_btn)
        outer.addLayout(head)

        # 卡片网格
        grid = QHBoxLayout()
        grid.setSpacing(14)
        grid.addWidget(self._make_env_card("admin", "管理员权限", "检测中..."))
        grid.addWidget(self._make_env_card("ets", "E听说进程", "检测中..."))
        grid.addWidget(self._make_env_card("stereo", "立体声混音", "检测中..."))
        outer.addLayout(grid)

        grid2 = QHBoxLayout()
        grid2.setSpacing(14)
        grid2.addWidget(self._make_env_card("deps", "Python依赖", "检测中..."))
        grid2.addWidget(self._make_env_card("screen", "显示器", "检测中..."))
        grid2.addWidget(self._make_env_card("tpl", "跟读模板", "检测中..."))
        outer.addLayout(grid2)

        # 综合建议
        self.env_summary = QLabel("正在检测环境，请稍候...")
        self.env_summary.setObjectName("cardlabel")
        self.env_summary.setWordWrap(True)
        self.env_summary.setStyleSheet(
            "background:#262838;border:1px solid #3a3d52;border-radius:10px;"
            "padding:12px;color:#d6d9e6;"
        )
        outer.addWidget(self.env_summary)

        # 快捷操作
        ops = QHBoxLayout()
        self.open_ets_btn = QPushButton("打开 E听说")
        self.open_ets_btn.setObjectName("ghost")
        self.open_ets_btn.clicked.connect(self._try_open_ets)
        self.goto_auto_btn = QPushButton("前往自动跟读 ▶")
        self.goto_auto_btn.clicked.connect(lambda: tabs_index(self, 1))
        ops.addWidget(self.open_ets_btn)
        ops.addWidget(self.goto_auto_btn)
        ops.addStretch()
        outer.addLayout(ops)

        outer.addStretch()
        w.setLayout(outer)
        return w

    def _make_env_card(self, key, label, value):
        card = QFrame()
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.setFixedHeight(110)
        lay = QVBoxLayout()
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        top = QHBoxLayout()
        dot = make_status_dot("#555")
        lab = QLabel(label)
        lab.setObjectName("cardlabel")
        top.addWidget(dot)
        top.addStretch()
        top.addWidget(lab)
        val = QLabel(value)
        val.setObjectName("cardval")
        val.setWordWrap(True)
        lay.addLayout(top)
        lay.addWidget(val)
        card.setLayout(lay)
        self.env_cards[key] = (dot, val)
        return card

    def _start_env_check(self):
        self.env_refresh_btn.setEnabled(False)
        self.env_summary.setText("正在检测环境，请稍候...")
        self.env_worker = EnvCheckWorker()
        self.env_worker.result_signal.connect(self._on_env_result)
        self.env_worker.start()

    def _on_env_result(self, res: dict):
        self.env_refresh_btn.setEnabled(True)

        def set_card(key, ok, detail):
            dot, val = self.env_cards.get(key, (None, None))
            if dot:
                dot.setStyleSheet(
                    "background:%s;border-radius:7px;border:1px solid rgba(255,255,255,0.2);"
                    % ("#51cf66" if ok else "#ff6b6b")
                )
            if val:
                val.setText(detail)

        if "error" in res:
            self.env_summary.setText(f"环境检测异常：{res['error']}")
            return

        set_card("admin", res["admin"], "已获取管理员权限" if res["admin"] else "未以管理员运行（点击启动器右键'以管理员运行'）")
        set_card("ets", res["ets"]["ok"], res["ets"]["detail"])
        set_card("stereo", res["stereo"]["ok"], res["stereo"]["detail"])
        set_card("deps", res["deps"]["ok"], res["deps"]["detail"])
        set_card("screen", res["screen"]["ok"], res["screen"]["detail"])

        # 模板状态（本地判断）
        tpl_ok = all(os.path.exists(os.path.join(self.pic_dir, f)) for f in self.helper.templates.values())
        set_card("tpl", tpl_ok, "四个按钮模板均已就绪" if tpl_ok else "模板未齐备，请到「模板管理」截取")

        # 综合建议
        problems = []
        if not res["admin"]: problems.append("管理员权限")
        if not res["ets"]["ok"]: problems.append("E听说未运行")
        if not res["stereo"]["ok"]: problems.append("立体声混音未就绪")
        if not res["deps"]["ok"]: problems.append("依赖缺失")
        if not tpl_ok: problems.append("模板缺失")
        if problems:
            self.env_summary.setText(
                "⚠️ 以下项目需处理后再开始：\n• " + "\n• ".join(problems) +
                "\n\n提示：用「启动E听说助手.bat」可自动提权并启用立体声混音。"
            )
            self.env_summary.setStyleSheet(
                "background:#2e2230;border:1px solid #ff6b6b;border-radius:10px;"
                "padding:12px;color:#ffd6d6;"
            )
        else:
            self.env_summary.setText(
                "✅ 环境全部就绪！可以前往「自动跟读」开始作业了。\n"
                "请确保 E听说 已进入跟读界面且窗口不被遮挡。"
            )
            self.env_summary.setStyleSheet(
                "background:#1f2e22;border:1px solid #51cf66;border-radius:10px;"
                "padding:12px;color:#c8f7d4;"
            )

    def _try_open_ets(self):
        import subprocess
        ets_dir = r"C:\Program Files (x86)\ETS"
        candidates = ["ETS.exe", "ETSStudent.exe", "ETSClient.exe"]
        for c in candidates:
            path = os.path.join(ets_dir, c)
            if os.path.exists(path):
                try:
                    subprocess.Popen(path)
                    self._log(f"已尝试启动: {path}")
                    QTimer.singleShot(2500, self._start_env_check)
                    return
                except Exception as e:
                    self._log(f"[错误] 启动失败: {e}")
        QMessageBox.information(
            self, "未找到 E听说",
            f"未在 {ets_dir} 找到 E听说 主程序。\n请手动打开 E听说 后点击「重新检测」。"
        )

    # ---------------- 自动跟读 ----------------
    def _build_automation_tab(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        info = QLabel(
            "使用说明：\n"
            "1. 打开 E听说 并进入到跟读作业界面（窗口不被遮挡、单显示器）。\n"
            "2. 在「模板管理」中截取并保存四个按钮图片。\n"
            "3. 点击「开始」启动自动跟读，程序会循环完成 播放→录音→跟读→停止。\n"
            "4. 任何时候可点击「停止」结束任务。"
        )
        info.setWordWrap(True)
        info.setStyleSheet("background:#262838;border-radius:10px;padding:12px;color:#d6d9e6;")
        layout.addWidget(info)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("▶ 开始自动跟读")
        self.stop_btn = QPushButton("■ 停止")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start_automation)
        self.stop_btn.clicked.connect(self._stop_automation)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box)

        w.setLayout(layout)
        return w

    def _build_template_tab(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 16)
        layout.addWidget(QLabel("截取 E听说 界面中的按钮作为模板图片，保存到本地 pic 目录。\n"
                                "点击按钮后，3 秒内将鼠标移到对应按钮上单击即可截取。"))
        self.tpl_labels = {}
        for key, fname in self.helper.templates.items():
            row = QHBoxLayout()
            cap_btn = QPushButton(f"截取 [{fname}]")
            cap_btn.setObjectName("ghost")
            cap_btn.clicked.connect(lambda _, k=key, f=fname: self._capture_template(k, f))
            label = QLabel("状态: 缺失")
            self.tpl_labels[key] = label
            row.addWidget(cap_btn)
            row.addWidget(label)
            row.addStretch()
            layout.addLayout(row)
        layout.addStretch()
        w.setLayout(layout)
        return w

    def _build_answer_tab(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("按试卷名搜索（留空显示全部）")
        search_btn = QPushButton("搜索")
        search_btn.clicked.connect(self._refresh_papers)
        search_row.addWidget(self.search_edit)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)
        self.paper_list = QListWidget()
        self.paper_list.itemClicked.connect(self._on_paper_selected)
        layout.addWidget(self.paper_list, 1)
        self.paper_info = QTextEdit()
        self.paper_info.setReadOnly(True)
        layout.addWidget(self.paper_info, 1)
        w.setLayout(layout)
        return w

    def _build_settings_tab(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 16)
        form = QFormLayout()
        form.setSpacing(10)
        self.silence_spin = QSpinBox()
        self.silence_spin.setRange(5, 100)
        self.silence_spin.setValue(self.helper.silence_frames)
        form.addRow("静默判定帧数（越大越迟钝）:", self.silence_spin)
        self.vol_spin = QDoubleSpinBox()
        self.vol_spin.setRange(0, 50)
        self.vol_spin.setValue(self.helper.volume_threshold)
        form.addRow("静默音量阈值:", self.vol_spin)
        self.rate_combo = QComboBox()
        self.rate_combo.addItems(["16000", "44100", "48000"])
        self.rate_combo.setCurrentText(str(self.helper.sample_rate))
        form.addRow("采样率:", self.rate_combo)
        self.max_spin = QSpinBox()
        self.max_spin.setRange(1, 500)
        self.max_spin.setValue(self.helper.max_rounds)
        form.addRow("最大轮次:", self.max_spin)
        self.admin_hint = QCheckBox("我已以管理员身份运行（推荐）")
        form.addRow(self.admin_hint)
        layout.addLayout(form)
        apply_btn = QPushButton("保存设置")
        apply_btn.clicked.connect(self._apply_settings)
        layout.addWidget(apply_btn)
        layout.addStretch()
        w.setLayout(layout)
        return w

    def _build_advanced_tab(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 16)
        disclaimer = QLabel(
            "⚠️ 高级模块：winmm.dll 劫持（实验性 / 高风险）\n\n"
            "本模块基于 DLL 搜索顺序劫持 + Detours API Hook 技术，可拦截 E听说 调用的\n"
            "系统多媒体/计时 API（参考 GitHub: Howie114514/ETSToolbox）。\n\n"
            "风险与免责：\n"
            "• 仅供个人技术研究与逆向工程教学，严禁用于考试作弊或侵权。\n"
            "• 部署会写入 C:\\Program Files (x86)\\ETS\\，可能触发杀软、违反软件协议。\n"
            "• 使用者自负全部法律与纪律责任，作者不承担任何后果。\n\n"
            "如何启用（需自行编译，默认不启用）：\n"
            "1. 进入 advanced/ 目录，安装 Detours 并用 CMake 编译出 winmm.dll。\n"
            "2. 以管理员运行：python advanced/deploy_dll.py deploy <你的winmm.dll>\n"
            "3. 重启 E听说 生效；恢复请用：python advanced/deploy_dll.py uninstall\n\n"
            "详见 advanced/README.md。本程序不内置任何作弊数值，仅提供技术框架。"
        )
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(
            "background:#2e2230;border:1px solid #ff6b6b;border-radius:10px;"
            "padding:14px;color:#ffd6d6;"
        )
        layout.addWidget(disclaimer)
        layout.addStretch()
        w.setLayout(layout)
        return w

    # ---------------- 自动跟读控制 ----------------
    def _start_automation(self):
        self.helper.reset()
        self.helper.pic_dir = self.pic_dir
        self.worker = AutomationWorker(self.helper)
        self.worker.log_signal.connect(self._log)
        self.worker.progress_signal.connect(lambda v: self.progress.setValue(v))
        self.worker.finished_signal.connect(self._on_automation_finished)
        self.worker.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._log(">>> 自动跟读已启动")

    def _stop_automation(self):
        if self.helper:
            self.helper.stop()
        self._log(">>> 已发送停止信号")

    def _on_automation_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._log(">>> 线程已结束")

    # ---------------- 模板管理 ----------------
    def _capture_template(self, key: str, fname: str):
        QMessageBox.information(
            self, "截取模板",
            f"点击确定后，请在 3 秒内将鼠标移动到 E听说 的「{fname}」按钮上并单击。"
        )
        # 用 QTimer 延时，避免阻塞 PyQt 主线程事件循环（窗口卡死）
        QTimer.singleShot(3000, lambda: self._do_capture_template(key, fname))

    def _do_capture_template(self, key: str, fname: str):
        try:
            x, y = pyautogui.position()
            region = (x - 60, y - 25, 120, 50)
            shot = pyautogui.screenshot(region=region)
            save_path = os.path.join(self.pic_dir, fname)
            shot.save(save_path)
            self._log(f"已保存模板: {save_path}")
            self._refresh_template_status()
            self._start_env_check()  # 刷新首页模板卡片
        except Exception as e:
            self._log(f"[错误] 截取模板失败: {e}")

    def _refresh_template_status(self):
        for key, fname in self.helper.templates.items():
            path = os.path.join(self.pic_dir, fname)
            exists = os.path.exists(path)
            label = self.tpl_labels.get(key)
            if label:
                label.setText(f"状态: {'已就绪' if exists else '缺失'}")
                label.setStyleSheet("color:#51cf66;" if exists else "color:#ff6b6b;")

    # ---------------- 答案查看 ----------------
    def _refresh_papers(self):
        self.paper_list.clear()
        kw = self.search_edit.text()
        try:
            papers = search_papers(kw) if kw else list_papers()
        except Exception as e:
            self._log(f"[错误] 读取试卷失败: {e}")
            papers = []
        if not papers:
            self.paper_list.addItem("（未找到试卷，请确认 E听说 已下载作业）")
            return
        for p in papers:
            self.paper_list.addItem(p["name"])

    def _on_paper_selected(self, item):
        name = item.text()
        if name.startswith("（"):
            return
        ets_dir = get_ets_dir()
        papers = list_papers(ets_dir)
        target = next((p for p in papers if p["name"] == name), None)
        if not target:
            return
        info = read_paper_info(target["path"])
        lines = [f"试卷: {info['name']}", f"路径: {info['path']}", ""]
        lines.append(f"文件数: {len(info['files'])}")
        lines.append(f"音频数: {len(info['audios'])}")
        lines.append(f"图片数: {len(info['images'])}")
        if info["text_hints"]:
            lines.append("")
            lines.append("---- 检测到的答案相关字段 ----")
            lines.extend(info["text_hints"][:200])
        else:
            lines.append("")
            lines.append("（未在 json 中找到明确答案字段，可查看下方资源列表）")
        if info["audios"]:
            lines.append(""); lines.append("---- 音频资源 ----")
            lines.extend(info["audios"][:50])
        if info["images"]:
            lines.append(""); lines.append("---- 图片资源 ----")
            lines.extend(info["images"][:50])
        self.paper_info.setPlainText("\n".join(lines))

    # ---------------- 设置 ----------------
    def _apply_settings(self):
        self.helper.silence_frames = self.silence_spin.value()
        self.helper.volume_threshold = self.vol_spin.value()
        self.helper.sample_rate = int(self.rate_combo.currentText())
        self.helper.max_rounds = self.max_spin.value()
        self._log(">>> 设置已保存")

    # ---------------- 日志 ----------------
    def _log(self, msg: str):
        self.log_box.append(msg)


def tabs_index(main_window, idx):
    """切换到指定 tab（供 lambda 使用）。"""
    mw = main_window
    if hasattr(mw, "centralWidget"):
        cw = mw.centralWidget()
        if isinstance(cw, QTabWidget):
            cw.setCurrentIndex(idx)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
