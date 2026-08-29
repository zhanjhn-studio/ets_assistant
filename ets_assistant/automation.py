"""
E听说自动化跟读核心模块
基于 deAlue/AutoETS 实现，修复了原代码的 global bug 与空列表判断问题。
使用 OpenCV 模板匹配定位按钮 + PyAutoGUI 点击 + PyAudio 录音。

兼容性说明：原 AutoETS 依赖 audioop（Python 3.13 已移除）。
本实现改用 numpy 计算 RMS 音量，可在任意 Python 版本运行。
"""
import os
import time
import threading
import struct
import cv2
import numpy as np
import pyautogui
import pyaudio
import wave

# 防止 pyautogui  Fail-Safe 误触（保留 0.5s 触发边界）
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3


def rms_volume(raw_bytes: bytes, width: int = 2) -> float:
    """用 numpy 计算音频 RMS（替代已移除的 audioop.rms，兼容 Python 3.13+）。"""
    if not raw_bytes:
        return 0.0
    # 将字节转为 int16 数组
    count = len(raw_bytes) // width
    if count == 0:
        return 0.0
    arr = np.frombuffer(raw_bytes[: count * width], dtype=np.int16).astype(np.float64)
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr ** 2)))


class ETSHelper:
    """E听说自动化助手核心类（线程安全设计）。"""

    def __init__(self, pic_dir: str, log_callback=print, progress_callback=None):
        self.pic_dir = pic_dir
        self.log = log_callback
        self.progress = progress_callback
        self._stop = threading.Event()
        self._running = False

        # 可调参数
        self.silence_frames = 20      # 连续静默帧数判定录音结束
        self.volume_threshold = 3     # 静默音量阈值
        self.sample_rate = 44100
        self.click_delay = 1.0        # 点击后等待
        self.max_rounds = 50          # 最大轮次保护

        # 模板文件名 -> 实际路径
        self.templates = {
            "play": "yuan.png",       # 播放原文
            "record": "luyin.png",    # 开始录音
            "stop": "stop.png",       # 停止录音
            "next": "next.png",       # 下一个
        }

    # ---------- 控制 ----------
    def stop(self):
        self._stop.set()

    @property
    def stopped(self):
        return self._stop.is_set()

    def reset(self):
        self._stop.clear()
        self._running = False

    # ---------- 模板匹配 ----------
    def _template_path(self, key: str) -> str:
        return os.path.join(self.pic_dir, self.templates.get(key, key))

    def locate(self, key: str):
        """在截图中用模板匹配定位按钮中心坐标，返回 (x, y) 或 None。"""
        tpl_path = self._template_path(key)
        if not os.path.exists(tpl_path):
            self.log(f"[错误] 模板图片缺失: {tpl_path}")
            return None
        shot_path = os.path.join(self.pic_dir, "screenshot.png")
        pyautogui.screenshot().save(shot_path)
        img = cv2.imread(shot_path)
        tpl = cv2.imread(tpl_path)
        if img is None or tpl is None:
            self.log("[错误] 截图或模板读取失败")
            return None
        h, w = tpl.shape[:2]
        result = cv2.matchTemplate(img, tpl, cv2.TM_SQDIFF_NORMED)
        min_val, _, top_left, _ = cv2.minMaxLoc(result)
        # 匹配度阈值，过小说明没找到
        if min_val > 0.15:
            return None
        center = (int(top_left[0] + w / 2), int(top_left[1] + h / 2))
        return center

    def click_template(self, key: str, name: str = ""):
        pos = self.locate(key)
        if pos is None:
            self.log(f"[失败] 未找到按钮: {name or key}")
            return False
        pyautogui.click(pos[0], pos[1])
        time.sleep(self.click_delay)
        return True

    # ---------- 录音 ----------
    def record(self, save_path: str) -> bool:
        """录音直到连续 silence_frames 帧音量低于阈值。返回是否录到内容。"""
        pa = pyaudio.PyAudio()
        # 动态探测默认输入设备参数，避免硬编码 channels=2 / 44100 在部分
        # 声卡（如单声道或采样率非 44100 的立体声混音）上抛 -9998 崩溃。
        try:
            dev_info = pa.get_default_input_device_info()
            channels = int(dev_info.get("maxInputChannels", 1)) or 1
            rate = int(dev_info.get("defaultSampleRate", self.sample_rate)) or self.sample_rate
        except Exception:
            channels, rate = 1, self.sample_rate
        channels = min(channels, 2)
        stream = pa.open(format=pyaudio.paInt16, channels=channels,
                         rate=rate, input=True, frames_per_buffer=2048)
        buf = []
        silent = 0
        self.log("录音中...")
        try:
            while not self.stopped:
                data = stream.read(2048, exception_on_overflow=False)
                buf.append(data)
                vol = rms_volume(data, 2)  # 2 = paInt16 样本字节宽度
                if vol <= self.volume_threshold:
                    silent += 1
                else:
                    silent = 0
                if silent >= self.silence_frames:
                    break
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

        if len(buf) == 0:
            return False
        wf = wave.open(save_path, "wb")
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"".join(buf))
        wf.close()
        self.log(f"录音完成: {save_path}（{channels}ch @ {rate}Hz）")
        return True

    def play(self, wav_path: str):
        if not os.path.exists(wav_path):
            self.log("[错误] 待播放文件不存在")
            return
        chunk = 1024
        wf = wave.open(wav_path, "rb")
        p = pyaudio.PyAudio()
        stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                        channels=wf.getnchannels(),
                        rate=wf.getframerate(), output=True)
        data = wf.readframes(chunk)
        self.log("播放中...")
        while len(data) != 0 and not self.stopped:
            stream.write(data)
            data = wf.readframes(chunk)
        stream.stop_stream()
        stream.close()
        p.terminate()
        self.log("播放结束")

    # ---------- 一轮跟读 ----------
    def cycle(self, round_idx: int):
        self.log(f"===== 第 {round_idx} 轮 =====")
        if not self.click_template("play", "播放原文"):
            return False
        if not self.record(os.path.join(self.pic_dir, "01.wav")):
            self.log("[警告] 本轮未录到声音，跳过")
            return False
        if not self.click_template("record", "开始录音"):
            return False
        self.play(os.path.join(self.pic_dir, "01.wav"))
        if not self.click_template("stop", "停止录音"):
            return False
        # 等待评分返回：轮询'下一个'按钮变绿（最多 10s），避免固定延时误判结束
        waited = 0.0
        while not self.stopped and not self.is_next_available() and waited < 10:
            time.sleep(0.5)
            waited += 0.5
        return True

    def is_next_available(self) -> bool:
        """通过像素颜色判断'下一个'按钮是否可点击（绿色 0,207,107）。"""
        pos = self.locate("next")
        if pos is None:
            return False
        return pyautogui.pixelMatchesColor(pos[0], pos[1], (0, 207, 107), tolerance=15)

    # ---------- 主流程 ----------
    def run(self):
        self._running = True
        self.log("开始自动跟读，请将 E听说 窗口置于前台且按钮不被遮挡。")
        if not self.cycle(1):
            self.log("[结束] 首轮失败，请检查模板图片与窗口位置。")
            self._running = False
            return
        round_idx = 1
        while not self.stopped and round_idx < self.max_rounds:
            if self.is_next_available():
                time.sleep(1)
                if not self.cycle(round_idx + 1):
                    break
                round_idx += 1
                if self.progress:
                    self.progress(round_idx)
            else:
                self.log("未检测到'下一个'按钮，任务结束。")
                break
        self.log(f"自动跟读结束，共完成 {round_idx} 轮。")
        self._running = False
