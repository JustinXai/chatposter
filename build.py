#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
群聊总结机器人 · 渲染层构建脚本
================================

把一份 analysis_*.json（结构化分析结果）灌进 index.html 的报面模板，
产出可直接打开、可直接截图成 3:4 长图的 HTML 日报。

设计原则：模板只认结构、不认内容。所以这个脚本只做三件事——
  1. 校验 JSON 是否符合字段契约（缺字段直接报错，不静默出半张报）
  2. 做「口径自洽」检查（各模块数字能不能互相反算，不通过只告警不阻断）
  3. 把数据注入模板的 REPORT_DATA 标记段，写出一份独立 HTML

用法：
    python build.py                                  # 用内置示例数据
    python build.py data/analysis.sample.json
    python build.py data/my.json -o out/my.html
    python build.py data/my.json --theme tech        # 换主题
    python build.py data/my.json --check             # 只体检，不生成

可选主题见 poster.html 顶部注释：gold（默认）/ kawaii / tech。
字段契约见 README 或 index.html 右侧「数据契约」卡片。
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

# ---------------------------------------------------------------- 常量

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "index.html")
DEFAULT_DATA = os.path.join(HERE, "data", "analysis.sample.json")

THEMES = ("gold", "kawaii", "tech")
DEFAULT_THEME = "gold"

START_MARK = "/* >>> REPORT_DATA_START"
END_MARK = "/* <<< REPORT_DATA_END <<< */"

# 契约：必填字段 -> 期望类型
CONTRACT = {
    "meta": dict,
    "stats": list,
    "hours": list,
    "topics": list,
    "ranking": list,
    "quote": dict,
}
TOPIC_REQUIRED = ("tag", "title", "mentions", "delta", "summary")

ERRORS = []
WARNINGS = []


# ---------------------------------------------------------------- 工具

def err(msg):
    ERRORS.append(msg)


def warn(msg):
    WARNINGS.append(msg)


def rule(title=""):
    print("\n" + "─" * 62)
    if title:
        print("  " + title)


def stat_of(stats, key):
    """按 stats 里的中文 key 取数值，取不到返回 None。"""
    for s in stats:
        if s.get("key") == key:
            return s.get("value")
    return None


# ---------------------------------------------------------------- 校验

def validate(data):
    """硬校验：结构不对就别往下走了。"""
    for key, typ in CONTRACT.items():
        if key not in data:
            err("缺少顶层字段：%s" % key)
        elif not isinstance(data[key], typ):
            err("字段类型不对：%s 应为 %s" % (key, typ.__name__))
    if ERRORS:
        return False

    m = data["meta"]
    for k in ("group", "date"):
        if not m.get(k):
            err("meta.%s 不能为空" % k)

    if len(data["hours"]) != 24:
        err("hours 必须是 24 个数字（按小时），当前 %d 个" % len(data["hours"]))

    for i, t in enumerate(data["topics"]):
        for k in TOPIC_REQUIRED:
            if k not in t:
                err("topics[%d] 缺少字段：%s" % (i, k))
        if isinstance(t.get("summary"), list) and not t["summary"]:
            err("topics[%d].summary 不能为空列表" % i)
        if not t.get("sources"):
            warn("topics[%d]「%s」没有 sources，摘要无法溯源" % (i, t.get("title", "?")))

    for i, r in enumerate(data["ranking"]):
        if not r.get("name") or not isinstance(r.get("msgs"), int):
            err("ranking[%d] 需要 name(str) 与 msgs(int)" % i)

    if not data["quote"].get("text"):
        err("quote.text 不能为空")

    return not ERRORS


def check_consistency(data):
    """软校验：报面上的数字必须能互相反算，否则读者第一眼就会怀疑。"""
    stats = data["stats"]
    total = stat_of(stats, "消息总量")

    s_hours = sum(data["hours"])
    if total is not None and s_hours != total:
        warn("口径不一致：24 小时柱状图合计 %s ≠ 消息总量 %s" % (s_hours, total))
    else:
        print("  [ok] 小时曲线合计 %s = 消息总量卡片" % s_hours)

    if total:
        peak = max(data["hours"])
        idx = data["hours"].index(peak)
        win = data["meta"].get("window", "")
        if win and not win.startswith("%02d:" % idx):
            warn("活跃时段标注为 %s，但峰值其实在 %02d:00（建议来自动算，别手填）" % (win, idx))
        else:
            print("  [ok] 峰值 %s 条落在 %02d:00，与活跃时段标注一致" % (peak, idx))

    s_mentions = sum(t.get("mentions", 0) for t in data["topics"])
    card_mentions = stat_of(stats, "话题提及")
    if card_mentions is not None and s_mentions != card_mentions:
        warn("口径不一致：话题提及合计 %s ≠ 卡片 %s" % (s_mentions, card_mentions))
    else:
        print("  [ok] 话题提及合计 %s = 话题提及卡片" % s_mentions)

    sig = data.get("signals") or {}
    s_sig = sum(sig.values())
    card_sig = stat_of(stats, "待跟进线索")
    if card_sig is not None and s_sig != card_sig:
        warn("口径不一致：线索明细合计 %s ≠ 卡片 %s" % (s_sig, card_sig))
    elif card_sig is not None:
        print("  [ok] 线索明细 %s = 待跟进卡片" % s_sig)

    if total:
        rank_sum = sum(r["msgs"] for r in data["ranking"])
        if rank_sum > total:
            warn("发言排行合计 %s 超过消息总量 %s，占比条会失真" % (rank_sum, total))
        else:
            print("  [ok] 排行前 %d 人合计 %s 条，占总量 %.1f%%"
                  % (len(data["ranking"]), rank_sum, rank_sum / total * 100))
    return True


