# -*- coding: utf-8 -*-
"""【模板】fetch_corpus.py —— 人物蒸馏工作流 · 全量语料抓取器

★ 本文件是**技能包模板**，不是项目脚本。
  复制到 <项目>/01_语料/ 后改下面几个常量。

用途：把整本小说的正文抓成本地章节 txt（一章一文件 `p<N>.txt`），
      作为后续台词归属、统计口径、引用核验的唯一语料底座。

★ 为什么"全量"是硬要求：
  抽样语料只能做草稿。本工作流所有统计（口头禅频次、章数、污染率）
  都建立在全量之上——章数不对，后面所有数字都不可信。

★ 抓取站的 JS 挑战通用解法（实战总结）：
  1. 首次请求返回几百字节的挑战页，token 形如 `let token = "<base64>"`，
     base64 解码 = `<unix时间戳>:<sha256>`。
  2. **该 token 通常不绑路径，可跨页全局复用** → 取一个，所有线程共用。
  3. 过一次后服务端下发 session cookie，后续请求连 challenge 都不用带。
  4. 每个线程独立 opener（cookie 不共享），但 token 可共享。
  5. 并发实测：1 线程 0.1 req/s → 4 线程 0.6 → 8 线程 1.5 → 16 线程 3.2（全成功）。

用法：
    python fetch_corpus.py [起始章] [结束章] [线程数]

⚠️ 不要把 stdout 写成 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)`，
   那样被 import 时会关掉底层 buffer 导致后续 print 全炸。
   本脚本只用 sys.stdout.reconfigure()。
"""
import base64
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ===== 需要按项目修改的常量 =====
BASE = 'https://ixdzs8.com'      # 抓取站（注意：某些子域证书过期，换子域）
BOOK = 503391                    # 书号
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chapters')
LAST_CHAP = 2085                 # 末章（从目录页读到的最大章号）
# 主角名 + 对照组角色名（用于 S2 台词归属，不是本脚本用）
PROTAGONIST = '角色名'
CONTRAST_ROLES = ['配角1', '配角2', '配角3']
# ================================

CHAL = re.compile(r'let token = "([^"]+)"')

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'same-origin',
    'Upgrade-Insecure-Requests': '1',
}

os.makedirs(OUT, exist_ok=True)


def new_opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),          # ★ 必须绕代理，否则本地/部分站点 502
        urllib.request.HTTPCookieProcessor(cj)), cj


def _get(op, url, referer=None, timeout=30):
    h = dict(H)
    h['Referer'] = referer or ('%s/read/%d/' % (BASE, BOOK))
    return op.open(urllib.request.Request(url, headers=h), timeout=timeout).read().decode(
        'utf-8', 'replace')


def get_shared_token():
    """取一个全局可用的 challenge token。返回 None 表示站点已放行。"""
    op, cj = new_opener()
    for _ in range(6):
        try:
            t = _get(op, '%s/read/%d/p1.html' % (BASE, BOOK))
        except Exception:
            time.sleep(1.0)
            continue
        m = CHAL.search(t)
        if m:
            return m.group(1)
        return None      # 已直接出正文
    return None


def extract(t):
    """从 HTML 抽出 (标题, 正文)。★ 正则要按目标站点的实际结构改。"""
    title = ''
    m = re.search(r'<h1[^>]*>(.*?)</h1>', t, re.S)
    if m:
        title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
    body = None
    for pat in [r'<div[^>]*id=["\']content["\'][^>]*>(.*?)</div>\s*</div>',
                r'<div[^>]*class=["\'][^"\']*chapter-content[^"\']*["\'][^>]*>(.*?)</div>',
                r'<article[^>]*>(.*?)</article>']:
        mm = re.search(pat, t, re.S)
        if mm:
            body = mm.group(1)
            break
    if body is None:
        body = '\n'.join(re.findall(r'<p[^>]*>(.*?)</p>', t, re.S))
    txt = re.sub(r'<br\s*/?>', '\n', body)
    txt = re.sub(r'</p>', '\n', txt)
    txt = re.sub(r'<[^>]+>', '', txt)
    for a, b in [('&nbsp;', ' '), ('&amp;', '&'), ('&quot;', '"'), ('&#39;', "'"),
                 ('&lt;', '<'), ('&gt;', '>'), ('&emsp;', ' ')]:
        txt = txt.replace(a, b)
    txt = re.sub(r'[ \t]+\n', '\n', txt)
    txt = re.sub(r'\n{2,}', '\n', txt).strip()
    lines = txt.split('\n')
    if lines and title and lines[0].strip() == title:
        lines = lines[1:]
    return title, '\n'.join(lines).strip()


