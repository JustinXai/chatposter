# -*- coding: utf-8 -*-
"""
export_group.py · 导出任意群最近 N 小时的干净稿，并出一张日报图。

用法（只传 ASCII 的群 id，群名自动从库里查，避免中文路径被 shell 截断）：
    python tools/export_group.py                       # 打印群清单供挑选
    python tools/export_group.py 12345678@chatroom
    python tools/export_group.py 12345678@chatroom --hours 48
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

    groups = pipe.find_groups(ACCOUNT, hours)
    if not gid:
        print('共 %d 个群，按最近活跃排序：' % len(groups))
        for g in groups:
            print('  %-34s %-28s %5d 条' % (g['id'], g['name'], g['n24']))
        print('\n用法：python tools/export_group.py <群id> [--hours N]')
        return

    g = next((x for x in groups if x['id'] == gid), None)
    name = g['name'] if g else gid

    msgs = pipe.dump(ACCOUNT, gid, hours)
    texts = [m for m in msgs if m['type'] == 1 and m['text']]

    merged = []
    for m in texts:
        if merged and merged[-1]['who'] == m['who'] and m['ts'] - merged[-1]['ts'] < 300:
            merged[-1]['parts'].append(m['text'])
        else:
            merged.append({'ts': m['ts'], 'who': m['who'], 'parts': [m['text']]})

    safe = re.sub(r'[^\w\u4e00-\u9fa5-]', '', name)[:32] or 'group'
    os.makedirs(pipe.DUMP, exist_ok=True)
    out = os.path.join(pipe.DUMP, '%s-clean.txt' % safe)
    open(out, 'w', encoding='utf-8').write('\n'.join(
        '%s  %s：%s' % (time.strftime('%H:%M', time.localtime(x['ts'])), x['who'],
                        ' / '.join(x['parts'])) for x in merged))

    hours_bin = [0] * 24
    for m in msgs:
        hours_bin[time.localtime(m['ts']).tm_hour] += 1
    rank = Counter(m['who'] for m in texts)
    peak = max(range(24), key=lambda i: hours_bin[i])

    print('群：%s  (%s)' % (name, gid))
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

    a = pipe.analyze(msgs, gid, hours, name=name, shares=pipe.rich_items(ACCOUNT, gid, hours))
    png, _hp = pipe.render(a, safe + '-' + time.strftime('%m%d'))
    print('规则版出图：%s' % png)


if __name__ == '__main__':
    main()
