r"""
E听说答案/试卷读取模块
参考 xiaoye8888/ETS-ANSWER-PICKER (eaa.py, 2026-08 最新, content2.json)
与 DMorest/ETSAnsReader (上海卷字段路径) 实现。
读取 Windows 本地 %Appdata%\ETS 目录下的已下载试卷数据。

关键修正（相比旧版本）：
1. 答案存放在 content_*/content.json 或 content2.json 子目录中，一个试卷含多个 content_* 目录，
   旧代码只在试卷根目录找单个 content.json，所以拿不到任何答案。
2. 真实答案字段：选择题 xt_nr + answer；其他题型 std[].value（及 ask/th 题号）。
3. 排除 common / pc_xst_dict / clear_cache 等非试卷系统目录。
"""
import os
import re
import json
import glob


# E听说本地数据根目录
def get_ets_dir() -> str:
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(appdata, "ETS")


# 非试卷的系统缓存目录，应排除
_NON_PAPER_DIRS = {"common", "pc_xst_dict", "clear_cache"}


def list_papers(ets_dir: str = None) -> list:
    """列出已下载的试卷（目录列表），按修改时间倒序。排除系统目录。"""
    if ets_dir is None:
        ets_dir = get_ets_dir()
    if not os.path.isdir(ets_dir):
        return []
    items = []
    for entry in os.listdir(ets_dir):
        full = os.path.join(ets_dir, entry)
        if not os.path.isdir(full):
            continue
        if entry.lower() in _NON_PAPER_DIRS:
            continue
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            mtime = 0
        items.append({"name": entry, "path": full, "mtime": mtime})
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def read_paper_info(paper_path: str) -> dict:
    """
    读取一份试卷的答案/题目信息。
    返回结构：
    {
      path, name, files, audios, images, jsons, text_hints,
      questions: [{no, type, content, answer, options, audio, image}],
      paper_title, exam_types
    }
    """
    info = {
        "path": paper_path,
        "name": os.path.basename(paper_path),
        "files": [],
        "audios": [],
        "images": [],
        "text_hints": [],
        "questions": [],
        "jsons": [],
        "paper_title": "",
        "exam_types": [],
    }
    if not os.path.isdir(paper_path):
        return info

    # 1) 收集所有文件、音频、图片、json
    candidate_jsons = []
    for root, _, files in os.walk(paper_path):
        for f in files:
            full = os.path.join(root, f)
            lower = f.lower()
            rel = os.path.relpath(full, paper_path)
            info["files"].append(rel)
            if lower.endswith((".mp3", ".wav", ".ogg", ".m4a")):
                info["audios"].append(rel)
            elif lower.endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                info["images"].append(rel)
            elif lower.endswith(".json"):
                candidate_jsons.append(full)
                info["jsons"].append(rel)

    # 2) 试卷元信息：template_*/res.json
    res_files = glob.glob(os.path.join(paper_path, "template_*", "res.json"))
    if not res_files:
        res_files = [j for j in candidate_jsons if j.lower().endswith("res.json")]
    for rf in res_files:
        try:
            with open(rf, "r", encoding="utf-8", errors="ignore") as fh:
                data = json.load(fh)
        except Exception:
            continue
        if isinstance(data, dict):
            t = data.get("set_intro", "")
            if t and not info["paper_title"]:
                info["paper_title"] = t
            for et in data.get("exam_type_list", []) or []:
                name = et.get("exam_type_name", "")
                score = et.get("exam_type_score", "")
                if name:
                    info["exam_types"].append(f"{name} (分值 {score})")

    # 3) 解析答案：content_*/content.json 或 content2.json
    #    优先顺序：content2.json > content.json
    content_files = []
    for jf in candidate_jsons:
        base = os.path.basename(jf).lower()
        if base in ("content.json", "content2.json"):
            # content2 优先
            if base == "content2.json":
                content_files.insert(0, jf)
            else:
                content_files.append(jf)

    seen_pairs = set()
    for cf in content_files:
        qs = _parse_content_file(cf)
        for q in qs:
            key = (str(q.get("no")), q.get("type"), q.get("content"), q.get("answer"))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            info["questions"].append(q)

    if not info["questions"]:
        info["text_hints"].append(
            "未在此试卷中找到可解析的答案数据。请确认已在 E听说 客户端中打开并下载过该试卷。"
        )

    return info


