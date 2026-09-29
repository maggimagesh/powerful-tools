"""Pure, GUI-free logic for every tool. Must stay Python 3.6 compatible."""
import ast
import base64
import colorsys
import csv
import io
import ipaddress
import json
import math
import operator
import os
import pwd
import re
from urllib.parse import quote, unquote

# ---------------------------------------------------------------- colors

def hex_to_rgb(s):
    s = s.strip().lstrip('#')
    if len(s) == 3:
        s = ''.join(c * 2 for c in s)
    if len(s) != 6 or not re.match(r'^[0-9a-fA-F]{6}$', s):
        raise ValueError('invalid hex color')
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def rgb_to_hex(r, g, b):
    return '#%02X%02X%02X' % (r, g, b)


def _pct(v):
    return int(round(v * 100))


def color_formats(r, g, b):
    """Return [(format name, text)] for an sRGB color with 0-255 channels."""
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    h, l, s = colorsys.rgb_to_hls(rf, gf, bf)
    hv, sv, vv = colorsys.rgb_to_hsv(rf, gf, bf)
    k = 1 - max(rf, gf, bf)
    if k >= 1:
        c = m = y = 0.0
    else:
        c, m, y = [(1 - x - k) / (1 - k) for x in (rf, gf, bf)]
    return [
        ('HEX', rgb_to_hex(r, g, b)),
        ('RGB', 'rgb(%d, %d, %d)' % (r, g, b)),
        ('HSL', 'hsl(%d, %d%%, %d%%)' % (int(round(h * 360)) % 360, _pct(s), _pct(l))),
        ('HSV', 'hsv(%d, %d%%, %d%%)' % (int(round(hv * 360)) % 360, _pct(sv), _pct(vv))),
        ('CMYK', 'cmyk(%d%%, %d%%, %d%%, %d%%)' % (_pct(c), _pct(m), _pct(y), _pct(k))),
        ('Decimal', str((r << 16) | (g << 8) | b)),
        ('Float', '%.3f, %.3f, %.3f' % (rf, gf, bf)),
    ]

# ---------------------------------------------------------------- Bulk Rename

CASE_MODES = ('none', 'lower', 'upper', 'title', 'capitalize')
APPLY_TO = ('name', 'ext', 'both')
_COUNTER = re.compile(r'\$\{n\}')


def _split(name):
    base, ext = os.path.splitext(name)
    return base, ext


def rename_one(name, search, replace, use_regex=False, case_sensitive=False,
               match_all=True, apply_to='name', case_mode='none', counter=None):
    """Compute the new name for a single file name. Raises ValueError on a bad regex."""
    base, ext = _split(name)
    if apply_to == 'name':
        target = base
    elif apply_to == 'ext':
        target = ext[1:] if ext else ''
    else:
        target = name
    if counter is not None:
        replace = _COUNTER.sub(lambda m: counter, replace)
    if search:
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = search if use_regex else re.escape(search)
        try:
            rx = re.compile(pattern, flags)
        except re.error as e:
            raise ValueError('Invalid regular expression: %s' % e)
        repl = replace if use_regex else replace.replace('\\', '\\\\')
        try:
            target = rx.sub(repl, target, count=0 if match_all else 1)
        except (re.error, IndexError) as e:
            raise ValueError('Invalid replacement: %s' % e)
    if case_mode == 'lower':
        target = target.lower()
    elif case_mode == 'upper':
        target = target.upper()
    elif case_mode == 'title':
        target = target.title()
    elif case_mode == 'capitalize':
        target = target[:1].upper() + target[1:].lower()
    if apply_to == 'name':
        return target + ext
    if apply_to == 'ext':
        return base + ('.' + target if target else '')
    return target


def rename_plan(names, search, replace, start=1, increment=1, padding=0, **opts):
    """New names for a list of names. ${n} in `replace` becomes a counter."""
    out = []
    n = start
    for name in names:
        counter = str(n).zfill(padding) if padding > 0 else str(n)
        new = rename_one(name, search, replace, counter=counter, **opts)
        if new != name:
            n += increment
        out.append(new)
    return out


