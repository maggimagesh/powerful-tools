"""Plain-assert tests for powerfultools.logic. Run: python3 tests/test_logic.py"""
import os
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


if __name__ == '__main__':
    t0 = time.time()
    tests = [(n, fn) for n, fn in sorted(globals().items()) if n.startswith('test_')]
    for n, fn in tests:
        fn()
        print('PASS', n)
    print('%d logic tests passed in %.2fs (Python %s)' % (len(tests), time.time() - t0, sys.version.split()[0]))