def _parse_content_file(jpath: str) -> list:
    """解析单个 content.json / content2.json，返回题目列表。"""
    try:
        with open(jpath, "r", encoding="utf-8", errors="ignore") as fh:
            raw = fh.read()
    except Exception:
        return []

    questions = []
    data = None
    try:
        data = json.loads(raw)
    except Exception:
        data = None

    # ---- A. 结构化 JSON 解析 ----
    if isinstance(data, dict):
        st = data.get("structure_type", "")
        info = data.get("info", data) if isinstance(data.get("info"), dict) else data

        q_type = _structure_to_type(st)

        # 朗读/跟读/复述类：原文在 info.value，AI 标记答案在 info.ai
        if isinstance(info, dict):
            value = _strip_html(info.get("value", ""))
            ai = _strip_html(info.get("ai", ""))
            audio = info.get("audio", "")
            image = info.get("image", "")
            if value or ai:
                questions.append({
                    "no": 1,
                    "type": q_type or "朗读/跟读",
                    "content": value,
                    "answer": ai or value,
                    "options": [],
                    "audio": audio,
                    "image": image,
                })

            # 选择题：xtlist 列表，每项含 xt_nr + answer
            xt = info.get("xtlist") or data.get("xtlist")
            if isinstance(xt, list):
                for i, item in enumerate(xt):
                    if not isinstance(item, dict):
                        continue
                    no = _clean_no(item.get("xt_nr", item.get("no", i + 1)))
                    q_text = _strip_html(
                        item.get("xt_nr_text", item.get("content", item.get("question", "")))
                    )
                    ans = item.get("answer", "")
                    questions.append({
                        "no": no,
                        "type": "听后选择",
                        "content": q_text,
                        "answer": str(ans),
                        "options": _extract_options(item),
                        "audio": "",
                        "image": "",
                    })

            # 问答/转述：question 列表，每项含 std(答案数组) / ask(提问) / th(题号)
            qlist = info.get("question") or data.get("question")
            if isinstance(qlist, list):
                for i, q in enumerate(qlist):
                    if not isinstance(q, dict):
                        continue
                    no = _clean_no(q.get("th", q.get("no", i + 1)))
                    ask = _strip_html(q.get("ask", q.get("question", "")))
                    std = q.get("std") or info.get("std") or data.get("std")
                    answers = _collect_std_answers(std)
                    questions.append({
                        "no": no,
                        "type": "听后回答/转述",
                        "content": ask,
                        "answer": "\n".join(answers) if answers else "",
                        "options": [],
                        "audio": "",
                        "image": "",
                    })

            # 顶层 std（部分题型答案直接挂在 info/std）
            if not qlist:
                std = info.get("std") or data.get("std")
                answers = _collect_std_answers(std)
                if answers:
                    questions.append({
                        "no": 1,
                        "type": "听后记录/转述",
                        "content": "",
                        "answer": "\n".join(answers),
                        "options": [],
                        "audio": "",
                        "image": "",
                    })

    # ---- B. 兜底：字符串扫描（移植自 xiaoye8888 eaa.py，已被验证）----
    if not questions:
        pairs = _eaa_scan(raw)
        for no, ans in pairs:
            questions.append({
                "no": no,
                "type": "未知",
                "content": "",
                "answer": ans,
                "options": [],
                "audio": "",
                "image": "",
            })

    return questions


def _structure_to_type(st: str) -> str:
    mapping = {
        "collector.read": "模仿朗读",
        "collector.word": "单词朗读",
        "collector.sentence": "句子朗读",
        "collector.scene": "情景问答",
        "collector.retell": "故事复述",
        "collector.listen": "听力理解",
    }
    return mapping.get(st, st)


