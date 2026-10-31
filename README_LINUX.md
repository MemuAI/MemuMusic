# MemuMusic on Linux

MemuMusic 1.1 runs on Linux the same way as on Windows: a local server on
`127.0.0.1` with the interface in a real desktop window (GTK + WebKitGTK
via pywebview). Audio plays in the window itself (`<audio>` streams from
the local server), so no native audio backend is needed. The app is
**not** a browser tab: if the window packages are missing, MemuMusic
shows an explicit page with the exact install command instead of
silently opening the browser.

## Quick start (portable tarball)

```sh
tar -xzf MemuMusic-1.1-linux.tar.gz
cd MemuMusic-1.1-linux
./MemuMusic
```

The launcher creates a virtualenv in
`~/.local/share/memumusic/venv` on first run and installs the pinned
dependencies from `requirements.txt` (network needed once). Later runs reuse
it; it is refreshed automatically when `requirements.txt` changes.

Optional, for an app-menu entry:

```sh
./packaging/install-linux.sh   # .desktop + icon into ~/.local/share, symlink in ~/.local/bin
```

## .deb (Debian/Ubuntu and derivatives)

```sh
sudo apt-get install -y ./memumusic_1.1_all.deb
memumusic
```

The package installs to `/usr/lib/memumusic`, the launcher to
`/usr/bin/memumusic`, and the same per-user virtualenv is used. The
`.deb` hard-depends on the window stack (`python3-gi`,
`gir1.2-gtk-3.0`, `libwebkit2gtk-4.1-0` / `gir1.2-webkit2-4.1`, with
4.0 alternatives for older releases), so `apt-get install` pulls the
window packages in automatically — the app opens as a desktop window.
It also hard-depends on the GStreamer base/good plugin sets and
recommends the bad/ugly/libav sets plus the PipeWire plugin, so
downloaded mp3/m4a/aac tracks actually play (WebKitGTK itself only
depends on base/good, which leaves those formats without a decoder).
For the portable tarball, install the same packages by hand first (see
Requirements below).

## Run modes

| Command | Behaviour |
|---|---|
| `memumusic` | Desktop window (pywebview: GTK + WebKitGTK, or Qt). If no WebView backend is available, MemuMusic keeps the local server up and shows an explicit page with the exact install command, with a link to open the player in the browser from that page — it never silently pretends a browser tab is the app. |
| `memumusic --browser` | Always open in the system browser (explicit opt-in, no install page). |
| `memumusic --serve` | Headless: print the local URL and serve until Ctrl-C. |
| `memumusic --serve --port 8765` | Headless on a fixed port. |
| `memumusic --version` | Print the version. |

## Requirements

- Python 3.10+ with `python3-venv` (Debian/Ubuntu: `python3-venv` package).
- For the native window: GTK + WebKitGTK with Python bindings. On
  Debian/Ubuntu/Linux Mint 22 (Ubuntu 24.04 base):
  ```sh
  sudo apt-get install -y python3-gi gir1.2-gtk-3.0 libwebkit2gtk-4.1-0 gir1.2-webkit2-4.1
  ```
  On older releases (Debian 11 / Ubuntu 22.04 / Linux Mint 21) use the
  4.0 variants: `libwebkit2gtk-4.0-37 gir1.2-webkit2-4.0`. On Fedora:
  `webkit2gtk4.1 python3-gobject`. Without these packages the desktop
  window cannot open; MemuMusic says so on screen (with the command
  above) instead of opening a browser tab unannounced. The `.deb`
  declares them as hard dependencies, so they arrive with the package.
  The launcher creates the venv with `--system-site-packages` precisely
  so these system bindings are visible inside it; an isolated venv
  cannot import `gi` at all.
- For sound: GStreamer plugins. WebKitGTK decodes `<audio>` with
  GStreamer and its own package only pulls the base/good sets, which
  cover wav/ogg/flac/opus — mp3 needs the ugly (or libav) set, m4a/aac
  need libav. Install them (and the PipeWire plugin) with:
  ```sh
  sudo apt-get install -y gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav gstreamer1.0-pipewire
  ```
  The `.deb` declares base/good as dependencies and the rest as
  recommendations, so a default `apt-get install` of the `.deb` brings
  them in. If there is still no sound, use the sound check in
  Settings → Playback → Sound check: it reports exactly which decoder
  or audio server (PipeWire/PulseAudio) is missing, and the command
  above.
- Optional: `ffmpeg` (loudness analysis, video thumbnails, some downloads).
  Without it those features report as unavailable; playback is unaffected.
- Optional: `ffmpeg` (loudness analysis, video thumbnails, some downloads).
  Without it those features report as unavailable; playback is unaffected.
- `yt-dlp` comes from the `yt-dlp` Python package in `requirements.txt`;
  the app can also download/update a standalone `yt-dlp` binary itself.

## Data locations (XDG)

- App data, library database, settings, logs:
  `$XDG_DATA_HOME/memumusic`, default `~/.local/share/memumusic`.
  Override with `MEMUMUSIC_DATA_DIR` or `--data-dir`.
- The library itself lives in `<data dir>/library` by default; change it in
  Settings. No files are written outside the data dir except the downloads
  folder you choose.

## Updates

The built-in updater checks GitHub releases, but installing an update from
the app is Windows-only (`can_install` is false on Linux): download the new
tarball/`.deb` and replace it. Checking for updates can be turned off in
Settings → Updates.

## No sound on Linux?

1. Open Settings → Playback → **Sound check** and press **Check**. It
   probes the GStreamer decoders, the running audio server and one real
   track, and tells you which of the three is at fault.
2. If decoders are missing, install them and restart MemuMusic:
   ```sh
   sudo apt-get install -y gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav gstreamer1.0-pipewire
   ```
3. If no audio server is running, start PipeWire (`systemctl --user start pipewire pipewire-pulse`)
   or PulseAudio for your session — the app itself never starts one.

## Known limitations

- No native window without GTK/WebKitGTK or Qt bindings: MemuMusic shows
  the install page (see Run modes) until the packages are installed.
- Global hotkeys and single-instance activation are best-effort: a second
  launch while the player is running exits quietly after activating the
  running copy; reopen the printed URL in your browser if activation
  fails.
- The `.deb` is `Architecture: all` (pure Python); it still needs the
  per-user virtualenv on first run.
