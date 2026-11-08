# -*- coding: utf-8 -*-
"""【模板】semantic_check.py —— 人物蒸馏工作流 · S7 语义级校验器（v2.1 新增）

★ 本文件是**技能包模板**，不是项目脚本。
  复制到 <项目>/02_核验/ 后改配置，或用环境变量指定路径。

--------------------------------------------------------------------------
为什么需要它（这是三个已有校验器都覆盖不到的那一格）
--------------------------------------------------------------------------
已有的三个校验器全是**字面匹配**：

    scan_fabrication.py  全文「」引号逐条回原文 —— 只能发现"这句话原文没有"
    verify_citations.py  直引 → 章号定位（滑窗指纹）—— 只能发现"章号对不上"
    selfcheck.py         数字对账 / 口径 / 格式 —— 只看得见数字和符号

它们**发现不了语义反转**。秦风项目实测的那条：

    原文（第300章）：「想让我不抓你回去也不是不可以，不过你得加钱！」
    写成：          「想让我帮你也不是不可以，不过你得加钱！」

字符串依然全部命中原文 → 三个校验器全绿 → 交付物带着一个**意思正好反了**的
台词进入 system prompt。模型学到的是"秦风是个乐于助人的好人"。

本脚本补的就是这一格：把档案里的**断言句**（不只是引号，还有结论、性格标签、
关系判断、禁忌）逐条拿去和原文段落做**蕴含判定（NLI）**：

    supported     原文支持这条断言
    contradicted  原文**明确相反**  ← 这就是"语义反转"，必须人工处理
    insufficient  原文查不到相关证据（可能是【推断】级，属正常，但要知情）

--------------------------------------------------------------------------
★ 它是旁路，不是主链
--------------------------------------------------------------------------
本脚本**不参与** S1–S6 的任何产出，只产出一份"待人复核清单"。
它需要模型推理（本地 Ollama 或 OpenAI 兼容 API），所以：
  · 不要把它塞进主流程的关键路径；
  · 它报的 contradicted 是**提示**不是判决 —— 语义判定本身有误报，
    最终仍由人读原文拍板（符合工作流「人工判据」那一档的定位）。

★ 反向验证（--selftest）
--------------------------------------------------------------------------
沿用工作流的铁律 6「自检器要做反向验证，否则是假绿」：
  --selftest 会从原文里取真实句子当"真断言"，再用**极性词替换**
  （不是→是、没有→有、不会→会、从不→总是…）造出"假断言"，
  两者都判一遍，报出**检出率**（假断言被判 contradicted）与
  **误报率**（真断言被判 contradicted）。
  检出率低 → 换个后端/模型；误报率高 → 这个后端不能信。

--------------------------------------------------------------------------
用法
--------------------------------------------------------------------------
    set DISTILL_ROOT=<D盘>\\UserFiles\\Desktop\\<项目名>_人物蒸馏
    set DISTILL_SRC=<项目>\\01_语料\\chapters
    set DISTILL_V2=<项目>\\03_交付物\\<角色名>_数字人系统提示词_v2.md
    set DISTILL_STATS=<项目>\\02_核验\\_stats
    set DISTILL_CHAR=<角色名>
    set DISTILL_NAMES=主角名,别名1,别名2

    python semantic_check.py                      # 全量断言（默认最多 60 条，防费用失控）
    python semantic_check.py --limit 200          # 放开上限
    python semantic_check.py --only-section 0,1,2 # 只查这几节
    python semantic_check.py --selftest           # 反向验证（先跑这个！）
    python semantic_check.py --backend ollama     # 用本地模型（不花钱）

后端选择（--backend，默认 auto）：
    auto    先试 ollama（127.0.0.1:11434），连不上再退回 api
    ollama  本地模型，默认 qwen3.5:9b（DISTILL_OLLAMA_MODEL 覆盖）
    api     OpenAI 兼容接口，默认 DeepSeek（DISTILL_LLM_BASE / MODEL 覆盖）
    stub    离线桩，不联网。只用来验证流程通不通（判定结果无意义）

报告输出：默认写 <DISTILL_STATS>；若该目录不可写（典型：项目放在 Windows
    「受控文件夹访问」保护的 图片/文档/音乐/视频 目录下，python.exe 未被放行，
    写文件会变成 FileNotFoundError），自动降级到 %TEMP%/蒸馏语义校验_<角色>，
    并在日志里打印降级原因与恢复办法。用 DISTILL_SEM_OUT 可指定别处。

密钥从环境变量读，**不要写进本文件**：
    DISTILL_LLM_KEY 或 DEEPSEEK_API_KEY 或 OPENAI_API_KEY

退出码：有 contradicted 时 1（便于脚本串联），否则 0。
"""
import os
import re
import sys
import json
import time
import hashlib
import tempfile
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))


