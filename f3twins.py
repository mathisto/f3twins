#!/usr/bin/env python3
"""f3twins: find the Fallout New Vegas decomp twin of a Fallout 3 function.

For a Fallout 3 PC 1.7.0.3 function address, ranks the functions of the public FNV decomp
(github.com/momusdigital/fnv_decomp) that are most likely the same original source, with file:line and a calibrated
confidence (high / medium / low). Start a match from the FNV twin: same structure, names and constants.

It matches Fallout 3 machine code (from your own copy of the game) against FNV *source text*, because the Steam
FalloutNV.exe is encrypted on disk. Signals: string literals, RTTI types in dynamic_casts, non-trivial constants, float
constants and callee names, weighted by rarity (IDF); link-order anchoring (both games keep their file and function
order, so a function between two known twins has its twin between their FNV counterparts); caller propagation; and a
second round that names callees through their own first-round twins. Known pairs come from same-named functions and
from F3 functions the project's reuse tooling named FUN_<FNV address>.

Setup (paths through environment variables; the first three are the same ones f3check uses):
  F3CHECK_IMAGE    your own Fallout3.exe, 1.7.0.3 (the image f3check accepts)
  F3CHECK_SYMBOLS  f3decomp_symbols.json   (f3decomp shared files)
  F3CHECK_INDEX    function_index.json     (f3decomp shared files)
  FNV_DECOMP       a clone of github.com/momusdigital/fnv_decomp
  F3TWINS_CACHE    where the index goes (default ./f3twins-cache). Derived from your game image: keep it private.
  F3TWINS_SEEDS    optional extra known pairs, {"<F3 addr>": "<FNV addr>"} (default: seeds.json beside this script)
  pip install capstone   (Python 3.10+)

  python f3twins.py build              index both sides (a few minutes, once; again when the shared symbols update)
  python f3twins.py all                precompute twins for every function (seconds)
  python f3twins.py 0x00664aa0 ...     top candidates for addresses
  python f3twins.py live 0x00664aa0    the same, with the evidence behind each score
  python f3twins.py validate [0.8]     recall on known pairs (optionally hiding that share of the anchors)
"""
import collections, json, math, os, pickle, re, struct, sys
from pathlib import Path


def _env_path(name, default=None):
    v = os.environ.get(name, default)
    if v is None: sys.exit('f3twins: set %s (see the docstring: python f3twins.py)' % name)
    return Path(v)


FNV = _env_path('FNV_DECOMP')
IMG = _env_path('F3CHECK_IMAGE')
SYM = _env_path('F3CHECK_SYMBOLS')
IDX = _env_path('F3CHECK_INDEX')
CACHE = _env_path('F3TWINS_CACHE', 'f3twins-cache')
FNV_CACHE = CACHE / 'fnv_index.pkl'          # from the public FNV source
F3_CACHE = CACHE / 'f3_features.pkl'         # from your game image: private
OUT = CACHE / 'twins.json'                   # from your game image: private

HEXY = re.compile(r'[0-9a-fA-F]{6,}')
KEYWORDS = set('if while for switch return sizeof static_cast reinterpret_cast const_cast dynamic_cast new delete '
               'case do else operator defined __declspec __asm catch throw typeid'.split())


# ------------------------------------------------------------------ names
def parse_ms(sym):
    """(scope, name) from an MSVC-decorated name, roughly. Constructors -> (C, C), destructors -> (C, ~C)."""
    if not sym.startswith('?'):
        return '', sym.lstrip('_').split('@')[0]
    s = sym[1:]
    kind = ''
    if s.startswith('?0'): kind, s = 'ctor', s[2:]
    elif s.startswith('?1'): kind, s = 'dtor', s[2:]
    elif s.startswith('?_G') or s.startswith('?_E'): kind, s = 'deldtor', s[3:]
    elif s.startswith('?'): return '', ''           # operators and other special names
    if s.startswith('$'): return '', ''             # templates: skip
    parts = s.split('@@')[0].split('@')
    parts = [p for p in parts if p and not p.startswith('?') and not p[0].isdigit()]
    if not parts: return '', ''
    if kind == 'ctor': return parts[0], parts[0]
    if kind == 'dtor': return parts[0], '~' + parts[0]
    if kind == 'deldtor': return parts[0], '`deleting~' + parts[0]
    return (parts[1] if len(parts) > 1 else ''), parts[0]


