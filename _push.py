#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提交并推送。"""
import os
import subprocess

ROOT = r"E:\群聊总结机器人"
REMOTE = "https://github.com/JustinXai/chatposter.git"
LOG = []


def run(args, show=True):
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    o = ((p.stdout or "") + (p.stderr or "")).strip()
    LOG.append("$ " + " ".join(args))
    if o:
        LOG.append(o)
    LOG.append("")
    return p.returncode, o


# 清理上次可能残留的 guard_report.txt 与 _g3.py
for n in ("guard_report.txt", "_g3.py"):
    p = os.path.join(ROOT, n)
    if os.path.exists(p):
        os.remove(p)

run(["git", "config", "user.name", "JustinXai"])
run(["git", "config", "user.email", "xdz199110@gmail.com"])

run(["git", "add", "-A"])
rc, o = run(["git", "status", "--short"])

MSG = """feat: ChatPoster —— 把微信群聊变成一张可直接发群的长图

本地全链路：解密微信 4.x 库 → 结构化分析 → 渲染「宽 1080 / 高随内容」日报图。

- 取数：只读提取 SQLCipher 4 密钥（不做 PBKDF2，32 字节裸 key 直用）
- 解密：page 4096 / reserve 80，WAL 按帧盐过滤，避免旧世代页污染
- 分析：正文前缀还原发送者；非文本消息按 zstd 魔数解压后分类
- 渲染：字段契约硬校验 + 口径自洽软校验，不合格不出图
- 硬规矩：全站不做行数截断，宁可图长也不省略（信息完整优先于版面紧凑）
- 隐私：只读、离线、不注入微信进程；仓库不含任何真实聊天数据

内含本地挂件（127.0.0.1:8756，点群出图）、脱敏示例图与仓库配置说明。"""

run(["git", "commit", "-m", MSG])
run(["git", "branch", "-M", "main"])
run(["git", "remote", "remove", "origin"])
run(["git", "remote", "add", "origin", REMOTE])
rc, o = run(["git", "push", "-u", "origin", "main", "--force"])
push_rc = rc

run(["git", "log", "--oneline", "-3"])
run(["git", "remote", "-v"])

LOG.append("=" * 60)
LOG.append("PUSH_RC=%d" % push_rc)
LOG.append("=" * 60)

open(os.path.join(ROOT, "push_report.txt"), "w", encoding="utf-8").write("\n".join(LOG))
print("\n".join(LOG))
