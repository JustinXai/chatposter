#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成脱敏示例图：用 poster.html 内置的虚构数据渲染，输出到 docs/demo.png。"""
import os
import re
import sys
import json
import subprocess

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import config as C  # noqa: E402

TEMPLATE = os.path.join(HERE, "poster.html")
DOCS = os.path.join(HERE, "docs")
os.makedirs(DOCS, exist_ok=True)

# 从模板里抽出内置的示例 REPORT（保证示例图与模板永远一致）
html = open(TEMPLATE, encoding="utf-8").read()
i = html.find("/* >>> REPORT_DATA_START")
j = html.find("/* <<< REPORT_DATA_END")
block = html[i:j]
m = re.search(r"const REPORT\s*=\s*(\{.*?\n\};)", block, re.S)
src = m.group(1)
# 用 Node 直接跑这段 JS 字面量，避免手写解析器踩引号/注释的坑
node = os.environ.get("CHATPOSTER_NODE") or "node"
tmp_js = os.path.join(DOCS, "_extract.js")
with open(tmp_js, "w", encoding="utf-8") as f:
    f.write("const REPORT = " + src + "\n")
    f.write("process.stdout.write(JSON.stringify(REPORT));\n")
r = subprocess.run([node, tmp_js], capture_output=True)
if r.returncode != 0:
    print(r.stderr.decode("utf-8", "replace"))
    raise SystemExit(1)
data = json.loads(r.stdout.decode("utf-8"))

jp = os.path.join(DOCS, "_demo.json")
with open(jp, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

hp = os.path.join(DOCS, "demo.html")
env = C.py_env()
p = subprocess.run([C.python_exe(), os.path.join(HERE, "build.py"), jp,
                    "-t", TEMPLATE, "-o", hp],
                   capture_output=True, env=env)
print(p.stdout.decode("utf-8", "replace"))
if p.returncode != 0:
    print(p.stderr.decode("utf-8", "replace"))
    raise SystemExit(1)

chrome = C.chrome_exe()
print("chrome:", chrome)
PROFILE = C.shot_profile()
flags = ["--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
         "--hide-scrollbars", "--force-device-scale-factor=1",
         "--user-data-dir=" + PROFILE]
url = "file:///" + hp.replace("\\", "/")

p = subprocess.run([chrome] + flags + ["--virtual-time-budget=2500",
                                       "--window-size=1080,1200", "--dump-dom", url],
                   capture_output=True)
mm = re.search(r"H (\d+) W (\d+)", p.stdout.decode("utf-8", "replace"))
H = int(mm.group(1)) if mm else 2000
print("measured H =", H)

png = os.path.join(DOCS, "demo.png")
if os.path.exists(png):
    os.remove(png)
subprocess.run([chrome] + flags + ["--virtual-time-budget=2500",
                                   "--window-size=1080,%d" % (H + 400),
                                   "--screenshot=" + png, url], capture_output=True)

try:
    from PIL import Image
    im = Image.open(png).convert("RGB")
    w, h = im.size
    px = im.load()
    bg = (25, 27, 31)
    last = h - 1
    while last > 0:
        if any(sum(abs(a - b) for a, b in zip(px[x, last], bg)) > 6 for x in (0, w // 2, w - 1)):
            break
        last -= 1
    if last + 1 < h:
        im.crop((0, 0, w, last + 1)).save(png)
    print("final size:", Image.open(png).size)
except Exception as e:
    print("crop skip:", e)

print("done ->", png)
