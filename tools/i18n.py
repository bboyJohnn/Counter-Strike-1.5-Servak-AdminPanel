"""Translations of the web panel: which texts the code has and whether everything is translated.

The source language is Russian. In static/app.js every text is wrapped in L('…'), and that Russian
text is the translation key. The server (app.py, cfg.py, …) sends its own messages in Russian and
the browser translates them with the same dictionary (Lsrv): %s and %d in them become {0}, {1}…
Words with a number use Pn(n, 'заход', 'захода', 'заходов'): their key is '#заходов' and the
value is an object with plural forms of the language — {"one": "{0} visit", "other": "{0} visits"}
(categories: zero, one, two, few, many, other — see Intl.PluralRules / CLDR).
Dictionaries are static/i18n/<code>.js: window.PANEL_I18N = { "Russian text": "translation", … }.

    python tools/i18n.py check           — per language: how much is translated, what is missing or extra,
                                           where the {0} placeholders do not match
    python tools/i18n.py keys > k.txt    — every key (number, key, where it is used); \\n inside a key is written as \\n
    python tools/i18n.py build en tr.txt — put translations into static/i18n/en.js from a file of
                                           «number<TAB>translation» lines (a plural key takes a JSON object)
    python tools/i18n.py sync            — rewrite all dictionaries in key order, dropping keys that are gone

Added a text to app.js? Wrap it in L('…'), run check and add the translations.
A missing translation just shows the Russian text; nothing breaks.
"""
import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / 'static' / 'app.js'
# модули, чьи тексты доходят до браузера: ошибки, подписи, журнал действий
PY_FILES = ['app.py', 'cfg.py', 'hl.py', 'humans.py', 'stats.py', 'geo.py', 'sysinfo.py', 'mapcycle.py', 'backups.py']
I18N_DIR = ROOT / 'static' / 'i18n'
CYR = re.compile('[А-Яа-яЁё]')
PH = re.compile(r'\{(\d+)\}')
PY_FMT = re.compile(r'%[-+ 0#]*\d*(?:\.\d+)?[sdrfx]')   # %s, %d, %.1f — место подстановки

LANGS = {'en': 'English', 'de': 'Deutsch', 'fr': 'Français', 'es': 'Español', 'pt': 'Português',
         'pl': 'Polski', 'ja': '日本語', 'zh': '中文（简体）'}

# строки Python, которые в браузер не попадают: журнал процесса, файлы
PY_SKIP = ('живой лог:', '# Карты сервера Half-Life', '# можно править и руками', '# После последней карты',
           'live bootstrap', 'reconcile:', 'stats:', 'Служебное|Service')


# ----------------------------------------------------------------- app.js: ключи из L('…') и Pn(…)