def real_name(scope, name):
    """True for names that look like real game names (not FUN_xxxxxxxx, stand-ins or generated shells)."""
    if not name or HEXY.search(name) or HEXY.search(scope): return False
    if name.startswith(('FUN_', 'unk', 'Unk', 'sub_', 'thunk', '`')): return False
    if re.search(r'\d{2,}$', scope) or re.search(r'\d{3,}', name): return False   # Interp71, Item123 style stand-ins
    return True


# ------------------------------------------------------------------ FNV source side
STR_RE = re.compile(r'"((?:[^"\\\n]|\\.)*)"')
HEX_RE = re.compile(r'\b0x([0-9a-fA-F]+)[uUlL]*\b')
DEC_RE = re.compile(r'(?<![\w.])(\d+)[uUlL]*\b(?!\.)')
FLT_RE = re.compile(r'(?<![\w.])(\d+\.\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?)[fF]?\b')
CALL_RE = re.compile(r'([A-Za-z_~]\w*)\s*\(')
DYN_RE = re.compile(r'dynamic_cast\s*<\s*(?:const\s+)?(\w+)')


def unescape(s):
    try: return bytes(s, 'latin-1', 'backslashreplace').decode('unicode_escape', 'replace')
    except Exception: return s


def f32(x):
    try: return struct.unpack('<f', struct.pack('<f', float(x)))[0]
    except (OverflowError, ValueError): return None


def text_features(body):
    feats = set()
    for m in STR_RE.finditer(body):
        v = unescape(m.group(1))
        if len(v) >= 3: feats.add('s:' + v)
    clean = STR_RE.sub('""', body)
    for m in HEX_RE.finditer(clean):
        v = int(m.group(1), 16)
        if 0x100 <= v <= 0xffffffff and not (0x400000 <= v < 0x1600000): feats.add('k:%d' % v)
    for m in DEC_RE.finditer(clean):
        v = int(m.group(1))
        if 0x100 <= v <= 0xffffffff: feats.add('k:%d' % v)
    for m in FLT_RE.finditer(clean):
        v = f32(m.group(1))
        if v is not None and v not in (0.0, 1.0): feats.add('f:%r' % v)
    for m in DYN_RE.finditer(clean): feats.add('t:' + m.group(1))
    for m in CALL_RE.finditer(clean):
        n = m.group(1)
        if n not in KEYWORDS: feats.add('c:' + n)
    return feats


def strip_comments(t):
    t = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'), t, flags=re.S)
    return re.sub(r'//[^\n]*', '', t)


def find_body(text, scope, name):
    """(line, body) of the first definition of scope::name (or name) in text, or None."""
    nm = re.escape(name.lstrip('~'))
    pats = []
    if scope:
        pats.append(re.compile(r'\b%s\s*::\s*%s%s\s*\(' % (re.escape(scope), '~' if name.startswith('~') else '', nm)))
    pats.append(re.compile(r'(?<![\w:.>])%s%s\s*\(' % ('~' if name.startswith('~') else '', nm)))
    for pat in pats:
        for m in pat.finditer(text):
            i = m.end() - 1; depth = 0
            while i < len(text):
                if text[i] == '(': depth += 1
                elif text[i] == ')':
                    depth -= 1
                    if depth == 0: break
                i += 1
            j = i + 1
            tail = text[j:j + 400]
            mm = re.match(r'\s*(?:const\s*)?(?:throw\s*\(\s*\)\s*)?(:[^{;]*)?\{', tail)
            if not mm: continue
            k = j + mm.end() - 1; depth = 0; start = k
            while k < len(text):
                c = text[k]
                if c == '"':
                    k += 1
                    while k < len(text) and text[k] != '"':
                        k += 2 if text[k] == '\\' else 1
                elif c == "'":
                    k += 1
                    while k < len(text) and text[k] != "'":
                        k += 2 if text[k] == '\\' else 1
                elif c == '{': depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0: break
                k += 1
            return text.count('\n', 0, m.start()) + 1, text[start:k + 1]
    return None


