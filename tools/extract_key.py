# -*- coding: utf-8 -*-
"""
wxkey9.py · 自研密钥提取（只读），复现 WCDB 配置对象解法。

链路：
  1) 只读打开 Weixin.exe（0x0010|0x0400，不写、不注入）
  2) 找 "com.Tencent.WCDB.Config.Cipher" 的地址 → 拼成 [addr][len] 对
  3) 全内存搜这个对，命中处往回 0x10 就是配置节点
  4) 节点 +0x28 → 配置对象；对象 +0x88 → {+0x8: 数据指针, +0x10: 长度}
  5) 读出数据块，与 32 字节常量掩码异或 → 得到明文 x'<64hex 密钥>[<32hex 盐>]'
  6) 用 SQLCipher 原始密钥的 HMAC 规则逐库校验，通过的就是真密钥

边界：只用 ReadProcessMemory，全程不写入微信进程。
"""
import ctypes
import ctypes.wintypes as wt
import subprocess
import json
import re
import struct
import hashlib
import hmac
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as C  # noqa: E402

PAGE = 4096
RESERVE = 80                      # IV(16) + HMAC(64)
NAME = b"com.Tencent.WCDB.Config.Cipher"
MASK = bytes.fromhex(
    "d2c7442458020000004889442450488b"
    "450048844c2448488944254048584c24"
)
HEX_RE = re.compile(rb"[xX]'([0-9a-fA-F]{64,192})'")

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.VirtualQueryEx.restype = ctypes.c_size_t
PQI, PVR = 0x0400, 0x0010
MEM_COMMIT, PAGE_NOACCESS, PAGE_GUARD = 0x1000, 0x01, 0x100


class MBI(ctypes.Structure):
    _fields_ = [('BaseAddress', ctypes.c_void_p), ('AllocationBase', ctypes.c_void_p),
                ('AllocationProtect', wt.DWORD), ('__a1', wt.DWORD),
                ('RegionSize', ctypes.c_size_t), ('State', wt.DWORD),
                ('Protect', wt.DWORD), ('Type', wt.DWORD), ('__a2', wt.DWORD)]


def pids():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV", "/NH"],
                       capture_output=True, text=True)
    out = []
    for line in r.stdout.strip().splitlines():
        p = line.strip('"').split('","')
        if len(p) >= 2 and p[1].isdigit():
            out.append(int(p[1]))
    return out


def find_bytes(h, needle, cap=64):
    hits = []
    buf = ctypes.create_string_buffer(8 << 20)
    br = ctypes.c_size_t(0)
    mbi = MBI()
    addr = 0
    while k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        base, size = mbi.BaseAddress or 0, mbi.RegionSize
        if (mbi.State == MEM_COMMIT and not (mbi.Protect & PAGE_GUARD)
                and mbi.Protect != PAGE_NOACCESS and size and size < (1 << 31)):
            off = 0
            while off < size and len(hits) < cap:
                n = min(len(buf), size - off)
                if k32.ReadProcessMemory(h, ctypes.c_void_p(base + off), buf, n,
                                         ctypes.byref(br)) and br.value:
                    data = buf.raw[:br.value]
                    i = data.find(needle)
                    while i >= 0 and len(hits) < cap:
                        hits.append(base + off + i)
                        i = data.find(needle, i + 1)
                off += n
        nxt = base + size
        if nxt <= addr:
            break
        addr = nxt
    return hits


def verify(enc_key, page1, salt=None):
    """SQLCipher 原始密钥校验：比对第 1 页尾部的 HMAC-SHA512。"""
    if len(page1) < PAGE:
        return False
    if len(enc_key) == 48 and salt is None:
        enc_key, salt = enc_key[:32], enc_key[32:]
    if salt is None:
        salt = page1[:16]
    elif len(salt) != 16:
        return False
    mac_salt = bytes(b ^ 0x3A for b in salt)
    mac_key = hashlib.pbkdf2_hmac('sha512', enc_key, mac_salt, 2, dklen=32)
    data = page1[16: PAGE - RESERVE + 16]
    stored = page1[PAGE - 64: PAGE]
    hm = hmac.new(mac_key, data, hashlib.sha512)
    hm.update(struct.pack('<I', 1))
    return hm.digest() == stored


def probable(b):
    return len(b) == 32 and len(set(b)) >= 15 and b != b'\x00' * 32 and b != b'\xff' * 32


