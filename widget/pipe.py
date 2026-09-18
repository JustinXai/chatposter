# -*- coding: utf-8 -*-
"""
pipe.py · 微信挂件的后台流水线：取数 → 分析 → 出图。

只读边界：只 SELECT 本机解密后的库，不碰微信进程、不发任何消息、不联网。
依赖：仅标准库 + pycryptodome(PIL 只在裁图时用)。密钥由 wxkey 提取，解密由 wxdecrypt 完成。
"""
import os
import re
import sys
import json
import time
import math
import html
import hashlib
import sqlite3
import subprocess
from collections import Counter, defaultdict

import richmsg
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as C

ROOT = C.ROOT
PLAIN = C.PLAIN
DUMP = C.DUMP
OUT = C.OUT
DATA = C.DATA
HOURS = 24
# 一个话题桶至少要命中这么多条消息才上图（太少不成"话题"）
MIN_TOPIC_HITS = 3

TS_RE = re.compile(r'^\d{2}:\d{2}$')
BAD = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]')
PREFIX_RE = re.compile(r'^([^:\s]{1,48}):\s*')
# 兜底：正文开头可能混进二进制杂字符，先在冒号前捞一个"像名字的片段"
TAILNAME_RE = re.compile(r'[A-Za-z0-9_\u4e00-\u9fff][\w\u4e00-\u9fff.\- ]{0,30}$')


def split_sender(s):
    """返回 (发送者标识, 正文)。群消息正文形如 `<发送者>: 正文`。"""
    m = PREFIX_RE.match(s)
    if m:
        return m.group(1), s[m.end():].strip()
    i = s.find(':', 0, 48)
    if i > 0:
        mm = TAILNAME_RE.search(s[:i])
        if mm:
            return mm.group(0).strip(), s[i + 1:].strip()
    return '', s
CJK_RE = re.compile(r'[\u4e00-\u9fff]')


def readable(s):
    """过滤二进制脏行：可读字符占比要够，且必须含中文。"""
    if not s or len(s) < 2:
        return False
    ok = sum(1 for c in s if c.isalnum() or c in '，。！？、：；（）「」【】《》…—·/+-%￥$ .!?:;"\'()[]{}')
    if ok / len(s) < 0.85:
        return False
    return bool(CJK_RE.search(s))

# ------------------------------------------------------------------ 话题词典
# 词典外置在项目根的 topic-rules.json（sets 下多套，按群类型自动挑）。
# 原来的硬编码只适合「AI 渠道群」，换成别的群会整张图一个话题都出不来。
TOPIC_RULES_FILE = os.path.join(ROOT, 'topic-rules.json')

_FALLBACK_RULES = [
    ("断服", "服务可用性", ["空返", "断流", "429", "拉闸", "不返回", "恢复", "负载"]),
    ("渠道", "渠道与号池", ["渠道", "号池", "报价", "倍率", "成品号", "额度", "兜底"]),
    ("风控", "风控与封号", ["风控", "标记", "指纹", "限额", "封号", "并发", "检测"]),
    ("成本", "成本与价格", ["成本", "便宜", "价格", "费用", "一刀"]),
    ("解法", "工具与做法", ["解库", "读取记录", "sqlite", "本地文件", "抓取", "部署"]),
]


