# -*- coding: utf-8 -*-
"""yt-dlp and ffmpeg for MemuMusic.

yt-dlp: a binary MemuMusic downloaded into ``music/bin`` wins (it can be updated in one click), then the
``yt_dlp`` python module, then a yt-dlp on PATH. Nothing found → :func:`update_ytdlp` fetches the
official release from GitHub. ffmpeg is optional: without it downloads keep the original bestaudio stream.
On Windows every child process runs with ``CREATE_NO_WINDOW`` and UTF-8 output.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .library import data_root

RELEASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
_UPDATE_LOCK = threading.Lock()
_VERSION_CACHE: Dict[str, Any] = {}

def bin_dir() -> Path:
    folder = data_root() / "bin"
    folder.mkdir(parents=True, exist_ok=True)
    return folder

def release_asset() -> str:
    system, machine = sys.platform, platform.machine().lower()
    if system.startswith("win"):
        return "yt-dlp.exe" if machine not in ("x86", "i386", "i686") else "yt-dlp_x86.exe"
    if system == "darwin":
        return "yt-dlp_macos"
    return "yt-dlp_linux_aarch64" if machine in ("aarch64", "arm64") else "yt-dlp_linux"

def own_binary() -> Path:
    return bin_dir() / ("yt-dlp.exe" if sys.platform.startswith("win") else "yt-dlp")

def popen_kwargs() -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"stdin": subprocess.DEVNULL, "env": {**os.environ, "PYTHONIOENCODING": "utf-8",
                                                                   "PYTHONUTF8": "1"}}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return kwargs

def python_module() -> Optional[Any]:
    try:
        import yt_dlp
        return yt_dlp
    except Exception:
        return None

def ytdlp_binary() -> Optional[str]:
    own = own_binary()
    if own.is_file():
        return str(own)
    if python_module() is not None:
        return None
    found = shutil.which("yt-dlp")
    return found or None

def ffmpeg_path() -> Optional[str]:
    for folder in (bin_dir(), Path(sys.executable).parent):
        for name in ("ffmpeg.exe", "ffmpeg"):
            if (folder / name).is_file():
                return str(folder / name)
    return shutil.which("ffmpeg")

def ffprobe_path() -> Optional[str]:
    ff = ffmpeg_path()
    if ff:
        sibling = Path(ff).with_name("ffprobe" + (".exe" if ff.endswith(".exe") else ""))
        if sibling.is_file():
            return str(sibling)
    return shutil.which("ffprobe")

def _run_version(cmd: List[str]) -> str:
    key = " ".join(cmd)
    try:
        stamp = os.path.getmtime(cmd[0]) if os.path.isabs(cmd[0]) else 0
    except OSError:
        stamp = 0
    cached = _VERSION_CACHE.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=20, text=True, encoding="utf-8",
                             errors="replace", **popen_kwargs()).stdout.strip().splitlines()
        version = out[0] if out else ""
    except (OSError, subprocess.SubprocessError):
        version = ""
    _VERSION_CACHE[key] = (stamp, version)
    return version

# GStreamer elements WebKitGTK needs to decode the formats MemuMusic
# serves (mp3/m4a/aac come from downloads; wav/ogg/flac/opus are covered
# by the base/good sets WebKitGTK already depends on). Sinks are the
# output side: pulsesink (PulseAudio / PipeWire's Pulse emulation) and
# pipewiresink (native PipeWire).
_AUDIO_ELEMENTS = {
    "playbin": ("playbin", "base"),
    "vorbisdec": ("vorbisdec", "base"),
    "opusdec": ("opusdec", "good"),
    "flacdec": ("flacdec", "good"),
    "mpg123audiodec": ("mpg123audiodec", "ugly"),
    "avdec_mp3": ("avdec_mp3", "libav"),
    "avdec_aac": ("avdec_aac", "libav"),
    "faad": ("faad", "bad"),
    "pulsesink": ("pulsesink", "good"),
    "pipewiresink": ("pipewiresink", "pipewire"),
    "autoaudiosink": ("autoaudiosink", "base"),
}
_AUDIO_CODEC_PACKAGES = ("gstreamer1.0-plugins-bad", "gstreamer1.0-plugins-ugly",
                         "gstreamer1.0-libav", "gstreamer1.0-pipewire")
_AUDIO_CACHE: Dict[str, Any] = {"at": 0.0, "value": None}


def _gst_elements() -> Dict[str, bool]:
    """``gst-inspect-1.0`` presence per element, or ``None`` values when the
    inspector itself is missing (the elements cannot be checked then)."""
    found = shutil.which("gst-inspect-1.0")
    if not found:
        return {name: None for name in _AUDIO_ELEMENTS}
    out: Dict[str, bool] = {}
    for name in _AUDIO_ELEMENTS:
        try:
            result = subprocess.run([found, name], capture_output=True, timeout=10,
                                    text=True, encoding="utf-8", errors="replace", **popen_kwargs())
            out[name] = result.returncode == 0 and "No such element" not in (result.stdout + result.stderr)
        except (OSError, subprocess.SubprocessError):
            out[name] = False
    return out


def _audio_server() -> str:
    """"pipewire", "pulseaudio", "none" or "unknown" on Linux, from the
    user runtime sockets first (no daemon is started by probing)."""
    if not sys.platform.startswith("linux"):
        return "unknown"
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    has_pipewire = Path(runtime, "pipewire-0").exists()
    has_pulse = Path(runtime, "pulse", "native").exists() or Path(runtime, "pulse").is_dir()
    if has_pipewire and has_pulse:
        return "pipewire"
    if has_pipewire:
        return "pipewire"
    if has_pulse:
        return "pulseaudio"
    return "none"


def audio_status() -> Dict[str, Any]:
    """What the Linux audio stack looks like for the WebKitGTK window.

    On a stock Debian/Ubuntu install WebKitGTK pulls only the base/good
    GStreamer sets, so mp3 (ugly/libav) and m4a/aac (libav) have no
    decoder and ``<audio>`` fails with MEDIA_ERR_SRC_NOT_SUPPORTED while
    wav/ogg keep playing. The UI turns this into a sound check with the
    exact ``apt`` command; on non-Linux systems the check is not
    applicable and ``supported`` is False.
    """
    if not sys.platform.startswith("linux"):
        return {"supported": False, "platform": sys.platform, "elements": {},
                "missing": [], "audio_server": "unknown", "command": ""}
    now = time.time()
    if _AUDIO_CACHE["value"] is not None and now - _AUDIO_CACHE["at"] < 60:
        return dict(_AUDIO_CACHE["value"])
    elements = _gst_elements()
    missing = [name for name, ok in elements.items()
               if ok is False and name in ("mpg123audiodec", "avdec_mp3", "avdec_aac", "faad")]
    value = {"supported": True, "platform": sys.platform,
             "gst_inspect": shutil.which("gst-inspect-1.0") or "",
             "elements": elements, "missing": missing,
             "audio_server": _audio_server(),
             "command": ("sudo apt-get install -y " + " ".join(_AUDIO_CODEC_PACKAGES))
                        if shutil.which("apt-get") else ""}
    _AUDIO_CACHE.update(at=now, value=value)
    return dict(value)


def status() -> Dict[str, Any]:
    binary = ytdlp_binary()
    module = python_module()
    if binary:
        version = _run_version([binary, "--version"])
        ytdlp = {"ok": bool(version), "version": version, "path": binary, "kind": "binary",
                 "own": binary == str(own_binary())}
    elif module is not None:
        version = getattr(getattr(module, "version", None), "__version__", "")
        ytdlp = {"ok": True, "version": version, "path": getattr(module, "__file__", ""), "kind": "module", "own": False}
    else:
        ytdlp = {"ok": False, "version": "", "path": "", "kind": "", "own": False}
    ff = ffmpeg_path()
    ff_version = _run_version([ff, "-version"]) if ff else ""
    return {"ytdlp": ytdlp, "ffmpeg": {"ok": bool(ff_version), "version": ff_version.replace("ffmpeg version ", "").split(" ")[0],
                                       "path": ff or ""},
            "audio": audio_status(),
            "update": dict(UPDATE_STATE)}

UPDATE_STATE: Dict[str, Any] = {"status": "idle", "error": "", "at": 0}

def update_ytdlp(client_factory=None) -> Dict[str, Any]:
    """Download (or refresh) the official yt-dlp release into ``music/bin``; atomic replace."""
    import httpx
    if not _UPDATE_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "Обновление уже идёт / An update is already running"}
    UPDATE_STATE.update(status="running", error="", at=time.time())
    target = own_binary()
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        factory = client_factory or (lambda: httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30, read=120)))
        with factory() as client:
            with client.stream("GET", RELEASE + release_asset(), headers={"User-Agent": "MemuMusic"}) as response:
                response.raise_for_status()
                with open(tmp, "wb") as handle:
                    for chunk in response.iter_bytes(1 << 16):
                        handle.write(chunk)
        if tmp.stat().st_size < 1_000_000:
            raise RuntimeError("Скачанный файл слишком мал / The downloaded file is too small")
        if not sys.platform.startswith("win"):
            tmp.chmod(0o755)
        os.replace(tmp, target)
        _VERSION_CACHE.clear()
        version = _run_version([str(target), "--version"])
        UPDATE_STATE.update(status="done", at=time.time())
        return {"ok": True, "version": version, "path": str(target)}
    except Exception as exc:
        UPDATE_STATE.update(status="error", error=f"{type(exc).__name__}: {exc}", at=time.time())
        try:
            tmp.unlink()
        except OSError:
            pass
        return {"ok": False, "error": UPDATE_STATE["error"]}
    finally:
        _UPDATE_LOCK.release()

def ensure_ytdlp() -> None:
    """Make sure some yt-dlp exists; fetch the release on first use."""
    if ytdlp_binary() or python_module() is not None:
        return
    result = update_ytdlp()
    if not result.get("ok"):
        raise RuntimeError("Не удалось скачать yt-dlp / Could not download yt-dlp: " + str(result.get("error")))

def probe_duration(path: Path) -> float:
    probe = ffprobe_path()
    if not probe:
        return 0.0
    try:
        out = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                             capture_output=True, timeout=20, text=True, encoding="utf-8", errors="replace",
                             **popen_kwargs()).stdout.strip()
        return float(out) if out else 0.0
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0.0