def db_files():
    """枚举待解密的库。目录来自 config（可用 CHATPOSTER_WX_ROOT 覆盖）。"""
    out = []
    dirs = C.account_dirs()
    if not dirs:
        print('！没找到微信数据目录。请设环境变量 CHATPOSTER_WX_ROOT 指向 xwechat_files。')
    for d in dirs:
        acc = os.path.basename(os.path.dirname(d))
        for root, _dirs, files in os.walk(d):
            for f in files:
                if f.endswith('.db'):
                    out.append((acc, f, os.path.join(root, f)))
    return out


def main():
    dbs = db_files()
    print('待解库 %d 个' % len(dbs))
    keys = {}

    def try_key(cand, extra_salt=None):
        got = 0
        for acc, rel, path in dbs:
            tag = '%s/%s' % (acc, rel)
            if tag in keys:
                continue
            try:
                with open(path, 'rb') as f:
                    page1 = f.read(PAGE)
            except Exception:
                continue
            for salt in ([extra_salt] if extra_salt else [None]):
                if verify(cand, page1, salt=salt):
                    keys[tag] = (cand + (salt or b'')).hex()
                    print('    [√] %-40s  key=%s%s' % (tag, cand.hex(),
                                                       ' salt=' + salt.hex() if salt else ''))
                    got += 1
        return got

    for pid in pids():
        h = k32.OpenProcess(PQI | PVR, False, pid)
        if not h:
            print('pid=%s 打不开（可能需要管理员权限）err=%s' % (pid, ctypes.get_last_error()))
            continue
        try:
            needles = find_bytes(h, NAME, cap=8)
            print('pid=%s 名字命中 %d 处' % (pid, len(needles)))
            if not needles:
                continue
            pairs = [struct.pack('<Q', a) + struct.pack('<Q', len(NAME)) for a in needles]
            total = 0
            for pair in pairs:
                for qaddr in find_bytes(h, pair, cap=64):
                    node = ctypes.create_string_buffer(0x50)
                    br = ctypes.c_size_t(0)
                    if not k32.ReadProcessMemory(h, ctypes.c_void_p(qaddr - 0x10), node, 0x50,
                                                 ctypes.byref(br)) or br.value < 0x40:
                        continue
                    nb = node.raw[:0x40]
                    if struct.unpack_from('<Q', nb, 0x10)[0] not in needles:
                        continue
                    if struct.unpack_from('<Q', nb, 0x18)[0] != len(NAME):
                        continue
                    cfg = struct.unpack_from('<Q', nb, 0x28)[0]
                    if not (0x10000 <= cfg < 0x800000000000):
                        continue
                    obj = ctypes.create_string_buffer(0x28)
                    if not k32.ReadProcessMemory(h, ctypes.c_void_p(cfg + 0x88), obj, 0x28,
                                                 ctypes.byref(br)) or br.value < 0x18:
                        continue
                    ob = obj.raw[:0x28]
                    dptr = struct.unpack_from('<Q', ob, 0x8)[0]
                    dlen = struct.unpack_from('<Q', ob, 0x10)[0]
                    if not (0 < dlen <= 1024 and 0x10000 <= dptr < 0x800000000000):
                        continue
                    blob = ctypes.create_string_buffer(dlen)
                    if not k32.ReadProcessMemory(h, ctypes.c_void_p(dptr), blob, dlen,
                                                 ctypes.byref(br)) or br.value != dlen:
                        continue
                    decoded = bytes(v ^ MASK[i % len(MASK)] for i, v in enumerate(blob[:br.value]))
                    total += 1
                    for m in HEX_RE.finditer(decoded):
                        run = m.group(1).decode().lower()
                        starts = [0]
                        if len(run) > 96:
                            starts += list(range(0, len(run) - 63, 32))
                            starts.append(len(run) - 64)
                        for s in dict.fromkeys(starts):
                            if s + 64 > len(run):
                                continue
                            cand = bytes.fromhex(run[s:s + 64])
                            if not probable(cand):
                                continue
                            es = None
                            if s + 96 <= len(run):
                                es = bytes.fromhex(run[s + 64:s + 96])
                            try_key(cand, es)
            print('  解出配置块 %d 个，命中密钥 %d 把' % (total, len(keys)))
        finally:
            k32.CloseHandle(h)
        if len(keys) >= len(dbs):
            break

    print('\n=== 结果：%d / %d 个库拿到密钥 ===' % (len(keys), len(dbs)))
    outp = C.KEYS_FILE
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    with open(outp, 'w', encoding='utf-8') as f:
        json.dump(keys, f, ensure_ascii=False, indent=2)
    print('已写入 %s（属于敏感文件，别进 Git、别外发）' % outp)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
