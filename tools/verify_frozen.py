import hashlib
from pathlib import Path
import sys
import types

from PyInstaller.archive.readers import CArchiveReader


def signature(code):
    return (code.co_code, tuple(signature(value) if isinstance(value, types.CodeType) else value for value in code.co_consts),
            code.co_names, code.co_varnames, code.co_freevars, code.co_cellvars, code.co_argcount,
            code.co_kwonlyargcount, code.co_flags, code.co_exceptiontable, code.co_linetable)


root = Path(__file__).resolve().parents[1]
exe = Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'dist/MemuMusic.exe'
archive = CArchiveReader(str(exe))
entries = {name.replace('\\', '/'): name for name in archive.toc}
count = 0
for path in (root / 'memumusic/web').rglob('*'):
    if not path.is_file():
        continue
    name = path.relative_to(root).as_posix()
    assert archive.extract(entries[name]) == path.read_bytes(), f'Stale asset: {name}'
    count += 1
pyz = archive.open_embedded_archive('PYZ.pyz')
for path in (root / 'memumusic').rglob('*.py'):
    parts = list(path.relative_to(root).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    name = '.'.join(parts)
    assert name in pyz.toc, f'Missing Python module: {name}'
    expected = compile(path.read_bytes(), str(path), 'exec', dont_inherit=True, optimize=1)
    assert signature(pyz.extract(name)) == signature(expected), f'Stale Python module: {name}'
for name in pyz.toc:
    assert not name.startswith('app.'), f'Unexpected dependency: {name}'
digest = hashlib.sha256(exe.read_bytes()).hexdigest()
exe.with_suffix('.exe.sha256').write_text(f'{digest}  {exe.name}\n', encoding='ascii')
print(f'PASS: {count} UI assets, standalone Python modules, no host package; SHA256={digest}')
