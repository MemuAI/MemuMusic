"""Background update checks and verified handoff to the Windows installer."""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import hmac
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable
from urllib.parse import quote, urljoin, urlsplit
import uuid

import httpx

from . import __version__, storage
from .paths import data_dir

REPOSITORY = "MemuAI/MemuMusic"
API = f"https://api.github.com/repos/{REPOSITORY}/releases"
RELEASE_BASE = f"https://github.com/{REPOSITORY}/releases"
INSTALLER_NAME = "MemuMusic-Setup.exe"
CHECKSUM_NAME = INSTALLER_NAME + ".sha256"
MAX_INSTALLER = 512 * 1024 * 1024
INTERVALS = (6, 12, 24, 168)
_VERSION = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
_SHA = re.compile(r"^[a-fA-F0-9]{64}$")
_ASSET_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com", "github-releases.githubusercontent.com"}


class UpdateError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def version_key(value: str) -> tuple:
    match = _VERSION.fullmatch(str(value or ""))
    if not match:
        raise ValueError("invalid version")
    major, minor, patch = (int(match.group(i)) for i in (1, 2, 3))
    raw = match.group(4)
    if not raw:
        return major, minor, patch, (1, ())
    pieces = raw.split(".")
    if any(not part or (part.isdigit() and len(part) > 1 and part.startswith("0")) for part in pieces):
        raise ValueError("invalid prerelease")
    return major, minor, patch, (0, tuple((0, int(part)) if part.isdigit() else (1, part) for part in pieces))


def _public_url(tag: str, name: str) -> str:
    return f"{RELEASE_BASE}/download/{quote(tag, safe='')}/{quote(name, safe='')}"


def _valid_url(url: str, hosts: set[str]) -> bool:
    try:
        parsed = urlsplit(url)
        return parsed.scheme == "https" and parsed.hostname in hosts and parsed.port in (None, 443) and not parsed.username and not parsed.password
    except ValueError:
        return False


def _asset(release: dict, name: str) -> dict | None:
    values = [a for a in release.get("assets", []) if isinstance(a, dict) and a.get("name") == name and a.get("state") == "uploaded"]
    if len(values) != 1:
        return None
    item = values[0]
    tag = str(release.get("tag_name") or "")
    if item.get("browser_download_url") != _public_url(tag, name):
        return None
    try:
        size = int(item.get("size"))
    except (ValueError, TypeError):
        return None
    if size < 1 or size > (4096 if name == CHECKSUM_NAME else MAX_INSTALLER):
        return None
    digest = item.get("digest") or ""
    if digest and (not isinstance(digest, str) or not digest.startswith("sha256:") or not _SHA.fullmatch(digest[7:])):
        return None
    return {"name": name, "url": item["browser_download_url"], "size": size,
            "digest": digest[7:].lower() if digest else ""}


def select_release(releases: list, current: str, channel: str) -> dict | None:
    try:
        current_key = version_key(current)
    except ValueError as exc:
        raise UpdateError("current_version_invalid") from exc
    options = []
    incomplete = False
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = str(release.get("tag_name") or "")
        try:
            key = version_key(tag)
        except ValueError:
            continue
        is_preview = bool(release.get("prerelease")) or key[3][0] == 0
        if (channel == "stable" and is_preview) or key <= current_key:
            continue
        installer, checksum = _asset(release, INSTALLER_NAME), _asset(release, CHECKSUM_NAME)
        if not installer or not checksum:
            incomplete = True
            continue
        options.append((key, {"version": tag.lstrip("v"), "tag": tag, "prerelease": is_preview,
                              "name": str(release.get("name") or tag)[:160],
                              "published_at": str(release.get("published_at") or "")[:40],
                              "page": f"{RELEASE_BASE}/tag/{quote(tag, safe='')}",
                              "installer": installer, "checksum": checksum}))
    if options:
        return max(options, key=lambda item: item[0])[1]
    if incomplete:
        raise UpdateError("installer_missing")
    return None


def _checksum(raw: bytes) -> str:
    if len(raw) > 4096:
        raise UpdateError("checksum_invalid")
    try:
        tokens = raw.decode("utf-8-sig").strip().split()
    except UnicodeError as exc:
        raise UpdateError("checksum_invalid") from exc
    if not 1 <= len(tokens) <= 2 or not _SHA.fullmatch(tokens[0]):
        raise UpdateError("checksum_invalid")
    if len(tokens) == 2 and tokens[1].lstrip("*") != INSTALLER_NAME:
        raise UpdateError("checksum_invalid")
    return tokens[0].lower()


