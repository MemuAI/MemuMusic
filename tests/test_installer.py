import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUILD = (ROOT / 'build').resolve()
SETUP = BUILD / 'test-installer/MemuMusic-Setup-test.exe'
BINARY = ROOT / 'dist/MemuMusic.exe'


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for part in iter(lambda: source.read(1024 * 1024), b''):
            result.update(part)
    return result.hexdigest()


def wait_for(predicate, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.1)
    raise AssertionError('Timed out waiting for test process')


@unittest.skipUnless(os.name == 'nt' and SETUP.is_file() and BINARY.is_file(), 'requires Windows, test setup and app EXE')
class InstallerTest(unittest.TestCase):
    def test_install_locked_update_rollback_relaunch_and_uninstall(self):
        BUILD.mkdir(exist_ok=True)
        temp = tempfile.TemporaryDirectory(prefix='memumusic-installer-', dir=BUILD)
        root = Path(temp.name).resolve()
        self.assertEqual(root.parent, BUILD)
        self.assertTrue(root.name.startswith('memumusic-installer-'))
        appdir = root / 'app'
        appdir.mkdir()
        app = appdir / 'MemuMusic.exe'
        data = appdir / 'User Music' / 'keep.txt'
        data.parent.mkdir()
        data.write_text('user content survives', encoding='utf-8')
        profile = root / 'profile'
        profile.mkdir()
        (profile / 'library-sentinel.txt').write_text('music library survives', encoding='utf-8')
        expected = digest(BINARY)
        common = ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', f'/DIR={appdir}']
        owned = []
        logs = []

        def run_setup(*args):
            log = root / f'install-{len(logs)}.log'
            logs.append(log)
            return subprocess.run([str(SETUP), *common, f'/LOG={log}', *args], cwd=root, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=35)

        def child_pids(parent):
            script = (f'Get-CimInstance Win32_Process -Filter "ParentProcessId={int(parent)}" | '
                      'Where-Object { $_.ExecutablePath -eq $env:MEMUMUSIC_TEST_APP -and '
                      '$_.CommandLine.Contains($env:MEMUMUSIC_TEST_READY) } | '
                      'ForEach-Object { $_.ProcessId }')
            result = subprocess.run(['powershell', '-NoProfile', '-Command', script], text=True, capture_output=True, check=True,
                                    env={**os.environ, 'MEMUMUSIC_TEST_APP': str(app), 'MEMUMUSIC_TEST_READY': str(first_ready)})
            return [int(value) for value in result.stdout.split() if value.isdigit()]

        def stop_tree(pid):
            subprocess.run(['taskkill', '/PID', str(int(pid)), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def app_pids():
            script = "$p=Get-CimInstance Win32_Process -Filter \"Name='MemuMusic.exe'\" | Where-Object { $_.ExecutablePath -eq $env:MEMUMUSIC_TEST_APP }; $p | ForEach-Object { $_.ProcessId }"
            result = subprocess.run(['powershell', '-NoProfile', '-Command', script], text=True, capture_output=True, check=True,
                                    env={**os.environ, 'MEMUMUSIC_TEST_APP': str(app)})
            return [int(pid) for pid in result.stdout.split() if pid.isdigit()]

        try:
            first = run_setup()
            self.assertEqual(first.returncode, 0)
            self.assertEqual(digest(app), expected)
            self.assertTrue((appdir / 'test-shortcuts/MemuMusic.lnk').is_file())
            uninstaller = appdir / 'unins000.exe'
            self.assertTrue(uninstaller.is_file())

            failure = run_setup('/MMFAIL=1')
            if failure.returncode == 0:
                print(logs[-1].read_text(encoding='utf-8-sig', errors='replace')[-4000:])
            self.assertNotEqual(failure.returncode, 0)
            self.assertEqual(digest(app), expected, 'a failed install must restore the prior executable')
            self.assertEqual(list(appdir.glob('MemuMusic.restore-*.exe')), [])
            self.assertEqual(data.read_text(encoding='utf-8'), 'user content survives')
            self.assertEqual((profile / 'library-sentinel.txt').read_text(encoding='utf-8'), 'music library survives')

            first_ready = root / 'first-ready.txt'
            old = subprocess.Popen([str(app), '--serve', '--data-dir', str(root / 'profile'), '--ready-file', str(first_ready)],
                                   cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            owned.append(old)
            wait_for(first_ready.is_file)
            child = []
            wait_for(lambda: bool(child_pids(old.pid)))
            child = child_pids(old.pid)
            self.assertEqual(len(child), 1, child)

            blocked = run_setup()
            self.assertNotEqual(blocked.returncode, 0, 'a running application must not be replaced')
            self.assertIsNone(old.poll(), 'setup must not kill the running app')
            self.assertEqual(digest(app), expected)
            remaining = list(appdir.glob('MemuMusic.restore-*.exe'))
            if remaining:
                print(logs[-1].read_text(encoding='utf-8-sig', errors='replace')[-7000:])
            self.assertEqual(remaining, [], 'blocked installation must not leave an orphan backup')

            lock_ready = root / 'lock-ready.txt'
            holder_code = '''import ctypes, pathlib, sys, time
f=ctypes.windll.kernel32.CreateFileW
f.restype=ctypes.c_void_p
f.argtypes=[ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
h=f(str(pathlib.Path(sys.argv[1])),0x80000000,1,None,3,0,None)
assert h not in (None, ctypes.c_void_p(-1).value)
pathlib.Path(sys.argv[2]).write_text('ready')
time.sleep(4)
ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(h))
'''
            holder = subprocess.Popen([sys.executable, '-c', holder_code, str(app), str(lock_ready)],
                                      cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
            owned.append(holder)
            wait_for(lock_ready.is_file)
            update_log = root / 'update.log'
            update = subprocess.Popen([str(SETUP), *common, f'/LOG={update_log}', f'/MMWAITPID={child[0]}', '/MMRELAUNCH=1'],
                                      cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            owned.append(update)
            time.sleep(.5)
            self.assertIsNone(update.poll(), 'update must wait for the supplied application PID')
            os.kill(child[0], signal.SIGTERM)
            time.sleep(.8)
            self.assertIsNone(update.poll(), 'update must also wait for the executable lock after the child exits')
            self.assertEqual(digest(app), expected)
            self.assertIsNone(holder.poll(), 'setup must not terminate another process holding a file')
            self.assertEqual(holder.wait(timeout=10), 0)
            self.assertEqual(update.wait(timeout=35), 0)
            wait_for((appdir / 'test-relaunch.ready').is_file)
            self.assertEqual(digest(app), expected)
            self.assertEqual(data.read_text(encoding='utf-8'), 'user content survives')
            self.assertEqual((profile / 'library-sentinel.txt').read_text(encoding='utf-8'), 'music library survives')
            try:
                wait_for(lambda: not list(appdir.glob('MemuMusic.restore-*.exe')), seconds=5)
            except AssertionError:
                print(update_log.read_text(encoding='utf-8-sig', errors='replace')[-5000:])
                raise

            unblocked = subprocess.run([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'],
                                       cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            self.assertNotEqual(unblocked.returncode, 0, 'uninstall must refuse while the app is running')
            self.assertTrue(app.exists())

            pids = app_pids()
            self.assertTrue(pids, 'the update must relaunch the app')
            for pid in pids:
                stop_tree(pid)
            time.sleep(.3)
            removed = subprocess.run([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'],
                                     cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            self.assertEqual(removed.returncode, 0)
            self.assertFalse(app.exists())
            self.assertEqual(data.read_text(encoding='utf-8'), 'user content survives')
        finally:
            for pid in app_pids():
                stop_tree(pid)
            for process in reversed(owned):
                if process.poll() is None:
                    stop_tree(process.pid)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
            time.sleep(.3)
            temp.cleanup()


if __name__ == '__main__':
    unittest.main()
