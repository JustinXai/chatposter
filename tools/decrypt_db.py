# -*- coding: utf-8 -*-
"""
wxdecrypt2.py · 用提取到的密钥把库解成普通 SQLite（原库只读）。

参数（已按实测校正）：
  page 4096，reserve 80 = IV(16) + HMAC(64)
  enc_key  = 32 字节裸 key（直接作 AES-256 密钥）
  第 1 页：明文头 "SQLite format 3\\0" + AES-CBC(enc, iv, page[16:4016]) + 80 个 0
  其余页：AES-CBC(enc, iv, page[0:4016]) + 80 个 0
  iv 位置 = page[4016:4032]
WAL：只合并帧盐与 WAL 头一致的帧（预分配 WAL 里残留旧世代帧，不过滤会解出坏页）。
"""
import ctypes  # noqa
import os
import sys
import json
import struct
import glob

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as C  # noqa: E402
from Crypto.Cipher import AES

PAGE = 4096
RESERVE = 80
ROOT = C.PLAIN
KEYS = C.KEYS_FILE


def aes(key, iv, data):
    return AES.new(key, AES.MODE_CBC, iv).decrypt(data)


def load_keys():
    with open(KEYS, encoding='utf-8') as f:
        return json.load(f)


def dec_page(key, page, pgno):
    iv = page[PAGE - RESERVE: PAGE - RESERVE + 16]
    if pgno == 1:
        return b'SQLite format 3\x00' + aes(key, iv, page[16: PAGE - RESERVE]) + b'\x00' * RESERVE
    return aes(key, iv, page[: PAGE - RESERVE]) + b'\x00' * RESERVE


def merge_wal(path, key, pages):
    wal = path + '-wal'
    if not os.path.exists(wal):
        return 0, 0
    data = open(wal, 'rb').read()
    if len(data) < 32:
        return 0, 0
    magic, ver, psz, seq = struct.unpack('>IIII', data[:16])
    salt1, salt2 = struct.unpack('>II', data[16:24])
    if magic not in (0x377f0682, 0x377f0683) or psz != PAGE:
        return 0, 0
    frame = 24 + psz
    n = (len(data) - 32) // frame
    last = -1
    for i in range(n):
        off = 32 + i * frame
        if struct.unpack('>I', data[off + 4:off + 8])[0]:
            last = i
    if last < 0:
        return 0, 0
    applied = skipped = 0
    for i in range(last + 1):
        off = 32 + i * frame
        pgno = struct.unpack('>I', data[off:off + 4])[0]
        f_s1, f_s2 = struct.unpack('>II', data[off + 8:off + 16])
        if (f_s1, f_s2) != (salt1, salt2):      # 旧世代帧，跳过
            skipped += 1
            continue
        body = data[off + 24: off + 24 + psz]
        if len(body) < psz or not pgno:
            continue
        pages[pgno] = dec_page(key, body, pgno)
        applied += 1
    return applied, skipped


def one(acc, rel, path, keys):
    tag = '%s/%s' % (acc, rel)
    ks = keys.get(tag)
    if not ks:
        return None
    kb = bytes.fromhex(ks)
    key, salt = kb[:32], kb[32:] if len(kb) >= 48 else None
    raw = open(path, 'rb').read()
    npage = len(raw) // PAGE
    pages = {}
    for i in range(npage):
        p = raw[i * PAGE:(i + 1) * PAGE]
        if len(p) < PAGE:
            break
        pages[i + 1] = dec_page(key, p, i + 1)
    ap, sk = merge_wal(path, key, pages)
    out = os.path.join(ROOT, acc, rel)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'wb') as f:
        for n in sorted(pages):
            f.write(pages[n])
    return out, len(pages), ap, sk


def main():
    keys = load_keys()
    targets = []
    for d in C.account_dirs():
        acc = os.path.basename(os.path.dirname(d))
        for root, _dr, files in os.walk(d):
            for f in files:
                if f.endswith('.db'):
                    targets.append((acc, f, os.path.join(root, f)))
    if not targets:
        print('！没找到待解密的库。请设 CHATPOSTER_WX_ROOT 指向 xwechat_files。')
        return

    ok = fail = 0
    import sqlite3
    for acc, rel, path in targets:
        try:
            r = one(acc, rel, path, keys)
        except Exception as e:
            print('  [x] %s/%s  %s' % (acc, rel, e))
            fail += 1
            continue
        if not r:
            continue
        outp, np_, ap, sk = r
        try:
            con = sqlite3.connect(outp)
            tabs = con.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
            con.execute('pragma quick_check').fetchone()
            con.close()
            print('  [√] %-16s %-22s %5d 页 WAL合并%4d 跳过%4d  表%3d'
                  % (acc, rel, np_, ap, sk, tabs))
            ok += 1
        except Exception as e:
            print('  [!] %-16s %-22s 解出来打不开：%s' % (acc, rel, e))
            fail += 1
    print('\n成功 %d，失败 %d，输出目录 %s' % (ok, fail, ROOT))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
