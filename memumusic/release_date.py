"""Дата выпуска текущей версии MemuMusic: релиз на GitHub, кэш, офлайн-фолбэк.

Дата, которую видит пользователь в «Настройки → Обновления»
(``GET /api/version``), берётся из релиза текущей версии на GitHub:
``GET https://api.github.com/repos/MemuAI/MemuMusic/releases/tags/v<версия>``,
поле ``published_at``. Тот же репозиторий, что опрашивает апдейтер
(``memumusic/updater.py``); адрес собран здесь явно, чтобы модуль
оставался на одной стандартной библиотеке.

Правила, от которых нельзя отступать:

* UI никогда не ждёт сеть: ``resolve_release_date`` только читает кэш и,
  если он устарел, запускает фоновый поток. Пока поток работает или сети
  нет, возвращается ``RELEASE_DATE`` из ``memumusic/__init__.py``.
* Кэш — ``release_date.json`` в каталоге данных, TTL 24 часа. Кэшируется
  только успешно полученная дата и только для той версии, для которой
  она запрашивалась: после обновления приложения старый кэш не подходит.
* Неудачная загрузка не кэшируется и не повторяется чаще раза в 10 минут,
  чтобы один недоступный GitHub не превращался в поток запросов.
* Любая ошибка сети, разбора или записи кэша молча приводит к фолбэку:
  без сети приложение работает ровно как раньше — даты просто нет,
  как и было до этого изменения.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import Tuple

from . import RELEASE_DATE, __version__

# Тот же репозиторий, что и ``REPOSITORY`` в memumusic/updater.py.
REPOSITORY = "MemuAI/MemuMusic"
CACHE_TTL_SECONDS = 24 * 60 * 60
_CACHE_FILE = "release_date.json"
_REQUEST_TIMEOUT_SECONDS = 10
# Пауза между повторными попытками после неудачной загрузки.
_RETRY_AFTER_SECONDS = 10 * 60
_MAX_RESPONSE_BYTES = 64 * 1024

_refresh_lock = threading.Lock()
_refresh_thread: threading.Thread | None = None
_last_failed_at = float("-inf")  # никогда не было неудач: cooldown не действует


def release_url(version: str = __version__) -> str:
    """Адрес релиза ``v<version>`` в GitHub API."""
    return f"https://api.github.com/repos/{REPOSITORY}/releases/tags/v{version}"


def parse_published_at(value: object) -> str:
    """``2026-10-30T18:22:10Z`` -> ``2026-10-30``; мусор -> ``""``."""
    text = str(value or "").strip()
    if len(text) < 10 or text[4] != "-" or text[7] != "-":
        return ""
    # Дата без времени тоже подходит: GitHub всегда отдаёт время, но
    # кэш и чужие ответы не должны ломаться из-за его отсутствия.
    if len(text) > 10:
        if text[10] not in ("T", " "):
            return ""
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return ""
        return parsed.date().isoformat()
    try:
        parsed = _date.fromisoformat(text)
    except ValueError:
        return ""
    return parsed.isoformat()


def _cache_path(data_dir: str | Path | None) -> Path:
    if data_dir is not None:
        return Path(data_dir) / _CACHE_FILE
    from .paths import data_dir as resolve_data_dir

    return resolve_data_dir() / _CACHE_FILE


def read_cached_release_date(data_dir: str | Path | None = None, *,
                             version: str = __version__,
                             now: float | None = None) -> str:
    """Свежая закэшированная дата или ``""``: кэша нет, он чужой или протух."""
    from .storage import load_json_with_recovery

    cached = load_json_with_recovery(_cache_path(data_dir), {})
    if not isinstance(cached, dict):
        return ""
    if cached.get("version") != version:
        return ""
    release_date = parse_published_at(cached.get("release_date"))
    if not release_date:
        return ""
    try:
        fetched_at = float(cached.get("fetched_at") or 0)
    except (TypeError, ValueError):
        return ""
    moment = time.time() if now is None else now
    if fetched_at <= 0 or moment - fetched_at > CACHE_TTL_SECONDS:
        return ""
    return release_date


def _write_cache(data_dir: str | Path | None, version: str, release_date: str) -> None:
    from .storage import save_json

    save_json(_cache_path(data_dir),
              {"version": version, "release_date": release_date,
               "fetched_at": int(time.time())},
              backup=False)


def _fetch_release_date(version: str) -> str:
    """Одна попытка спросить GitHub; любая ошибка -> ``""``, без исключений."""
    request = urllib.request.Request(
        release_url(version),
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "MemuMusic"})
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read(_MAX_RESPONSE_BYTES) or b"{}")
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return parse_published_at(payload.get("published_at"))


def _refresh_release_date(data_dir: str | Path | None, version: str) -> None:
    global _last_failed_at
    release_date = _fetch_release_date(version)
    if release_date:
        try:
            _write_cache(data_dir, version, release_date)
        except OSError:
            # Кэш — удобство, а не обязательство: следующий запрос
            # просто попробует сеть ещё раз.
            pass
    else:
        with _refresh_lock:
            _last_failed_at = time.monotonic()


def _start_refresh(data_dir: str | Path | None, version: str) -> None:
    global _refresh_thread
    with _refresh_lock:
        if _refresh_thread is not None and _refresh_thread.is_alive():
            return
        if time.monotonic() - _last_failed_at < _RETRY_AFTER_SECONDS:
            return
        _refresh_thread = threading.Thread(
            target=_refresh_release_date, args=(data_dir, version),
            name="memumusic-release-date", daemon=True)
        _refresh_thread.start()


def resolve_release_date(data_dir: str | Path | None = None, *,
                         version: str = __version__) -> Tuple[str, str]:
    """Дата выпуска и её источник: ``("2026-10-30", "github")`` или фолбэк.

    Никогда не ходит в сеть в вызывающем потоке: при устаревшем кэше
    запускает фоновую загрузку, а возвращает ``RELEASE_DATE`` из
    ``memumusic/__init__.py`` с источником ``"fallback"``. Следующий вызов
    после успешной загрузки вернёт дату из кэша с источником ``"github"``.
    """
    cached = read_cached_release_date(data_dir, version=version)
    if cached:
        return cached, "github"
    _start_refresh(data_dir, version)
    return RELEASE_DATE, "fallback"