def validate_plan(paths, new_names):
    """Status per item: unchanged, ok, invalid, duplicate or exists."""
    moving = set(os.path.abspath(p) for p, n in zip(paths, new_names)
                 if os.path.basename(p) != n)
    targets = {}
    status = []
    for p, n in zip(paths, new_names):
        d = os.path.dirname(os.path.abspath(p))
        dest = os.path.join(d, n)
        if n == os.path.basename(p):
            status.append('unchanged')
        elif not n or n in ('.', '..') or '/' in n or '\0' in n or len(n.encode()) > 255:
            status.append('invalid')
        elif dest in targets:
            status.append('duplicate')
            status[targets[dest]] = 'duplicate'
        elif os.path.lexists(dest) and not (dest in moving or _same_file(dest, p)):
            status.append('exists')
        else:
            status.append('ok')
        targets.setdefault(dest, len(status) - 1)
    # an unchanged item occupying a target name blocks that rename
    keep = set(os.path.abspath(p) for p, s in zip(paths, status) if s == 'unchanged')
    for i, (p, n) in enumerate(zip(paths, new_names)):
        if status[i] == 'ok' and os.path.join(os.path.dirname(os.path.abspath(p)), n) in keep:
            status[i] = 'exists'
    return status


def _same_file(a, b):
    # case-only renames on case-insensitive filesystems
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def apply_renames(pairs):
    """Rename [(old, new)] safely (handles swaps). Returns the list actually done.
    On failure everything is rolled back and the error re-raised."""
    pairs = [(os.path.abspath(o), os.path.abspath(n)) for o, n in pairs if o != n]
    temps = []
    done = []
    try:
        for i, (old, new) in enumerate(pairs):
            tmp = os.path.join(os.path.dirname(old), '.pt-rename-%d-%d.tmp' % (os.getpid(), i))
            os.rename(old, tmp)
            temps.append((old, tmp, new))
        for old, tmp, new in temps:
            if os.path.lexists(new):
                raise FileExistsError('%s already exists' % new)
            os.rename(tmp, new)
            done.append((old, tmp, new))
    except Exception:
        for old, tmp, new in reversed(done):
            os.rename(new, tmp)
        for old, tmp, new in reversed(temps):
            if os.path.lexists(tmp):
                os.rename(tmp, old)
        raise
    return [(o, n) for o, t, n in done]

def apply_renames_nested(pairs, deepest_first=True):
    """Like apply_renames but safe when some items live inside renamed folders:
    each depth level is renamed as one atomic group. Returns steps in execution order."""
    groups = {}
    for o, n in pairs:
        o = os.path.abspath(o)
        groups.setdefault(o.rstrip('/').count('/'), []).append((o, os.path.abspath(n)))
    done_groups = []
    try:
        for depth in sorted(groups, reverse=deepest_first):
            done_groups.append(apply_renames(groups[depth]))
    except Exception:
        for g in reversed(done_groups):
            apply_renames([(n, o) for o, n in g])
        raise
    return [step for g in done_groups for step in g]


def track_paths(paths, steps):
    """Follow `paths` through rename steps (including renamed parent folders)."""
    for o, n in steps:
        pre = o.rstrip('/') + '/'
        paths = [n if p == o else (n + '/' + p[len(pre):] if p.startswith(pre) else p) for p in paths]
    return paths

# ---------------------------------------------------------------- hosts file

_HOST = re.compile(r'^(?=.{1,253}$)[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,62})(?:\.[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,62}))*\.?$')


def valid_ip(s):
    try:
        ipaddress.ip_address(s.split('%', 1)[0])
        return True
    except ValueError:
        return False


def valid_hostname(s):
    return bool(_HOST.match(s))


def valid_hosts(s):
    parts = s.split()
    return bool(parts) and all(valid_hostname(p) for p in parts)


def _parse_entry(body):
    if '#' in body:
        body, comment = body.split('#', 1)
        comment = comment.strip()
    else:
        comment = ''
    parts = body.split()
    if len(parts) >= 2 and valid_ip(parts[0]) and all(valid_hostname(p) for p in parts[1:]):
        return parts[0], ' '.join(parts[1:]), comment
    return None


def parse_hosts(text):
    """Returns a list of items; entries are dicts, anything else is kept as a raw string."""
    items = []
    for line in text.splitlines():
        s = line.strip()
        enabled = True
        if s.startswith('#'):
            enabled = False
            s = s.lstrip('#').strip()
        e = _parse_entry(s) if s else None
        if e:
            d = {'enabled': enabled, 'ip': e[0], 'hosts': e[1], 'comment': e[2]}
            d['_orig'] = (enabled, e[0], e[1], e[2])
            d['_line'] = line
            items.append(d)
        else:
            items.append(line)
    return items