def build_fnv():
    units = json.loads((FNV / 'build' / 'units.json').read_text(encoding='utf-8'))['units']
    entries, texts, found = [], {}, 0
    for u in units:
        src = u['source']
        p = FNV / src
        if src not in texts:
            try: texts[src] = strip_comments(p.read_text(encoding='utf-8', errors='replace'))
            except OSError: texts[src] = ''
        text = texts[src]
        for f in u['functions']:
            scope, name = parse_ms(f['symbol'])
            if not name: continue
            hit = find_body(text, scope, name) if text else None
            feats, line = set(), 0
            if hit:
                line, body = hit
                feats = text_features(body); found += 1
            entries.append(dict(addr=int(f['address'], 16), symbol=f['symbol'], scope=scope, name=name,
                                size=f['size'], src=src, line=line, feats=feats, real=real_name(scope, name)))
    print('FNV: %d functions, bodies found for %d' % (len(entries), found))
    return entries


# ------------------------------------------------------------------ Fallout 3 image side
def load_pe(path):
    b = path.read_bytes()
    pe = struct.unpack_from('<I', b, 0x3c)[0]
    nsec = struct.unpack_from('<H', b, pe + 6)[0]
    optsz = struct.unpack_from('<H', b, pe + 20)[0]
    base = struct.unpack_from('<I', b, pe + 24 + 28)[0]
    secs = []; o = pe + 24 + optsz
    for _ in range(nsec):
        vs, va, rs, rp = struct.unpack_from('<IIII', b, o + 8)
        secs.append((base + va, max(vs, rs), rp, rs)); o += 40
    return b, secs


class Image:
    def __init__(self, path):
        self.b, self.secs = load_pe(path)

    def off(self, va):
        for sva, sz, rp, rs in self.secs:
            if sva <= va < sva + sz and va - sva < rs: return rp + va - sva
        return None

    def read(self, va, n):
        o = self.off(va)
        return None if o is None else self.b[o:o + n]

    def cstr(self, va, maxlen=200):
        o = self.off(va)
        if o is None: return None
        e = self.b.find(b'\0', o, o + maxlen)
        if e < 0 or e - o < 3: return None
        s = self.b[o:e]
        if all(32 <= c < 127 or c in (9, 10, 13) for c in s): return s.decode('latin-1')
        return None


def build_f3():
    import capstone
    from capstone import x86_const as X
    img = Image(IMG)
    sym = json.loads(SYM.read_text(encoding='utf-8'))['functions']
    names = {}
    for e in sym:
        a = int(e['address'], 16)
        names.setdefault(a, e['symbol'])
    addrs = sorted({int(e['address'], 16) for e in json.loads(IDX.read_text())})
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32); md.detail = True
    feats = {}
    for i, a in enumerate(addrs):
        if not (0x401000 <= a < 0xfde58b): continue
        size = (addrs[i + 1] - a) if i + 1 < len(addrs) else 64
        if size <= 0 or size > 0x10000: continue
        code = img.read(a, size)
        if not code: continue
        fs, callees = set(), []
        for ins in md.disasm(code, a):
            if ins.id == X.X86_INS_CALL and ins.operands and ins.operands[0].type == X.X86_OP_IMM:
                callees.append(ins.operands[0].imm & 0xffffffff); continue
            for op in ins.operands:
                v = None; is_mem = False
                if op.type == X.X86_OP_IMM: v = op.imm & 0xffffffff
                elif op.type == X.X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
                    v = op.mem.disp & 0xffffffff; is_mem = True
                if v is None: continue
                if 0x400000 <= v < 0x1600000:
                    s = img.cstr(v)
                    if s: fs.add('s:' + s); continue
                    td = img.cstr(v + 8)
                    if td and td.startswith(('.?AV', '.?AU')): fs.add('t:' + td[4:].split('@')[0]); continue
                    if is_mem and op.size in (4, 8) and ins.mnemonic.startswith('f'):
                        raw = img.read(v, op.size)
                        if raw:
                            fv = struct.unpack('<f', raw)[0] if op.size == 4 else f32(struct.unpack('<d', raw)[0])
                            if fv is not None and fv == fv and fv not in (0.0, 1.0): fs.add('f:%r' % fv)
                elif not is_mem and v >= 0x100 and v not in (0xffffffff, 0xfffffffe) and v < 0xffff0000:
                    fs.add('k:%d' % v)
        feats[a] = (size, fs, callees)
    print('F3: features for %d functions' % len(feats))
    return feats, names


