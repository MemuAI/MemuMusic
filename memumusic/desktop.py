from __future__ import annotations

import json
import logging
import os
import sys
from urllib.parse import urlsplit
import webbrowser

from .paths import data_dir, web_dir
from .server import LocalServer
from .storage import save_json

log = logging.getLogger(__name__)


class Instance:
    def __init__(self):
        self.handle = None

    def acquire(self) -> bool:
        self.handle = (data_dir() / "instance.lock").open("a+b")
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                if self.handle.read(1) == b"":
                    self.handle.write(b"0")
                    self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.handle.close()
            self.handle = None
            return False

    def close(self):
        if self.handle:
            self.handle.close()
            self.handle = None


class Native:
    def __init__(self):
        self._window = None

    def choose_folder(self):
        import webview
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return str(result[0]) if result else ""

    def choose_files(self):
        import webview
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
            file_types=("Audio (*.mp3;*.flac;*.m4a;*.aac;*.ogg;*.opus;*.wav;*.webm;*.wma;*.alac;*.aiff)", "All files (*.*)"))
        return list(result or ())

    def open_url(self, url: str):
        parsed = urlsplit(str(url))
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Unsupported URL")
        return webbrowser.open(url)

    def toggle_fullscreen(self):
        self._window.toggle_fullscreen()

    def activate(self):
        if self._window:
            self._window.show()
            self._window.restore()

    def close_for_update(self):
        if self._window:
            self._window.destroy()


def activate_existing() -> bool:
    try:
        import httpx
        state = json.loads((data_dir() / "runtime.json").read_text(encoding="utf-8"))
        port = int(state["port"])
        if not 0 < port < 65536:
            return False
        response = httpx.post(f"http://127.0.0.1:{port}/api/window/activate",
                              cookies={"memumusic_session": state["session"]}, timeout=3, trust_env=False)
        return response.is_success
    except Exception:
        return False


def run():
    import webview
    instance = Instance()
    if not instance.acquire():
        if not activate_existing():
            raise RuntimeError("MemuMusic уже запущен / MemuMusic is already running")
        return
    native = Native()
    server = None
    try:
        server = LocalServer(activate=native.activate, close_window=native.close_for_update).start()
        save_json(data_dir() / "runtime.json", {"port": server.port, "session": server.session, "pid": os.getpid()}, backup=False)
        try:
            geometry = json.loads((data_dir() / "window.json").read_text(encoding="utf-8"))
            width = max(800, min(2400, int(geometry.get("width", 1280))))
            height = max(520, min(1600, int(geometry.get("height", 820))))
        except (OSError, ValueError, TypeError, AttributeError):
            width, height = 1280, 820
        native._window = webview.create_window("MemuMusic", server.url, js_api=native,
            width=width, height=height, min_size=(720, 480), background_color="#08080b", text_select=True)

        def save_window():
            try:
                save_json(data_dir() / "window.json", {"width": native._window.width, "height": native._window.height}, backup=False)
            except Exception:
                log.exception("Could not save window size")
        native._window.events.closing += save_window
        webview.start(gui="edgechromium" if sys.platform == "win32" else None,
                      private_mode=False, storage_path=str(data_dir() / "webview"), icon=str(web_dir() / "icon.ico"))
    finally:
        from .music import downloader
        downloader.shutdown()
        if server:
            server.stop()
        (data_dir() / "runtime.json").unlink(missing_ok=True)
        instance.close()