def format_entry(d):
    line = ('' if d['enabled'] else '# ') + d['ip'].strip() + '\t' + ' '.join(d['hosts'].split())
    if d.get('comment', '').strip():
        line += '\t# ' + d['comment'].strip()
    return line


def serialize_hosts(items):
    lines = []
    for it in items:
        if isinstance(it, dict):
            key = (it['enabled'], it['ip'], it['hosts'], it.get('comment', ''))
            lines.append(it['_line'] if it.get('_orig') == key else format_entry(it))
        else:
            lines.append(it)
    return '\n'.join(lines) + '\n'

# ---------------------------------------------------------------- environment variables

ENV_BEGIN = '# >>> Powerful Tools: environment variables >>>'
ENV_END = '# <<< Powerful Tools: environment variables <<<'
# markers written by pre-release builds; recognised and replaced by the current ones on save
LEGACY_ENV = ('# >>> PowerToys for Linux: environment variables >>>',
              '# <<< PowerToys for Linux: environment variables <<<')
_BEGINS = (ENV_BEGIN, LEGACY_ENV[0])
_ENDS = (ENV_END, LEGACY_ENV[1])
_ENV_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def valid_env_name(n):
    return bool(_ENV_NAME.match(n))


def valid_env_value(v):
    return '\n' not in v and '\r' not in v and '\0' not in v


def env_quote(v):
    # double quotes keep $VAR expansion (e.g. PATH="$PATH:/opt/bin")
    return '"' + v.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`') + '"'


def env_unquote(s):
    if len(s) < 2 or s[0] != '"' or s[-1] != '"':
        return s
    out, i, s = [], 0, s[1:-1]
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s) and s[i + 1] in '\\"`$':
            out.append(s[i + 1])
            i += 2
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


def env_block_parse(text):
    out, inside = [], False
    for line in text.splitlines():
        if line.strip() in _BEGINS:
            inside = True
        elif line.strip() in _ENDS:
            inside = False
        elif inside:
            m = re.match(r'^\s*export\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
            if m:
                out.append((m.group(1), env_unquote(m.group(2).strip())))
    return out


def env_block_render(text, variables):
    """Replace (or append) the managed block in a ~/.profile text."""
    for n, v in variables:
        if not valid_env_name(n):
            raise ValueError('Invalid variable name: %r' % n)
        if not valid_env_value(v):
            raise ValueError('Value of %s must be a single line' % n)
    block = [ENV_BEGIN] + ['export %s=%s' % (n, env_quote(v)) for n, v in variables] + [ENV_END]
    lines = text.splitlines()
    stripped = [l.strip() for l in lines]
    try:
        b = next(i for i, l in enumerate(stripped) if l in _BEGINS)
        e = next(i for i, l in enumerate(stripped) if i > b and l in _ENDS)
        lines[b:e + 1] = block if variables else []
    except StopIteration:
        if variables:
            if lines and lines[-1].strip():
                lines.append('')
            lines += block
    return '\n'.join(lines) + '\n' if lines else ''

# ---------------------------------------------------------------- calculator

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod, ast.Pow: operator.pow}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {n: getattr(math, n) for n in (
    'sqrt', 'sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'log', 'log10', 'log2',
    'exp', 'floor', 'ceil', 'radians', 'degrees', 'sinh', 'cosh', 'tanh')}
_FUNCS.update({'abs': abs, 'round': round, 'ln': math.log, 'factorial': math.factorial})
_CONSTS = {'pi': math.pi, 'e': math.e, 'tau': 2 * math.pi}