# ------------------------------------------------------------------ scoring
class Scorer:
    def __init__(self, fnv):
        self.fnv = sorted(fnv, key=lambda e: e['addr'])
        self.pos = {e['addr']: i for i, e in enumerate(self.fnv)}
        df = collections.Counter(f for e in self.fnv for f in e['feats'])
        n = sum(1 for e in self.fnv if e['feats'])
        self.idf = {f: math.log(n / c) for f, c in df.items()}
        self.inv = collections.defaultdict(list)
        for i, e in enumerate(self.fnv):
            for f in e['feats']:
                if df[f] <= 400: self.inv[f].append(i)       # very common features only score, never retrieve
        byname = collections.defaultdict(list)
        for i, e in enumerate(self.fnv): byname[fnv_call_name(e)].append(i)
        self.callees_of = {}
        for i, e in enumerate(self.fnv):
            cs = [byname[f[2:]][0] for f in e['feats'] if f.startswith('c:') and len(byname.get(f[2:], ())) == 1]
            if cs: self.callees_of[i] = cs

    def score(self, size, fs, extra=None, k=3):
        extra = extra or {}
        cand = collections.Counter()
        for f in fs:
            for i in self.inv.get(f, ()): cand[i] += 1
        pool = {i for i, _ in cand.most_common(200)} | set(extra)
        out = []
        for i in pool:
            e = self.fnv[i]
            shared = fs & e['feats']
            sc = sum(self.idf.get(f, 0) for f in shared) + extra.get(i, 0)
            r = e['size'] / max(size, 1)
            if r < 0.33 or r > 4.0: sc *= 0.5                 # FNV /Od code runs larger than FO3 /O2
            out.append((sc, i, shared))
        out.sort(key=lambda t: -t[0])
        return out[:k]


def f3_feature_set(fs, callees, names, cmap, exclude_self=None):
    out = set(fs)
    for c in callees:
        if c == exclude_self: continue
        if c in cmap: out.add('c:' + cmap[c]); continue
        sym = names.get(c)
        if sym:
            scope, name = parse_ms(sym)
            if real_name(scope, name): out.add('c:' + name.lstrip('~'))
    return out


def fnv_call_name(e):
    return e['name'].lstrip('~') if e['real'] else (e['name'] if e['name'].startswith('FUN_') else e['name'])


def load_all(rebuild=False):
    CACHE.mkdir(parents=True, exist_ok=True)
    if FNV_CACHE.exists() and not rebuild: fnv = pickle.loads(FNV_CACHE.read_bytes())
    else:
        fnv = build_fnv(); FNV_CACHE.write_bytes(pickle.dumps(fnv))
    if F3_CACHE.exists() and not rebuild: f3, names = pickle.loads(F3_CACHE.read_bytes())
    else:
        f3, names = build_f3(); F3_CACHE.write_bytes(pickle.dumps((f3, names)))
    return fnv, f3, names


def seeds(fnv, names):
    """F3 address -> FNV entry for unique same-name pairs (both sides real names)."""
    fk = collections.defaultdict(list)
    for e in fnv:
        if e['real'] and e['scope']: fk[(e['scope'], e['name'])].append(e)
    out = {}
    for a, sym in names.items():
        scope, name = parse_ms(sym)
        if scope and real_name(scope, name):
            l = fk.get((scope, name))
            if l and len(l) == 1: out[a] = l[0]
    return out


ANCHOR_BONUS, ANCHOR_REACH, CALLER_BONUS = 4.0, 12, 3.0


def context_bonus(a, ordinal, f3_order, twin_idx, callers, sc):
    """Link-order anchoring (nearest twinned F3 neighbours on each side) and caller propagation."""
    extra = collections.Counter()
    k = ordinal[a]
    for step in (-1, 1):                                       # previous and next anchors
        for d in range(1, ANCHOR_REACH + 1):
            j = k + step * d
            if not (0 <= j < len(f3_order)): break
            t = twin_idx.get(f3_order[j])
            if t is None: continue
            for dd in range(1, d + 5):                          # FNV may hold a few extra (or fewer) functions
                i = t - step * dd
                if 0 <= i < len(sc.fnv):
                    extra[i] += ANCHOR_BONUS * math.exp(-abs(dd - d) / 1.5) / (1 + 0.15 * d)
            break
    for c in callers.get(a, ()):
        t = twin_idx.get(c)
        if t is not None:
            for i in set(sc.callees_of.get(t, ())): extra[i] += CALLER_BONUS
    return extra


