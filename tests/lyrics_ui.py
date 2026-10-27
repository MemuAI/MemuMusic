import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memumusic.music import library, lyrics


def run():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        data = work / 'data'
        updates = data / 'updates' / 'state.json'
        updates.parent.mkdir(parents=True)
        updates.write_text(json.dumps({'config': {'enabled': False, 'auto_download': False}}), encoding='utf8')
        ready = work / 'ready.txt'
        exe = Path(sys.argv[1]) if len(sys.argv) > 1 else None
        cmd = [str(exe)] if exe else [sys.executable, '-m', 'memumusic']
        proc = subprocess.Popen(cmd + ['--serve', '--data-dir', str(data), '--ready-file', str(ready)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(300):
                if ready.exists(): break
                if proc.poll() is not None: raise RuntimeError(proc.communicate()[1].decode(errors='replace'))
                time.sleep(.1)
            url = ready.read_text(encoding='utf8')
            with httpx.Client(base_url=url, trust_env=False, timeout=20) as client:
                client.get('/')
                def call(op, args):
                    r = client.post('/api/music/call', json={'op':op, 'args':args}); r.raise_for_status(); return r.json()['result']
                call('settings.set', {'auto_lyrics':False})
                track = work / 'Test - Song.wav'
                with wave.open(str(track), 'wb') as f:
                    f.setparams((1, 2, 22050, 0, 'NONE', 'not compressed')); f.writeframes(b'\0\0' * 22050 * 5)
                tid = call('import.files', {'paths':[str(track)]})['tracks'][0]['id']
                lib = library.Library(data / 'library')
                candidates = [dict(source='lrclib', title='Song', artist='Test', duration=5, synced=[[1,'私は日本人'],[3,'日本語']], plain='私は日本人\n日本語', instrumental=False), dict(source='qq', title='Song', artist='Test', duration=5, synced=[[1,'你好'],[3,'世界']], plain='你好\n世界', instrumental=False)]
                lyrics._save_meta(lib, tid, alts=candidates, choice=0); lyrics._apply(lib, tid, candidates[0]); lib.close()
                with sync_playwright() as p:
                    chrome = os.environ.get('MEMUMUSIC_CHROMIUM', 'C:/Program Files/Google/Chrome/Application/chrome.exe')
                    browser = p.chromium.launch(executable_path=chrome if Path(chrome).is_file() else None, headless=True, args=['--mute-audio'])
                    page = browser.new_page(viewport={'width':1280,'height':820})
                    errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(url); page.wait_for_function("document.documentElement.dataset.ready === 'true'")
                    page.evaluate("async id => { const tracks=(await MemuMusic.API.call('library.list')).tracks; MemuMusic.Player.playList(tracks,id,'test'); MemuMusic.Player.pause(); MemuMusic.NP().open(); }", tid)
                    page.locator('#ly-bar [data-ly="roman"]').wait_for(timeout=20000)
                    page.locator('#ly-bar [data-ly="alts"]').click()
                    page.locator('#ly-bar [data-ly="pick"][data-i="1"]').click()
                    page.wait_for_function("document.querySelector('#ly-bar .mm-ly-src span')?.textContent === 'QQ Music'")
                    page.locator('#ly-bar [data-ly="roman"]').click()
                    page.wait_for_function("document.querySelector('#lyrics-inner').textContent.includes('ni hao')")
                    assert call('lyrics.get', {'id':tid})['synced'][0][1] == '你好'
                    page.locator('[data-lylang]').select_option('ja')
                    page.locator('#ly-bar [data-ly="alts"]').click()
                    page.locator('#ly-bar [data-ly="pick"][data-i="0"]').click()
                    page.wait_for_function("document.querySelector('#lyrics-inner').textContent.includes('nihongo')")
                    page.locator('#ly-bar [data-ly="edit"]').click()
                    area = page.locator('.mm-lyrics-paste textarea')
                    assert '私は日本人' in area.input_value()
                    page.evaluate("document.body.style.userSelect='none'; let contents=''; Object.defineProperty(navigator,'clipboard',{value:{writeText:async v=>{contents=v},readText:async()=>contents},configurable:true})")
                    box = area.bounding_box(); page.mouse.move(box['x']+20,box['y']+23); page.mouse.down(); page.mouse.move(box['x']+95,box['y']+23,steps=8); page.mouse.up()
                    assert area.evaluate('e => e.selectionEnd-e.selectionStart') > 0
                    area.click(button='right'); page.locator('.mm-ly-edit-menu [data-action="select"]').click()
                    assert area.evaluate('e => e.selectionEnd-e.selectionStart') == len(area.input_value())
                    area.click(button='right'); page.locator('.mm-ly-edit-menu [data-action="copy"]').click()
                    area.fill('replace'); area.click(button='right'); page.locator('.mm-ly-edit-menu [data-action="select"]').click()
                    area.click(button='right'); page.locator('.mm-ly-edit-menu [data-action="paste"]').click()
                    assert '私は日本人' in area.input_value()
                    original = '[00:01.00]안녕하세요!\n[00:03.00]사랑해'
                    call('lyrics.set', {'id': tid, 'text': original})
                    korean = call('lyrics.romanize', {'id': tid, 'language': 'ko'})
                    assert korean['synced'][0][1] == 'annyeonghaseyo!', korean
                    assert korean['synced'][1][1] == 'saranghae', korean
                    assert call('lyrics.get', {'id': tid})['synced'][0][1] == '안녕하세요!'
                    assert not errors, errors
                    browser.close()
            print('PASS: standalone lyrics source selection, romanization, selection and context menu')
        finally:
            if os.name == 'nt' and proc.poll() is None:
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(.25)
            elif proc.poll() is None:
                proc.terminate()
            try:
                proc.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()


if __name__ == '__main__': run()
