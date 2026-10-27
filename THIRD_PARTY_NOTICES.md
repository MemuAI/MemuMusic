# Third-party components

The application uses open-source dependencies distributed under their respective licenses:

- Python — Python Software Foundation License.
- pywebview — BSD-3-Clause; pythonnet — MIT; clr-loader — MIT.
- FastAPI — MIT; Starlette — BSD-3-Clause; Uvicorn — BSD-3-Clause.
- HTTPX — BSD-3-Clause; HTTP Core — BSD-3-Clause; h11 — MIT.
- Pillow — MIT-CMU.
- Mutagen — GPL-2.0-or-later. The executable includes Mutagen for reading and writing audio metadata. Its complete upstream source and license are available at https://github.com/quodlibet/mutagen (version 1.48.1).
- pykakasi — GPL-3.0-or-later, Japanese text readings; source: https://codeberg.org/miurahr/pykakasi (version 2.3.0).
- korean-romanizer — GPL-3.0, Korean text readings; source: https://github.com/osori/korean-romanizer (version 0.25).
- pypinyin — MIT, Chinese text readings; source: https://github.com/mozillazg/python-pinyin (version 0.55.0).
- yt-dlp — Unlicense; its dependencies retain their own licenses. Source: https://github.com/yt-dlp/yt-dlp (version 2026.8.19).
- PyInstaller — GPL with the bootloader exception.
- Microsoft Edge WebView2 — Microsoft runtime, installed separately.

Bundled package license files are included by the build tooling. Optional FFmpeg is not distributed with this application.

The music engine retains its original MIT copyright notice in `licenses/music-engine-MIT.txt`. The application includes GPL-covered components; the preview release provides their upstream source archives and retains their license notices in the executable.
