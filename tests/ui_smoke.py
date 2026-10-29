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
        update_state = work / 'data' / 'updates' / 'state.json'
        update_state.parent.mkdir(parents=True)
        update_state.write_text(json.dumps({'config': {'enabled': False, 'auto_download': False}}), encoding='utf-8')
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
            def wait_offset(track_id, expected):
                deadline = time.monotonic() + 5
                actual = None
                while time.monotonic() < deadline:
                    actual = call('lyrics.get', {'id': track_id})['offset']
                    if actual == expected:
                        return
                    time.sleep(.05)
                raise AssertionError(f'Offset for {track_id}: expected {expected}, got {actual}')
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
                if not args.module_json:
                    assert page.locator('.music-titlebar-name').count() == 0
                    assert page.locator('[data-window].pywebview-drag-region, .pywebview-drag-region [data-window]').count() == 0
                    assert page.evaluate("getComputedStyle(document.querySelector('.music-titlebar')).backgroundColor === 'rgba(0, 0, 0, 0)'")
                    assert page.locator('#app').bounding_box()['y'] == 0
                    assert page.locator('.music-titlebar').bounding_box()['height'] == 36
                    for width, height in ((720, 480), (1280, 820)):
                        page.set_viewport_size({'width': width, 'height': height})
                        assert page.locator('.mm-brand').bounding_box()['y'] >= 36
                    page.set_viewport_size({'width': 1280, 'height': 820})
                    page.evaluate("MemuMusic.Theme.set('mode', 'light')")
                    assert page.evaluate("document.documentElement.hasAttribute('data-music-caption-light')")
                page.evaluate("async id => { const tr = await MemuMusic.API.call('library.list'); MemuMusic.Player.playList(tr.tracks, id, 'Test'); MemuMusic.NP().open(); }", tid)
                page.wait_for_function("MemuMusic.Player.times().cur > .1")
                page.evaluate("MemuMusic.Player.pause()")
                if not args.module_json:
                    assert not page.evaluate("document.documentElement.hasAttribute('data-music-caption-light')")
                    assert page.locator('#np').bounding_box()['y'] == 0
                    page.evaluate("MemuMusic.Theme.set('npTheme', 'auto')")
                    assert page.evaluate("document.documentElement.hasAttribute('data-music-caption-light')")
                    page.wait_for_timeout(650)
                    page.screenshot(path=str(root / 'build' / 'now-playing-light.png'))
                    page.evaluate("MemuMusic.Theme.set('npTheme', 'dark')")
                    page.wait_for_timeout(650)
                    page.screenshot(path=str(root / 'build' / 'now-playing-dark.png'))
                    page.evaluate('''() => {
                      window._windowMock = {maximized:false, fullscreen:false, calls:0, fail:false};
                      window.pywebview = {api: {
                        window_state: async () => ({..._windowMock}),
                        toggle_fullscreen: async () => { _windowMock.calls++; await new Promise(r => setTimeout(r, 40)); if (_windowMock.fail) throw Error('test fullscreen failure'); _windowMock.fullscreen = !_windowMock.fullscreen; return {..._windowMock}; },
                        toggle_maximize: async () => { _windowMock.maximized = !_windowMock.maximized; return {..._windowMock}; }
                      }};
                      window.dispatchEvent(new Event('pywebviewready'));
                    }''')
                    page.locator('[data-window="maximize"]').click()
                    page.wait_for_function("document.documentElement.hasAttribute('data-music-maximized')")
                    assert page.locator('[data-window="maximize"] .restore').is_visible()
                    page.evaluate("_windowMock.fail = true")
                    page.keyboard.press('F11')
                    page.wait_for_timeout(100)
                    assert not page.evaluate("document.documentElement.classList.contains('music-fullscreen')")
                    page.evaluate("_windowMock.fail = false")
                    page.keyboard.press('F11')
                    page.keyboard.press('F11')
                    page.wait_for_function("document.documentElement.classList.contains('music-fullscreen')")
                    assert page.evaluate('_windowMock.calls') == 2
                    assert not page.locator('.music-titlebar').is_visible()
                    page.keyboard.press('Escape')
                    page.wait_for_function("!document.documentElement.classList.contains('music-fullscreen')")
                    assert page.locator('#np').is_visible()
                    assert page.locator('.music-titlebar').is_visible()
                assert page.locator('#bar-title').inner_text() == 'First'
                assert page.locator('#ly-bar [data-ly="roman"]').count() == 0
                page.evaluate("MemuMusic.Theme.set('accent', '#1fb2ff')")
                assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--tint').trim()") == '#1fb2ff'
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
                wait_offset(tid, 0)
                page.locator('#ly-bar [data-ly="off+"]').click()
                page.evaluate("async id => { const tr=await MemuMusic.API.call('library.list'); MemuMusic.Player.playList(tr.tracks,id,'Test'); MemuMusic.Player.pause(); }", tracks[1]['id'])
                wait_offset(tid, .1)
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
                if not args.module_json:
                    assert page.locator('.mm-brand').inner_text() == 'MemuMusic'
                    assert page.locator('.mm-desktop-tools').count() == 0
                    page.evaluate('''() => { const old=MemuMusic.API.soft; MemuMusic.API.soft=async (op,args,fallback)=>{
                      if(op==='online.search') return {results:[{url:'https://music.youtube.com/watch?v=abc',title:'First',artist:'Example',source:'ytmusic'}]};
                      if(op==='online.related') return [{id:'x',url:'https://music.youtube.com/watch?v=xyz',title:'New track',artist:'Other',source:'ytmusic',tags:[]}];
                      return old(op,args,fallback);
                    }; }''')
                    page.locator('#nav [data-go="recommendations"]').click()
                    page.locator('[data-rec-run]').click()
                    page.wait_for_function("document.querySelector('[data-rec-results]')?.textContent.includes('New track')")
                    page.locator('#nav [data-go="home"]').click()
                    page.locator('#nav [data-go="recommendations"]').click()
                    assert 'New track' in page.locator('[data-rec-results]').inner_text()
                    page.locator('#nav [data-go="settings"]').click()
                    page.locator('[data-stab="updates"]').click()
                    page.locator('[data-update-action="check"]').wait_for()
                    status = client.get('/api/updates/status')
                    status.raise_for_status()
                    assert status.json()['config']['enabled'] is False
                    assert status.json()['last_checked'] == 0
                    for width, height in ((720, 480), (1280, 820), (1920, 1080)):
                        page.set_viewport_size({'width': width, 'height': height})
                        for selector in ('[data-stab="updates"]', '[data-update-action="check"]', '[data-update-config="interval_hours"]'):
                            box = page.locator(selector).bounding_box()
                            assert box and box['width'] > 0 and box['x'] >= 0 and box['x'] + box['width'] <= width + 1, (selector, width, box)
                        page.screenshot(path=str(root / 'build' / f'updates-{width}.png'))
                    page.set_viewport_size({'width': 1280, 'height': 820})
                    page.locator('[data-update-config="interval_hours"]').select_option('6')
                    page.wait_for_function('''() => fetch('/api/updates/status').then(r => r.json()).then(s => s.config.interval_hours === 6)''')
                    page.locator('[data-stab="library"]').click()
                    assert page.locator('#add-files, #imp-browse, .mm-desktop-tools').count() == 0
                    page.locator('#imp-dir').fill(str(work))
                    with page.expect_response(lambda response: response.url.endswith('/api/music/call') and response.request.post_data_json.get('op') == 'import.folder') as imported:
                        page.locator('#imp-go').click()
                    assert imported.value.ok
                    page.locator('[data-stab="appearance"]').click()
                    assert page.locator('.mm-ap-languages .mm-ap-card').count() == 2
                    page.locator('[data-app-language="ru"]').scroll_into_view_if_needed()
                    page.screenshot(path=str(root / 'build' / 'language-picker.png'))
                    page.locator('[data-app-language="en"]').click()
                else:
                    page.evaluate("App.setLanguage('en')")
                page.wait_for_function("document.documentElement.lang === 'en'")
                page.wait_for_function("document.querySelector('#nav [data-go=search] span').textContent === 'Search'")
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