def _env(name, default=None):
    return os.environ.get(name) or default


ROOT = _env('DISTILL_ROOT') or os.path.abspath(os.path.join(HERE, '..', '..'))
SRC = _env('DISTILL_SRC') or os.path.join(ROOT, '01_语料', 'chapters')
V2 = _env('DISTILL_V2',
          os.path.join(ROOT, '03_交付物', '角色名_数字人系统提示词_v2.md'))
STATS = _env('DISTILL_STATS') or os.path.join(ROOT, '02_核验', '_stats')
CHAR = _env('DISTILL_CHAR', '角色')
NAMES = [x.strip() for x in _env('DISTILL_NAMES', '').split(',') if x.strip()]
NAMES = NAMES or [CHAR]

# 参与语义校验的章节。**只放「事实型」的节**：身份卡 / 公理 / 性格 / 准则 / 关系网 / 履历 / 世界观。
# 排除三类：
#   §4        统计数字，已由 final_stats + audit_authoritative 复现，不是语义问题；
#   §8 §9     场景应答与示例对话，是"该怎么演"，由 selfcheck + scan_fabrication 覆盖；
#   §0.5 §0.6 §10 §11  指令与**负面清单**（"❌ 不要做 X"）。
#              这一类是 v2.1 实测踩到的最大误报源：NLI 会把"❌ 不要写文艺腔"当成
#              "这个角色不写文艺腔"去原文里找反例，一找一个准——163 条里 15 条 contradicted，
#              其中 10 条全来自 §10。指令不是事实断言，不该进语义校验。
DEF_SECTIONS = _env('DISTILL_SEM_SECTIONS', '0,1,2,3,7,12,13')

# 负面清单行（"❌ 不要做 X"）永远是指令不是事实，即使把 §10 手动加回来也跳过。
NEG_MARK = ('❌', '⚠️', '🚫')

# 报告输出目录。默认就是 STATS；若 STATS 不可写（最常见原因：项目放在 Windows 的
# 「受控文件夹访问」保护目录里，如 图片/文档/音乐/视频，python.exe 没有写入白名单，
# 写文件会静默失败成 FileNotFoundError），自动降级到临时目录，并打印降级原因。
OUT = _env('DISTILL_SEM_OUT') or STATS
_OUT_DIR = None

MAX_CLAIMS = int(_env('DISTILL_SEM_MAX', '60'))
EVIDENCE_K = 4               # 每条断言取几个候选段落
EVIDENCE_CHARS = 1400        # 证据拼起来的总长度上限
CONTEXT_CHARS = 700          # 单个段落过长时截断长度


# ---------------------------------------------------------------- 输出目录降级

def out_dir():
    """返回一个**确实写得进去**的输出目录（只探测一次，结果缓存）。"""
    global _OUT_DIR
    if _OUT_DIR:
        return _OUT_DIR
    for d in (OUT, os.path.join(tempfile.gettempdir(), '蒸馏语义校验_%s' % CHAR)):
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, '.write_test')
            with open(probe, 'w', encoding='utf-8') as f:
                f.write('ok')
            os.remove(probe)
        except Exception:
            continue
        _OUT_DIR = d
        if os.path.abspath(d) != os.path.abspath(OUT):
            print('!! 输出目录不可写：%s' % OUT)
            print('   （多半是项目在 Windows「受控文件夹访问」保护目录里，python.exe 未被放行）')
            print('   已降级写到：%s' % d)
            print('   要改回原目录：Windows 安全中心 → 病毒和威胁防护 → 勒索软件防护 →')
            print('   「通过受控文件夹访问允许应用」→ 添加 python.exe，或关掉该开关。')
        return _OUT_DIR
    _OUT_DIR = os.path.join(tempfile.gettempdir(), '蒸馏语义校验_%s' % CHAR)
    return _OUT_DIR


