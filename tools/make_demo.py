#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成脱敏示例图：用 poster.html 内置的虚构数据，为每套主题各渲染一张。

输出：
    docs/demo-gold.png     暗夜鎏金（默认）
    docs/demo-paper.png    晨光纸感
    docs/demo-crimson.png  深红夜航
    docs/demo.png          与默认主题一致，供旧链接兼容

数据全部是模板内置的虚构示例，不含任何真实聊天内容。
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import config as C  # noqa: E402

TEMPLATE = os.path.join(HERE, "poster.html")
DOCS = os.path.join(HERE, "docs")
os.makedirs(DOCS, exist_ok=True)

# 主题 -> (输出名, 图外底色 RGB)。底色用于裁掉底部空白。
THEMES = {
    "gold":    ("demo-gold.png",    (25, 27, 31)),
    "paper":   ("demo-paper.png",   (232, 227, 218)),
    "crimson": ("demo-crimson.png", (42, 20, 24)),
}


def extract_sample():
    """从模板里抽出内置 REPORT（JS 字面量），用 Node 执行后转成 JSON。"""
    html = open(TEMPLATE, encoding="utf-8").read()
    i = html.find("/* >>> REPORT_DATA_START")
    j = html.find("/* <<< REPORT_DATA_END")
    m = re.search(r"const REPORT\s*=\s*(\{.*?\n\};)", html[i:j], re.S)
    src = m.group(1)
    node = os.environ.get("CHATPOSTER_NODE") or "node"
    tmp = os.path.join(DOCS, "_extract.js")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("const REPORT = " + src + "\n")
        f.write("process.stdout.write(JSON.stringify(REPORT));\n")
    r = subprocess.run([node, tmp], capture_output=True)
    os.remove(tmp)
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "replace"))
        raise SystemExit(1)
    return json.loads(r.stdout.decode("utf-8"))


def shoot(html_path, png_path, chrome, bg):
    PROFILE = C.shot_profile()
    flags = ["--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
             "--hide-scrollbars", "--force-device-scale-factor=1",
             "--user-data-dir=" + PROFILE]
    url = "file:///" + html_path.replace("\\", "/")

    p = subprocess.run([chrome] + flags + ["--virtual-time-budget=2500",
                                           "--window-size=1080,1200", "--dump-dom", url],
                       capture_output=True)
    m = re.search(r"H (\d+) W (\d+)", p.stdout.decode("utf-8", "replace"))
    H = int(m.group(1)) if m else 2000

    if os.path.exists(png_path):
        os.remove(png_path)
    subprocess.run([chrome] + flags + ["--virtual-time-budget=2500",
                                       "--window-size=1080,%d" % (H + 400),
                                       "--screenshot=" + png_path, url],
                   capture_output=True)

    try:
        from PIL import Image
        im = Image.open(png_path).convert("RGB")
        w, h = im.size
        px = im.load()
        last = h - 1
        while last > 0:
            if any(sum(abs(a - b) for a, b in zip(px[x, last], bg)) > 6
                   for x in (0, w // 2, w - 1)):
                break
            last -= 1
        if last + 1 < h:
            im.crop((0, 0, w, last + 1)).save(png_path)
        return Image.open(png_path).size
    except Exception as e:
        print("  裁边跳过:", e)
        return None


def main():
    data = extract_sample()
    jp = os.path.join(DOCS, "_demo.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    chrome = C.chrome_exe()
    if not chrome:
        raise SystemExit("没找到 Chrome / Edge，请设 CHATPOSTER_CHROME")
    print("chrome:", chrome)

    for theme, (name, bg) in THEMES.items():
        hp = os.path.join(DOCS, "_demo-%s.html" % theme)
        r = subprocess.run([C.python_exe(), os.path.join(HERE, "build.py"), jp,
                            "-t", TEMPLATE, "-o", hp, "--theme", theme],
                           capture_output=True, env=C.py_env())
        if r.returncode != 0:
            print(r.stdout.decode("utf-8", "replace"))
            print(r.stderr.decode("utf-8", "replace"))
            raise SystemExit(1)

        png = os.path.join(DOCS, name)
        size = shoot(hp, png, chrome, bg)
        print("  [%s] %-20s %s" % (theme, name, size))
        os.remove(hp)

        # 默认主题额外复制一份 demo.png，兼容旧引用
        if theme == "gold":
            import shutil
            shutil.copyfile(png, os.path.join(DOCS, "demo.png"))

    os.remove(jp)
    print("\n完成，输出目录：docs/")


if __name__ == "__main__":
    main()
