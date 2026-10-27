from __future__ import annotations

import asyncio
import threading
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from .updater import UpdateError, Updater


def register_update_routes(app, updater: Updater | None = None, close_window: Callable | None = None) -> Updater:
    updater = updater or Updater()

    @app.get('/api/updates/status')
    async def updates_status():
        return updater.status()

    @app.post('/api/updates/settings')
    async def updates_settings(request: Request):
        try:
            changes = await request.json()
            return await asyncio.to_thread(updater.settings, changes)
        except (UpdateError, ValueError) as exc:
            return JSONResponse({'error': exc.code if isinstance(exc, UpdateError) else 'invalid_settings'}, 400)

    @app.post('/api/updates/check')
    async def updates_check():
        return {'started': updater.check(), 'status': updater.status()}

    @app.post('/api/updates/download')
    async def updates_download():
        return {'started': updater.download(), 'status': updater.status()}

    @app.post('/api/updates/auto')
    async def updates_auto():
        return {'started': updater.auto(), 'status': updater.status()}

    @app.post('/api/updates/install')
    async def updates_install():
        if close_window is None:
            return JSONResponse({'error': 'unsupported'}, 409)
        try:
            result = await asyncio.to_thread(updater.install)
        except UpdateError as exc:
            return JSONResponse({'error': exc.code}, 400)
        # Give the browser time to receive the response before the local server shuts down.
        timer = threading.Timer(.6, updater.close_after_handoff, args=(close_window,))
        timer.daemon = True
        timer.start()
        return result

    return updater