def run(targets, fnv, f3, names, seedmap, exclude_seed_of_target=False, rounds=2, margin=1.5):
    sc = Scorer(fnv)
    cmap = {a: fnv_call_name(e) for a, e in seedmap.items()}
    twin_idx = {a: sc.pos[e['addr']] for a, e in seedmap.items() if e['addr'] in sc.pos}
    f3_order = sorted(f3)
    ordinal = {a: i for i, a in enumerate(f3_order)}
    callers = collections.defaultdict(list)
    for a, (_, _, cs) in f3.items():
        for c in cs: callers[c].append(a)
    res = {}
    for rnd in range(rounds):
        res = {}
        for a in targets:
            if a not in f3: continue
            size, fs, callees = f3[a]
            m, ti = cmap, twin_idx
            if exclude_seed_of_target and a in twin_idx:
                m = dict(cmap); m.pop(a, None); ti = dict(twin_idx); ti.pop(a, None)
            feats = f3_feature_set(fs, callees, names, m)
            res[a] = sc.score(size, feats, context_bonus(a, ordinal, f3_order, ti, callers, sc))
        if rnd + 1 < rounds:                                  # propagate confident twins into the maps
            for a, r in res.items():
                if a in twin_idx or not r: continue
                if r[0][0] >= 8 and (len(r) == 1 or r[0][0] >= margin * r[1][0]):
                    cmap[a] = fnv_call_name(sc.fnv[r[0][1]]); twin_idx[a] = r[0][1]
    return res, sc


def reuse_pairs(fnv, names):
    """F3 address -> FNV entry where the F3 function is named FUN_<FNV address> (the project's New Vegas reuse
    tooling names reused functions after their FNV twin). Code addresses only; statics and data are skipped."""
    by = {e['addr']: e for e in fnv}
    out = {}
    for a, sym in names.items():
        if not (0x401000 <= a < 0xfde58b) or sym.startswith('?$S'): continue
        scope, name = parse_ms(sym)
        m = re.fullmatch(r'FUN_([0-9a-fA-F]{8})', name or '')
        if not m: continue
        v = int(m.group(1), 16)
        if v != a and v in by: out[a] = by[v]
    return out


def validate(fnv, f3, names, holdout=0.0):
    if holdout:                                               # hide a random share of all seeds; score only those
        import random
        rnd = random.Random(1); full = all_seeds(fnv, names)
        hidden = {a: e for a, e in full.items() if rnd.random() < holdout}
        kept = {a: e for a, e in full.items() if a not in hidden}
        _validate('holdout %.0f%% of all seeds' % (100 * holdout), hidden, fnv, f3, names, seedmap=kept)
        return
    for label, truth in (('same-name pairs', seeds(fnv, names)), ('NV-reuse pairs', reuse_pairs(fnv, names))):
        _validate(label, truth, fnv, f3, names)


def all_seeds(fnv, names):
    m = reuse_pairs(fnv, names); m.update(seeds(fnv, names))
    # Hand-confirmed pairs ({"<F3 addr>": "<FNV addr>"}): seeds.json beside this script, or F3TWINS_SEEDS.
    extra = Path(os.environ.get('F3TWINS_SEEDS', Path(__file__).resolve().parent / 'seeds.json'))
    if extra.exists():
        by = {e['addr']: e for e in fnv}
        for a, f in json.loads(extra.read_text()).items():
            e = by.get(int(f, 16))
            if e: m.setdefault(int(a, 16), e)
    return m


def _validate(label, sm, fnv, f3, names, seedmap=None):
    seedmap = all_seeds(fnv, names) if seedmap is None else seedmap
    targets = [a for a in sm if a in f3 and (f3[a][1] or f3[a][2])]
    print('\n%s: %d (with features: %d)' % (label, len(sm), len(targets)))
    # The target's own name is never a feature of itself (features come from its body); exclude its seed so it cannot
    # name itself through recursion. Callees are named through the seed map, as in production.
    res, sc = run(targets, fnv, f3, names, seedmap, exclude_seed_of_target=True)
    bands = [(0, 128), (128, 256), (256, 512), (512, 1024), (1024, 1 << 30)]
    tot = collections.Counter()
    for a in targets:
        size = f3[a][0]; band = next(b for b in bands if b[0] <= size < b[1])
        r = res.get(a) or []
        truth = sm[a]['addr']
        top = [sc.fnv[i]['addr'] for _, i, _ in r]
        tot[(band, 'n')] += 1
        if top[:1] == [truth]: tot[(band, '1')] += 1
        if truth in top[:3]: tot[(band, '3')] += 1
        if not r: tot[(band, 'none')] += 1
    print('%-12s %6s %8s %8s %8s' % ('size band', 'n', 'recall@1', 'recall@3', 'no cand'))
    for b in bands:
        n = tot[(b, 'n')]
        if n: print('%-12s %6d %7.1f%% %7.1f%% %7.1f%%' % ('%d-%s' % (b[0], b[1] if b[1] < 1 << 30 else '+'), n,
                    100 * tot[(b, '1')] / n, 100 * tot[(b, '3')] / n, 100 * tot[(b, 'none')] / n))


