# Third-party components

The application uses open-source dependencies distributed under their respective licenses:

- Python — Python Software Foundation License.
- pywebview — BSD-3-Clause; pythonnet — MIT; clr-loader — MIT.
- FastAPI — MIT; Starlette — BSD-3-Clause; Uvicorn — BSD-3-Clause.
- HTTPX — BSD-3-Clause; HTTP Core — BSD-3-Clause; h11 — MIT.
- Pillow — MIT-CMU.
- Mutagen — GPL-2.0-or-later. The executable includes Mutagen for reading and writing audio metadata. Its complete upstream source and license are available at https://github.com/quodlibet/mutagen (version 1.48.1).
- yt-dlp — Unlicense; its dependencies retain their own licenses. Source: https://github.com/yt-dlp/yt-dlp (version 2026.8.19).
- PyInstaller — GPL with the bootloader exception.
- Microsoft Edge WebView2 — Microsoft runtime, installed separately.

Bundled package license files are included by the build tooling. Optional FFmpeg is not distributed with this application.

The music engine retains its original MIT copyright notice in `licenses/music-engine-MIT.txt`. The application includes GPL-covered Mutagen; the preview release also provides its upstream source archive and retains the GPL license in the executable.