def out_path(name):
    return os.path.join(out_dir(), name)


def _dump(name, obj, indent=None):
    """落盘 JSON；写不进去也不让整个流程崩在最后一步。"""
    p = out_path(name)
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=indent)
        return p
    except Exception as e:
        print('!! 写 %s 失败：%r' % (p, e))
        return None


# ---------------------------------------------------------------- 停用词 / 极性词

STOP = set('的了是在有和与就都而及或一个我你他她它们这那之也不很才把被给让到'
           '对于从向为以所如若则并且但因所以可以会要能没做说看着想上下中前后'
           '什么怎么非常已经还是如果因为或者但是而且然后真正一直更加更最')

# 极性词对（用于 --selftest 造"语义反转"的假断言）。顺序有讲究：
# 先长后短，避免 "不是" 被 "是" 提前命中。
# ★ 只收「两侧都是能独立成立的词」且替换后不会造出病句的：
#   多字词优先（喜欢→讨厌、朋友→敌人）；单字只留极性极强的少数几个，
#   且必须配 _degenerate() 检查（"是不是"→"是是"、"好坏"→"好好" 这类不算反转、算病句，
#   模型会把它判成 supported，是**假红**，会把检出率压低）。
POLAR_PAIRS = [
    ('不是', '是'), ('没有', '有'), ('不会', '会'), ('不能', '能'),
    ('不敢', '敢'), ('不要', '要'), ('不信', '信'), ('不愿', '愿'),
    ('从不', '总是'), ('总是', '从不'), ('讨厌', '喜欢'), ('喜欢', '讨厌'),
    ('朋友', '敌人'), ('敌人', '朋友'), ('敌人', '好友'),
    ('好人', '坏人'), ('坏人', '好人'), ('忠诚', '背叛'), ('背叛', '忠诚'),
]


def _degenerate(orig, new):
    """替换后是不是造出了原句没有的「叠字」病句（如 是是 / 好好 / 敢敢）。"""
    dup = r'(.)\1'
    a = set(re.findall(dup, orig))
    b = set(re.findall(dup, new))
    return bool(b - a)


def swap_polarity(s):
    """把一句话的极性翻过来。造不出**干净**的反转就返回 None（宁可少造，不造假红）。"""
    for a, b in POLAR_PAIRS:
        i = s.find(a)
        if i < 0:
            continue
        new = s[:i] + b + s[i + len(a):]
        if _degenerate(s, new):
            continue
        return new
    return None


# ---------------------------------------------------------------- 语料装载

def load_books():
    """清洗后语料：[(标题, [段落, ...], 文件名), ...]。与 final_stats 同口径。"""
    # 优先复用项目里的 final_stats（口径唯一），没有就自己读
    for p in (HERE, os.path.join(ROOT, '02_核验'), _env('DISTILL_VERIFY_DIR') or ''):
        if p and os.path.isfile(os.path.join(p, 'final_stats.py')):
            sys.path.insert(0, p)
            break
    try:
        import final_stats as FS           # noqa
        books = FS.load_books()
        if books:
            return books
    except Exception as e:
        print('（未能复用 final_stats.load_books：%r，改为自行读语料）' % (e,))

    res = []
    if not os.path.isdir(SRC):
        print('!! 找不到语料目录:', SRC)
        return res
    fns = [f for f in os.listdir(SRC) if f.endswith('.txt')]
    fns.sort(key=lambda x: int(re.match(r'p(\d+)\.txt', x).group(1))
             if re.match(r'p(\d+)\.txt', x) else 0)
    for fn in fns:
        with open(os.path.join(SRC, fn), encoding='utf-8', errors='replace') as f:
            lines = f.read().split('\n')
        title = lines[0].strip() if lines else fn
        body = [l.strip() for l in lines[1:] if l.strip()]
        res.append((title, body, fn))
    return res


def chap_no(title_or_fn):
    m = re.match(r'p(\d+)\.txt', title_or_fn or '')
    if m:
        return int(m.group(1))
    m = re.search(r'第\s*(\d+)\s*章', title_or_fn or '')
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------- 断言抽取

CITE_RE = re.compile(r'【[^】]{0,200}】')
ARROW_TAIL = re.compile(r'(?:→|->|=>).*$')


