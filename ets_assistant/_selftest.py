import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from answer_reader import _eaa_scan, _parse_content_file

# 1) eaa 字符串扫描：模拟 content2.json 选择题+std
sample = (
    '{"xt_nr":"1.","xt_nr_text":"What color is it?","answer":"A"}'
    '{"std":[{"value":"Because it is red."},{"value":"It is big."}]}'
)
print("eaa_scan =>", _eaa_scan(sample))

# 2) JSON 解析：选择题 xtlist
p = os.path.join(tempfile.mkdtemp(), "content.json")
with open(p, "w", encoding="utf-8") as f:
    json.dump({"info": {"xtlist": [
        {"xt_nr": "1.", "xt_nr_text": "Q1 text", "answer": "B"},
        {"xt_nr": "2.", "xt_nr_text": "Q2 text", "answer": "C"},
    ]}}, f)
print("\njson xtlist =>")
for q in _parse_content_file(p):
    print("  ", q)

# 3) JSON 解析：朗读 collector.listen
p2 = os.path.join(tempfile.mkdtemp(), "content2.json")
with open(p2, "w", encoding="utf-8") as f:
    json.dump({"structure_type": "collector.listen",
               "info": {"value": "<p>Read aloud</p>", "ai": "<b>AI tip</b>", "audio": "x.mp3"}}, f)
print("\njson read =>")
for q in _parse_content_file(p2):
    print("  ", q)

# 4) JSON 解析：question/std 问答
p3 = os.path.join(tempfile.mkdtemp(), "content.json")
with open(p3, "w", encoding="utf-8") as f:
    json.dump({"info": {"question": [
        {"th": "1", "ask": "Please answer 1.", "std": [{"value": "Answer one."}]},
        {"th": "2", "ask": "Please answer 2.", "std": [{"value": "Answer two."}]},
    ]}}, f)
print("\njson question/std =>")
for q in _parse_content_file(p3):
    print("  ", q)
print("\nALL OK")
