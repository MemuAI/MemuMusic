from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import socket
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn

from . import __version__, storage
from .music import api
from .paths import data_dir, web_dir
from .updater_routes import register_update_routes

log = logging.getLogger(__name__)
COOKIE = "memumusic_session"


def bundle(path: Path) -> str:
    def include(match):
        part = (path.parent / match[1]).resolve()
        if not part.is_relative_to(web_dir().resolve()):
            raise ValueError("Invalid asset include")
        return bundle(part)
    return re.sub(r"/\* @include:([^*]+?) \*/", include, path.read_text(encoding="utf-8"))


def load_ui() -> dict:
    value = storage.load_json_with_recovery(data_dir() / "ui-state.json", {})
    return value if isinstance(value, dict) else {}


def save_ui(patch: dict) -> dict:
    patch = {key: value for key, value in patch.items() if key in ("player", "prefs", "recent_searches", "language")}
    if len(json.dumps(patch, ensure_ascii=False)) > 2_000_000:
        raise ValueError("Слишком много данных / State is too large")
    def update(value):
        value = value if isinstance(value, dict) else {}
        if isinstance(patch.get("player"), dict):
            patch["player"] = {**(value.get("player") if isinstance(value.get("player"), dict) else {}), **patch["player"]}
        value.update(patch)
        return value
    return storage.mutate_json(data_dir() / "ui-state.json", {}, update)


def create_app(session: str | None = None, activate=None, close_window=None) -> FastAPI:
    session = session or secrets.token_urlsafe(32)
    app = FastAPI(title="MemuMusic", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    assets = {"/assets/main.js": (bundle(web_dir() / "main.js"), "text/javascript"),
              "/assets/style.css": (bundle(web_dir() / "style.css"), "text/css")}
    translations = json.loads((web_dir() / "i18n.json").read_text(encoding="utf-8"))

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            if not secrets.compare_digest(request.cookies.get(COOKIE, ""), session):
                return JSONResponse({"error": "Session expired. Reopen MemuMusic."}, 403)
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"error": "Origin is not allowed"}, 403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; media-src 'self' data: blob:; "
            "connect-src 'self'; font-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index():
        ui = await asyncio.to_thread(load_ui)
        bootstrap = json.dumps({"saved": ui, "translations": translations, "version": __version__}, ensure_ascii=False).replace("<", "\\u003c")
        html = (web_dir() / "index.html").read_text(encoding="utf-8").replace("__BOOTSTRAP__", bootstrap)
        response = HTMLResponse(html, headers={"Cache-Control": "no-store"})
        response.set_cookie(COOKIE, session, httponly=True, samesite="strict")
        return response

    @app.get("/health")
    async def health():
        return {"app": "MemuMusic", "version": __version__}

    @app.get("/assets/main.js")
    @app.get("/assets/style.css")
    async def generated_asset(request: Request):
        text, media_type = assets[request.url.path]
        return Response(text, media_type=media_type, headers={"Cache-Control": "no-cache"})

    @app.post("/api/state")
    async def state(request: Request):
        try:
            patch = await request.json()
            if not isinstance(patch, dict):
                raise ValueError("Expected a JSON object")
            return {"result": await asyncio.to_thread(save_ui, patch)}
        except (ValueError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, 400)

    @app.post("/api/window/activate")
    async def focus():
        if activate:
            await asyncio.to_thread(activate)
        return {"ok": True}

    @app.post("/api/music/call")
    async def operation(request: Request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            result = await api.call_async(str(body.get("op", "")), body.get("args"),
                                          base=str(request.base_url).rstrip("/"),
                                          lang="en" if body.get("lang") == "en" else "ru", sender="desktop")
            return {"result": result}
        except Exception as exc:
            if not isinstance(exc, (ValueError, KeyError, TypeError)):
                log.exception("Music operation failed")
            payload, status = api.error_payload(exc)
            return JSONResponse(payload, status)

    @app.api_route("/api/music/stream/{track_id}", methods=["GET", "HEAD"])
    async def stream(track_id: str, request: Request, t: str = ""):
        return await asyncio.to_thread(api.stream_track, track_id, t, request.headers.get("range", ""))

    @app.api_route("/api/music/online-audio/{token}", methods=["GET", "HEAD"])
    async def online_audio_stream(token: str, request: Request):
        from .music import online_audio
        return await online_audio.stream(token, request)

    @app.api_route("/api/music/cover/{track_id}", methods=["GET", "HEAD"])
    async def cover(track_id: str, t: str = ""):
        return await asyncio.to_thread(api.cover_image, track_id, t)

    @app.get("/api/music/thumb")
    async def thumbnail(u: str = "", t: str = ""):
        return await asyncio.to_thread(api.thumb_image, u, t)

    register_update_routes(app, close_window=close_window)
    app.mount("/assets", StaticFiles(directory=web_dir()), name="assets")
    return app


class LocalServer:
    def __init__(self, port: int = 0, activate=None, close_window=None):
        self.session = secrets.token_urlsafe(32)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        self.socket.bind(("127.0.0.1", port))
        self.port = self.socket.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.app = create_app(self.session, activate, close_window)
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port,
                                                   log_level="warning", log_config=None, access_log=False,
                                                   loop="asyncio", http="h11", lifespan="on", ws="none", timeout_graceful_shutdown=2))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True)

    def start(self):
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                self.stop()
                raise RuntimeError("Не удалось запустить MemuMusic / Could not start MemuMusic")
            time.sleep(0.02)
        return self

    def stop(self):
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout=4)
        self.socket.close()