def clean_claim(s):
    s = CITE_RE.sub('', s or '')
    s = s.replace('**', '').replace('`', '')
    s = re.sub(r'^\s*[-*\d]+[.、)]?\s*', '', s)          # 列表符号 / 序号
    s = re.sub(r'^\s*📌\s*|^\s*⚠️\s*|^\s*★\s*', '', s)
    s = re.sub(r'\s+', ' ', s).strip(' ｜|')
    return s.strip()


def is_quote_dominated(s):
    """整句基本都是「」里的台词 → 交给 scan_fabrication，不在这里查。"""
    if not s:
        return True
    inner = sum(len(x) for x in re.findall(r'[「『]([^」』]*)[」』]', s))
    return inner >= max(4, len(s) * 0.72)


_BOOKTITLE = re.compile(r'《[^》]{0,80}》')


def split_sentences(line):
    # 先保护书名号里的标点：《这个反派有点良心，但是不多！》里的 "！" 不是句末，
    # 否则会把一句话劈成 "…《这个反派有点良心，但是不多！" + "》的主角…" 两个残缺断言。
    hold = []

    def _stash(m):
        hold.append(m.group(0))
        return '\x00%d\x00' % (len(hold) - 1)

    line = _BOOKTITLE.sub(_stash, line)
    # 按句号类切，但保留 ！？ 组合（秦风原书大量 "！？"）
    parts = re.split(r'(?<=[。；;])\s*|(?<=[！!？?])(?![！!？?])', line)
    out = []
    for p in parts:
        p = re.sub(r'\x00(\d+)\x00', lambda m: hold[int(m.group(1))], p).strip()
        if p:
            out.append(p)
    return out


def extract_claims(md, sections):
    """按章节抽取断言句。返回 [{节, 行, 断言}]。"""
    lines = md.replace('\r\n', '\n').split('\n')
    cur = None
    out = []
    in_code = False
    for i, raw in enumerate(lines, 1):
        line = raw.rstrip()
        if line.startswith('```'):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r'^#{1,4}\s*§?\s*(\d+(?:\.\d+)?)', line)
        if m:
            cur = m.group(1)
            continue
        if cur not in sections or not line.strip():
            continue
        if line.lstrip().startswith('---'):
            continue
        body = line.strip()
        if body.lstrip('> *-').startswith(NEG_MARK):
            continue                                  # 负面清单/警告行：是指令不是事实
        if body.startswith('|'):
            cells = [c.strip() for c in body.strip('|').split('|')]
            cells = [c for c in cells if c != '']
            if not cells or set(''.join(cells)) <= set('-: '):
                continue
            # 表格：最后一列通常是【依据】，不进断言；其余列拼成断言
            body = '、'.join(cells[:-1]) if len(cells) > 1 else cells[0]
            body = ARROW_TAIL.sub('', body)
        for sent in split_sentences(clean_claim(body)):
            if not sent or is_quote_dominated(sent):
                continue
            core = re.sub(r'[\s，。！？、；：""\'「」『』…—·\*\(\)（）]', '', sent)
            if not (6 <= len(core) <= 120):
                continue
            out.append({'节': cur, '行': i, '断言': sent,
                        '章号': [int(x) for x in re.findall(r'第\s*(\d+)\s*章',
                                                         raw)]})
    # 去重（同一句可能在多节重复）
    seen, uniq = set(), []
    for c in out:
        k = re.sub(r'[\s，。！？、；：]', '', c['断言'])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(c)
    return uniq


# ---------------------------------------------------------------- 检索（纯标准库）

def ngrams(s, ns=(2, 3)):
    """CJK n-gram（只取含实词的），用于检索打分。"""
    out = set()
    chars = [c for c in s]
    n = len(chars)
    for k in ns:
        for i in range(n - k + 1):
            g = ''.join(chars[i:i + k])
            if g[0] in STOP or g[-1] in STOP:
                continue
            if not re.search(r'[\u4e00-\u9fffA-Za-z]', g):
                continue
            if all(c in STOP or not c.strip() for c in g):
                continue
            out.add(g)
    return out