class JsScan:
    """Мини-разбор JS: пропускает комментарии, строки, регулярки; заходит внутрь ${…}."""
    KW = {'return', 'typeof', 'case', 'do', 'else', 'in', 'of', 'new', 'delete', 'void', 'throw',
          'instanceof', 'yield', 'await'}
    ESC = {'n': '\n', 't': '\t', 'r': '\r', '0': '\0'}

    def __init__(self, src):
        self.src = src
        self.keys = []

    def string(self, i):
        """Строка '…' или "…" с позиции i: (конец, значение)."""
        q, j, out = self.src[i], i + 1, []
        while self.src[j] != q:
            if self.src[j] == '\\':
                c = self.src[j + 1]
                if c == 'u':
                    out.append(chr(int(self.src[j + 2:j + 6], 16)))
                    j += 6
                    continue
                out.append(self.ESC.get(c, c))
                j += 2
                continue
            out.append(self.src[j])
            j += 1
        return j + 1, ''.join(out)

    def skip_ws(self, j):
        while j < len(self.src):
            if self.src[j] in ' \t\r\n':
                j += 1
            elif self.src.startswith('//', j):
                j = self.src.index('\n', j)
            elif self.src.startswith('/*', j):
                j = self.src.index('*/', j) + 2
            else:
                break
        return j

    def strings_from(self, j):
        """Строка или сумма строк с позиции j: (конец, значение) или (j, None)."""
        j = self.skip_ws(j)
        if self.src[j] not in '\'"':
            return j, None
        j, val = self.string(j)
        while True:
            k = self.skip_ws(j)
            if self.src[k] != '+':
                break
            k = self.skip_ws(k + 1)
            if self.src[k] not in '\'"':
                break
            j, more = self.string(k)
            val += more
        return j, val

    def l_call(self, j, ctx=False):
        """После «L(»: первый аргумент — строка или сумма строк. Lx('контекст', 'текст') — ключ «контекст|текст»."""
        prefix = ''
        if ctx:
            j, prefix = self.strings_from(j)
            if prefix is None:
                return
            j = self.skip_ws(j)
            if self.src[j] != ',':
                return
            prefix += '|'
            j += 1
        j, val = self.strings_from(j)
        if val is not None:
            self.keys.append((prefix + val, self.src.count('\n', 0, j) + 1))

    def pn_call(self, j):
        """После «Pn(»: число, потом три формы слова. Ключ — «#» + третья форма."""
        depth = 0
        while True:                       # пропустить первый аргумент до запятой верхнего уровня
            c = self.src[j]
            if c in '([{':
                depth += 1
            elif c in ')]}':
                depth -= 1
            elif c == ',' and depth == 0:
                break
            j += 1
        forms = []
        for _ in range(3):
            j, val = self.strings_from(j + 1)
            if val is None:
                return
            forms.append(val)
            j = self.skip_ws(j)
        self.keys.append(('#' + forms[2], self.src.count('\n', 0, j) + 1))

    def code(self, i, stop_brace=False):
        src, n, depth, prev = self.src, len(self.src), 0, None
        while i < n:
            c = src[i]
            if c in ' \t\r\n':
                i += 1
            elif src.startswith('//', i):
                j = src.find('\n', i)
                i = n if j < 0 else j
            elif src.startswith('/*', i):
                i = src.index('*/', i) + 2
            elif c in '\'"':
                i, _ = self.string(i)
                prev = 'v'
            elif c == '`':
                i += 1
                while src[i] != '`':
                    if src[i] == '\\':
                        i += 2
                    elif src.startswith('${', i):
                        i = self.code(i + 2, True) + 1
                    else:
                        i += 1
                i += 1
                prev = 'v'
            elif c == '/' and (prev is None or prev in self.KW or prev not in ('v', ')', ']', '}')):
                j, cls = i + 1, False
                while cls or src[j] != '/':
                    if src[j] == '\\':
                        j += 1
                    elif src[j] == '[':
                        cls = True
                    elif src[j] == ']':
                        cls = False
                    j += 1
                i = j + 1
                while i < n and src[i].isalpha():
                    i += 1
                prev = 'v'
            elif c.isalpha() or c in '_$':
                j = i
                while j < n and (src[j].isalnum() or src[j] in '_$'):
                    j += 1
                word = src[i:j]
                if word in ('L', 'Lx', 'Pn') and src[i - 1] != '.':
                    k = self.skip_ws(j)
                    if src[k] == '(' and not src[i - 9:i].endswith('function '):
                        if word == 'Pn':
                            self.pn_call(k + 1)
                        else:
                            self.l_call(k + 1, word == 'Lx')
                prev = word if word in self.KW else 'v'
                i = j
            elif c.isdigit():
                while i < n and (src[i].isalnum() or src[i] in '._'):
                    i += 1
                prev = 'v'
            else:
                if stop_brace and c == '}' and depth == 0:
                    return i
                depth += c == '{'
                depth -= c == '}'
                prev = c
                i += 1
        return i


def js_keys():
    sc = JsScan(APP_JS.read_text(encoding='utf-8'))
    sc.code(0)
    return sc.keys


# ----------------------------------------------------------------- *.py: тексты сервера

def py_to_ph(text):
    """'%s: от %d до %d.' → '{0}: от {1} до {2}.' (нумерация заново в каждой строке)."""
    out = []
    for line in text.split('\n'):
        n = [0]

        def sub(m):
            if m.group(0) == '%%':
                return '%'
            n[0] += 1
            return '{%d}' % (n[0] - 1)
        out.append(re.sub(r'%%|%[-+ 0#]*\d*(?:\.\d+)?[sdrfx]', sub, line))
    return '\n'.join(out)


def py_keys(path):
    src = path.read_text(encoding='utf-8')
    toks = [t for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type not in (tokenize.NL, tokenize.COMMENT)]
    keys = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.type != tokenize.STRING:
            i += 1
            continue
        # подряд идущие строки Python склеивает сам
        j, parts = i, []
        while j < len(toks) and toks[j].type == tokenize.STRING:
            parts.append(toks[j])
            j += 1
        prev = toks[i - 1] if i else None
        is_doc = prev is None or prev.type in (tokenize.INDENT, tokenize.NEWLINE, tokenize.DEDENT) and \
            parts[0].string.startswith(('"""', "'''")) and toks[j].type == tokenize.NEWLINE
        i = j
        if is_doc or any(p.string[:1] in 'bBfF' for p in parts):
            continue
        try:
            val = "".join(ast.literal_eval(p.string) for p in parts)
        except Exception:
            continue
        if not isinstance(val, str) or not CYR.search(val) or any(s in val for s in PY_SKIP):
            continue
        nxt = toks[j] if j < len(toks) else None
        if nxt is not None and nxt.type == tokenize.OP and nxt.string == '%' or PY_FMT.search(val):
            val = py_to_ph(val)
        elif '{' in val:
            continue        # .format-шаблоны и SQL — не тексты для людей
        if nxt is not None and nxt.type == tokenize.OP and nxt.string == '+':
            val += '{%d}' % len(PH.findall(val.split('\n')[-1]))
        for line in val.split('\n'):
            line = line.strip(' ')
            if CYR.search(line):
                keys.append((line, parts[0].start[0]))
    return keys


