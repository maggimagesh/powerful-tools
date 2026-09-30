"""Plain-assert tests for powerfultools.logic. Run: python3 tests/test_logic.py"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.environ.get('PT_SRC', os.path.join(os.path.dirname(__file__), '..', 'src')))
from powerfultools import logic as L  # noqa: E402


def test_colors():
    assert L.hex_to_rgb('#ff8000') == (255, 128, 0)
    assert L.hex_to_rgb('abc') == (170, 187, 204)
    for bad in ('', '#12', 'zzzzzz', '#1234567'):
        try:
            L.hex_to_rgb(bad)
            assert False, bad
        except ValueError:
            pass
    f = dict(L.color_formats(255, 0, 0))
    assert f['HEX'] == '#FF0000' and f['RGB'] == 'rgb(255, 0, 0)'
    assert f['HSL'] == 'hsl(0, 100%, 50%)' and f['HSV'] == 'hsv(0, 100%, 100%)'
    assert f['CMYK'] == 'cmyk(0%, 100%, 100%, 0%)'
    assert f['Decimal'] == str(0xFF0000)
    assert dict(L.color_formats(0, 0, 0))['CMYK'] == 'cmyk(0%, 0%, 0%, 100%)'
    assert dict(L.color_formats(255, 255, 255))['HSL'] == 'hsl(0, 0%, 100%)'
    assert dict(L.color_formats(0, 0, 255))['HSL'] == 'hsl(240, 100%, 50%)'


def test_rename():
    r = L.rename_one
    assert r('Photo.JPG', 'photo', 'img') == 'img.JPG'
    assert r('Photo.JPG', 'photo', 'img', case_sensitive=True) == 'Photo.JPG'
    assert r('a_a_a.txt', 'a', 'b', match_all=False) == 'b_a_a.txt'
    assert r('a_a_a.txt', 'a', 'b') == 'b_b_b.txt'
    assert r('a.txt', 'txt', 'md', apply_to='ext') == 'a.md'
    assert r('a.txt', 'a.t', 'b.t', apply_to='both') == 'b.txt'
    assert r('a.txt', 'a.t', 'X') == 'a.txt'  # literal dot not in base name
    assert r('IMG_2020.png', r'IMG_(\d+)', r'photo-\1', use_regex=True) == 'photo-2020.png'
    assert r('x.txt', 'x', r'a\1b') == r'a\1b.txt'  # backslashes literal without regex
    assert r('hello world.txt', '', '', case_mode='title') == 'Hello World.txt'
    assert r('Hello.TXT', '', '', case_mode='upper') == 'HELLO.TXT'
    assert r('.bashrc', 'bash', 'zsh') == '.zshrc'
    try:
        r('a', '(', 'b', use_regex=True)
        assert False
    except ValueError:
        pass
    try:
        r('a', 'a', r'\2', use_regex=True)
        assert False
    except ValueError:
        pass
    plan = L.rename_plan(['a.jpg', 'b.jpg', 'c.png'], '^.*$', 'pic-${n}', use_regex=True, start=1, padding=3)
    assert plan == ['pic-001.jpg', 'pic-002.jpg', 'pic-003.png'], plan
    plan = L.rename_plan(['a.jpg', 'x.jpg', 'b.jpg'], 'b|a', 'n${n}', use_regex=True, start=5, increment=5)
    assert plan == ['n5.jpg', 'x.jpg', 'n10.jpg'], plan


def test_rename_apply():
    d = tempfile.mkdtemp()
    for n in ('a', 'b', 'c', 'keep'):
        with open(os.path.join(d, n), 'w') as f:
            f.write(n)
    paths = [os.path.join(d, n) for n in ('a', 'b', 'c')]
    # swap a<->b, c -> keep (blocked), c -> a (dup with b->a)
    assert L.validate_plan(paths, ['b', 'a', 'c']) == ['ok', 'ok', 'unchanged']
    assert L.validate_plan(paths, ['b', 'a', 'keep']) == ['ok', 'ok', 'exists']
    assert L.validate_plan(paths, ['x', 'x', 'c']) == ['duplicate', 'duplicate', 'unchanged']
    assert L.validate_plan(paths, ['', 'a/b', '..']) == ['invalid', 'invalid', 'invalid']
    assert L.validate_plan(paths, ['c', 'b', 'c']) == ['exists', 'unchanged', 'unchanged']
    done = L.apply_renames([(paths[0], os.path.join(d, 'b')), (paths[1], os.path.join(d, 'a'))])
    assert len(done) == 2
    assert open(os.path.join(d, 'a')).read() == 'b' and open(os.path.join(d, 'b')).read() == 'a'
    # failure rolls back
    try:
        L.apply_renames([(os.path.join(d, 'a'), os.path.join(d, 'z')), (os.path.join(d, 'b'), os.path.join(d, 'keep'))])
        assert False
    except FileExistsError:
        pass
    assert sorted(os.listdir(d)) == ['a', 'b', 'c', 'keep'], os.listdir(d)
    assert open(os.path.join(d, 'a')).read() == 'b'


def test_rename_nested():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, 'F'))
    open(os.path.join(d, 'F', 'x'), 'w').close()
    paths = [os.path.join(d, 'F'), os.path.join(d, 'F', 'x')]
    steps = L.apply_renames_nested([(paths[0], os.path.join(d, 'G')), (paths[1], os.path.join(d, 'F', 'y'))])
    assert os.path.exists(os.path.join(d, 'G', 'y'))
    now = L.track_paths(paths, steps)
    assert now == [os.path.join(d, 'G'), os.path.join(d, 'G', 'y')], now
    undo = [(n, o) for o, n in reversed(steps)]
    steps2 = L.apply_renames_nested(undo, deepest_first=False)
    assert os.path.exists(os.path.join(d, 'F', 'x'))
    assert L.track_paths(now, steps2) == paths


def test_hosts():
    text = ('# comment line\n127.0.0.1\tlocalhost\n'
            '# 10.0.0.1 blocked.example  # old\n::1 ip6-localhost ip6-loopback\n\n'
            '#not an entry at all\nfe80::1%lo0 link.local\n')
    items = L.parse_hosts(text)
    entries = [i for i in items if isinstance(i, dict)]
    assert len(entries) == 4, entries
    assert entries[1]['enabled'] is False and entries[1]['ip'] == '10.0.0.1' and entries[1]['comment'] == 'old'
    assert L.serialize_hosts(items) == text  # untouched round trip
    entries[1]['enabled'] = True
    out = L.serialize_hosts(items)
    assert '10.0.0.1\tblocked.example\t# old' in out and '# comment line' in out
    assert L.valid_ip('192.168.1.1') and L.valid_ip('::1') and not L.valid_ip('300.1.1.1')
    assert L.valid_hosts('a.b c-d') and not L.valid_hosts('') and not L.valid_hosts('-bad')
    assert not L.valid_hostname('a' * 64) and L.valid_hostname('a' * 63)


def test_env():
    prof = '# my profile\nexport FOO=1\n'
    vars_ = [('PATH', '$PATH:/opt/x'), ('Q', 'say "hi" `x` \\ end')]
    out = L.env_block_render(prof, vars_)
    assert out.startswith(prof) and L.ENV_BEGIN in out
    assert L.env_block_parse(out) == vars_
    out2 = L.env_block_render(out, [('A', 'b')])
    assert L.env_block_parse(out2) == [('A', 'b')] and out2.count(L.ENV_BEGIN) == 1
    assert L.env_block_render(out2, []) .strip() == prof.strip()
    old = 'x=1\n' + L.LEGACY_ENV[0] + '\nexport OLD="v"\n' + L.LEGACY_ENV[1] + '\n'
    assert L.env_block_parse(old) == [('OLD', 'v')]  # pre-release block is still read
    up = L.env_block_render(old, [('OLD', 'v'), ('NEW', 'w')])
    assert L.LEGACY_ENV[0] not in up and up.count(L.ENV_BEGIN) == 1 and up.startswith('x=1\n'), up
    assert L.env_block_parse(up) == [('OLD', 'v'), ('NEW', 'w')]
    for bad in [('1X', 'v'), ('A-B', 'v'), ('A', 'line1\nline2')]:
        try:
            L.env_block_render('', [bad])
            assert False
        except ValueError:
            pass
    # values survive a real shell
    sh = L.env_block_render('', vars_)
    got = subprocess.check_output(['sh', '-c', sh + 'printf %s "$Q"'], env={'PATH': '/usr/bin:/bin'})
    assert got.decode() == 'say "hi" `x` \\ end', got


def test_calc():
    c = L.calculate
    assert c('2+3*4') == '14' and c('=2^10') == '1024' and c('10/4') == '2.5'
    assert c('sqrt(16)') == '4' and c('pi') == '3.14159265359' and c('1,000*2') == '2000'
    assert c('-(3)') == '-3' and c('7//2') == '3' and c('7%3') == '1' and c('factorial(5)') == '120'
    for bad in ('', '1/0', '__import__("os")', 'a+1', '9**99999', '2**2**2**2**2', 'factorial(1e9)',
                'sqrt(-1)', '"x"*3', 'True+1', 'open("f")', '(' * 400):
        try:
            c(bad)
            assert False, bad
        except ValueError:
            pass


def test_edges():
    w, h, nch = 10, 5, 3
    rs = w * nch
    data = bytearray(b'\xff' * rs * h)
    for y in range(h):  # black vertical line at x=7
        data[y * rs + 7 * nch:y * rs + 8 * nch] = b'\0\0\0'
    data = bytes(data)
    assert L.scan_edge(data, rs, nch, w, h, 2, 2, 1, 0, 10) == 4  # x=3..6
    assert L.scan_edge(data, rs, nch, w, h, 2, 2, -1, 0, 10) == 2
    assert L.scan_edge(data, rs, nch, w, h, 2, 2, 0, 1, 10) == 2
    assert L.scan_edge(data, rs, nch, w, h, 2, 2, 0, -1, 10) == 2
    assert L.scan_edge(data, rs, nch, w, h, 2, 2, 1, 0, 255) == 7


def test_resize():
    cs = L.compute_size
    assert cs(4000, 3000, 1920, 1080) == (1440, 1080, 1440, 1080)
    assert cs(4000, 3000, 1920, 1080, mode='fill') == (1920, 1440, 1920, 1080)
    assert cs(4000, 3000, 1920, 1080, mode='stretch') == (1920, 1080, 1920, 1080)
    assert cs(4000, 3000, 50, 0, unit='percent') == (2000, 1500, 2000, 1500)
    assert cs(100, 100, 1920, 1080, shrink_only=True) == (100, 100, 100, 100)
    assert cs(100, 50, 200, 0) == (200, 100, 200, 100)
    assert cs(1, 1000, 10, 10) == (1, 10, 1, 10)
    try:
        cs(100, 100, 0, 0)
        assert False
    except ValueError:
        pass
    ex = {'/p/a (Small).jpg'}
    assert L.output_path('/p/a.jpg', 'Small') == '/p/a (Small).jpg'
    assert L.output_path('/p/a.jpg', 'Small', exists=lambda p: p in ex) == '/p/a (Small) (2).jpg'
    assert L.output_path('/p/a.gif', 'S', pattern='%1_%2', ext='.png') == '/p/a_S.png'


def test_paste():
    t = L.paste_transform
    assert t('json', '{"a":[1,2]}') == '{\n  "a": [\n    1,\n    2\n  ]\n}'
    assert t('jsonmin', '{ "a" : 1 }') == '{"a":1}'
    assert t('mdtable', 'a,b\n1,2\n3') == '| a | b |\n|---|---|\n| 1 | 2 |\n| 3 |  |'
    assert t('mdtable', 'x\ty\n1\t2') == '| x | y |\n|---|---|\n| 1 | 2 |'
    assert t('b64dec', t('b64enc', 'héllo')) == 'héllo'
    assert t('urldec', t('urlenc', 'a b&c')) == 'a b&c'
    assert t('unique', 'a\nb\na') == 'a\nb' and t('sort', 'b\nA\nc') == 'A\nb\nc'
    assert t('trim', '  a  \n b ') == 'a\nb' and t('oneline', 'a\n\n b') == 'a b'
    for bad in (('json', 'nope'), ('b64dec', '***')):
        try:
            t(*bad)
            assert False
        except ValueError:
            pass


def test_file_unlocker():
    d = tempfile.mkdtemp()
    f = os.path.join(d, 'locked file.txt')
    open(f, 'w').close()
    p = subprocess.Popen([sys.executable, '-c', 'import sys,time; h=open(sys.argv[1]); print("ok", flush=True); time.sleep(30)', f],
                         stdout=subprocess.PIPE)
    try:
        p.stdout.readline()
        res, _denied = L.find_lockers([f])
        assert any(r['pid'] == p.pid and f in r['files'] for r in res), res
        res, _ = L.find_lockers([d])  # folder match is recursive
        assert any(r['pid'] == p.pid for r in res)
        res, _ = L.find_lockers([f + 'x'])
        assert not any(r['pid'] == p.pid for r in res)
    finally:
        p.kill()
        p.wait()


def test_fancy_zones():
    for n in (2, 3, 4):
        z = L.zone_rects(n, 10, 32, 1921, 1049)  # odd sizes: no gap, no overlap
        assert len(z) == n and sum(w * h for _x, _y, w, h in z) == 1921 * 1049, z
        assert z[0][:2] == (10, 32) and max(x + w for x, _y, w, _h in z) == 1931 and max(y + h for _x, y, _w, h in z) == 1081
    assert L.zone_rects(2, 0, 0, 100, 50) == [(0, 0, 50, 50), (50, 0, 50, 50)]
    assert L.zone_rects(3, 0, 0, 100, 50)[1:] == [(50, 0, 50, 25), (50, 25, 50, 25)]
    # measured on GNOME (Yaru): in a 400px-wide window the maximize button spans x 320-354
    assert L.maximize_button_rect(':minimize,maximize,close', 0, 0, 400) == (314, 0, 40, 44)
    assert L.maximize_button_rect('close,minimize,maximize:appmenu', 100, 50, 400) == (186, 50, 40, 44)
    assert L.maximize_button_rect('appmenu:close', 0, 0, 400) is None
    # a 200x20 strip of title bar with glyphs drawn 29px apart (a compact app) and a toolbar icon further left
    w, h, strip = 200, 20, {}
    for x0 in (60, 124, 153, 182):
        for x in range(x0, x0 + 10):
            for y in range(6, 16):
                strip[(x, y)] = (220, 220, 220)
    data = bytes(bytearray(v for y in range(h) for x in range(w) for v in strip.get((x, y), (30, 30, 30))))
    assert L.button_slots(data, w * 3, 3, w, h, 3) == ([(114, 143), (143, 172), (172, 201)], 10)
    assert L.button_slots(data, w * 3, 3, w, h, 4) is None  # the toolbar icon is not in step with the buttons
    assert L.button_slots(bytes(bytearray([30]) * (w * h * 3)), w * 3, 3, w, h, 3) is None
    assert L.window_geometry((100, 100, 900, 600)) == (100, 100, 900, 600)
    assert L.window_geometry((100, 100, 900, 600), frame=(0, 0, 37, 0)) == (100, 100, 900, 563)
    assert L.window_geometry((100, 100, 900, 600), shadow=(26, 26, 23, 29)) == (74, 77, 952, 652)


def raises(fn, *args, **kw):
    """True if the call is refused with ValueError; any other exception is a bug and propagates."""
    try:
        fn(*args, **kw)
    except ValueError:
        return True
    return False


def test_edge_cases():
    # colors: surrounding spaces, lower case, every channel boundary
    assert L.hex_to_rgb('  #FfFfFf ') == (255, 255, 255) and L.hex_to_rgb('000') == (0, 0, 0)
    assert all(raises(L.hex_to_rgb, bad) for bad in ('#', 'ffff', '#ggg', 'fff fff', '٣٣٣'))
    for rgb in ((0, 0, 0), (255, 255, 255), (1, 2, 3), (254, 1, 128)):
        assert L.hex_to_rgb(dict(L.color_formats(*rgb))['HEX']) == rgb
    # rename: nothing to search for, unicode, hidden files, names without extension, extension-only changes
    r = L.rename_one
    assert r('a.txt', '', 'x') == 'a.txt' and r('', 'a', 'b') == '' and r('noext', 'no', 'an') == 'anext'
    assert r('café.TXT', 'É', 'e') == 'cafe.TXT' and r('a.tar.gz', 'gz', 'xz', apply_to='ext') == 'a.tar.xz'
    assert r('a', 'a', 'b', apply_to='ext') == 'a' and r('a.b', 'b', '', apply_to='ext') == 'a'
    assert r('x.txt', 'x', '${n}') == '${n}.txt' and r('x.txt', 'x', '${n}', counter='7') == '7.txt'
    assert r('a.b', '.', '-', apply_to='both') == 'a-b' and r('AbC.x', '', '', case_mode='capitalize') == 'Abc.x'
    assert L.rename_plan([], 'a', 'b') == [] and L.rename_plan(['a'], 'a', '${n}', start=0, padding=4) == ['0000']
    assert L.track_paths(['/a/b/c', '/a/bc'], [('/a/b', '/a/z')]) == ['/a/z/c', '/a/bc']  # /a/bc is not inside /a/b
    assert L.apply_renames([]) == [] and L.apply_renames([('/same', '/same')]) == []
    # hosts: Windows line ends, no final newline, IPv6, comments and junk are all kept as they are
    for text in ('', '\n', '127.0.0.1 a', '127.0.0.1 a\r\n::1 b\r\n', '# only a comment\n', 'not a host line\n\n\n'):
        assert L.serialize_hosts(L.parse_hosts(text)) == (text if text.endswith('\n') else text + '\n'), repr(text)
    assert [i['hosts'] for i in L.parse_hosts('1.1.1.1 a b  c\n##  2.2.2.2 d\n') if isinstance(i, dict)] == ['a b c', 'd']
    assert not any(isinstance(i, dict) for i in L.parse_hosts('1.1.1.1\n1.1.1.1 bad_host! \n999.1.1.1 a\n'))
    assert L.valid_ip('0.0.0.0') and L.valid_ip('::') and L.valid_ip('fe80::1%eth0.1') and L.valid_ip('::ffff:1.2.3.4')
    assert not any(L.valid_ip(b) for b in ('', ' ', '1.2.3', '1.2.3.4.5', '01.2.3.256', '1.2.3.4/24', 'localhost', ':::'))
    assert L.valid_hostname('a.b.') and L.valid_hostname('_srv.a') and L.valid_hostname('xn--bcher-kva.example')
    assert not any(L.valid_hostname(b) for b in ('', '.', 'a..b', '.a', 'a b', 'a/b', '*.a', 'a' * 254, 'bücher.de'))
    # environment variables: an empty block is removed, other lines never change, odd values survive a round trip
    assert L.env_block_render('', []) == '' and L.env_block_parse('') == [] and L.env_block_render('x\n', []) == 'x\n'
    assert L.env_block_parse(L.ENV_BEGIN + '\nexport A=1\n') == [('A', '1')]  # block without an end marker
    assert L.env_block_parse('export OUTSIDE=1\n' + L.ENV_BEGIN + '\nnot an export\n' + L.ENV_END + '\n') == []
    for v in ('', ' ', "it's", '\\', '\\\\"', '$', '$$', 'a=b', '#x', 'éè ❤', '\t', 'x' * 5000):
        assert L.env_block_parse(L.env_block_render('keep\n', [('V', v)])) == [('V', v)], repr(v)
    assert L.env_unquote('"') == '"' and L.env_unquote('plain') == 'plain' and L.env_unquote('""') == ''
    # calculator: formats, precedence, limits on both sides
    c = L.calculate
    assert c(' 1 + 1 ') == '2' and c('2^3^2') == '512' and c('-2^2') == '-4' and c('10 ÷ 4 × 2') == '5'
    assert c('0.1+0.2') == '0.3' and c('1e3') == '1000' and c('2**1000') != '' and c('factorial(0)') == '1'
    assert c('round(2.567, 2)') == '2.57' and c('log(8, 2)') == '3' and c('abs(-3)') == '3' and c('tau/pi') == '2'
    assert c('x' * 0 + '1' + '+1' * 149) == '150' and raises(c, '1' + '+1' * 150)  # 300 characters at most
    assert all(raises(c, b) for b in ('=', '1+', '1 2', 'pi()', 'sqrt()', 'sqrt(1,2,3)', 'log(0)', 'factorial(1.5)',
                                      'factorial(-1)', 'factorial(1001)', '5%0', '5//0', '1e999', '(-8)**0.5', '1j',
                                      'acos(2)', 'None', '[1]', '{1}', '1<2', 'not 1', '1 and 2', '~1', '1<<2'))
    # image sizes: one side given, percent, never zero, rounding, shrink-only on the exact size
    cs = L.compute_size
    assert cs(100, 50, 0, 25) == (50, 25, 50, 25) and cs(3, 3, 1, 1) == (1, 1, 1, 1) and cs(10, 10, 10, 10) == (10, 10, 10, 10)
    assert cs(1000, 1, 10, 10) == (10, 1, 10, 1) and cs(100, 100, 150, 0, unit='percent') == (150, 150, 150, 150)
    assert cs(100, 100, 50, 200, unit='percent') == (50, 200, 50, 200) and cs(100, 100, 100, 100, shrink_only=True) == (100, 100, 100, 100)
    assert cs(100, 100, 300, 50, mode='fill') == (300, 300, 300, 50) and cs(100, 100, 300, 50, mode='fill', shrink_only=True) == (100, 100, 100, 100)
    assert all(raises(cs, *a) for a in ((0, 10, 5, 5), (10, 0, 5, 5), (-1, 10, 5, 5), (10, 10, -5, -5), (10, 10, 0, 0, 'fit', 'percent')))
    assert L.output_path('/p/a', 'S') == '/p/a (S)' and L.output_path('/p/.hidden', 'S') == '/p/.hidden (S)'
    assert L.output_path('/p/a.b.jpg', 'S', pattern='') == '/p/a.b.jpg' and L.output_path('a.jpg', 'S') == 'a (S).jpg'
    # paste: empty input, quoting, non-ASCII, a field too long for the CSV reader
    t = L.paste_transform
    assert t('plain', '') == '' and t('upper', 'straße') == 'STRASSE' and t('title', "it's") == "It'S"
    assert t('mdtable', '"a,1",b|c\n') == '| a,1 | b\\|c |\n|---|---|' and t('noblank', '\n \na\n\n') == 'a'
    assert t('json', '"é"') == '"é"' and t('jsonmin', '[ ]') == '[]' and t('urlenc', '/é ') == '%2F%C3%A9%20'
    assert t('b64dec', ' aGk=\n') == 'hi' and t('b64enc', '') == '' and t('sort', '') == '' and t('unique', '\n\n') == ''
    assert all(raises(t, *b) for b in (('json', ''), ('jsonmin', '{'), ('b64dec', 'aGk'), ('b64dec', '/w=='),
                                       ('mdtable', ''), ('mdtable', ' \n '), ('mdtable', 'a,"' + 'x' * 200000 + '"')))
    try:
        t('no-such-action', 'x')
        assert False
    except KeyError:
        pass
    # screen ruler: corners, a one-pixel image, full tolerance
    one = bytes(bytearray([9, 9, 9]))
    assert all(L.scan_edge(one, 3, 3, 1, 1, 0, 0, dx, dy, 0) == 0 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
    flat = bytes(bytearray([7]) * (4 * 4 * 4))  # 4 channels: alpha is ignored
    assert L.scan_edge(flat, 16, 4, 4, 4, 0, 0, 1, 0, 0) == 3 and L.scan_edge(flat, 16, 4, 4, 4, 3, 3, -1, 0, 0) == 3
    # file unlocker: nothing to find, nothing to read
    assert L.find_lockers([])[0] == [] and L.find_lockers(['/no/such/file'], proc='/no/such/proc') == ([], 0)
    assert L.find_lockers(['/no/such/file'])[0] == []


def test_fancy_zones_edges():
    for n in (2, 3, 4):
        for x, y, w, h in ((0, 0, 1, 1), (-1920, -200, 1920, 1080), (0, 0, 3, 3), (5, 5, 0, 0), (0, 27, 3840, 2133)):
            z = L.zone_rects(n, x, y, w, h)  # a second monitor left of the first has negative coordinates
            assert len(z) == n and sum(zw * zh for _x, _y, zw, zh in z) == w * h, (n, z)
            assert all(zw >= 0 and zh >= 0 and zx >= x and zy >= y and zx + zw <= x + w and zy + zh <= y + h
                       for zx, zy, zw, zh in z), (n, z)
    mb = L.maximize_button_rect
    assert mb('', 0, 0, 400) is None and mb(':', 0, 0, 400) is None and mb('menu:minimize,close', 0, 0, 400) is None
    assert mb('maximize', 10, 20, 400) == (16, 20, 40, 44) and mb(':maximize', 0, 0, 400) == (354, 0, 40, 44)
    assert mb('close,maximize,minimize:', 0, 0, 400) == (46, 0, 40, 44) and mb(':icon,maximize,junk,close', 0, 0, 400) == (314, 0, 40, 44)
    assert mb(':maximize,close', -1920, 0, 1920) == (-86, 0, 40, 44) and mb(':maximize', 0, 0, 10)[0] == -36
    g = L.window_geometry
    assert g((0, 0, 1, 1), frame=(5, 5, 30, 5)) == (0, 0, 1, 1)  # never asks for an empty or negative size
    assert g((-1920, 0, 960, 1080), frame=(1, 1, 30, 1), shadow=(10, 10, 10, 10)) == (-1930, -10, 978, 1069)
    # title-bar strips: one button, buttons on the left, too few, uneven spacing, glyphs too small, all one colour
    w, h = 200, 20

    def strip(starts, size=10):
        ink = set((x, y) for x0 in starts for x in range(x0, x0 + size) for y in range(6, 6 + size))
        return bytes(bytearray(v for y in range(h) for x in range(w) for v in ((220,) * 3 if (x, y) in ink else (30,) * 3)))
    bs = L.button_slots
    assert bs(strip([180]), w * 3, 3, w, h, 1) == ([(169, 201)], 10)
    assert bs(strip([8, 40, 72]), w * 3, 3, w, h, 3, from_right=False) == ([(-3, 29), (29, 61), (61, 93)], 10)
    assert bs(strip([150, 182]), w * 3, 3, w, h, 3) is None and bs(strip([100, 150, 182]), w * 3, 3, w, h, 3) is None
    assert bs(strip([20, 52, 84]), w * 3, 3, w, h, 3) is None  # too far from the window edge to be its buttons
    assert bs(strip([124, 153, 182], size=3), w * 3, 3, w, h, 3) is None and bs(strip([]), w * 3, 3, w, h, 3) is None
    assert bs(strip([0, 100, 190]), w * 3, 3, w, h, 3) is None  # wider apart than any title bar spaces them
    assert bs(bytes(bytearray(3)), 3, 3, 1, 1, 1) is None


def test_security():
    # hosts file is written as administrator: nothing typed into a field may start a second line in it
    assert L.valid_ip('fe80::1%eth0')
    for evil in ('127.0.0.1%\n6.6.6.6 bank.example', '::1%x\n6.6.6.6 bank.example', '127.0.0.1%eth0', 'fe80::1%a b',
                 'fe80::1%', '1.2.3.4\n', '::1\n', '::1%a\r6.6.6.6 b', '::1%a\tb', '1.2.3.4 #'):
        assert not L.valid_ip(evil), repr(evil)
    assert not L.valid_hostname('bank.example\n') and not L.valid_hosts('a\x00b')
    for sep in '\n\r\x0b\x0c\x1c\x1d\x1e\x85  ':
        line = L.format_entry({'enabled': True, 'ip': '127.0.0.1', 'hosts': 'a', 'comment': 'c%s6.6.6.6 bank.example' % sep})
        assert line.splitlines() == [line], repr(line)
    # a form feed inside a comment is not a line end: saving must not turn the text after it into a live entry
    text = '# note\x0c6.6.6.6 bank.example\n# 10.0.0.1 off.example\n'
    items = L.parse_hosts(text)
    [e for e in items if isinstance(e, dict)][0]['enabled'] = True
    out = L.serialize_hosts(items)
    assert out == '# note\x0c6.6.6.6 bank.example\n10.0.0.1\toff.example\n', repr(out)
    # calculator: every hostile input is refused with ValueError, none runs code, crashes or eats memory
    for evil in ('9**999', '9**999*9**999', 'factorial(1000)', '__import__("os").system("id")', '().__class__',
                 'open("/etc/passwd").read()', '[1]*10**9', '"a"*10**9', 'lambda: 1', 'abs.__self__', 'sqrt.__call__(4)',
                 '1 if 1 else 2', '(1).real', 'f"{1}"', '1;2', 'exec("1")', 'eval("1")', 'pi.__class__', 'abs(abs)',
                 'round(1, 2, 3)', 'log(10, 1)', '9**9**9', '1e308*10', '2**1001', '1e101**2', '-' * 301 + '1'):
        assert raises(L.calculate, evil), evil
    # bulk rename: a new name can never leave its folder, and a stray temporary file is never replaced
    d = tempfile.mkdtemp()
    a = os.path.join(d, 'a')
    open(a, 'w').close()
    for evil in ('../a', 'x/../../y', '/etc/passwd', 'x\0y', '.', '..', '', 'n' * 256, 'é' * 128):
        assert L.validate_plan([a], [evil]) == ['invalid'], repr(evil)
    assert L.validate_plan([a], [L.rename_one('a', '^', '../../', use_regex=True)]) == ['invalid']
    assert L.output_path('/p/a.jpg', 'S', pattern='../../etc/%1') == '/p/.._.._etc_a.jpg'
    stray = os.path.join(d, '.pt-rename-%d-0.tmp' % os.getpid())
    with open(stray, 'w') as f:
        f.write('precious')
    try:
        L.apply_renames([(a, os.path.join(d, 'b'))])
        assert False
    except FileExistsError:
        pass
    assert open(stray).read() == 'precious' and os.path.exists(a) and not os.path.exists(os.path.join(d, 'b'))
    # environment variables land in ~/.profile, which every login runs: values are data, never commands
    evil = ['$(touch PWNED)', '`touch PWNED`', '"; touch PWNED; "', '$((1+1))$(touch PWNED)', '${X:-$(touch PWNED)}',
            "'; touch PWNED #", '\\"; touch PWNED; \\"', '\\$(touch PWNED)', '\\', '$(', ';touch PWNED', '|touch PWNED',
            '&touch PWNED&', '>PWNED', '\\\\$(touch PWNED)']
    block = L.env_block_render('', [('V%d' % i, v) for i, v in enumerate(evil)])
    assert L.env_block_parse(block) == [('V%d' % i, v) for i, v in enumerate(evil)]
    subprocess.check_call(['sh', '-c', block], cwd=d, env={'PATH': '/usr/bin:/bin'})
    assert not os.path.exists(os.path.join(d, 'PWNED')), block
    got = subprocess.check_output(['sh', '-c', block + 'printf %s "$V0|$V11"'], cwd=d, env={'PATH': '/usr/bin:/bin'})
    assert got.decode() == '$(touch PWNED)||touch PWNED', got
    got = subprocess.check_output(['sh', '-c', L.env_block_render('', [('P', '$HOME/bin:${HOME}')]) + 'printf %s "$P"'],
                                  env={'PATH': '/usr/bin:/bin', 'HOME': '/h'})
    assert got.decode() == '/h/bin:/h', got  # variables still expand
    for name, value in (('A;touch PWNED', 'v'), ('A B', 'v'), ('A=1', 'v'), ('', 'v'), ('A\n', 'v'), ('$(x)', 'v'),
                        ('A', 'v\nexport B=1'), ('A', 'v\r'), ('A', 'v\0')):
        assert raises(L.env_block_render, '', [(name, value)]), (name, value)
    # the scan that runs as administrator takes any text as a path and only ever reads /proc
    res, _denied = L.find_lockers(['', '--help', '/proc/1/root', '\n', '/' + 'x' * 5000, '/etc/../etc/shadow'])
    assert all(set(r) == {'pid', 'name', 'cmdline', 'user', 'uid', 'files'} for r in res)
    shutil.rmtree(d)


if __name__ == '__main__':
    t0 = time.time()
    tests = [(n, fn) for n, fn in sorted(globals().items()) if n.startswith('test_')]
    for n, fn in tests:
        fn()
        print('PASS', n)
    print('%d logic tests passed in %.2fs (Python %s)' % (len(tests), time.time() - t0, sys.version.split()[0]))
