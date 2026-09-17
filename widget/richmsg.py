# -*- coding: utf-8 -*-
"""
richmsg.py · 从「应用消息 / 图片 / 视频」的 XML 里抽出「群内分享物」。

微信 4.x 消息正文规则（实测）：
    message_content 前 4 字节 = 0x28 b5 2f fd —— 这正是 zstd 魔数，整段就是 zstd 帧；
    WCDB_CT_message_content = 4 表示已压缩。解压后是 XML（可能带 "发送者: " 前缀）。
    短文本消息则跳过 10 字节容器头后即为 UTF-8 明文。

隐私红线：本模块只产出「文件名 / 链接标题 / 体积 / 发送者」，
          **绝不读取或落盘任何文件内容**。
"""
import re

XML_HEAD_RE = re.compile(r'^([^:<\n]{1,48}):\s*(?=<)', re.S)


def _tag(t):
    return re.compile(r'<%s[^>]*>(.*?)</%s>' % (t, t), re.S)


RE_TITLE = _tag('title')
RE_TYPE = _tag('type')
RE_URL = _tag('url')
RE_TOTALLEN = _tag('totallen')
RE_FILENAME = _tag('filename')
RE_DES = _tag('des')
RE_IMG = re.compile(r'<img\b[^>]*aeskey="([0-9a-fA-F]{16,64})"')
RE_VIDEO = re.compile(r'<videomsg\b')
RE_EMOJI = re.compile(r'<emoji\b')
RE_LOC = re.compile(r'<location\b')

EXT_RE = re.compile(r'\.([A-Za-z0-9]{1,8})$')
DOC_EXT = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'md', 'csv', 'rtf',
    'zip', 'rar', '7z', 'tar', 'gz', 'apk', 'exe', 'dmg', 'iso',
    'mp4', 'mov', 'avi', 'mkv', 'mp3', 'm4a', 'wav', 'flac',
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg',
    'html', 'htm', 'json', 'xml', 'py', 'js', 'ts', 'java', 'go', 'sql', 'sh',
    'psd', 'ai', 'sketch', 'fig', 'epub', 'mobi', 'numbers', 'pages', 'key',
}

TYPE_KIND = {
    '5': 'link', '4': 'link', '3': 'music', '33': 'miniprogram', '36': 'miniprogram',
    '44': 'miniprogram', '62': 'video', '63': 'live', '51': 'channels',
    '19': 'chatrecord', '87': 'chatrecord', '2001': 'redpacket', '2000': 'transfer',
    '57': 'quote', '48': 'location', '17': 'realtime_location',
    '6': 'file', '74': 'file',
}


def decode(blob, compressed_flag, zstd_mod=None):
    """把 message_content 还原成字符串（XML 或纯文本），失败返回 None。"""
    if blob is None:
        return None
    if not isinstance(blob, bytes):
        try:
            blob = bytes(blob)
        except Exception:
            return str(blob)
    if zstd_mod is not None and blob[:4] == b'\x28\xb5\x2f\xfd':
        try:
            return zstd_mod.ZstdDecompressor().decompress(
                blob, max_output_size=1 << 20).decode('utf-8', 'ignore')
        except Exception:
            pass
    for off in (10, 0, 8, 12, 16):
        if off >= len(blob):
            continue
        chunk = blob[off:]
        if b'\x01\x00' in chunk:
            chunk = chunk.split(b'\x01\x00')[0]
        try:
            t = chunk.decode('utf-8')
        except UnicodeDecodeError:
            continue
        if t and sum(1 for c in t if c.isprintable()) / len(t) > 0.9:
            return t
    return None


def parse(text, fallback_who=''):
    """把解出来的 XML 归类。返回 dict 或 None（引用类直接丢弃）。"""
    if not text:
        return None
    who = fallback_who
    m = XML_HEAD_RE.match(text)
    if m:
        who = m.group(1).strip()
        text = text[m.end():].lstrip()
    if not text.lstrip().startswith('<'):
        return None

    def first(rx):
        mm = rx.search(text)
        if not mm:
            return ''
        v = mm.group(1).strip()
        if v.startswith('<![CDATA['):          # 去掉 CDATA 包裹
            v = v[9:]
        if v.endswith(']]>'):
            v = v[:-3]
        return v.strip()

    title = first(RE_TITLE)
    atype = first(RE_TYPE)
    url = first(RE_URL)
    total = first(RE_TOTALLEN)
    size = int(total) if total.isdigit() else 0

    ext = ''
    if title:
        m2 = EXT_RE.search(title.strip())
        if m2:
            ext = m2.group(1).lower()

    if atype in ('6', '74') or (ext in DOC_EXT and total.isdigit()):
        return {'kind': 'file', 'name': title or first(RE_FILENAME),
                'size': size, 'who': who, 'type': atype or '6'}
    if RE_IMG.search(text):
        return {'kind': 'image', 'name': '', 'size': 0, 'who': who, 'type': '3'}
    if RE_VIDEO.search(text):
        return {'kind': 'video', 'name': title, 'size': size, 'who': who, 'type': '43'}
    if RE_EMOJI.search(text):
        return {'kind': 'emoji', 'name': '', 'size': 0, 'who': who, 'type': '47'}
    if RE_LOC.search(text):
        return {'kind': 'location', 'name': '', 'size': 0, 'who': who, 'type': '48'}

    kind = TYPE_KIND.get(atype)
    if kind == 'quote':
        return None
    if kind == 'link':
        dom = ''
        mm = re.match(r'https?://([^/]+)', url or '')
        if mm:
            dom = mm.group(1)
        return {'kind': 'link', 'name': title, 'size': 0, 'who': who,
                'type': atype, 'url': dom, 'mp': 'mp.weixin.qq.com' in (url or '')}
    if kind:
        return {'kind': kind, 'name': title, 'size': size, 'who': who, 'type': atype}
    return {'kind': 'app', 'name': title, 'size': size, 'who': who, 'type': atype or '?'}


def fmt_size(n):
    if not n:
        return ''
    for u, d in (('GB', 1 << 30), ('MB', 1 << 20), ('KB', 1 << 10)):
        if n >= d:
            return '%.1f %s' % (n / d, u)
    return '%d B' % n
