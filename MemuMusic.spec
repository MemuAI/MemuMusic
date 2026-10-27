from PyInstaller.utils.hooks import collect_data_files
import runpy

runpy.run_path('tools/collect_notices.py', run_name='__main__')

datas = [('memumusic/web', 'memumusic/web')]
datas += collect_data_files('yt_dlp')
datas += collect_data_files('pykakasi')
datas += collect_data_files('pypinyin')
datas += [('build/licenses', 'licenses'), ('LICENSE', 'licenses/application-LICENSE'), ('THIRD_PARTY_NOTICES.md', 'licenses/THIRD_PARTY_NOTICES.md')]
a = Analysis(['launch.py'], pathex=[], binaries=[], datas=datas,
    hiddenimports=['webview.platforms.edgechromium', 'uvicorn.logging', 'uvicorn.loops.asyncio',
                   'uvicorn.protocols.http.h11_impl', 'uvicorn.lifespan.on', 'PIL.JpegImagePlugin',
                   'PIL.PngImagePlugin', 'PIL.WebPImagePlugin', 'mutagen.mp3', 'mutagen.flac',
                   'mutagen.mp4', 'mutagen.oggvorbis', 'mutagen.oggopus', 'mutagen.wave', 'mutagen.aiff'],
    excludes=['tkinter', 'pytest', 'IPython', 'numpy', 'pandas', 'matplotlib', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6'],
    hookspath=[], hooksconfig={}, runtime_hooks=[], noarchive=False, optimize=1)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='MemuMusic',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    disable_windowed_traceback=False, icon='memumusic/web/icon.ico')
