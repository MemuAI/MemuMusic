import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--module-json", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    root.joinpath('build').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        ready = work / "ready.txt"
        cmd = [str(args.exe)] if args.exe else [sys.executable, "-m", "memumusic"]
        process = subprocess.Popen(cmd + ["--serve", "--data-dir", str(work / "data"), "--ready-file", str(ready)], cwd=root,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(300):
                if ready.is_file():
                    break
                if process.poll() is not None:
                    raise RuntimeError(process.communicate()[1].decode(errors="replace"))
                time.sleep(.1)
            url = ready.read_text(encoding="utf-8")
            client = httpx.Client(base_url=url, trust_env=False, timeout=30)
            client.get("/")
            def call(op, params=None):
                response = client.post("/api/music/call", json={"op": op, "args": params or {}})
                response.raise_for_status()
                return response.json()["result"]
            call("settings.set", {"auto_lyrics": False, "artist_photos": False, "lyrics_sync": "smart"})
            tracks = []
            for name in ("First", "Second"):
                song = work / f"Example - {name}.wav"
                with wave.open(str(song), "wb") as audio:
                    audio.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
                    audio.writeframes(b"\0\0" * 22050 * 12)
                tracks.append(call("import.files", {"paths": [str(song)]})["tracks"][0])
            tid = tracks[0]["id"]
            call("lyrics.set", {"id": tid, "text": "[00:00.00]First line\n[00:04.00]Second line\n[00:08.00]Last line"})
            call("lyrics.offset", {"id": tid, "offset": .03})
            chrome = os.environ.get("MEMUMUSIC_CHROMIUM", "C:/Program Files/Google/Chrome/Application/chrome.exe")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=chrome if Path(chrome).is_file() else None,
                    headless=True, args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"])
                page = browser.new_page(viewport={"width": 1280, "height": 820})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                if args.module_json:
                    package = json.loads(args.module_json.read_text(encoding="utf-8"))
                    bridge = '''const Memu = window.Memu = { ...App, get lang(){return App.lang;}, music: {call: async(op,args)=>{
                      const r=await fetch('/api/music/call',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({op,args,lang:App.lang})});
                      const d=await r.json();if(d.error)throw new Error(d.error);return d.result;}}};\n'''
                    page.route("**/assets/main.js", lambda route: route.fulfill(body=bridge + package["js"], content_type="text/javascript"))
                    page.route("**/assets/style.css", lambda route: route.fulfill(body=package["css"], content_type="text/css"))
                page.goto(url)
                page.wait_for_function("document.documentElement.dataset.ready === 'true'", timeout=20000)
                assert not errors, errors
                page.evaluate("async id => { const tr = await MemuMusic.API.call('library.list'); MemuMusic.Player.playList(tr.tracks, id, 'Test'); MemuMusic.NP().open(); }", tid)
                page.wait_for_function("MemuMusic.Player.times().cur > .1")
                page.evaluate("MemuMusic.Player.pause()")
                try:
                    page.locator('#ly-bar [data-ly="sync"]').wait_for(timeout=18000)
                except Exception:
                    print(json.dumps(page.evaluate("({current:MemuMusic.Player.current()?.id,bar:document.getElementById('ly-bar').outerHTML,text:document.getElementById('lyrics-inner').innerText,errors:[]})"), ensure_ascii=False), flush=True)
                    print(errors, flush=True)
                    page.screenshot(path=str(root / 'build/ui-failure.png'))
                    raise
                page.locator('#ly-bar [data-ly="sync"]').click()
                page.wait_for_function("document.getElementById('lyrics').dataset.sync === 'line'")
                assert call("settings.get")["lyrics_sync"] == "line"
                assert page.locator('.mm-lyric.on > span').evaluate("e => getComputedStyle(e).backgroundImage") == 'none'
                print('PASS: startup, real audio playback and line-mode switch', flush=True)
                page.screenshot(path=str(root / 'build/now-playing.png'))
                page.locator('#ly-bar [data-ly="off-reset"]').click()
                page.wait_for_timeout(600)
                assert call("lyrics.get", {"id": tid})["offset"] == 0
                page.locator('#ly-bar [data-ly="off+"]').click()
                page.evaluate("async id => { const tr=await MemuMusic.API.call('library.list'); MemuMusic.Player.playList(tr.tracks,id,'Test'); MemuMusic.Player.pause(); }", tracks[1]['id'])
                page.wait_for_timeout(550)
                assert call('lyrics.get', {'id': tid})['offset'] == .1
                assert call('lyrics.get', {'id': tracks[1]['id']})['offset'] == 0
                page.evaluate("async id => { const tr=await MemuMusic.API.call('library.list'); MemuMusic.Player.playList(tr.tracks,id,'Test'); MemuMusic.Player.pause(); }", tid)
                page.locator('#ly-bar [data-ly="sync"]').wait_for()
                page.locator('#ly-bar [data-ly="edit"]').click()
                page.locator('.mm-lyrics-paste textarea').fill('f')
                page.locator('[data-ly="save"]').click()
                page.locator('#ly-bar [data-ly="edit"]').wait_for()
                assert call("lyrics.get", {"id": tid})["plain"] == 'f'
                page.locator('#ly-bar [data-ly="edit"]').click()
                page.locator('.mm-lyrics-paste textarea').fill('Corrected lyrics\nSecond line')
                page.locator('[data-ly="save"]').click()
                page.locator('#ly-bar [data-ly="edit"]').wait_for()
                assert call("lyrics.get", {"id": tid})["plain"].startswith('Corrected lyrics')
                page.locator('#ly-bar [data-ly="edit"]').click()
                page.locator('.mm-lyrics-paste textarea').fill('')
                page.locator('[data-ly="save"]').click()
                page.locator('#ly-bar [data-ly="edit"]').wait_for()
                assert not call("lyrics.get", {"id": tid})["plain"]
                page.locator('#ly-bar [data-ly="edit"]').click()
                page.locator('.mm-lyrics-paste textarea').fill('Draft must survive a failed save')
                page.route('**/api/music/call', lambda route: route.fulfill(status=503, json={"error":"Simulated failure"}) if route.request.post_data_json.get('op') == 'lyrics.set' else route.continue_())
                page.locator('[data-ly="save"]').click()
                page.wait_for_timeout(400)
                assert page.locator('.mm-lyrics-paste textarea').input_value() == 'Draft must survive a failed save'
                assert not page.locator('[data-ly="save"]').is_disabled()
                page.unroute('**/api/music/call')
                page.locator('[data-ly="cancel"]').click()
                page.locator('#np-close').click()
                for name in ('library', 'playlists', 'download', 'stats', 'settings', 'home'):
                    page.locator(f'#nav [data-go="{name}"]').click()
                    page.wait_for_timeout(80)
                page.select_option('#app-language', 'en')
                page.wait_for_function("document.documentElement.lang === 'en'")
                page.wait_for_timeout(500)
                assert '[object Object]' not in page.inner_text('body')
                assert page.evaluate("document.getElementById('app').scrollTop === 0 && Math.abs(document.getElementById('bar').getBoundingClientRect().bottom - innerHeight) < 1")
                root.joinpath('build').mkdir(exist_ok=True)
                page.screenshot(path=str(root / 'build' / ('module-ui.png' if args.module_json else 'standalone-ui.png')))
                assert not errors, errors
                browser.close()
                print('PASS: real UI, audio library, line mode, exact reset, f recovery, empty reset, failed-save draft, navigation, language')
        finally:
            if os.name == 'nt' and process.poll() is None:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(.25)
            elif process.poll() is None:
                process.terminate()
            try:
                process.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()


if __name__ == '__main__':
    main()
