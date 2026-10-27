import importlib.metadata
import json
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1]
out = root / 'build/licenses'
out.mkdir(parents=True, exist_ok=True)
for path in (root / 'licenses').rglob('*'):
    if path.is_file():
        target = out / path.relative_to(root / 'licenses')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
packages = []
for dist in importlib.metadata.distributions():
    name = dist.metadata.get('Name', 'unknown')
    if name.lower() in {'pip', 'setuptools', 'playwright', 'greenlet', 'pyee'}:
        continue
    packages.append({'name': name, 'version': dist.version})
    for entry in dist.files or ():
        if not any(word in entry.name.upper() for word in ('LICENSE', 'COPYING', 'NOTICE')):
            continue
        path = Path(dist.locate_file(entry))
        if path.is_file():
            target = out / name / entry.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if python_license.is_file():
    shutil.copyfile(python_license, out / 'Python-LICENSE.txt')
(out / 'packages.json').write_text(json.dumps(sorted(packages, key=lambda row: row['name'].lower()), indent=2), encoding='utf-8')
