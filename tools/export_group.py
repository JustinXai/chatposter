# -*- coding: utf-8 -*-
"""
export_group.py · 导出任意群最近 N 小时的干净稿，并出一张日报图。

用法（只传 ASCII 的群 id，群名自动从库里查，避免中文路径被 shell 截断）：
    python tools/export_group.py                       # 打印群清单供挑选
    python tools/export_group.py 12345678@chatroom
    python tools/export_group.py 12345678@chatroom --hours 48
    python tools/export_group.py 12345678@chatroom --theme tech        # gold / kawaii / tech
    python tools/export_group.py 12345678@chatroom --day 2026-09-07    # 只出某一天（群安静时用）
"""
import os
import re
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'widget'))
import pipe  # noqa: E402

ACCOUNT = pipe.default_account()


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    gid = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else None
    hours = 24
    if '--hours' in sys.argv:
        hours = int(sys.argv[sys.argv.index('--hours') + 1])
    theme = pipe.DEFAULT_THEME
    if '--theme' in sys.argv:
        theme = sys.argv[sys.argv.index('--theme') + 1]
        if theme not in pipe.THEME_BG:
            print('主题只能是：%s' % ' / '.join(pipe.THEME_BG))
            return
    day = None
    if '--day' in sys.argv:
        day = sys.argv[sys.argv.index('--day') + 1]
        try:
            time.strptime(day, '%Y-%m-%d')
        except Exception:
            print('日期格式应为 YYYY-MM-DD，例如 --day 2026-09-07')
            return

    groups = pipe.find_groups(ACCOUNT, hours)
    if not gid:
        print('共 %d 个群，按最近活跃排序：' % len(groups))
        for g in groups:
            print('  %-34s %-28s %5d 条' % (g['id'], g['name'], g['n24']))
        print('\n用法：python tools/export_group.py <群id> [--hours N] [--theme %s] [--day YYYY-MM-DD]'
              % '|'.join(pipe.THEME_BG))
        return

    g = next((x for x in groups if x['id'] == gid), None)
    name = g['name'] if g else gid

    # 按天出图时，把取数窗口放宽到覆盖那天
    fetch_hours = hours
    if day:
        t0 = time.mktime(time.strptime(day, '%Y-%m-%d'))
        fetch_hours = max(hours, int((time.time() - t0) / 3600) + 24)

    msgs_all = pipe.dump(ACCOUNT, gid, fetch_hours)
    if day:
        msgs = [m for m in msgs_all
                if time.strftime('%Y-%m-%d', time.localtime(m['ts'])) == day]
    else:
        msgs = msgs_all
    texts = [m for m in msgs if m['type'] == 1 and m['text']]

    merged = []
    for m in texts:
        if merged and merged[-1]['who'] == m['who'] and m['ts'] - merged[-1]['ts'] < 300:
            merged[-1]['parts'].append(m['text'])
        else:
            merged.append({'ts': m['ts'], 'who': m['who'], 'parts': [m['text']]})

    safe = re.sub(r'[^\w\u4e00-\u9fa5-]', '', name)[:32] or 'group'
    os.makedirs(pipe.DUMP, exist_ok=True)
    out = os.path.join(pipe.DUMP, '%s-clean%s.txt' % (safe, ('-' + day) if day else ''))
    open(out, 'w', encoding='utf-8').write('\n'.join(
        '%s  %s：%s' % (time.strftime('%H:%M', time.localtime(x['ts'])), x['who'],
                        ' / '.join(x['parts'])) for x in merged))

    hours_bin = [0] * 24
    for m in msgs:
        hours_bin[time.localtime(m['ts']).tm_hour] += 1
    rank = Counter(m['who'] for m in texts)
    peak = max(range(24), key=lambda i: hours_bin[i])

    print('群：%s  (%s)' % (name, gid))
    if day:
        print('范围：%s 当日 00:00-23:59' % day)
    print('消息 %d 条（文本 %d），合并成 %d 行' % (len(msgs), len(texts), len(merged)))
    print('稿子：%s (%.1f KB)' % (out, os.path.getsize(out) / 1024))
    print('hours   : %s' % hours_bin)
    print('sum     : %d' % sum(hours_bin))
    print('峰值    : %02d:00 (%d)' % (peak, hours_bin[peak]))
    print('发言人数: %d' % len(rank))
    print('排行 Top12：')
    for n, c in rank.most_common(12):
        print('   %-24s %d' % (n, c))
    print('Top6 合计: %d' % sum(c for _, c in rank.most_common(6)))

    shares = pipe.rich_items(ACCOUNT, gid, 24 * 3 if day else hours)
    a = pipe.analyze(msgs_all if day else msgs, gid, fetch_hours if day else hours,
                     name=name, shares=shares, day=day)
    print('话题词典: %s  →  话题 %d 个'
          % (a['meta'].get('topic_set'), len(a['topics'])))
    for t in a['topics']:
        print('   [%s] %s  提及 %d' % (t['tag'], t['title'], t['mentions']))

    tag = safe + '-' + (day.replace('-', '')[4:] if day else time.strftime('%m%d'))
    png, _hp = pipe.render(a, tag, theme=theme)
    print('规则版出图：%s' % png)


if __name__ == '__main__':
    main()
