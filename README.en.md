# MemuMusic

A desktop music player for Windows with a local library, playlists, online search and downloads, synchronized lyrics, an equalizer, visualizer, metadata editor and listening statistics.

[Русская версия](README.md)

## Run

Download and run `MemuMusic-Setup.exe` from Releases. The installer adds the app to the Windows Start menu and installed-apps list. No Python is required. A portable `MemuMusic.exe` is also available. Microsoft Edge WebView2 Runtime is required and is usually present on Windows 10/11.

Import files or folders in the library settings, or drop audio files into the window. Folder imports leave your files in place. Downloads and dropped files go to your configured download folder. Press `F11` for fullscreen. Language, appearance, queue and preferences persist across restarts.

Your library and settings are stored in `%LOCALAPPDATA%\MemuMusic`. Use `MEMUMUSIC_DATA_DIR` or `--data-dir` to select a different location.

yt-dlp is included and can be updated from the download settings. Optional FFmpeg is required for conversion, loudness analysis and some metadata operations. Place it on `PATH` or in the library's `bin` folder. Availability of online sources depends on the service, region and authentication.

In Now Playing you can choose among lyric variants, edit them, and enable offline romanization for Japanese, Chinese or Korean. Language detection is automatic, so ambiguous characters may be read incorrectly; the original text is preserved.

Recommendations find similar songs on YouTube Music based on your library. Play streams an available track without adding a file to the library; downloading is a separate action.

Use **Updates** in settings to control automatic checks and downloads. Installation starts when you choose it and keeps your library. The portable EXE opens the installer when updating. Uninstalling the app does not remove your library files.

## Development

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m memumusic
```

Build the executable with `powershell -ExecutionPolicy Bypass -File build.ps1`. To build the installer, install Inno Setup 6 and then run `powershell -ExecutionPolicy Bypass -File build-installer.ps1`.

Run the local UI without opening a desktop window:

```powershell
.venv\Scripts\python.exe -m memumusic --serve --data-dir .\build\test-data
```

The server binds only to `127.0.0.1` and selects a free port. API requests require a session cookie and pass an Origin check. Closing the desktop window stops playback.

Project license: Unlicense. Retained copyright notices and dependency licenses are listed in `licenses/` and `THIRD_PARTY_NOTICES.md`.