# ---------------------------------------------------------------- 注入

def inject(data, template_path=TEMPLATE, out_path=None, theme=DEFAULT_THEME):
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    i = html.find(START_MARK)
    j = html.find(END_MARK)
    if i < 0 or j < 0 or j < i:
        raise SystemExit("[x] 模板里找不到 REPORT_DATA 标记段，无法注入：%s" % template_path)

    # 防止 JSON 里出现 </script> 把标签提前闭合
    payload = json.dumps(data, ensure_ascii=False, indent=2).replace("</", "<\\/")
    new_block = (START_MARK + " · 构建脚本 build.py 只替换这一段的字面量 <<< */\n"
                 "const REPORT = " + payload + ";\n")

    html = html[:i] + new_block + html[j:]

    # 注入主题（模板里 <html data-theme="...">）
    if theme and theme != DEFAULT_THEME:
        html = re.sub(r'(<html[^>]*\bdata-theme=")[^"]*(")',
                      lambda m: m.group(1) + theme + m.group(2), html, count=1)

    # 注入生成时间戳（可选，模板里没有就跳过）
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = html.replace("learning edition", "built " + stamp + " · learning edition")

    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
    return html


def default_out(data):
    date = re.sub(r"[^0-9A-Za-z\-]", "", str(data["meta"].get("date", "report"))) or "report"
    return os.path.join(HERE, "out", "report-%s.html" % date)


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="群聊总结机器人 · 渲染层构建脚本")
    ap.add_argument("data", nargs="?", default=DEFAULT_DATA, help="analysis JSON 路径")
    ap.add_argument("-t", "--template", default=TEMPLATE, help="模板 HTML 路径（默认 index.html）")
    ap.add_argument("-o", "--out", default=None, help="输出 HTML 路径")
    ap.add_argument("--theme", default=DEFAULT_THEME, choices=THEMES,
                    help="主题：gold 暗夜鎏金（默认）/ kawaii 奶油卡通 / tech 办公科技")
    ap.add_argument("--check", action="store_true", help="只做校验，不生成文件")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("群聊总结机器人 · 渲染层构建")
    print("  数据：" + args.data)

    if not os.path.exists(args.data):
        raise SystemExit("[x] 数据文件不存在：%s" % args.data)
    if not os.path.exists(args.template):
        raise SystemExit("[x] 模板文件不存在：%s" % args.template)
    with open(args.data, "r", encoding="utf-8") as f:
        data = json.load(f)

    rule("1 / 字段契约")
    if not validate(data):
        for e in ERRORS:
            print("  [x] " + e)
        print("\n契约校验未通过，已中止（不生成半张报）。")
        return 1
    print("  [ok] 顶层字段齐全：%s" % "、".join(CONTRACT.keys()))
    print("  [ok] 话题 %d 个 / 排行 %d 人 / 小时 %d 个数据点"
          % (len(data["topics"]), len(data["ranking"]), len(data["hours"])))

    rule("2 / 口径自洽")
    check_consistency(data)

    if WARNINGS:
        print("\n  告警 %d 条（不影响生成，但建议核对）：" % len(WARNINGS))
        for w in WARNINGS:
            print("  [!] " + w)

    if args.check:
        rule()
        print("体检完成，未生成文件（--check）。")
        return 0

    rule("3 / 注入模板")
    out = args.out or default_out(data)
    inject(data, template_path=args.template, out_path=out, theme=args.theme)
    size = os.path.getsize(out)
    print("  [ok] 模板：%s" % os.path.relpath(args.template, HERE))
    print("  [ok] 主题：%s" % args.theme)
    print("  [ok] 输出：%s  (%.1f KB)" % (os.path.relpath(out, HERE), size / 1024))

    rule()
    print("报面：%s | %s | 消息 %s 条 / 活跃 %s 人 / 话题 %s 次 / 线索 %s 条"
          % (data["meta"]["group"], data["meta"]["date"],
             stat_of(data["stats"], "消息总量"), stat_of(data["stats"], "活跃成员"),
             stat_of(data["stats"], "话题提及"), stat_of(data["stats"], "待跟进线索")))
    print("下一步：浏览器打开该 HTML；需要图片版就用无头浏览器截长图。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