def all_keys():
    seen = {}
    for k, ln in js_keys():
        seen.setdefault(k, 'app.js:%d' % ln)
    for name in PY_FILES:
        p = ROOT / name
        if p.exists():
            for k, ln in py_keys(p):
                seen.setdefault(k, '%s:%d' % (name, ln))
    return seen


# ----------------------------------------------------------------- словари

HEAD = ('// {name} — translation of the Half-Life server web panel. The key is the Russian text from static/app.js\n'
        '// and the server modules; keep {{0}}, {{1}}… placeholders. Keys starting with # are plural forms.\n'
        '// Check: python tools/i18n.py check\n')


def load_dict(code):
    p = I18N_DIR / ('%s.js' % code)
    if not p.exists():
        return {}
    text = p.read_text(encoding='utf-8')
    body = text[text.index('{', text.index('PANEL_I18N')):text.rindex('}') + 1]
    return json.loads(body)


def save_dict(code, d, keys):
    order = [k for k in keys if k in d]
    lines = ['%s: %s' % (json.dumps(k, ensure_ascii=False), json.dumps(d[k], ensure_ascii=False)) for k in order]
    I18N_DIR.mkdir(exist_ok=True)
    (I18N_DIR / ('%s.js' % code)).write_text(
        HEAD.format(name=LANGS.get(code, code)) + 'window.PANEL_I18N = {\n' + ',\n'.join(lines) + '\n};\n',
        encoding='utf-8', newline='\n')


def ph_set(s):
    if isinstance(s, dict):
        return sorted(set().union(*(PH.findall(v) for v in s.values() if isinstance(v, str)))) if s else []
    return sorted(set(PH.findall(s)))


def bad_value(k, v):
    """Что не так с переводом: пусто, не тот тип, не те подстановки."""
    if k.startswith('#'):
        if not isinstance(v, dict) or 'other' not in v:
            return 'plural key needs an object with at least "other"'
        if any(not isinstance(x, str) or '{0}' not in x for x in v.values()):
            return 'every plural form needs {0}'
        return ''
    if not isinstance(v, str) or not v.strip():
        return 'empty'
    if ph_set(k) != ph_set(v):
        return 'placeholders differ'
    return ''


def check():
    keys = all_keys()
    print('keys: %d (app.js and server modules)' % len(keys))
    bad = 0
    for code, name in LANGS.items():
        d = load_dict(code)
        missing = [k for k in keys if k not in d]
        extra = [k for k in d if k not in keys]
        wrong = [(k, bad_value(k, d[k])) for k in keys if k in d and bad_value(k, d[k])]
        print('%-3s %-14s translated %4d / %d, missing %d, extra %d, broken %d' % (
            code, name, len(keys) - len(missing), len(keys), len(missing), len(extra), len(wrong)))
        for k in missing[:8]:
            print('      missing: %s   (%s)' % (k.replace('\n', '\\n')[:90], keys[k]))
        for k, why in wrong[:8]:
            print('      %s: %s  ->  %s' % (why, k[:60], str(d[k])[:60]))
        bad += len(wrong)
    return bad


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'check'
    if cmd == 'check':
        sys.exit(1 if check() else 0)
    keys = all_keys()
    order = list(keys)
    if cmd == 'keys':
        for n, k in enumerate(order, 1):
            print('%d\t%s\t%s' % (n, k.replace('\\', '\\\\').replace('\n', '\\n'), keys[k]))
    elif cmd == 'build':
        code, src = sys.argv[2], Path(sys.argv[3])
        d = load_dict(code)
        for line in src.read_text(encoding='utf-8').splitlines():
            if not line.strip() or line.startswith('#'):
                continue
            num, _, tr = line.partition('\t')
            k = order[int(num) - 1]
            d[k] = json.loads(tr) if k.startswith('#') else tr.replace('\\n', '\n')
        save_dict(code, d, order)
        print('%s: %d translations' % (code, len(d)))
    elif cmd == 'sync':
        for code in LANGS:
            save_dict(code, load_dict(code), order)
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