def _collect_std_answers(std) -> list:
    """从 std 结构（list / dict）中提取所有 value 文本。"""
    out = []
    if isinstance(std, list):
        for item in std:
            if isinstance(item, dict):
                v = item.get("value", "")
                if v:
                    out.append(_strip_html(v))
            elif isinstance(item, list):
                out.extend(_collect_std_answers(item))
    elif isinstance(std, dict):
        for v in std.get("value", []) if isinstance(std.get("value"), list) else [std.get("value")]:
            if v:
                out.append(_strip_html(v))
    return [o for o in out if o]


def _extract_options(item: dict) -> list:
    opts = item.get("options", item.get("choices", []))
    if isinstance(opts, dict):
        return [f"{k}: {v}" for k, v in opts.items()]
    if isinstance(opts, list):
        return [str(o) for o in opts]
    return []


def _clean_no(v) -> object:
    if v is None:
        return ""
    s = str(v).strip().rstrip(".")
    m = re.search(r"\d+", s)
    return m.group(0) if m else s


def _strip_html(raw):
    if not isinstance(raw, str):
        return ""
    return re.sub(r"<[^>]+>", "", raw).replace("&nbsp;", " ").strip()


def _eaa_scan(content: str):
    """
    移植自 xiaoye8888/ETS-ANSWER-PICKER 的 eaa.py（2026-08 验证可用）。
    对 content2.json 原文做字符串扫描，提取 (题号, 答案) 列表。
    """
    if not content or "collector.read" in content:
        return []
    th_list, aw_list = [], []
    a = 0
    n = len(content)
    while a < n:
        c1 = content[a:a + 7]
        if c1 == 'xt_nr":':
            th = content[a + 8:a + 10].replace(".", "")
            a += 10
            while a < n:
                if content[a:a + 8] == 'answer":':
                    a += 9
                    aw = content[a:a + 1]
                    th_list.append(_clean_no(th))
                    aw_list.append(aw)
                    break
                a += 1
        elif c1 == '"std":[':
            a += 8
            while True:
                # 在 std 内寻找 "value" 或离开标记
                while a + 7 <= n and content[a:a + 7] != '"value"' and content[a:a + 5] != '"ref"':
                    a += 1
                if a + 7 > n or content[a:a + 7] != '"value"':
                    break
                a += 9
                b = 0
                aw = ""
                th = ""
                th_from_th = False
                # 提取 value 字符串
                while a + b < n:
                    if content[a + b] != '"' or (a + b > 0 and content[a + b - 1] == "\\"):
                        aw += content[a + b]
                        b += 1
                    else:
                        # 向后/向前搜索题号字段
                        found_th = False
                        bb = b
                        while a + bb < n:
                            seg = content[a + bb:a + bb + 5]
                            if seg == 'ask":':
                                # 从 ask 值取首个数字
                                m = re.search(r"\d+", content[a + bb + 5:a + bb + 80])
                                if m:
                                    th = m.group(0)
                                found_th = True
                                break
                            elif content[a + bb:a + bb + 4] == 'th":':
                                th = content[a + bb + 5:a + bb + 7].strip()
                                th_from_th = True
                                found_th = True
                                break
                            elif content[a + bb:a + bb + 7] == '"std":[':
                                bb -= 1
                                break
                            elif content[a + bb:a + bb + 5] in ('"xh":', '"xth":'):
                                break
                            bb += 1
                        if found_th:
                            th_list.append(_clean_no(th))
                            aw_list.append(_strip_html(aw).rstrip("."))
                        a += bb if bb > 0 else b
                        break
                if not th_from_th:
                    break
        a += 1
    return list(zip(th_list, aw_list))


def search_papers(keyword: str, ets_dir: str = None) -> list:
    """按关键字搜索试卷名。"""
    papers = list_papers(ets_dir)
    kw = keyword.strip().lower()
    if not kw:
        return papers
    return [p for p in papers if kw in p["name"].lower()]
