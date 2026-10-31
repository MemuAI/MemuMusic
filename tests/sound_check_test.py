"""Linux sound diagnostics: GStreamer/audio-server probe, the .deb audio
dependencies, and the i18n keys the sound check and the player error
mapping rely on."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "memumusic" / "web"
MODULE = ROOT.parent / "MemuAI" / "app" / "module_builtins" / "music"


class AudioStatusTests(unittest.TestCase):
    def test_audio_status_shape(self):
        from memumusic.music import tools
        value = tools.audio_status()
        for key in ("supported", "platform", "elements", "missing", "audio_server", "command"):
            self.assertIn(key, value)
        self.assertIsInstance(value["elements"], dict)
        for name, ok in value["elements"].items():
            self.assertIn(ok, (True, False, None), name)
        # Unknown is not "missing": without gst-inspect-1.0 the probe must
        # not claim decoders are absent.
        if not value["gst_inspect"]:
            self.assertEqual(value["missing"], [])
        self.assertIn(value["audio_server"], ("pipewire", "pulseaudio", "none", "unknown"))

    def test_audio_status_reports_missing_decoder(self):
        from memumusic.music import tools
        tools._AUDIO_CACHE.update(at=0.0, value=None)
        calls = {"avdec_aac": 1, "mpg123audiodec": 0, "faad": 0}
        real_run = tools.subprocess.run

        def fake_run(cmd, **kwargs):
            name = cmd[-1]
            result = mock.Mock()
            result.returncode = calls.get(name, 0)
            result.stdout = "" if result.returncode == 0 else "No such element"
            result.stderr = ""
            return result

        with mock.patch.object(tools.shutil, "which",
                               side_effect=lambda name: "/usr/bin/" + name), \
             mock.patch.object(tools.subprocess, "run", side_effect=fake_run):
            tools._AUDIO_CACHE.update(at=0.0, value=None)
            value = tools.audio_status()
        tools._AUDIO_CACHE.update(at=0.0, value=None)
        self.assertEqual(value["missing"], ["avdec_aac"])
        self.assertIn("gstreamer1.0-libav", value["command"])
        self.assertTrue(value["elements"]["mpg123audiodec"])

    def test_tools_status_includes_audio(self):
        from memumusic.music import tools
        self.assertIn("audio", tools.status())
        self.assertIsInstance(tools.status()["audio"], dict)

    def test_deb_declares_audio_dependencies(self):
        script = (ROOT / "tools" / "build-linux-deb.sh").read_text(encoding="utf-8")
        depends = next(line for line in script.splitlines() if line.startswith("Depends:"))
        recommends = next(line for line in script.splitlines() if line.startswith("Recommends:"))
        self.assertIn("gstreamer1.0-plugins-base", depends)
        self.assertIn("gstreamer1.0-plugins-good", depends)
        for package in ("gstreamer1.0-plugins-bad", "gstreamer1.0-plugins-ugly",
                        "gstreamer1.0-libav", "gstreamer1.0-pipewire"):
            self.assertIn(package, recommends, package)

    def test_sound_check_i18n_keys(self):
        data = json.loads((WEB / "i18n.json").read_text(encoding="utf-8"))
        keys = ("set.sound", "set.sound_hint", "set.sound_check", "set.sound_check_go",
                "set.sound_check_idle", "set.sound_check_ok", "set.sound_check_ok_partial",
                "set.sound_check_bad", "set.sound_check_notsupported", "set.sound_check_no_gst",
                "set.sound_check_missing", "set.sound_check_no_server", "set.sound_check_server",
                "set.sound_check_no_track", "set.sound_check_probe_ok", "set.sound_check_probe_decode",
                "set.sound_check_probe_network", "set.sound_check_probe_blocked",
                "set.sound_check_probe_timeout", "set.sound_check_probe_fail",
                "error.play_decode", "error.play_blocked", "error.play_network")
        for lang in ("ru", "en"):
            for key in keys:
                self.assertIn(key, data[lang], f"{lang}:{key}")

    def test_error_mapping_i18n_keys_in_module_copy(self):
        if not MODULE.is_dir():
            self.skipTest("module copy is not in this checkout")
        data = json.loads((MODULE / "i18n.json").read_text(encoding="utf-8"))
        for lang in ("ru", "en"):
            for key in ("error.play_decode", "error.play_blocked", "error.play_network"):
                self.assertIn(key, data[lang], f"{lang}:{key}")


if __name__ == "__main__":
    unittest.main()