def fetch_one(pid, token):
    """取单章。返回 (章号, 状态, 字符数)。状态：ok / cached / fail / empty。"""
    path = os.path.join(OUT, 'p%d.txt' % pid)
    if os.path.exists(path) and os.path.getsize(path) > 200:
        return pid, 'cached', 0

    op, cj = new_opener()
    url = ('%s/read/%d/p%s.html?challenge=%s' %
           (BASE, BOOK, pid, urllib.parse.quote(token or '', safe='')))
    t = None
    for _ in range(3):
        try:
            t = _get(op, url)
        except Exception:
            time.sleep(0.8)
            continue
        if CHAL.search(t):
            nt = get_shared_token()
            if nt:
                token = nt
                url = ('%s/read/%d/p%s.html?challenge=%s' %
                       (BASE, BOOK, pid, urllib.parse.quote(token, safe='')))
                continue
            try:
                t2 = _get(op, '%s/read/%d/p%s.html' % (BASE, BOOK, pid))
                if not CHAL.search(t2):
                    t = t2
            except Exception:
                pass
            break
        break
    if t is None or CHAL.search(t):
        return pid, 'fail', 0
    title, txt = extract(t)
    if not txt or len(txt) < 50:
        return pid, 'empty', 0
    with open(path, 'w', encoding='utf-8') as f:
        f.write(title + '\n' + txt)
    return pid, 'ok', len(txt.replace('\n', ''))


def fetch_toc():
    op, cj = new_opener()
    t = _get(op, '%s/read/%d/' % (BASE, BOOK), referer=BASE + '/')
    items, seen = [], set()
    for m in re.finditer(r'href="(/read/%d/p(\d+)\.html)"[^>]*>(.*?)</a>' % BOOK, t, re.S):
        pid = int(m.group(2))
        if pid in seen:
            continue
        seen.add(pid)
        items.append({'id': pid, 'name': re.sub(r'<[^>]+>', '', m.group(3)).strip()})
    return items


def verify_coverage(expected):
    """★ 落盘后必跑：核覆盖率、缺章、乱码。"""
    files = [f for f in os.listdir(OUT) if f.endswith('.txt')]
    ids = set()
    total = 0
    for f in files:
        m = re.match(r'p(\d+)\.txt', f)
        if not m:
            continue
        ids.add(int(m.group(1)))
        total += len(open(os.path.join(OUT, f), encoding='utf-8', errors='replace').read())
    missing = sorted(set(range(1, expected + 1)) - ids)
    # PUA 字体混淆检测：私用区字符
    pua = 0
    for f in files[:200]:
        txt = open(os.path.join(OUT, f), encoding='utf-8', errors='replace').read()
        pua += sum(1 for ch in txt if '\ue000' <= ch <= '\uf8ff')
    print('=' * 56)
    print('落盘章数     : %d / 期望 %d' % (len(ids), expected))
    print('总字符数     : %d' % total)
    print('缺章         : %s' % (missing[:30] if missing else '无'))
    print('PUA 乱码字符 : %d（前 200 章抽样）' % pua)
    print('覆盖率       : %.2f%%' % (len(ids) / expected * 100 if expected else 0))
    ok = (len(ids) == expected) and not missing
    print('结论         : %s' % ('✅ 语料完整' if ok else '❌ 语料不全，先补齐再往下走'))
    return ok


def main():
    lo = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    hi = int(sys.argv[2]) if len(sys.argv) > 2 else LAST_CHAP
    nthread = int(sys.argv[3]) if len(sys.argv) > 3 else 8

    tpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'toc.json')
    if os.path.exists(tpath):
        toc = json.load(open(tpath, encoding='utf-8'))
    else:
        toc = fetch_toc()
        json.dump(toc, open(tpath, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('TOC: %d entries | id %d - %d' %
          (len(toc), min(x['id'] for x in toc), max(x['id'] for x in toc)), flush=True)

    token = get_shared_token()
    print('shared token: %s' % ((token[:24] + '...') if token else 'NONE(可能已放行)'), flush=True)

    targets = list(range(lo, hi + 1))
    done = fail = cached = empty = 0
    total = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=nthread) as ex:
        futs = [ex.submit(fetch_one, i, token) for i in targets]
        n = 0
        for fu in as_completed(futs):
            pid, st, sz = fu.result()
            n += 1
            if st == 'ok':
                done += 1
                total += sz
            elif st == 'cached':
                cached += 1
            elif st == 'empty':
                empty += 1
            else:
                fail += 1
            if n % 100 == 0:
                el = time.time() - t0
                rate = n / max(el, 1) * 60
                print('[%d/%d] ok=%d cached=%d fail=%d empty=%d chars=%d  %.0f章/分  eta=%.1f分' % (
                    n, len(targets), done, cached, fail, empty, total, rate,
                    (len(targets) - n) / max(rate, 0.01)), flush=True)
    print('FINAL ok=%d cached=%d fail=%d empty=%d chars=%d  用时%.1f分' % (
        done, cached, fail, empty, total, (time.time() - t0) / 60), flush=True)

    print('\n--- 覆盖率核验 ---', flush=True)
    verify_coverage(hi)


if __name__ == '__main__':
    main()