def confidence(r):
    """Measured on a holdout with 80% of anchors hidden: high ~93% right at rank 1, medium ~76%, low ~45%."""
    if not r: return 'none'
    shared = r[0][2] if len(r[0]) > 2 else set()
    if shared and all(f.startswith('f:') for f in shared): return 'low'   # float constants alone mislead
    s1 = r[0][0]; s2 = r[1][0] if len(r) > 1 else 0.0
    q = s1 / max(s2, 0.1)
    strong = sum(1 for f in shared if f[:2] in ('s:', 't:', 'k:'))
    calls = sum(1 for f in shared if f.startswith('c:'))
    conf = 'high' if s1 >= 20 and q >= 2 else 'medium' if s1 >= 10 and q >= 1.5 else 'low'
    if conf == 'high' and strong == 0 and calls < 2: conf = 'medium'      # anchoring alone is not enough for high
    return conf


def show(addrs, fnv, f3, names):
    if OUT.exists():                                          # the full run has the most propagation context
        pre = json.loads(OUT.read_text())
        if all(('0x%08x' % a) in pre for a in addrs):
            for a in addrs:
                r = pre['0x%08x' % a]
                print('== 0x%08x (%s B)  confidence: %s' % (a, f3.get(a, (0,))[0], r[0]['conf']))
                for c in r:
                    print('  %6.1f  %s  fnv %s  %s:%d' % (c['score'], (c['scope'] + '::' if c['scope'] else '') + c['name'],
                                                         c['fnv'], c['src'], c['line']))
            print('(precomputed by `f3twins.py all`; run `f3twins.py live <addr>` to see the evidence)')
            return
    live(addrs, fnv, f3, names)


def live(addrs, fnv, f3, names):
    sm = all_seeds(fnv, names)
    res, sc = run(addrs, fnv, f3, names, sm)
    for a in addrs:
        print('== 0x%08x (%s B)  confidence: %s' % (a, f3.get(a, (0,))[0], confidence(res.get(a))))
        for s, i, shared in res.get(a) or []:
            e = sc.fnv[i]
            ev = sorted(shared, key=lambda f: -sc.idf.get(f, 0))[:5]
            print('  %6.1f  %s  fnv 0x%08x %dB  %s:%d' % (s, (e['scope'] + '::' if e['scope'] else '') + e['name'],
                                                        e['addr'], e['size'], e['src'], e['line']))
            print('          evidence: %s' % '; '.join(x[:60] for x in ev))


def main():
    if len(sys.argv) < 2: sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == 'build':
        load_all(rebuild=True); return
    fnv, f3, names = load_all()
    if cmd == 'validate': validate(fnv, f3, names, float(sys.argv[2]) if len(sys.argv) > 2 else 0.0)
    elif cmd == 'all':
        sm = all_seeds(fnv, names)
        res, sc = run(list(f3), fnv, f3, names, sm)
        out = {('0x%08x' % a): [dict(conf=confidence(r), score=round(s, 1), fnv=('0x%08x' % sc.fnv[i]['addr']), name=sc.fnv[i]['name'],
                                     scope=sc.fnv[i]['scope'], src=sc.fnv[i]['src'], line=sc.fnv[i]['line'])
                                for s, i, _ in r] for a, r in res.items() if r}
        OUT.write_text(json.dumps(out)); print('wrote', OUT, len(out))
    elif cmd == 'live': live([int(x, 16) for x in sys.argv[2:]], fnv, f3, names)
    else: show([int(x, 16) for x in sys.argv[1:]], fnv, f3, names)


if __name__ == '__main__':
    main()
