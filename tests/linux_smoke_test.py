"""Linux smoke tests: XDG data dir, no unconditional Windows imports, browser fallback.

Run: python -m pytest tests/linux_smoke_test.py
The server/fallback tests need the runtime dependencies (fastapi, httpx,
pywebview is NOT required — the fallback is what gets exercised) and are
skipped when they are missing.
"""
import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "memumusic"


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


class PathsTests(unittest.TestCase):
    def test_data_dir_uses_xdg_data_home(self):
        from memumusic.paths import data_dir
        with tempfile.TemporaryDirectory() as tmp:
            xdg = Path(tmp) / "xdg-data"
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(xdg)}, clear=False):
                with mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("MEMUMUSIC_DATA_DIR", None)
                    got = data_dir()
            self.assertEqual(got, xdg / "memumusic")
            self.assertTrue(got.is_dir())

    def test_data_dir_defaults_to_local_share(self):
        from memumusic.paths import data_dir
        env = {k: v for k, v in os.environ.items() if k not in ("XDG_DATA_HOME", "MEMUMUSIC_DATA_DIR")}
        home = Path(tempfile.mkdtemp())
        try:
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("pathlib.Path.home", return_value=home):
                    got = data_dir()
            self.assertEqual(got, home / ".local" / "share" / "memumusic")
        finally:
            import shutil
            shutil.rmtree(home, ignore_errors=True)

    def test_data_dir_override_wins(self):
        from memumusic.paths import data_dir
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"MEMUMUSIC_DATA_DIR": tmp}):
                self.assertEqual(data_dir(), Path(tmp).resolve())


class ImportsTests(unittest.TestCase):
    def test_no_unconditional_windows_imports(self):
        forbidden = {"winreg", "msvcrt", "_winapi", "winsound"}
        offenders = []
        for path in sorted([*PKG.glob("*.py"), *PKG.glob("music/*.py")]):
            for name in _top_level_imports(path) & forbidden:
                offenders.append(f"{path.relative_to(ROOT)}: {name}")
        self.assertEqual(offenders, [])

    def test_webview_is_lazy_in_desktop(self):
        self.assertNotIn("webview", _top_level_imports(PKG / "desktop.py"))

    def test_window_icon_is_png_on_linux(self):
        from memumusic.desktop import _window_icon
        icon = _window_icon()
        if sys.platform != "win32":
            self.assertEqual(icon.name, "icon.png")
        self.assertTrue(icon.is_file(), icon)


class BrowserFallbackTests(unittest.TestCase):
    def test_serve_in_browser_opens_url_and_waits(self):
        from memumusic.desktop import _serve_in_browser

        class FakeServer:
            url = "http://127.0.0.1:9"

        with mock.patch("memumusic.desktop.webbrowser.open") as opener, \
                mock.patch("memumusic.desktop.time.sleep", side_effect=KeyboardInterrupt):
            _serve_in_browser(FakeServer())
        opener.assert_called_once_with("http://127.0.0.1:9")

    @unittest.skipUnless(sys.platform != "win32", "browser fallback is a non-Windows path")
    def test_run_without_webview_falls_back_to_browser(self):
        pytest_fastapi = True
        try:
            import fastapi  # noqa: F401
            import httpx  # noqa: F401
        except ImportError:
            pytest_fastapi = False
        if not pytest_fastapi:
            self.skipTest("fastapi/httpx are not installed")
        import memumusic.desktop as desktop
        import time as _time

        real_sleep = _time.sleep

        def fake_sleep(seconds):
            # LocalServer.start() polls with sleep(0.02); the browser fallback
            # waits with sleep(0.5). Only interrupt the latter.
            if seconds >= 0.5:
                raise KeyboardInterrupt
            real_sleep(seconds)

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"MEMUMUSIC_DATA_DIR": tmp}), \
                    mock.patch.dict(sys.modules, {"webview": None}), \
                    mock.patch("memumusic.desktop.webbrowser.open") as opener, \
                    mock.patch("memumusic.desktop.time.sleep", side_effect=fake_sleep):
                desktop.run()
        opener.assert_called_once()
        opened = opener.call_args.args[0]
        self.assertTrue(opened.startswith("http://127.0.0.1:"), opened)


class HeadlessServerTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux-only smoke test")
    def test_health_and_settings_over_http(self):
        try:
            import httpx
        except ImportError:
            self.skipTest("httpx is not installed")
        from memumusic.server import LocalServer
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"MEMUMUSIC_DATA_DIR": tmp}):
                server = LocalServer().start()
            try:
                client = httpx.Client(base_url=server.url, trust_env=False, timeout=10)
                self.assertEqual(client.get("/health").json()["app"], "MemuMusic")
                client.get("/")  # sets the session cookie required by /api/*
                response = client.post("/api/music/call", json={"op": "settings.get", "args": {}})
                self.assertEqual(response.status_code, 200)
                self.assertIn("library_dir", response.json()["result"])
                client.close()
            finally:
                server.stop()


if __name__ == "__main__":
    unittest.main()
