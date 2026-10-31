from __future__ import annotations

import json
import logging
import os
import sys
import time
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
        self._maximized = False
        self._fullscreen = False

    def window_state(self):
        return {"maximized": self._maximized, "fullscreen": self._fullscreen}

    def _notify_state(self, maximized=None):
        if maximized is not None:
            self._maximized = maximized
        if self._window:
            try:
                self._window.evaluate_js("window.dispatchEvent(new CustomEvent('music-window-state', {detail: "
                                         + json.dumps(self.window_state()) + "}));")
            except Exception:
                log.debug("Window state is not ready", exc_info=True)

    def minimize_window(self):
        self._window.minimize()

    def toggle_maximize(self):
        target = not self._maximized
        if self._maximized:
            self._window.restore()
        else:
            self._window.maximize()
        self._maximized = target
        return self.window_state()

    def close_window(self):
        self._window.destroy()

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
        self._fullscreen = not self._fullscreen
        self._notify_state()
        return self.window_state()

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


def _window_icon():
    """Window icon: .ico for the Windows shell, .png everywhere else (GTK)."""
    return web_dir() / ("icon.ico" if sys.platform == "win32" else "icon.png")


def run(browser: bool = False):
    """Open the desktop window, or explain clearly when no WebView is available.

    On Linux pywebview needs GTK + WebKitGTK (or Qt); on a system without
    them ``webview.start`` raises, and silently opening a browser tab made
    the app look like a website. Instead, the local server keeps running
    and the user gets an explicit page with the exact install command
    (:func:`_serve_webkit_missing`). Only an explicit ``--browser`` still
    opens the browser directly, without that page.
    """
    try:
        import webview
    except ImportError:
        webview = None
    if browser:
        webview = None
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
        if webview is None:
            if browser:
                _serve_in_browser(server)
            else:
                # pywebview itself is missing: do not pretend the browser
                # tab is the app — show what is missing and how to fix it.
                _serve_webkit_missing(server)
            return
        try:
            geometry = json.loads((data_dir() / "window.json").read_text(encoding="utf-8"))
            width = max(800, min(2400, int(geometry.get("width", 1280))))
            height = max(520, min(1600, int(geometry.get("height", 820))))
        except (OSError, ValueError, TypeError, AttributeError):
            width, height = 1280, 820
        native._window = webview.create_window("MemuMusic", server.url, js_api=native,
            width=width, height=height, min_size=(720, 480), background_color="#08080b", text_select=True, frameless=True, easy_drag=False)

        native._window.events.maximized += lambda: native._notify_state(maximized=True)
        native._window.events.restored += lambda: native._notify_state(maximized=False)

        def save_window():
            try:
                save_json(data_dir() / "window.json", {"width": native._window.width, "height": native._window.height}, backup=False)
            except Exception:
                log.exception("Could not save window size")
        native._window.events.closing += save_window
        try:
            webview.start(gui="edgechromium" if sys.platform == "win32" else None,
                          private_mode=False, storage_path=str(data_dir() / "webview"), icon=str(_window_icon()))
        except Exception:
            # No usable WebView backend (e.g. Linux without GTK/WebKitGTK):
            # show the explicit "window is unavailable" page instead of
            # silently opening a browser tab.
            log.warning("WebView is unavailable, showing the WebKitGTK install page", exc_info=True)
            native._window = None
            _serve_webkit_missing(server)
    finally:
        from .music import downloader
        downloader.shutdown()
        if server:
            server.stop()
        (data_dir() / "runtime.json").unlink(missing_ok=True)
        instance.close()


def _webkit_install_commands() -> list[str]:
    """Exact system-package commands that provide the desktop window."""
    if sys.platform == "win32":
        return []
    return [
        # Debian 12+ / Ubuntu 24.04+ / Linux Mint 22+ (WebKitGTK 4.1).
        "sudo apt-get install -y python3-gi gir1.2-gtk-3.0 libwebkit2gtk-4.1-0 gir1.2-webkit2-4.1",
        # Debian 11 / Ubuntu 22.04 / Linux Mint 21 (WebKitGTK 4.0).
        "sudo apt-get install -y python3-gi gir1.2-gtk-3.0 libwebkit2gtk-4.0-37 gir1.2-webkit2-4.0",
    ]