class Retriever(object):
    """倒排索引 + idf 打分。索引只在"断言用到的词表"上建，省内存也省时间。"""

    def __init__(self, books, log=print):
        self.books = books
        self.log = log
        self.paras = []          # [(章号, 段落号, 文本)]
        for title, body, fn in books:
            cn = chap_no(fn) or chap_no(title)
            for pi, p in enumerate(body):
                self.paras.append((cn, pi, p))
        self.post = {}           # token -> [段落下标]
        self.df = {}

    def build(self, vocab):
        head = set(t[0] for t in vocab)
        for idx, (cn, pi, txt) in enumerate(self.paras):
            toks = set()
            chars = txt
            n = len(chars)
            for k in (2, 3):
                for i in range(n - k + 1):
                    if chars[i] not in head:
                        continue
                    g = chars[i:i + k]
                    if g in vocab:
                        toks.add(g)
            for t in toks:
                self.post.setdefault(t, []).append(idx)
        self.df = dict((t, len(v)) for t, v in self.post.items())
        self.log('检索索引：%d 段落 / %d 个关键词' % (len(self.paras), len(self.df)))

    def top(self, claim, k=EVIDENCE_K, prefer_chaps=None):
        import math
        toks = ngrams(claim)
        score = {}
        for t in toks:
            lst = self.post.get(t)
            if not lst:
                continue
            w = 1.0 / math.log(1 + self.df.get(t, 1) + 1)
            for idx in lst:
                score[idx] = score.get(idx, 0.0) + w
        if not score:
            return []
        prefer = set(prefer_chaps or [])
        if prefer:
            for idx in list(score.keys()):
                if self.paras[idx][0] in prefer:
                    score[idx] += 2.5
        best = sorted(score.items(), key=lambda x: -x[1])[:k * 3]
        # 同章相邻段落合并一下，避免证据被同一段切碎
        picked, used = [], set()
        for idx, _ in best:
            if idx in used:
                continue
            used.add(idx)
            picked.append(idx)
        return picked[:k]

    def evidence_text(self, idxs):
        buf, total = [], 0
        for idx in idxs:
            cn, pi, txt = self.paras[idx]
            t = txt if len(txt) <= CONTEXT_CHARS else txt[:CONTEXT_CHARS] + '…'
            piece = '【第%d章】%s' % (cn, t)
            if total + len(piece) > EVIDENCE_CHARS:
                break
            buf.append(piece)
            total += len(piece)
        return '\n'.join(buf)


# ---------------------------------------------------------------- 模型后端

SYS_PROMPT = (
    '你是小说文本核对员。给你一句【角色档案断言】和若干段【小说原文】。'
    '请判断该断言是否被原文支持。判定标准：\n'
    'supported    —— 原文明确支持这条断言。\n'
    'contradicted —— 原文**明确相反**（极性/对象/条件/程度被写反了，或原文写的正好是反面）。\n'
    'insufficient —— 原文没有能支持或反驳它的内容（档案属于合理推测，不算错）。\n'
    '特别注意：只要"意思反了"就必须判 contradicted，不要因为没有完全逐字相同就放过。\n'
    '只输出一个 JSON，不要任何解释文字：\n'
    '{"label":"supported|contradicted|insufficient","quote":"原文中最关键的一句话",'
    '"reason":"一句话说明理由"}')