def _num(node):
    if node.__class__.__name__ == 'Constant':
        v = node.value
    elif node.__class__.__name__ == 'Num':  # Python < 3.8
        v = node.n
    else:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError('not a number')
    return v


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    v = _num(node)
    if v is not None:
        return v
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and (abs(b) > 1000 or abs(a) > 1e100):
            raise ValueError('number too large')
        return _BIN[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
        return _UN[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS and not node.keywords and 1 <= len(node.args) <= 2):
        args = [_eval(a) for a in node.args]
        if node.func.id == 'factorial' and (args[0] > 1000 or args[0] != int(args[0])):
            raise ValueError('factorial argument out of range')
        return _FUNCS[node.func.id](*[int(a) if node.func.id == 'factorial' else a for a in args])
    raise ValueError('unsupported expression')


def calculate(expr):
    """Safely evaluate a math expression; returns a display string. Raises ValueError."""
    e = expr.strip().lstrip('=').replace('^', '**').replace('×', '*').replace('÷', '/').replace(',', '')
    if not e or len(e) > 300:
        raise ValueError('empty')
    try:
        tree = ast.parse(e, mode='eval')
        v = _eval(tree)
    except (SyntaxError, TypeError, ZeroDivisionError, OverflowError, RecursionError) as ex:
        raise ValueError(str(ex))
    if isinstance(v, complex) or v != v or v in (float('inf'), float('-inf')):
        raise ValueError('no real result')
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        v = int(v)
    if isinstance(v, int):
        if abs(v) >= 10 ** 30:
            return '%.12g' % v
        return str(v)
    return '%.12g' % v

# ---------------------------------------------------------------- screen ruler

def pixel_at(data, rowstride, nch, x, y):
    i = y * rowstride + x * nch
    return data[i], data[i + 1], data[i + 2]


def scan_edge(data, rowstride, nch, w, h, x, y, dx, dy, tolerance):
    """Steps from (x, y) in direction (dx, dy) while pixels stay within tolerance."""
    r0, g0, b0 = pixel_at(data, rowstride, nch, x, y)
    n = 0
    cx, cy = x + dx, y + dy
    while 0 <= cx < w and 0 <= cy < h:
        r, g, b = pixel_at(data, rowstride, nch, cx, cy)
        if abs(r - r0) > tolerance or abs(g - g0) > tolerance or abs(b - b0) > tolerance:
            break
        n += 1
        cx += dx
        cy += dy
    return n

# ---------------------------------------------------------------- image resizer

def compute_size(sw, sh, tw, th, mode='fit', unit='px', shrink_only=False):
    """Returns (scaled_w, scaled_h, final_w, final_h). final differs only for 'fill' (crop)."""
    if sw <= 0 or sh <= 0:
        raise ValueError('bad source size')
    if unit == 'percent':
        th = th or tw
        tw, th = sw * tw / 100.0, sh * th / 100.0
        mode = 'stretch'
    if tw <= 0 and th <= 0:
        raise ValueError('width or height required')
    if mode == 'stretch' and tw > 0 and th > 0:
        sx, sy = tw / float(sw), th / float(sh)
    else:
        if tw <= 0:
            s = th / float(sh)
        elif th <= 0:
            s = tw / float(sw)
        elif mode == 'fill':
            s = max(tw / float(sw), th / float(sh))
        else:
            s = min(tw / float(sw), th / float(sh))
        sx = sy = s
    if shrink_only and (sx > 1 or sy > 1):
        return sw, sh, sw, sh
    nw, nh = max(1, int(round(sw * sx))), max(1, int(round(sh * sy)))
    if mode == 'fill' and unit == 'px' and tw > 0 and th > 0:
        return nw, nh, min(nw, int(round(tw))), min(nh, int(round(th)))
    return nw, nh, nw, nh


def output_path(path, size_name, pattern='%1 (%2)', ext=None, exists=os.path.exists):
    d, name = os.path.split(path)
    base, old_ext = os.path.splitext(name)
    ext = ext if ext is not None else old_ext
    stem = pattern.replace('%1', base).replace('%2', size_name) or base
    stem = stem.replace('/', '_')
    out = os.path.join(d, stem + ext)
    i = 2
    while exists(out):
        out = os.path.join(d, '%s (%d)%s' % (stem, i, ext))
        i += 1
    return out

# ---------------------------------------------------------------- advanced paste

def _md_table(text):
    rows_src = [l for l in text.splitlines() if l.strip()]
    if not rows_src:
        raise ValueError('Clipboard is empty')
    delim = '\t' if '\t' in rows_src[0] else ','
    rows = list(csv.reader(io.StringIO('\n'.join(rows_src)), delimiter=delim))
    width = max(len(r) for r in rows)
    rows = [[c.strip().replace('|', '\\|') for c in r] + [''] * (width - len(r)) for r in rows]
    out = ['| ' + ' | '.join(rows[0]) + ' |', '|' + '---|' * width]
    out += ['| ' + ' | '.join(r) + ' |' for r in rows[1:]]
    return '\n'.join(out)


def _json_pretty(t):
    try:
        return json.dumps(json.loads(t), indent=2, ensure_ascii=False)
    except ValueError as e:
        raise ValueError('Not valid JSON: %s' % e)


def _json_min(t):
    try:
        return json.dumps(json.loads(t), separators=(',', ':'), ensure_ascii=False)
    except ValueError as e:
        raise ValueError('Not valid JSON: %s' % e)


def _b64d(t):
    try:
        return base64.b64decode(''.join(t.split()), validate=True).decode('utf-8')
    except (ValueError, UnicodeDecodeError):
        raise ValueError('Not valid Base64 text')


def _unique(t):
    seen, out = set(), []
    for l in t.splitlines():
        if l not in seen:
            seen.add(l)
            out.append(l)
    return '\n'.join(out)


PASTE_ACTIONS = [
    ('plain', 'Plain text', lambda t: t),
    ('trim', 'Trim whitespace', lambda t: '\n'.join(l.strip() for l in t.strip().splitlines())),
    ('upper', 'UPPERCASE', lambda t: t.upper()),
    ('lower', 'lowercase', lambda t: t.lower()),
    ('title', 'Title Case', lambda t: t.title()),
    ('json', 'Format JSON', _json_pretty),
    ('jsonmin', 'Minify JSON', _json_min),
    ('mdtable', 'CSV/TSV to Markdown table', _md_table),
    ('oneline', 'Join lines', lambda t: ' '.join(l.strip() for l in t.splitlines() if l.strip())),
    ('noblank', 'Remove blank lines', lambda t: '\n'.join(l for l in t.splitlines() if l.strip())),
    ('sort', 'Sort lines', lambda t: '\n'.join(sorted(t.splitlines(), key=str.lower))),
    ('unique', 'Remove duplicate lines', _unique),
    ('urlenc', 'URL encode', lambda t: quote(t, safe='')),
    ('urldec', 'URL decode', lambda t: unquote(t)),
    ('b64enc', 'Base64 encode', lambda t: base64.b64encode(t.encode('utf-8')).decode('ascii')),
    ('b64dec', 'Base64 decode', _b64d),
]


def paste_transform(action, text):
    for key, _label, fn in PASTE_ACTIONS:
        if key == action:
            return fn(text)
    raise KeyError(action)

# ---------------------------------------------------------------- file unlocker

def _user(uid):
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def find_lockers(paths, proc='/proc'):
    """Processes using any of `paths` (files or folders, recursive).
    Returns (list of dicts, number of processes we could not inspect)."""
    targets = [os.path.realpath(p) for p in paths]
    me = os.getpid()

    def match(p):
        if p.endswith(' (deleted)'):
            p = p[:-10]
        for t in targets:
            if p == t or p.startswith(t.rstrip('/') + '/'):
                return True
        return False

    results, denied = [], 0
    try:
        pids = [int(d) for d in os.listdir(proc) if d.isdigit()]
    except OSError:
        return [], 0
    for pid in sorted(pids):
        if pid == me:
            continue
        base = os.path.join(proc, str(pid))
        files = set()
        blocked = False
        try:
            for fd in os.listdir(os.path.join(base, 'fd')):
                try:
                    p = os.readlink(os.path.join(base, 'fd', fd))
                except OSError:
                    continue
                if p.startswith('/') and match(p):
                    files.add(p)
        except PermissionError:
            blocked = True
        except OSError:
            continue  # process exited
        for link in ('cwd', 'exe'):
            try:
                p = os.readlink(os.path.join(base, link))
                if match(p):
                    files.add(p)
            except OSError:
                pass
        try:
            with open(os.path.join(base, 'maps')) as f:
                for line in f:
                    parts = line.split(None, 5)
                    if len(parts) == 6 and parts[5].startswith('/') and match(parts[5].strip()):
                        files.add(parts[5].strip())
        except OSError:
            pass
        if blocked and not files:
            denied += 1
            continue
        if not files:
            continue
        try:
            with open(os.path.join(base, 'comm')) as f:
                name = f.read().strip()
            with open(os.path.join(base, 'cmdline'), 'rb') as f:
                cmd = f.read().replace(b'\0', b' ').decode('utf-8', 'replace').strip()
            uid = os.stat(base).st_uid
        except OSError:
            continue
        results.append({'pid': pid, 'name': name, 'cmdline': cmd or name,
                        'user': _user(uid), 'uid': uid, 'files': sorted(files)})
    return results, denied