@contextmanager
def _asset_response(client: httpx.Client, asset: dict):
    url = asset["url"]
    for _ in range(6):
        if not _valid_url(url, _ASSET_HOSTS):
            raise UpdateError("untrusted_url")
        with client.stream("GET", url, follow_redirects=False) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise UpdateError("network")
                url = urljoin(url, location)
                continue
            response.raise_for_status()
            yield response
            return
    raise UpdateError("untrusted_url")


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def registered_install_dir(executable: str | None = None) -> Path | None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\MemuMusic") as key:
            folder, kind = winreg.QueryValueEx(key, "InstallPath")
        if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
            return None
        folder = Path(os.path.expandvars(folder)).resolve()
        current = Path(executable or sys.executable).resolve()
        expected = folder / "MemuMusic.exe"
        if os.path.normcase(str(current)) != os.path.normcase(str(expected.resolve())):
            return None
        return folder
    except (OSError, ValueError, TypeError):
        return None


def bootloader_pid() -> int:
    """The one-file bootloader is the process that keeps the installed EXE open."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return os.getpid()
    try:
        import ctypes
        from ctypes import wintypes
        class ProcessInfo(ctypes.Structure):
            _fields_ = [("reserved1", ctypes.c_void_p), ("peb", ctypes.c_void_p),
                        ("reserved2a", ctypes.c_void_p), ("reserved2b", ctypes.c_void_p),
                        ("process_id", ctypes.c_size_t), ("parent_id", ctypes.c_size_t)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
        ntdll.NtQueryInformationProcess.argtypes = (wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG))
        ntdll.NtQueryInformationProcess.restype = ctypes.c_long
        info = ProcessInfo()
        status = ntdll.NtQueryInformationProcess(kernel.GetCurrentProcess(), 0, ctypes.byref(info), ctypes.sizeof(info), None)
        if status != 0 or not info.parent_id:
            return os.getpid()
        handle = kernel.OpenProcess(0x1000, False, int(info.parent_id))
        if not handle:
            return os.getpid()
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                if os.path.normcase(os.path.realpath(buffer.value)) == os.path.normcase(os.path.realpath(sys.executable)):
                    return int(info.parent_id)
        finally:
            kernel.CloseHandle(handle)
    except (OSError, AttributeError, ValueError):
        pass
    return os.getpid()


class Updater:
    def __init__(self, root: Path | None = None, current_version: str | None = None,
                 client_factory: Callable[[], httpx.Client] | None = None, clock: Callable[[], float] = time.time):
        self.root = Path(root or data_dir()) / "updates"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / INSTALLER_NAME
        self.current = current_version or __version__
        self.clock = clock
        self.client_factory = client_factory or (lambda: httpx.Client(timeout=httpx.Timeout(30, connect=8), follow_redirects=False,
            headers={"User-Agent": "MemuMusic-Updater", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}))
        self._lock = threading.RLock()
        self._operation = threading.Lock()
        self._handoff = None
        cached = storage.load_json_with_recovery(self.root / "state.json", {})
        if not isinstance(cached, dict):
            cached = {}
        config = cached.get("config") if isinstance(cached.get("config"), dict) else {}
        default_channel = "preview" if version_key(self.current)[3][0] == 0 else "stable"
        self._config = {"enabled": config.get("enabled", True) is not False,
                        "auto_download": config.get("auto_download", True) is not False,
                        "channel": config.get("channel") if config.get("channel") in ("stable", "preview") else default_channel,
                        "interval_hours": config.get("interval_hours") if config.get("interval_hours") in INTERVALS else 24}
        try:
            last_checked = float(cached.get("last_checked", 0))
            if not 0 <= last_checked <= self.clock() + 60:
                last_checked = 0
        except (ValueError, TypeError):
            last_checked = 0
        if cached.get("current_version") != self.current:
            last_checked = 0
        self._state = {"phase": "idle", "current_version": self.current, "last_checked": last_checked,
                       "latest": None, "progress": 0, "total": 0, "error": "", "checksum": ""}
        if last_checked and cached.get("result") == "up_to_date":
            self._state["phase"] = "up_to_date"
        saved = cached.get("latest")
        if isinstance(saved, dict):
            try:
                # Revalidate cached metadata before it can affect the UI or a download.
                restored = select_release([{**saved, "tag_name": saved["tag"], "assets": [
                    {"name": item["name"], "browser_download_url": item["url"], "size": item["size"],
                     "digest": "sha256:" + item["digest"] if item.get("digest") else "", "state": "uploaded"}
                    for item in (saved["installer"], saved["checksum"])], "draft": False}], self.current, self._config["channel"])
                if restored:
                    self._state.update(latest=restored, phase="available")
                    expected = str(cached.get("download_checksum") or "")
                    if _SHA.fullmatch(expected) and self.path.is_file() and self.path.stat().st_size == restored["installer"]["size"]:
                        self._state.update(phase="ready", checksum=expected.lower(), total=restored["installer"]["size"], progress=restored["installer"]["size"])
            except (KeyError, TypeError, ValueError, OSError, UpdateError):
                pass

    def status(self) -> dict:
        with self._lock:
            return {**copy.deepcopy(self._state), "config": dict(self._config), "busy": self._operation.locked(), "installed": registered_install_dir() is not None,
                    "can_install": sys.platform == "win32" and bool(getattr(sys, "frozen", False))}

    def _save(self):
        with self._lock:
            data = {"config": dict(self._config), "last_checked": self._state["last_checked"],
                    "current_version": self.current, "result": self._state["phase"],
                    "latest": self._state["latest"], "download_checksum": self._state["checksum"] if self._state["phase"] == "ready" else ""}
        storage.save_json(self.root / "state.json", data)

    def settings(self, changes: dict) -> dict:
        allowed = {"enabled", "auto_download", "channel", "interval_hours"}
        if not isinstance(changes, dict) or set(changes) - allowed:
            raise UpdateError("invalid_settings")
        with self._lock:
            for key, value in changes.items():
                if key in ("enabled", "auto_download") and not isinstance(value, bool):
                    raise UpdateError("invalid_settings")
                if key == "channel" and value not in ("stable", "preview"):
                    raise UpdateError("invalid_settings")
                if key == "interval_hours" and (not isinstance(value, int) or value not in INTERVALS):
                    raise UpdateError("invalid_settings")
            changed_channel = "channel" in changes and changes["channel"] != self._config["channel"]
            self._config.update(changes)
            if changed_channel:
                self._state.update(phase="idle", latest=None, checksum="", last_checked=0, error="")
        self._save()
        return self.status()

    def _list(self, client: httpx.Client) -> list:
        response = client.get(API, params={"per_page": 100}, follow_redirects=False)
        response.raise_for_status()
        if len(response.content) > 8 * 1024 * 1024:
            raise UpdateError("invalid_response")
        data = response.json()
        if not isinstance(data, list):
            raise UpdateError("invalid_response")
        return data

    def _read_checksum(self, client: httpx.Client, candidate: dict) -> str:
        asset = candidate["checksum"]
        with _asset_response(client, asset) as response:
            parts = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 4096:
                    raise UpdateError("checksum_invalid")
                parts.append(chunk)
        data = b"".join(parts)
        if len(data) != asset["size"]:
            raise UpdateError("checksum_invalid")
        if asset["digest"] and not hmac.compare_digest(hashlib.sha256(data).hexdigest(), asset["digest"]):
            raise UpdateError("checksum_mismatch")
        value = _checksum(data)
        expected = candidate["installer"]["digest"]
        if expected and not hmac.compare_digest(value, expected):
            raise UpdateError("checksum_mismatch")
        return value

    def _error(self, exc: Exception):
        if isinstance(exc, UpdateError):
            code = exc.code
        elif isinstance(exc, (httpx.HTTPError, OSError)):
            code = "network" if isinstance(exc, httpx.HTTPError) else "disk"
        else:
            code = "invalid_response"
        with self._lock:
            self._state.update(phase="error", error=code)

    def _check(self):
        with self._lock:
            channel = self._config["channel"]
        with self.client_factory() as client:
            candidate = select_release(self._list(client), self.current, channel)
        with self._lock:
            if channel != self._config["channel"]:
                self._state.update(phase="idle", latest=None, checksum="", error="")
                return
            old = self._state["latest"]
            retain = bool(candidate and old and candidate["tag"] == old["tag"] and
                          candidate["installer"]["digest"] == old["installer"]["digest"] and
                          candidate["checksum"]["digest"] == old["checksum"]["digest"] and
                          self._state["checksum"] and self.path.is_file() and self.path.stat().st_size == candidate["installer"]["size"])
            self._state.update(phase="ready" if retain else "available" if candidate else "up_to_date",
                               latest=candidate, last_checked=self.clock(), error="", progress=0, total=0,
                               checksum=self._state["checksum"] if retain else "")
            auto = self._config["auto_download"] and candidate is not None and not retain
        self._save()
        return auto

    def _download(self):
        with self._lock:
            candidate = copy.deepcopy(self._state["latest"])
        if not candidate:
            raise UpdateError("no_update")
        temp = self.root / f"download-{uuid.uuid4().hex}.part"
        try:
            with self.client_factory() as client:
                expected = self._read_checksum(client, candidate)
                asset = candidate["installer"]
                digest = hashlib.sha256()
                size = 0
                first = b""
                with _asset_response(client, asset) as response, temp.open("xb") as handle:
                    for chunk in response.iter_bytes(128 * 1024):
                        if not first:
                            first = chunk[:2]
                        size += len(chunk)
                        if size > asset["size"] or size > MAX_INSTALLER:
                            raise UpdateError("download_size")
                        handle.write(chunk)
                        digest.update(chunk)
                        with self._lock:
                            self._state.update(progress=size, total=asset["size"])
                    handle.flush()
                    os.fsync(handle.fileno())
            if first != b"MZ" or size != asset["size"]:
                raise UpdateError("download_size")
            if not hmac.compare_digest(digest.hexdigest(), expected):
                raise UpdateError("checksum_mismatch")
            with self._lock:
                if not self._state["latest"] or self._state["latest"]["tag"] != candidate["tag"]:
                    raise UpdateError("update_changed")
                os.replace(temp, self.path)
                self._state.update(phase="ready", checksum=expected, error="", progress=size, total=size)
            self._save()
        finally:
            temp.unlink(missing_ok=True)

    def _schedule(self, phase: str, work: Callable):
        if not self._operation.acquire(blocking=False):
            return False
        with self._lock:
            self._state.update(phase=phase, error="", progress=0, total=0)
        def worker():
            auto = False
            try:
                auto = bool(work())
            except Exception as exc:
                self._error(exc)
            finally:
                self._operation.release()
            if auto:
                self.download()
        threading.Thread(target=worker, name="music-updates", daemon=True).start()
        return True

    def check(self):
        return self._schedule("checking", self._check)

    def download(self):
        return self._schedule("downloading", self._download)

    def auto(self):
        with self._lock:
            cfg, state = dict(self._config), dict(self._state)
        if not cfg["enabled"]:
            return False
        if self.clock() - float(state["last_checked"] or 0) >= cfg["interval_hours"] * 3600:
            return self.check()
        if cfg["auto_download"] and state["phase"] == "available":
            return self.download()
        return False

    def install(self, launcher: Callable[..., Any] = subprocess.Popen) -> dict:
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            raise UpdateError("unsupported")
        if not self._operation.acquire(blocking=False):
            raise UpdateError("busy")
        try:
            with self._lock:
                candidate = copy.deepcopy(self._state["latest"])
                stored_checksum = self._state["checksum"]
                channel = self._config["channel"]
            if not candidate or not stored_checksum or not self.path.is_file():
                raise UpdateError("not_downloaded")
            # Cached metadata is untrusted until it has been checked against GitHub again.
            with self.client_factory() as client:
                live = select_release(self._list(client), self.current, channel)
                if not live or live["tag"] != candidate["tag"]:
                    raise UpdateError("update_changed")
                expected = self._read_checksum(client, live)
            if self.path.stat().st_size != live["installer"]["size"] or not hmac.compare_digest(_digest(self.path), expected):
                raise UpdateError("checksum_mismatch")
            if not hmac.compare_digest(stored_checksum, expected):
                raise UpdateError("checksum_mismatch")
            directory = registered_install_dir()
            working_dir = Path(tempfile.gettempdir()).resolve()
            if directory and working_dir.is_relative_to(directory.resolve()):
                raise UpdateError("unsafe_directory")
            args = [str(self.path), "/SP-", "/NORESTART", f"/MMWAITPID={bootloader_pid()}", "/MMRELAUNCH=1"]
            if directory:
                args.extend(["/SILENT", f"/DIR={directory}"])
            args.append(f"/LOG={self.root / 'installer.log'}")
            child_env = {key: value for key, value in os.environ.items()
                         if not key.startswith("_PYI_") and key not in ("_MEIPASS2", "PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV")}
            child_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            child = launcher(args, cwd=str(working_dir), env=child_env,
                             creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            with self._lock:
                self._handoff = child
                self._state.update(phase="installing", error="")
            return {"launched": True, "installed": directory is not None}
        except (httpx.HTTPError, OSError) as exc:
            raise UpdateError("network" if isinstance(exc, httpx.HTTPError) else "launch_failure") from exc
        finally:
            self._operation.release()

    def close_after_handoff(self, close_window: Callable):
        with self._lock:
            child = self._handoff
        if child is None or (hasattr(child, "poll") and child.poll() is not None):
            self._error(UpdateError("launch_failure"))
            return
        try:
            close_window()
        except Exception:
            self._error(UpdateError("launch_failure"))