def _post_json(url, payload, headers, timeout=60):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def _pick_json(text):
    if not text:
        return None
    m = re.search(r'\{[\s\S]*?\}', text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        try:
            return json.loads(m.group(0).replace("'", '"'))
        except Exception:
            return None


class ApiBackend(object):
    name = 'api'

    def __init__(self, log=print):
        self.base = (_env('DISTILL_LLM_BASE') or 'https://api.deepseek.com/v1').rstrip('/')
        self.model = _env('DISTILL_LLM_MODEL') or 'deepseek-chat'
        self.key = (_env('DISTILL_LLM_KEY') or _env('DEEPSEEK_API_KEY')
                    or _env('OPENAI_API_KEY') or '')
        self.log = log
        self.calls = 0

    def ok(self):
        return bool(self.key)

    def judge(self, claim, evidence):
        url = self.base + '/chat/completions'
        payload = {
            'model': self.model,
            'temperature': 0,
            'max_tokens': 300,
            'messages': [
                {'role': 'system', 'content': SYS_PROMPT},
                {'role': 'user', 'content':
                 '【角色档案断言】\n%s\n\n【小说原文】\n%s' % (claim, evidence)},
            ],
        }
        hdr = {'Content-Type': 'application/json',
               'Authorization': 'Bearer ' + self.key}
        last = ''
        for attempt in (1, 2, 3):
            try:
                r = _post_json(url, payload, hdr)
                self.calls += 1
                txt = (r.get('choices') or [{}])[0].get('message', {}).get('content', '')
                d = _pick_json(txt) or {}
                return {'label': (d.get('label') or 'unknown').strip().lower(),
                        'quote': (d.get('quote') or '').strip(),
                        'reason': (d.get('reason') or '').strip()}
            except Exception as e:
                last = repr(e)
                time.sleep(1.5 * attempt)
        return {'label': 'error', 'quote': '', 'reason': last}


class OllamaBackend(object):
    name = 'ollama'

    def __init__(self, log=print):
        self.url = (_env('DISTILL_OLLAMA') or 'http://127.0.0.1:11434').rstrip('/')
        self.model = _env('DISTILL_OLLAMA_MODEL') or 'qwen3.5:9b'
        self.log = log
        self.calls = 0

    def ok(self):
        try:
            with urllib.request.urlopen(self.url + '/api/tags', timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def judge(self, claim, evidence):
        payload = {
            'model': self.model,
            'stream': False,
            'format': 'json',
            'options': {'temperature': 0},
            'messages': [
                {'role': 'system', 'content': SYS_PROMPT},
                {'role': 'user', 'content':
                 '【角色档案断言】\n%s\n\n【小说原文】\n%s' % (claim, evidence)},
            ],
        }
        try:
            r = _post_json(self.url + '/api/chat', payload,
                           {'Content-Type': 'application/json'}, timeout=180)
            self.calls += 1
            d = _pick_json((r.get('message') or {}).get('content', '')) or {}
            return {'label': (d.get('label') or 'unknown').strip().lower(),
                    'quote': (d.get('quote') or '').strip(),
                    'reason': (d.get('reason') or '').strip()}
        except Exception as e:
            return {'label': 'error', 'quote': '', 'reason': repr(e)}


class StubBackend(object):
    """离线桩：只验证流程。判定规则是"共享 3-gram 就 supported"，毫无语义能力。"""
    name = 'stub'

    def __init__(self, log=print):
        self.calls = 0

    def ok(self):
        return True

    def judge(self, claim, evidence):
        self.calls += 1
        a = ngrams(claim, (3,))
        b = ngrams(evidence, (3,))
        share = len(a & b)
        return {'label': 'supported' if share >= 3 else 'insufficient',
                'quote': '', 'reason': 'stub：共享三元组 %d 个' % share}


def make_backend(kind, log=print):
    oll = OllamaBackend(log)
    api = ApiBackend(log)
    kind = (kind or 'auto').lower()
    if kind == 'stub':
        return StubBackend(log)
    if kind == 'ollama':
        if not oll.ok():
            print('!! Ollama 连不上（%s），改用 api 后端' % oll.url)
            return api
        print('后端：ollama / %s' % oll.model)
        return oll
    if kind == 'api':
        if not api.ok():
            print('!! 没有 API key（设 DISTILL_LLM_KEY 或 DEEPSEEK_API_KEY），改用 stub')
            return StubBackend(log)
        print('后端：api / %s @ %s' % (api.model, api.base))
        return api
    # auto
    if oll.ok():
        print('后端：ollama / %s（自动探测成功）' % oll.model)
        return oll
    if api.ok():
        print('后端：api / %s @ %s（Ollama 未启动，自动退回）' % (api.model, api.base))
        return api
    print('!! 没有可用后端（Ollama 未启动且无 API key），改用 stub（结果无意义）')
    return StubBackend(log)


# ---------------------------------------------------------------- 反向验证

def selftest(books, backend, k=8):
    """从原文取真句当"真断言"，极性词替换后当"假断言"，量一量后端的本事。"""
    print('\n' + '=' * 62)
    print('反向验证：真断言必须放行、假断言必须被抓（铁律 6）')
    print('=' * 62)
    probes = []
    name_re = re.compile('|'.join(re.escape(n) for n in NAMES))
    for title, body, fn in books:
        if len(probes) >= k * 6:
            break
        cn = chap_no(fn)
        for p in body:
            if len(probes) >= k * 6:
                break
            for sent in split_sentences(p):
                if not (8 <= len(sent) <= 60) or not name_re.search(sent):
                    continue
                if is_quote_dominated(sent):
                    continue
                flipped = swap_polarity(sent)
                if not flipped or flipped == sent:
                    continue
                probes.append((re.sub(r'[「」“”]', '', sent),
                               re.sub(r'[「」“”]', '', flipped), cn))
                break
    probes = probes[:k]
    if not probes:
        print('没找到可用的探针句（极性词一个都没命中）—— 换个 DISTILL_NAMES 再试')
        return None

    vocab = set()
    for a, b, _ in probes:
        vocab |= ngrams(a) | ngrams(b)
    rt = Retriever(books, log=lambda m: None)
    rt.build(vocab)

    hit = miss_true = 0
    print('%-4s %-9s %-9s %s' % ('#', '真断言', '假断言', '结论'))
    rows = []
    for i, (truth, fake, cn) in enumerate(probes, 1):
        ev = rt.evidence_text(rt.top(truth, prefer_chaps=[cn]))
        r1 = backend.judge(truth, ev)
        r2 = backend.judge(fake, ev)
        caught = r2.get('label') == 'contradicted'
        false_alarm = r1.get('label') == 'contradicted'
        hit += 1 if caught else 0
        miss_true += 1 if false_alarm else 0
        rows.append({'真断言': truth, '真判定': r1.get('label'),
                     '假断言': fake, '假判定': r2.get('label'), '章': cn})
        print('%-4d %-9s %-9s %s' % (i, r1.get('label'), r2.get('label'),
                                     '抓到' if caught else '漏掉'))
    n = len(probes)
    print('-' * 62)
    print('检出率（假断言被判 contradicted）：%d/%d = %.0f%%' % (hit, n, 100.0 * hit / n))
    print('误报率（真断言被判 contradicted）：%d/%d = %.0f%%' % (miss_true, n,
                                                        100.0 * miss_true / n))
    print('★ 检出率低 → 换更强的模型；误报率高 → 这个后端的结果不能直接采信。')
    p = _dump('语义校验_反向验证.json',
              {'检出': hit, '总数': n, '误报': miss_true, '明细': rows}, indent=1)
    print('报告:', p)
    return {'hit': hit, 'n': n, 'false_alarm': miss_true}


# ---------------------------------------------------------------- 主流程

def main():
    argv = sys.argv[1:]
    limit = MAX_CLAIMS
    only = None
    backend_kind = 'auto'
    do_selftest = False
    no_cache = False
    for i, a in enumerate(argv):
        if a == '--limit' and i + 1 < len(argv):
            limit = int(argv[i + 1])
        elif a == '--only-section' and i + 1 < len(argv):
            only = [x.strip() for x in argv[i + 1].split(',') if x.strip()]
        elif a == '--backend' and i + 1 < len(argv):
            backend_kind = argv[i + 1]
        elif a == '--selftest':
            do_selftest = True
        elif a == '--no-cache':
            no_cache = True

    sections = set(only) if only else set(x for x in DEF_SECTIONS.split(',') if x)
    print('角色=%s 语料=%s' % (CHAR, SRC))
    print('档案=%s' % V2)

    books = load_books()
    if not books:
        print('!! 语料为空，退出')
        return 1
    print('语料：%d 章' % len(books))

    backend = make_backend(backend_kind)

    if do_selftest:
        r = selftest(books, backend, k=int(_env('DISTILL_SEM_SELFTEST_K', '8')))
        return 0 if r else 1

    if not os.path.isfile(V2):
        print('!! 找不到档案文件:', V2)
        return 1
    md = open(V2, encoding='utf-8').read()
    claims = extract_claims(md, sections)
    print('断言抽取：%d 条（节 %s）' % (len(claims), ','.join(sorted(sections))))
    if limit and len(claims) > limit:
        print('  → 按 --limit 截前 %d 条（全量请加 --limit 0）' % limit)
        claims = claims[:limit]
    if not claims:
        print('没有可校验的断言，退出')
        return 0

    vocab = set()
    for c in claims:
        vocab |= ngrams(c['断言'])
    print('关键词表：%d 个，开始建索引…' % len(vocab))
    t0 = time.time()
    rt = Retriever(books)
    rt.build(vocab)
    print('索引完成（%.1f 秒）' % (time.time() - t0))

    cache_path = out_path('语义校验_缓存.json')
    cache = {}
    if os.path.isfile(cache_path) and not no_cache:
        try:
            cache = json.load(open(cache_path, encoding='utf-8'))
        except Exception:
            cache = {}

    stats = {'supported': 0, 'contradicted': 0, 'insufficient': 0,
             'unknown': 0, 'error': 0}
    results = []
    t0 = time.time()
    for i, c in enumerate(claims, 1):
        claim = c['断言']
        idxs = rt.top(claim, prefer_chaps=c.get('章号'))
        ev = rt.evidence_text(idxs)
        if not ev:
            r = {'label': 'insufficient', 'quote': '', 'reason': '检索不到相关原文'}
        else:
            key = hashlib.md5((backend.name + '\x00' + getattr(backend, 'model', '')
                               + '\x00' + claim + '\x00' + ev).encode('utf-8')).hexdigest()
            if key in cache:
                r = cache[key]
            else:
                r = backend.judge(claim, ev)
                if r.get('label') not in ('error',):
                    cache[key] = r
        lab = r.get('label') or 'unknown'
        stats[lab] = stats.get(lab, 0) + 1
        results.append(dict(c, 判定=lab, 依据原文=r.get('quote', ''),
                            理由=r.get('reason', ''),
                            候选章=sorted(set(rt.paras[x][0] for x in idxs))))
        if i % 10 == 0 or lab == 'contradicted':
            print('  [%d/%d] %s  §%s %s' % (i, len(claims), lab, c['节'],
                                            claim[:40]))

    _dump('语义校验_缓存.json', cache)
    jp = _dump('%s_语义校验.json' % CHAR, results, indent=1)

    bad = [r for r in results if r['判定'] == 'contradicted']
    soft = [r for r in results if r['判定'] == 'insufficient']
    mp = out_path('%s_语义校验.md' % CHAR)
    with open(mp, 'w', encoding='utf-8') as f:
        f.write('# %s · 语义级校验报告（S7 旁路）\n\n' % CHAR)
        f.write('> 判定口径：supported=原文支持 / contradicted=**原文明确相反**（语义反转）/ '
                'insufficient=原文查不到证据（可能是【推断】级，属正常）\n')
        f.write('> 后端：%s ｜ 断言 %d 条 ｜ 耗时 %.0f 秒\n\n'
                % (backend.name, len(results), time.time() - t0))
        f.write('| 判定 | 条数 |\n|---|---|\n')
        for k in ('supported', 'contradicted', 'insufficient', 'unknown', 'error'):
            f.write('| %s | %d |\n' % (k, stats.get(k, 0)))
        f.write('\n## ⚠️ 与原文矛盾（必须人工处理）\n\n')
        if not bad:
            f.write('无。\n')
        for r in bad:
            f.write('- **§%s（行 %s）**：%s\n  - 原文依据：%s\n  - 理由：%s\n'
                    % (r['节'], r['行'], r['断言'], r['依据原文'], r['理由']))
        f.write('\n## 证据不足（多为【推断】级，供知情）\n\n')
        for r in soft[:80]:
            f.write('- §%s：%s\n' % (r['节'], r['断言']))
        f.write('\n## 全部明细\n\n| 判定 | 节 | 断言 | 理由 |\n|---|---|---|---|\n')
        for r in results:
            f.write('| %s | §%s | %s | %s |\n'
                    % (r['判定'], r['节'], r['断言'].replace('|', '/'),
                       (r['理由'] or '').replace('|', '/')))
    print('=' * 62)
    print('判定汇总：' + '  '.join('%s=%d' % (k, stats.get(k, 0)) for k in
                              ('supported', 'contradicted', 'insufficient',
                               'unknown', 'error')))
    print('模型调用：%d 次 ｜ 耗时 %.0f 秒' % (getattr(backend, 'calls', 0),
                                        time.time() - t0))
    print('报告:', mp)
    print('数据:', jp)
    if bad:
        print('★ 有 %d 条与原文矛盾，逐条读原文确认后再交付。' % len(bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
