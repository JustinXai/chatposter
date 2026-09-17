# -*- coding: utf-8 -*-
"""
app.py · 微信挂件（本地小服务）

左边列群，点一个 → 后台跑「取数 → 分析 → 出图」→ 右边直接出长图。
只在本机 127.0.0.1 上监听，不对外网开放。
"""
import os
import sys
import json
import time
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipe  # noqa: E402

HOST, PORT = '127.0.0.1', 8756
OUT = os.path.join(pipe.ROOT, 'out')

_groups = {'t': 0, 'v': []}
_lock = threading.Lock()


def get_groups(force=False):
    with _lock:
        if force or not _groups['v'] or time.time() - _groups['t'] > 120:
            _groups['v'] = pipe.find_groups()
            _groups['t'] = time.time()
        return _groups['v']


PAGE = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>微信挂件 · 群聊日报</title>
<style>
:root{--bg:#0b0c0e;--sf:#14171c;--ink:#ecedef;--ink2:#9aa0a6;--ink3:#666c74;
      --line:rgba(255,255,255,.10);--acc:#d9a24b;--up:#e5534b;
      --mono:ui-monospace,"JetBrains Mono",Consolas,monospace;
      --sans:"Microsoft YaHei","PingFang SC",system-ui,sans-serif;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);height:100vh;display:flex;overflow:hidden}
.side{width:300px;flex:none;border-right:1px solid var(--line);display:flex;flex-direction:column}
.head{padding:18px 18px 14px;border-bottom:1px solid var(--line)}
.head h1{font-size:15px;font-weight:700;letter-spacing:.02em}
.head p{font-size:11px;color:var(--ink3);margin-top:6px;font-family:var(--mono)}
.list{flex:1;overflow-y:auto;padding:8px}
.g{padding:11px 12px;border-radius:8px;cursor:pointer;display:flex;gap:10px;align-items:baseline;transition:.15s}
.g:hover{background:rgba(255,255,255,.04)}
.g.on{background:rgba(217,162,75,.10);box-shadow:inset 2px 0 0 var(--acc)}
.g .n{flex:1;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.g .c{font-family:var(--mono);font-size:12px;color:var(--ink3)}
.g.on .n{color:#fff}
.main{flex:1;display:flex;flex-direction:column;min-width:0}
.bar{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:14px}
.btn{background:var(--acc);color:#1a1408;border:0;border-radius:8px;padding:9px 16px;
     font-size:13px;font-weight:700;cursor:pointer;font-family:var(--sans)}
.btn:disabled{opacity:.45;cursor:default}
.st{font-family:var(--mono);font-size:11.5px;color:var(--ink3)}
.stage{flex:1;overflow:auto;padding:22px;display:flex;justify-content:center;align-items:flex-start}
.stage img{width:100%;max-width:760px;border-radius:10px;border:1px solid var(--line);display:block}
.empty{color:var(--ink3);font-size:13px;margin-top:80px;text-align:center;line-height:2}
.empty b{color:var(--ink2)}
</style></head><body>
<div class="side">
  <div class="head"><h1>微信挂件 · 群聊日报</h1>
    <p id="cnt">正在读取群列表…</p></div>
  <div class="list" id="list"></div>
</div>
<div class="main">
  <div class="bar">
    <button class="btn" id="go" disabled>生成日报图</button>
    <span class="st" id="st">选一个群，然后点左边按钮</span>
  </div>
  <div class="stage" id="stage">
    <div class="empty">左边选一个群 → 点「生成日报图」<br>
      <b>流程</b>：读近 24 小时记录 → 结构化分析 → 模板渲染 → 截图成长图</div>
  </div>
</div>
<script>
let cur=null, groups=[];
const $=s=>document.querySelector(s);
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
async function load(){
  const r=await fetch('/api/groups'); groups=await r.json();
  $('#cnt').textContent=groups.length+' 个群 · '+groups.filter(g=>g.n24>0).length+' 个 24h 活跃';
  $('#list').innerHTML=groups.map((g,i)=>`<div class="g" data-i="${i}">
    <span class="n">${esc(g.name)}</span><span class="c">${g.n24}</span></div>`).join('');
  document.querySelectorAll('.g').forEach(el=>el.onclick=()=>pick(+el.dataset.i));
}
function pick(i){
  cur=groups[i];
  document.querySelectorAll('.g').forEach(e=>e.classList.toggle('on',+e.dataset.i===i));
  $('#go').disabled=false;
  $('#st').textContent='已选：'+cur.name+'（近 24h '+cur.n24+' 条）';
}
$('#go').onclick=async()=>{
  if(!cur) return;
  const b=$('#go'); b.disabled=true; b.textContent='生成中…';
  $('#st').textContent='正在读取记录并生成…';
  const t0=Date.now();
  try{
    const r=await fetch('/api/build',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({group:cur.id,name:cur.name})});
    const d=await r.json();
    if(d.error){$('#st').textContent='失败：'+d.error;b.disabled=false;b.textContent='生成日报图';return}
    $('#stage').innerHTML=`<img src="${d.png}?t=${Date.now()}">`;
    $('#st').textContent='完成：'+d.count+' 条消息，用时 '+((Date.now()-t0)/1000).toFixed(1)+'s';
  }catch(e){$('#st').textContent='失败：'+e}
  b.disabled=false; b.textContent='重新生成';
};
load();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split('?')[0]
        if p in ('/', '/index.html'):
            return self._send(200, PAGE, 'text/html; charset=utf-8')
        if p == '/api/groups':
            try:
                return self._send(200, json.dumps(get_groups(), ensure_ascii=False))
            except Exception as e:
                return self._send(500, json.dumps({'error': str(e)}, ensure_ascii=False))
        if p.startswith('/out/'):
            f = os.path.join(OUT, os.path.basename(p[5:]))
            if os.path.exists(f):
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(os.path.getsize(f)))
                self.end_headers()
                with open(f, 'rb') as fh:
                    self.wfile.write(fh.read())
                return
        return self._send(404, 'not found', 'text/plain; charset=utf-8')

    def do_POST(self):
        if self.path.split('?')[0] != '/api/build':
            return self._send(404, 'not found', 'text/plain; charset=utf-8')
        n = int(self.headers.get('Content-Length') or 0)
        try:
            req = json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            req = {}
        gid, gname = req.get('group'), req.get('name') or req.get('group')
        if not gid:
            return self._send(400, json.dumps({'error': 'no group'}, ensure_ascii=False))
        try:
            r = pipe.build_report(pipe.default_account(), gid, name=gname)
            png = '/out/' + os.path.basename(r['png'])
            return self._send(200, json.dumps(
                {'png': png, 'count': r['count'], 'name': gname}, ensure_ascii=False))
        except Exception as e:
            traceback.print_exc()
            return self._send(500, json.dumps({'error': str(e)}, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    srv = ThreadingHTTPServer((HOST, PORT), H)
    print('微信挂件已启动： http://%s:%d' % (HOST, PORT))
    srv.serve_forever()
