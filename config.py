# -*- coding: utf-8 -*-
"""
config.py · 全局配置（唯一一处放本机路径的地方）

所有路径都可以用环境变量覆盖，默认值按各平台常见位置猜测。
不要在这里写死任何账号、密钥、真实群名。
"""
import os
import sys
import shutil
import tempfile

# ----------------------------------------------------------------- 项目根
ROOT = os.environ.get("CHATPOSTER_ROOT") or os.path.dirname(os.path.abspath(__file__))

OUT = os.path.join(ROOT, "out")
DATA = os.path.join(ROOT, "data")
PLAIN = os.environ.get("CHATPOSTER_PLAIN") or os.path.join(OUT, "wx_plain")
DUMP = os.path.join(OUT, "wx_dump")
KEYS_FILE = os.environ.get("CHATPOSTER_KEYS") or os.path.join(OUT, "wx_keys.json")

# ----------------------------------------------------------------- 微信数据目录
# 微信 4.x 的数据根。默认扫盘下最常见的几个位置，扫不到就靠环境变量指定。
_DEFAULT_WX_ROOTS = [
    r"D:\Documents\xwechat_files",
    r"C:\Users\%s\Documents\xwechat_files" % os.environ.get("USERNAME", ""),
    r"C:\Users\%s\Documents\WeChat Files" % os.environ.get("USERNAME", ""),
    r"D:\WeChat Files",
    r"E:\WeChat Files",
]


def wx_roots():
    """返回存在的微信数据根目录列表。CHATPOSTER_WX_ROOT 可用 ; 分隔多个。"""
    env = os.environ.get("CHATPOSTER_WX_ROOT")
    cands = [p for p in env.split(";") if p] if env else _DEFAULT_WX_ROOTS
    return [p for p in cands if p and os.path.isdir(p)]


def account_dirs():
    """返回所有 <账号目录>/db_storage 的路径。"""
    out = []
    for root in wx_roots():
        try:
            entries = os.listdir(root)
        except Exception:
            continue
        for name in entries:
            d = os.path.join(root, name, "db_storage")
            if os.path.isdir(d):
                out.append(d)
    return out


# ----------------------------------------------------------------- 落款 / 联系方式
# 报的右下角可以放「名字 + 二维码」，方便读者扫码加你。
# 两种给法：
#   1) 分析稿 JSON 里写 contact 字段（优先级最高，示例数据就是这么写的）
#   2) 什么都不写，在这里用环境变量配一次，之后每张图都带上
CONTACT_NAME = os.environ.get("CHATPOSTER_CONTACT_NAME") or ""
CONTACT_ROLE = os.environ.get("CHATPOSTER_CONTACT_ROLE") or ""
CONTACT_NOTE = os.environ.get("CHATPOSTER_CONTACT_NOTE") or "扫码加我"
# 二维码图片：默认找 assets/qr.png，也可以用环境变量指到任意位置
QR_FILE = os.environ.get("CHATPOSTER_QR") or os.path.join(ROOT, "assets", "qr.png")


# ----------------------------------------------------------------- 运行时
def python_exe():
    """当前解释器。子进程复用同一个，避免写死某个绝对路径。"""
    return os.environ.get("CHATPOSTER_PY") or sys.executable


def chrome_exe():
    """找一个可用的 Chrome / Edge 无头内核。"""
    env = os.environ.get("CHATPOSTER_CHROME")
    if env and os.path.isfile(env):
        return env
    cands = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
    ]
    for p in cands:
        if p and os.path.isfile(p):
            return p
    for exe in ("chrome", "google-chrome", "chromium", "msedge"):
        p = shutil.which(exe)
        if p:
            return p
    return ""


def shot_profile():
    """无头浏览器用的临时 profile 目录。"""
    return os.path.join(tempfile.gettempdir(), "chatposter_shot_profile")


def py_env():
    """子进程环境：确保中文输出不乱码。"""
    return dict(os.environ, PYTHONIOENCODING="utf-8")


def ensure_dirs():
    for d in (OUT, DATA):
        os.makedirs(d, exist_ok=True)