def _webkit_missing_page(app_url: str) -> str:
    """The page shown when MemuMusic cannot open a desktop window."""
    import html
    safe_url = html.escape(app_url, quote=True)
    if sys.platform == "win32":
        fix = ("<p>MemuMusic needs its WebView component (Microsoft Edge "
               "WebView2). Reinstall MemuMusic, or run it in the browser "
               "for now: <code>memumusic --browser</code>.</p>")
    else:
        blocks = "".join(
            f"<pre><code>{html.escape(cmd)}</code></pre>"
            f"<button type=\"button\" onclick=\"navigator.clipboard.writeText(this.previousElementSibling.textContent)\">"
            "Скопировать / Copy</button>"
            for cmd in _webkit_install_commands()
        )
        fix = (
            "<p>Для окна приложения нужны GTK и WebKitGTK. Установите их "
            "одной командой и запустите MemuMusic снова:</p>"
            f"{blocks}"
            "<p>After installing, close this page and start MemuMusic again. "
            "The .deb package installs these packages automatically.</p>"
        )
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MemuMusic — нет окна приложения / No desktop window</title>
<style>
body{{background:#08080b;color:#e8e8ee;font:16px/1.55 system-ui,sans-serif;
margin:0;padding:48px 20px}}main{{max-width:720px;margin:0 auto}}
h1{{font-size:26px;margin:0 0 12px}}pre{{background:#17171f;border:1px solid #2c2c3a;
border-radius:10px;padding:12px 14px;white-space:pre-wrap;word-break:break-all;
overflow:hidden;scrollbar-width:none}}pre::-webkit-scrollbar{{display:none}}code{{font-size:14px}}
a.button,button{{display:inline-block;background:#7c5cff;color:#fff;border:0;
border-radius:10px;padding:10px 18px;margin:6px 8px 6px 0;cursor:pointer;
text-decoration:none;font:inherit}}a.plain{{color:#b9a8ff}}.muted{{color:#9a9aa8}}
</style></head><body><main>
<h1>MemuMusic не может открыть окно приложения</h1>
<p>MemuMusic is running — its local server is up — but the desktop window
backend (GTK + WebKitGTK) is not installed, so there is no app window to
show. This is not the player interface: install the packages below to get
the real window.</p>
{fix}
<p><a class="button" href="{safe_url}">Открыть MemuMusic в браузере / Open in browser</a></p>
<p class="muted">Сервер плеера: <a class="plain" href="{safe_url}">{safe_url}</a>.
Чтобы всегда открывать в браузере: <code>memumusic --browser</code>.</p>
</main></body></html>"""


def _serve_webkit_missing(server) -> None:
    """Serve the "no window backend" page and keep the player server up.

    The page is served by a tiny second local server (127.0.0.1, ephemeral
    port) so it works without touching the player server or any other
    module: the user sees exactly what is missing and the exact command,
    can still open the player in the browser from the page, and restarts
    MemuMusic after installing the packages.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    page = _webkit_missing_page(server.url).encode("utf-8")

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server naming
            if self.path == "/health":
                body = b"ok"
            elif self.path in ("/", "/index.html"):
                body = page
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8" if body is page else "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # keep the fallback quiet
            pass

    fallback = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    fallback.daemon_threads = True
    threading.Thread(target=fallback.serve_forever, daemon=True).start()
    fallback_url = f"http://127.0.0.1:{fallback.server_address[1]}/"
    commands = _webkit_install_commands()
    print("MemuMusic: no desktop window backend (GTK/WebKitGTK) is available.", flush=True)
    for cmd in commands:
        print(f"MemuMusic: install it with: {cmd}", flush=True)
    print(f"MemuMusic: details: {fallback_url}  player: {server.url}", flush=True)
    log.warning("Desktop window unavailable; showing install page at %s (player at %s)",
                fallback_url, server.url)
    try:
        webbrowser.open(fallback_url)
    except Exception:
        log.debug("Could not open the system browser", exc_info=True)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        fallback.shutdown()
        fallback.server_close()


def _serve_in_browser(server) -> None:
    """Keep the local server up and open it in the default browser."""
    print(server.url, flush=True)
    try:
        webbrowser.open(server.url)
    except Exception:
        log.debug("Could not open the system browser", exc_info=True)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
