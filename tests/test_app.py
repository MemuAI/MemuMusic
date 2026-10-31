import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name).resolve()
        cls.previous = os.environ.get("MEMUMUSIC_DATA_DIR")
        os.environ["MEMUMUSIC_DATA_DIR"] = str(cls.root / "profile")
        from memumusic.server import LocalServer
        cls.server = LocalServer().start()
        cls.client = httpx.Client(base_url=cls.server.url, trust_env=False, timeout=30)
        cls.client.get("/")
        cls.call("settings.set", {"auto_lyrics": False, "artist_photos": False, "auto_analyze": False})
        cls.song = cls.root / "Example - First.wav"
        with wave.open(str(cls.song), "wb") as output:
            output.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
            output.writeframes(b"\0\0" * 22050 * 8)
        cls.track = cls.call("import.files", {"paths": [str(cls.song)]})["tracks"][0]

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.server.stop()
        from memumusic.music.library import _LIBS
        for key, lib in list(_LIBS.items()):
            if Path(key).resolve().is_relative_to(cls.root):
                lib.close()
                del _LIBS[key]
        if cls.previous is None:
            os.environ.pop("MEMUMUSIC_DATA_DIR", None)
        else:
            os.environ["MEMUMUSIC_DATA_DIR"] = cls.previous
        cls.temp.cleanup()

    @classmethod
    def call(cls, op, args=None):
        response = cls.client.post("/api/music/call", json={"op": op, "args": args or {}})
        response.raise_for_status()
        return response.json()["result"]

    def test_independent_data_and_import(self):
        settings = self.call("settings.get")
        self.assertTrue(Path(settings["library_dir"]).is_relative_to(self.root))
        result = self.call("import.files", {"paths": [str(self.song), str(self.root / "missing.mp3")]})
        self.assertEqual(len(result["tracks"]), 1)
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(self.call("library.list")["total"], 1)

    def test_session_origin_and_host_boundary(self):
        anonymous = httpx.post(self.server.url + "/api/music/call", json={"op": "library.list"}, trust_env=False)
        self.assertEqual(anonymous.status_code, 403)
        self.assertEqual(httpx.get(self.server.url + "/api/updates/status", trust_env=False).status_code, 403)
        self.assertEqual(self.client.post("/api/updates/settings", json={"enabled": False}, headers={"Origin": "https://untrusted.invalid"}).status_code, 403)
        status = self.client.get("/api/updates/status")
        self.assertEqual(status.status_code, 200)
        self.assertIn("current_version", status.json())
        self.assertEqual(self.client.post("/api/music/call", json={"op": "library.list"}, headers={"Origin": "https://untrusted.invalid"}).status_code, 403)
        self.assertEqual(self.client.get("/health", headers={"Host": "untrusted.invalid"}).status_code, 400)

    def test_real_audio_range_and_invalid_media_token(self):
        url = self.track["stream"]
        response = self.client.get(url, headers={"Range": "bytes=0-43"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(response.content), 44)
        self.assertTrue(response.content.startswith(b"RIFF"))
        self.assertEqual(self.client.get(url.split("?")[0] + "?t=wrong").status_code, 403)
        self.assertEqual(self.client.get(url, headers={"Range": "bytes=999999999-"}).status_code, 416)

    def test_stream_range_etag_if_range_and_head(self):
        url = self.track["stream"]
        full = self.client.get(url)
        self.assertEqual(full.status_code, 200)
        self.assertEqual(full.headers["content-type"], "audio/wav")
        self.assertEqual(full.headers["accept-ranges"], "bytes")
        self.assertEqual(int(full.headers["content-length"]), len(full.content))
        etag = full.headers.get("etag")
        last_modified = full.headers.get("last-modified")
        self.assertTrue(etag, "stream must carry an ETag for If-Range seeking")
        self.assertTrue(last_modified, "stream must carry Last-Modified")
        # Suffix and open-ended ranges.
        suffix = self.client.get(url, headers={"Range": "bytes=-100"})
        self.assertEqual((suffix.status_code, len(suffix.content)), (206, 100))
        self.assertEqual(suffix.headers["content-range"], f"bytes {len(full.content) - 100}-{len(full.content) - 1}/{len(full.content)}")
        opened = self.client.get(url, headers={"Range": "bytes=100-"})
        self.assertEqual(opened.status_code, 206)
        self.assertEqual(opened.headers["content-range"], f"bytes 100-{len(full.content) - 1}/{len(full.content)}")
        # A matching If-Range keeps the slice; a stale one gets the file.
        self.assertEqual(self.client.get(url, headers={"Range": "bytes=0-43", "If-Range": etag}).status_code, 206)
        self.assertEqual(self.client.get(url, headers={"Range": "bytes=0-43", "If-Range": last_modified}).status_code, 206)
        stale = self.client.get(url, headers={"Range": "bytes=0-43", "If-Range": '"stale"'})
        self.assertEqual(stale.status_code, 200)
        self.assertEqual(len(stale.content), len(full.content))
        # HEAD honours ranges with headers only; 416 carries Accept-Ranges.
        head = self.client.head(url, headers={"Range": "bytes=0-43"})
        self.assertEqual(head.status_code, 206)
        self.assertEqual(head.content, b"")
        self.assertEqual(head.headers["content-range"], "bytes 0-43/" + str(len(full.content)))
        bad = self.client.get(url, headers={"Range": "bytes=999999999-"})
        self.assertEqual(bad.status_code, 416)
        self.assertEqual(bad.headers["accept-ranges"], "bytes")
        self.assertIn("etag", bad.headers)

    def test_manual_lyrics_short_text_recovery_and_clear(self):
        tid = self.track["id"]
        self.assertEqual(self.call("lyrics.set", {"id": tid, "text": "f"})["plain"], "f")
        self.assertEqual(self.call("lyrics.get", {"id": tid})["plain"], "f")
        fixed = self.call("lyrics.set", {"id": tid, "text": "[00:00.00]First line\n[00:04.00]Second line"})
        self.assertEqual(len(fixed["synced"]), 2)
        self.assertFalse(self.call("lyrics.set", {"id": tid, "text": ""})["plain"])

    def test_exact_offset_reset_and_sync_mode_persistence(self):
        tid = self.track["id"]
        self.call("lyrics.offset", {"id": tid, "offset": .03})
        self.assertEqual(self.call("lyrics.offset", {"id": tid, "offset": 0})["offset"], 0)
        self.assertEqual(self.call("settings.set", {"lyrics_sync": "line"})["lyrics_sync"], "line")
        self.assertEqual(self.call("settings.get")["lyrics_sync"], "line")

    def test_ui_state_survives_port_change(self):
        self.client.post("/api/state", json={"language": "en", "prefs": {"test": "persisted"}}).raise_for_status()
        from memumusic.server import load_ui
        self.assertEqual(load_ui()["prefs"]["test"], "persisted")
        self.assertIn('"language": "en"', self.client.get("/").text)

    def test_final_position_does_not_erase_saved_queue(self):
        self.client.post("/api/state", json={"player": {"queue": [{"id": self.track["id"]}], "position": 1}}).raise_for_status()
        self.client.post("/api/state", json={"player": {"position": 7}}).raise_for_status()
        from memumusic.server import load_ui
        self.assertEqual(load_ui()["player"]["position"], 7)
        self.assertEqual(load_ui()["player"]["queue"][0]["id"], self.track["id"])

    def test_playlists_and_preferences(self):
        playlist = self.call("playlist.create", {"name": "Example", "track_ids": [self.track["id"]]})
        self.assertEqual(len(self.call("playlist.get", {"id": playlist["id"]})["tracks"]), 1)
        self.call("playlist.delete", {"id": playlist["id"]})
        self.call("library.like", {"id": self.track["id"], "liked": True})
        self.assertTrue(self.call("library.get", {"id": self.track["id"]})["liked"])


if __name__ == "__main__":
    unittest.main()