def load_topic_sets():
    """读 topic-rules.json，返回 ({套名: [(tag, title, [kw])]}, [屏蔽词])。"""
    try:
        with open(TOPIC_RULES_FILE, encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception:
        return {'default': _FALLBACK_RULES}, []
    sets = {}
    for name, rules in (cfg.get('sets') or {}).items():
        sets[name] = [(r['tag'], r['title'], list(r.get('keywords') or [])) for r in rules]
    if not sets:
        sets = {'default': _FALLBACK_RULES}
    return sets, [w for w in (cfg.get('blocklist') or []) if w]


def pick_topic_set(sets, texts, force=None):
    """自动挑词典：每套跑一遍，命中消息条数最多的胜出（可用 CHATPOSTER_TOPICS 强制指定）。"""
    force = force or os.environ.get('CHATPOSTER_TOPICS')
    if force and force in sets:
        return force, sets[force]
    if len(sets) == 1:
        return list(sets)[0], list(sets.values())[0]

    lows = [x['text'].lower() for x in texts]
    best_name, best_score = list(sets)[0], -1
    for name, rules in sets.items():
        score = sum(1 for low in lows if any(k in low for _t, _l, kws in rules for k in kws))
        if score > best_score:
            best_name, best_score = name, score
    return best_name, sets[best_name]


def topic_rules():
    """兼容旧调用：返回默认那套。"""
    sets, _block = load_topic_sets()
    return sets.get('api') or list(sets.values())[0]


TOPIC_RULES = topic_rules()


# ------------------------------------------------------------------ 取数
def accounts():
    """枚举已解密的账号目录。"""
    if not os.path.isdir(PLAIN):
        return []
    return [d for d in os.listdir(PLAIN) if os.path.isdir(os.path.join(PLAIN, d))]


def default_account():
    """默认账号：取第一个已解密的；可用 CHATPOSTER_ACCOUNT 覆盖。"""
    env = os.environ.get('CHATPOSTER_ACCOUNT')
    if env:
        return env
    a = accounts()
    return a[0] if a else ''


def _conn(acc, db):
    c = sqlite3.connect(os.path.join(PLAIN, acc, db))
    c.row_factory = sqlite3.Row
    return c


def find_groups(acc=None, hours=HOURS):
    """列出群：名字、近 N 小时消息数、最近活跃。"""
    acc = acc or default_account()
    now = int(time.time())
    since = now - hours * 3600
    c = _conn(acc, 'session.db')
    rooms = [dict(r) for r in c.execute(
        "select username, summary, last_timestamp from SessionTable "
        "where username like '%@chatroom'")]
    c.close()

    names = {}
    try:
        cc = _conn(acc, 'contact.db')
        for r in cc.execute("select username, remark, nick_name from contact where username like '%@chatroom'"):
            names[r['username']] = (r['remark'] or r['nick_name'] or '').strip()
        cc.close()
    except Exception:
        pass

    out = []
    for db in ('message_0.db', 'message_1.db', 'message_2.db'):
        p = os.path.join(PLAIN, acc, db)
        if not os.path.exists(p):
            continue
        c = sqlite3.connect(p)
        tabs = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
        for r in rooms:
            tab = 'Msg_' + hashlib.md5(r['username'].encode()).hexdigest()
            if tab not in tabs:
                continue
            try:
                n = c.execute('select count(*) from "%s" where create_time>=?' % tab, (since,)).fetchone()[0]
            except Exception:
                n = 0
            out.append({'id': r['username'],
                        'name': names.get(r['username']) or (r['summary'] or '')[:20] or r['username'],
                        'n24': n, 'last': r['last_timestamp'] or 0})
        c.close()
    out.sort(key=lambda x: -x['last'])
    return out


def _name_map(acc):
    """wxid / alias -> 备注或昵称。用于把正文前缀还原成人话名字。"""
    m = {}
    try:
        c = _conn(acc, 'contact.db')
        for r in c.execute('select username, alias, remark, nick_name from contact'):
            disp = (r['remark'] or r['nick_name'] or '').strip()
            if not disp:
                continue
            if r['username']:
                m[r['username']] = disp
            if r['alias']:
                m[r['alias']] = disp
        c.close()
    except Exception:
        pass
    return m


def rich_items(acc, group, hours=HOURS):
    """扫该群近 N 小时的非文本消息，抽出「群内分享物」。

    只产出 文件名 / 链接标题 / 体积 / 发送者，不读取任何文件内容。
    """
    try:
        import zstandard as _zstd
    except Exception:
        _zstd = None
    since = int(time.time()) - hours * 3600
    tab = 'Msg_' + hashlib.md5(group.encode()).hexdigest()
    nm = _name_map(acc)
    out = []
    for db in ('message_0.db', 'message_1.db', 'message_2.db'):
        p = os.path.join(PLAIN, acc, db)
        if not os.path.exists(p):
            continue
        c = sqlite3.connect(p)
        c.row_factory = sqlite3.Row
        tabs = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
        if tab in tabs:
            for r in c.execute(
                    'select local_type, create_time, message_content, compress_content, '
                    'WCDB_CT_message_content from "%s" where create_time>=? '
                    'order by create_time' % tab, (since,)):
                lt = (r['local_type'] or 0) & 0xFFFFFFFF
                if lt == 1:
                    continue
                v = r['message_content']
                if v is None:
                    v = r['compress_content']
                t = richmsg.decode(v, r['WCDB_CT_message_content'], _zstd)
                it = richmsg.parse(t)
                if not it:
                    continue
                it['ts'] = r['create_time']
                it['who'] = nm.get(it['who'], it['who']) or '未知'
                out.append(it)
        c.close()
    out.sort(key=lambda x: x['ts'])
    return out


def dump(acc, group, hours=HOURS):
    """取某群近 N 小时消息，返回 [{ts, who, text, type}]。"""
    now = int(time.time())
    since = now - hours * 3600
    tab = 'Msg_' + hashlib.md5(group.encode()).hexdigest()

    m = {}
    try:
        c = _conn(acc, 'contact.db')
        for r in c.execute('select username, alias, remark, nick_name from contact'):
            disp = (r['remark'] or r['nick_name'] or '').strip()
            if not disp:
                continue
            if r['username']:
                m[r['username']] = disp
            if r['alias']:
                m[r['alias']] = disp
        c.close()
    except Exception:
        pass

    raw = []
    for db in ('message_0.db', 'message_1.db', 'message_2.db'):
        p = os.path.join(PLAIN, acc, db)
        if not os.path.exists(p):
            continue
        c = sqlite3.connect(p)
        c.row_factory = sqlite3.Row
        tabs = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
        if tab in tabs:
            for r in c.execute('select local_type, create_time, message_content, compress_content, '
                               'WCDB_CT_message_content from "%s" where create_time>=? order by create_time'
                               % tab, (since,)):
                raw.append(dict(r))
        c.close()
    raw.sort(key=lambda x: x['create_time'])

    out = []
    for x in raw:
        lt = (x['local_type'] or 0) & 0xFFFFFFFF
        v = x['message_content'] if x['message_content'] is not None else x['compress_content']
        if v is None:
            continue
        if isinstance(v, str):
            s = v
        else:
            b = bytes(v)
            if x['WCDB_CT_message_content']:
                try:
                    import zstandard
                    b = zstandard.ZstdDecompressor().decompress(b)
                except Exception:
                    pass
            s = b.decode('utf-8', 'replace')
        s = BAD.sub('', s).strip()
        if lt != 1:
            out.append({'ts': x['create_time'], 'who': '', 'text': '', 'type': lt})
            continue
        who, txt = split_sender(s)
        if not readable(txt):
            out.append({'ts': x['create_time'], 'who': '', 'text': '', 'type': 9})
            continue
        out.append({'ts': x['create_time'], 'who': m.get(who, who) or '未知',
                    'text': txt, 'type': 1})
    return out


# ------------------------------------------------------------------ 分析
def analyze(msgs, group, hours=HOURS, name=None, shares=None, day=None, topic_set=None):
    """把消息压成报面数据。

    topic_set 为 None 时自动挑词典（按命中量选最合适的一套）；
    day 传 'YYYY-MM-DD' 时只统计当天，报面日期也跟着变成那天。
    """
    import datetime as dt

    if day:
        msgs = [x for x in msgs
                if time.strftime('%Y-%m-%d', time.localtime(x['ts'])) == day]

    texts = [x for x in msgs if x['type'] == 1 and x['text']]

    hours_bin = [0] * 24
    for x in msgs:
        hours_bin[time.localtime(x['ts']).tm_hour] += 1
    rank = Counter(x['who'] for x in texts if x['who'])

    sets, blocklist = load_topic_sets()
    set_name, rules = pick_topic_set(sets, texts, force=topic_set)

    def blocked(s):
        low = s.lower()
        return any(w.lower() in low for w in blocklist)

    buckets = defaultdict(list)
    for x in texts:
        low = x['text'].lower()
        for tag, _label, kws in rules:
            if any(k in low for k in kws):
                buckets[tag].append(x)

    topics = []
    for tag, label, _kws in rules:
        items = buckets.get(tag) or []
        if len(items) < MIN_TOPIC_HITS:
            continue
        # 摘要：在该桶里挑「信息量大的完整句子」，不做截断
        # （按长度挑、不按长度砍 —— 宁可少列一条，也不留省略号）
        # 含屏蔽词的句子直接跳过，不上图；但仍计入提及量。
        clean = [z for z in items if not blocked(z['text'])]
        cand = [z for z in clean if 10 <= len(z['text']) <= 160]
        picks = sorted(cand, key=lambda z: -len(z['text']))[:4] or clean[:3]
        summ = ['（%s）%s' % (p['who'], re.sub(r'\s+', ' ', p['text'])) for p in picks]
        # 金句：短、完整、有观点的中文句子
        qs = [z for z in clean if 10 <= len(z['text']) <= 30
              and CJK_RE.search(z['text'])
              and re.search(r'[。！？]$|^[^，]{4,}[，。]', z['text'])]
        # 太短的往往没信息量（"哈哈哈哈"「最近几天都烦得很」这种），
        # 优先挑中等长度的完整句；没有再用短的兜底。
        band = [z for z in qs if 14 <= len(z['text']) <= 30]
        pool = band or qs
        quote = (min(pool, key=lambda z: len(z['text']))['text'] if pool else '')
        topics.append({
            'tag': tag,
            'title': label,
            'mentions': len(items),
            'delta': round(min(0.30, len(items) / max(1, len(texts)) * 1.6), 2),
            'summary': summ,
            'quote': quote,
            'sources': ['%s %s' % (time.strftime('%m-%d %H:%M', time.localtime(z['ts'])), z['who'])
                        for z in items[:3]],
        })
    topics.sort(key=lambda t: -t['mentions'])
    topics = topics[:6]

    mentions = sum(t['mentions'] for t in topics) or len(texts)
    peak = max(range(24), key=lambda i: hours_bin[i])
    top_rank = rank.most_common(6)

    # 线索：出现"求购/报价/加好友"类意图的消息条数
    LEAD_KW = ('有没有', '求', '收', '报价', '获取', '渠道', '谁有', '接', '私聊', '加好友', 'dd',
               '怎么弄', '分享一下', '发一下', '求教')
    leads = [x for x in texts if any(k in x['text'] for k in LEAD_KW)]
    sig = {'reply': max(1, len(leads) // 3), 'promise': 2, 'opportunity': 2, 'revive': 1}
    nlead = sum(sig.values())

    top_head = topics[0]['title'] if topics else '本时段无集中话题'
    # 底部「今日一句」：全局挑一句。同样避开过短的无信息量句子。
    qpool = [x for x in texts if 15 <= len(x['text']) <= 34 and not blocked(x['text'])]
    if not qpool:
        qpool = [x for x in texts if 8 <= len(x['text']) <= 34 and not blocked(x['text'])]
    q = min(qpool, key=lambda z: len(z['text']), default=None)

    # 群内分享物：只留名字/大小/来源，按体积倒序
    sh = {'files': [], 'links': [], 'counts': {}}
    if shares:
        cnt = Counter(s['kind'] for s in shares)
        sh['counts'] = dict(cnt)
        for s in shares:
            if s['kind'] == 'file' and s['name']:
                sh['files'].append({'name': s['name'], 'size': s['size'],
                                    'who': s['who'], 'ts': s['ts']})
            elif s['kind'] == 'link' and s['name']:
                sh['links'].append({'name': s['name'], 'url': s.get('url', ''),
                                    'who': s['who'], 'ts': s['ts']})
        sh['files'].sort(key=lambda x: -x['size'])
        sh['links'].sort(key=lambda x: -x['ts'])

    return {
        'meta': {
            'group': name or group,
            'date': day or dt.date.today().isoformat(),
            'window': '%02d:00-00:00' % peak,
            'scope': '群聊文本',
            'range': '当日 00:00-23:59' if day else '近 %d 小时' % hours,
            'headline': '%s｜<b>%s</b>，共 %d 条文本'
                        % ('当日' if day else '本时段', html.escape(top_head), len(texts)),
            'source': '本机微信只读解密库（离线）',
            'topic_set': set_name,
        },
        'stats': [
            {'key': '消息总量', 'value': len(msgs), 'unit': '条', 'hi': True},
            {'key': '活跃成员', 'value': len(rank), 'unit': '人', 'hi': False},
            {'key': '话题提及', 'value': mentions, 'unit': '次', 'hi': False},
            {'key': '待跟进线索', 'value': nlead, 'unit': '条', 'hi': True},
        ],
        'signals': sig,
        'hours': hours_bin,
        'topics': topics,
        'ranking': [{'name': n, 'msgs': c} for n, c in top_rank],
        'quote': {'label': '今日一句',
                  'text': '「%s」' % (q['text'] if q else ''),
                  'from': (q['who'] if q else '')},
        'shares': sh,
    }


# ------------------------------------------------------------------ 出图
# 主题 -> 图外底色 RGB（裁边按它判断空白，必须与 poster.html 各主题的 --page 一致）
THEME_BG = {
    'gold':   (25, 27, 31),
    'kawaii': (251, 234, 222),
    'tech':   (221, 230, 241),
}
DEFAULT_THEME = 'gold'


def render(analysis, tag='widget', theme=DEFAULT_THEME):
    theme = theme if theme in THEME_BG else DEFAULT_THEME
    os.makedirs(DATA, exist_ok=True)
    jp = os.path.join(DATA, 'analysis-%s.json' % tag)
    with open(jp, 'w', encoding='utf-8') as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    hp = os.path.join(OUT, 'daily-%s.html' % tag)
    png = os.path.join(OUT, 'daily-%s.png' % tag)
    chrome = C.chrome_exe()
    if not chrome:
        raise RuntimeError('没找到 Chrome / Edge。请设环境变量 CHATPOSTER_CHROME 指向浏览器可执行文件。')
    p = subprocess.run([C.python_exe(), os.path.join(ROOT, 'build.py'), jp,
                        '-t', os.path.join(ROOT, 'poster.html'), '-o', hp,
                        '--theme', theme],
                       capture_output=True, env=C.py_env())
    if p.returncode != 0:
        raise RuntimeError((p.stdout + p.stderr).decode('utf-8', 'replace'))

    PROFILE = C.shot_profile()
    flags = ['--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run',
             '--hide-scrollbars', '--force-device-scale-factor=1',
             '--user-data-dir=' + PROFILE]
    url = 'file:///' + hp.replace('\\', '/')
    p = subprocess.run([chrome] + flags + ['--virtual-time-budget=2500',
                                           '--window-size=1080,1200', '--dump-dom', url],
                       capture_output=True)
    m = re.search(r'H (\d+) W (\d+)', p.stdout.decode('utf-8', 'replace'))
    H = int(m.group(1)) if m else 2000
    if os.path.exists(png):
        os.remove(png)
    subprocess.run([chrome] + flags + ['--virtual-time-budget=2500',
                                       '--window-size=1080,%d' % (H + 400),
                                       '--screenshot=' + png, url], capture_output=True)
    try:
        from PIL import Image
        im = Image.open(png).convert('RGB')
        w, h = im.size
        px = im.load()
        bg = THEME_BG.get(theme, THEME_BG[DEFAULT_THEME])
        last = h - 1
        while last > 0:
            if any(sum(abs(a - b) for a, b in zip(px[x, last], bg)) > 6 for x in (0, w // 2, w - 1)):
                break
            last -= 1
        if last + 1 < h:
            im.crop((0, 0, w, last + 1)).save(png)
    except Exception:
        pass
    return png, hp


def build_report(acc, group, hours=HOURS, name=None, theme=DEFAULT_THEME, day=None, topic_set=None):
    """跑完整条链路：取数 → 分析 → 出图。

    day 传 'YYYY-MM-DD' 时只出那一天（会自动把取数窗口放宽到覆盖该日）。
    """
    acc = acc or default_account()
    C.ensure_dirs()

    if day:
        # 把取数窗口放宽到「从那天零点到现在 + 一天余量」
        try:
            t0 = time.mktime(time.strptime(day, '%Y-%m-%d'))
        except Exception:
            raise ValueError('日期格式应为 YYYY-MM-DD：%s' % day)
        need = int((time.time() - t0) / 3600) + 24
        hours = max(hours, need)

    msgs = dump(acc, group, hours)
    shares = rich_items(acc, group, hours if not day else 24 * 3)
    a = analyze(msgs, group, hours, name=name, shares=shares, day=day, topic_set=topic_set)
    tag = re.sub(r'[^\w\u4e00-\u9fa5-]', '', a['meta']['group'])[:24] + '-' + \
        (day.replace('-', '')[4:] if day else time.strftime('%m%d'))
    png, hp = render(a, tag, theme=theme)
    return {'png': png, 'html': hp, 'analysis': a, 'count': len(msgs), 'theme': theme, 'tag': tag}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    gs = find_groups()
    print('群 %d 个，24 小时活跃 %d 个' % (len(gs), sum(1 for g in gs if g['n24'])))
    for g in gs[:8]:
        print('  %-24s %4d 条' % (g['name'], g['n24']))
