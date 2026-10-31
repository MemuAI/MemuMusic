"""Custom MemuMusic themes: the shared JS logic, the assembled bundle and
persistence of the themes in the data directory (ui-state.json).

The JS checks run in node with stubbed browser globals; the harness is
written to a temporary directory, never into the repository.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "memumusic" / "web"

HARNESS = r'''"use strict";
const fs = require("fs");
const vm = require("vm");
const WEB = process.argv[2];
const custom = require(WEB + "/custom-themes.js");
function eq(a, b, label) {
  const x = JSON.stringify(a), y = JSON.stringify(b);
  if (x !== y) throw new Error(label + ": expected " + y + ", got " + x);
}
function throws(fn, key, label) {
  try { fn(); } catch (e) { if (e.message !== key) throw new Error(label + ": wrong error " + e.message); return; }
  throw new Error(label + ": no error thrown");
}
const theme = custom.normalize({ name: "  Ocean 2 ", h: 200, s: 50, acc: ["#1fb2ff", "#3a6bff", "#2fd8c8"],
  light: [95, 99], dark: [6, 10, 0.5], tokens: { dark: { "--mm-bg": "#101418" } } });
eq(theme.format, "memumusic-theme", "format");
eq(theme.name, "Ocean 2", "name trimmed");
eq(theme.id.startsWith("custom:"), true, "custom id");
eq(custom.toBuiltin(theme).acc, ["#1fb2ff", "#3a6bff", "#2fd8c8"], "accents");
eq(custom.parseImport(custom.exportText(theme)), theme, "export/import round-trip");
const fromMemu = custom.parseImport(JSON.stringify({ format: "memuai-theme", schema: 1, name: "Memu",
  base: "dark", author: "A", tokens: { "--bg": "#202020", "--panel": "#2a2a2a", "--text": "#eeeeee", "--accent": "#ff8800" },
  elements: { x: 1 }, look: { layout: {} }, prefs: {}, css: "body{}" }));
eq(fromMemu.tokens.dark["--mm-bg"], "#202020", "memuai bg mapped");
eq(fromMemu.tokens.dark["--mm-surface"], "#2a2a2a", "memuai panel mapped");
eq(fromMemu.tokens.dark["--mm-text"], "#eeeeee", "memuai text mapped");
eq(fromMemu.acc[0], "#ff8800", "memuai accent mapped");
eq(fromMemu.elements, undefined, "memuai-only fields ignored");
throws(() => custom.parseImport("not json"), "ui.custom.err.json", "bad json");
throws(() => custom.parseImport('{"format":"other","name":"x"}'), "ui.custom.err.format", "bad format");
throws(() => custom.parseImport('{"name":""}'), "ui.custom.err.name", "empty name");
throws(() => custom.normalize({ name: "x", acc: ["red"] }), "ui.custom.err.color", "bad colour");
throws(() => custom.normalize({ name: "x", h: "soon" }), "ui.custom.err.range", "bad number");
const safe = custom.normalize({ name: "x", tokens: { dark: { "--mm-bg": "red; background:url(evil)", "--mm-text": "#112233", "--nope": "#000" } } });
eq(safe.tokens.dark, { "--mm-text": "#112233" }, "unsafe tokens dropped");
eq(custom.loadList([theme, { name: "" }, theme, "junk"]).length, 1, "loadList drops damaged");
let items = custom.upsert([], theme);
items = custom.upsert(items, Object.assign({}, theme, { name: "Renamed" }));
eq(items.length, 1, "upsert replaces");
eq(items[0].name, "Renamed", "upsert rename");
eq(custom.remove(items, theme.id).length, 0, "remove");
eq(custom.fallbackId(items, theme.id), theme.id, "fallback keeps active");
eq(custom.fallbackId([], "custom:x"), "cover", "fallback to cover");
eq(custom.fallbackId(custom.remove(items, theme.id), theme.id), "cover", "fallback after delete");
const full = Array.from({ length: 48 }, (_, i) => custom.normalize({ name: "t" + i }));
throws(() => custom.upsert(full, { name: "one more" }), "ui.custom.err.limit", "limit");
const varTheme = custom.normalize({ name: "Vars", h: 200, s: 50,
  vars: { "--mm-gap": "10px", "--mm-cover-opacity": 0.1, "--mm-font": "Georgia, serif", "--mm-nope": "x", "--mm-tile": "soon", "--mm-rk": 1.3 },
  css: ":root{--mm-gap:9px}" });
eq(varTheme.vars, { "--mm-rk": "1.3", "--mm-gap": "10px", "--mm-font": "Georgia, serif", "--mm-cover-opacity": "0.1" }, "vars normalised");
eq(varTheme.css, ":root{--mm-gap:9px}", "css kept");
eq(custom.parseImport(custom.exportText(varTheme)), varTheme, "vars/css round-trip");
eq(custom.normalize({ name: "BadCss", css: "a{background:url(evil)}" }).css, "", "unsafe css dropped");
eq(custom.normalize({ name: "BadCss2", css: ".a{color:red" }).css, "", "unbalanced css dropped");
eq(custom.validateCss(".a{color:#fff}"), "", "css valid");
eq(custom.validateCss(".a{color:#fff"), "ui.custom.err.css", "css unbalanced");
eq(custom.validateCss("@import 'x'"), "ui.custom.err.css", "css import rejected");
eq(custom.hexToHsl("#ff2bd6")[0] > 300 && custom.hexToHsl("#ff2bd6")[0] < 320, true, "hexToHsl pink hue");
eq(custom.hslToHex(0, 100, 50), "#ff0000", "hslToHex red");
eq(custom.normHex("#f0a"), "#ff00aa", "normHex short");
eq(fromMemu.css, "body{}", "memuai css carried");
console.log("pure checks OK");

const createdStyles = [];
const vars = {};
const root = {
  style: { setProperty(k, v) { vars[k] = v; }, removeProperty(k) { delete vars[k]; }, colorScheme: "" },
  setAttribute(k, v) { this["attr:" + k] = v; },
  getAttribute(k) { return k === "data-theme" ? "dark" : this["attr:" + k]; },
  classList: { add() {}, remove() {}, toggle() {} },
  toggleAttribute() {},
};
const sandbox = {
  console, Memu: undefined,
  App: { lang: "ru", setLanguage() {} },
  window: {}, document: { getElementById: () => null, querySelector: () => null, documentElement: root,
    head: { appendChild() {} },
    createElement: () => { const el = { textContent: "", removed: false, setAttribute() {}, remove() { this.removed = true; } }; createdStyles.push(el); return el; } },
  matchMedia: () => ({ matches: true, addEventListener() {} }),
  getComputedStyle: () => ({ getPropertyValue: () => "" }),
  root,
  S: { prefs: { customThemes: [theme, custom.normalize({ name: "Dyn", h: 10, s: 60, dyn: true }),
    custom.normalize({ name: "Light", h: 200, s: 50, tokens: { dark: {}, light: { "--mm-text": "#123456" } } }),
    custom.normalize({ name: "Vars", h: 200, s: 50, vars: { "--mm-gap": "10px", "--mm-cover-opacity": 0.1 }, css: ":root{--mm-gap:9px}" })],
    ui: { theme: "cover", mode: "dark" } } },
  savePrefs() {}, applyPalette() {}, applyCalm() {},
  Player: { current: () => null },
  NP: {}, Fx: { reduce: { addEventListener() {} } },
  SETTINGS_TABS: [], ambient: null, coverArt: () => "",
  $: () => null, $$: () => [],
  esc: (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]),
  t: (k) => k, debounce: (f) => f, icon: () => "",
};
sandbox.window.matchMedia = sandbox.matchMedia;
vm.createContext(sandbox);
const art = fs.readFileSync(WEB + "/art.js", "utf8");
const ct = fs.readFileSync(WEB + "/custom-themes.js", "utf8");
const themeJs = fs.readFileSync(WEB + "/theme.js", "utf8");
vm.runInContext(art + "\n" + ct + "\n" + themeJs + "\n;globalThis.__Theme = Theme;", sandbox);
const Theme = sandbox.__Theme;
Theme.ui.theme = "midnight";
Theme.apply();
eq([...Theme.accents()], ["#7c5cff", "#ff5c8a", "#20c7b5"], "builtin accents unchanged");
eq(Theme.coverAccent(), false, "builtin coverAccent");
eq(Theme.coverSoft(), true, "builtin coverSoft");
const midnightBg = vars["--mm-bg"];
Theme.ui.theme = theme.id;
Theme.apply();
eq(vars["--mm-bg"], "#101418", "explicit token wins");
eq(vars["--mm-bg"] === midnightBg, false, "custom background differs");
eq([...Theme.accents()], ["#1fb2ff", "#3a6bff", "#2fd8c8"], "custom accents");
eq(Theme.coverAccent(), false, "custom accents win over cover");
const dyn = sandbox.S.prefs.customThemes[1];
Theme.ui.theme = dyn.id;
Theme.apply();
eq(Theme.coverAccent(), true, "dyn custom follows cover");
Theme.ui.theme = "custom:gone";
Theme.apply();
eq([...Theme.accents()], ["#7c5cff", "#ff5c8a", "#20c7b5"], "unknown custom id falls back");
Theme.ui.mode = "light";
Theme.ui.theme = sandbox.S.prefs.customThemes[2].id;
Theme.apply();
eq(vars["--mm-text"], "#123456", "explicit light token applies");
// Tint reset (screenshot: pink/purple wash after a theme or accent change).
Theme.ui.theme = "cover"; Theme.ui.accent = ""; Theme.ui.mode = "dark";
Theme.apply();
Theme.paint(["#ff2bd6", "#00d9ff", "#a6ff2e"]);
eq(vars["--tint"], "#ff2bd6", "cover paint tints");
if (Theme.coverHue() == null) throw new Error("dyn hue not set by cover paint");
Theme.ui.theme = "graphite";
Theme.apply();
eq(vars["--tint"], "#e4e4e7", "apply-only switch drops cover tint");
eq(Theme.coverHue(), null, "dyn hue reset on non-dyn theme");
Theme.ui.theme = "cover"; Theme.apply();
Theme.paint(["#ff2bd6", "#00d9ff", "#a6ff2e"]);
Theme.ui.accent = "#22d39b"; Theme.apply();
eq(vars["--tint"], "#22d39b", "manual accent wins in apply-only refresh");
Theme.resetTint();
eq(vars["--tint"], "#22d39b", "resetTint keeps manual accent");
Theme.ui.accent = ""; Theme.resetTint();
eq(vars["--tint"], "#7c5cff", "resetTint restores theme accents");
// Theme variables and custom CSS apply, and do not leak to the next theme.
const storedVarTheme = sandbox.S.prefs.customThemes[3];
Theme.ui.theme = storedVarTheme.id; Theme.apply();
eq(vars["--mm-gap"], "10px", "theme var applies");
eq(vars["--mm-cover-opacity"], "0.1", "theme overlay var applies");
eq(createdStyles.length, 1, "custom css element created");
eq(createdStyles[0].textContent, ":root{--mm-gap:9px}", "custom css applied");
Theme.ui.theme = "midnight"; Theme.apply();
eq(vars["--mm-gap"], undefined, "theme var removed on switch");
eq(createdStyles[0].removed, true, "custom css element removed on switch");
let captured = "";
const hostStub = { addEventListener() {}, querySelector() { return { addEventListener() {} }; } };
Object.defineProperty(hostStub, "innerHTML", { get() { return captured; }, set(v) { captured = v; } });
Theme.render(hostStub);
if (!captured.includes("ui.theme.midnight_hint")) throw new Error("builtin theme hint missing from render");
if (captured.includes("<span>}</span>")) throw new Error("broken card template in render");
if (!captured.includes("ui.custom.title")) throw new Error("custom themes group missing from render");
if (!captured.includes(theme.id)) throw new Error("custom theme card missing from render");
if (!captured.includes("ct-file")) throw new Error("import input missing from render");
if (!captured.includes("mm-ct-picker")) throw new Error("custom picker missing from render");
if (!captured.includes("data-ap-picker")) throw new Error("accent picker missing from render");
if (captured.includes('type="color"')) throw new Error("native colour input still rendered");
console.log("render checks OK");
console.log("theme.js checks OK");
'''

try:
    import httpx  # noqa: F401
    from memumusic.server import LocalServer  # noqa: F401
    HAS_SERVER = True
except Exception:
    HAS_SERVER = False

NODE = shutil.which("node")


def run_harness(tmp):
    harness = Path(tmp) / "custom_themes_harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    return subprocess.run([NODE, str(harness), str(WEB)], capture_output=True, text=True, timeout=60)


class CustomThemesJsTests(unittest.TestCase):
    @unittest.skipUnless(NODE, "node is required")
    def test_custom_themes_logic_and_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_harness(tmp)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("pure checks OK", result.stdout)
        self.assertIn("theme.js checks OK", result.stdout)
        self.assertIn("render checks OK", result.stdout)

    @unittest.skipUnless(NODE, "node is required")
    def test_js_files_parse(self):
        for name in ("main.js", "theme.js", "custom-themes.js"):
            result = subprocess.run([NODE, "--check", str(WEB / name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(HAS_SERVER and NODE, "server deps and node are required")
    def test_assembled_bundle_parses(self):
        sys.path.insert(0, str(ROOT))
        from memumusic.paths import web_dir
        from memumusic.server import bundle
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.js"
            text = bundle(web_dir() / "main.js")
            path.write_text(text, encoding="utf-8")
            result = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True)
        self.assertIn("CustomThemes", text)
        self.assertIn("ctEditorHtml", text)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_i18n_has_custom_theme_keys(self):
        data = json.loads((WEB / "i18n.json").read_text(encoding="utf-8"))
        keys = ("ui.custom.title", "ui.custom.hint", "ui.custom.new", "ui.custom.import", "ui.custom.edit",
                "ui.custom.duplicate", "ui.custom.export", "ui.custom.delete", "ui.custom.name",
                "ui.custom.author", "ui.custom.description", "ui.custom.hue", "ui.custom.sat",
                "ui.custom.dark_bg", "ui.custom.dark_surface", "ui.custom.dark_sat",
                "ui.custom.light_bg", "ui.custom.light_surface", "ui.custom.accents",
                "ui.custom.dyn", "ui.custom.dyn_hint", "ui.custom.mono", "ui.custom.base",
                "ui.custom.base_dark", "ui.custom.base_light", "ui.custom.tokens",
                "ui.custom.token_bg", "ui.custom.token_surface", "ui.custom.token_text",
                "ui.custom.token_panel", "ui.custom.token_panel2", "ui.custom.token_line",
                "ui.custom.token_hover", "ui.custom.token_muted", "ui.custom.token_faint",
                "ui.custom.token_shadow",
                "ui.custom.auto", "ui.custom.from", "ui.custom.save", "ui.custom.cancel",
                "ui.custom.empty", "ui.custom.saved", "ui.custom.deleted", "ui.custom.duplicated",
                "ui.custom.imported", "ui.custom.copy", "ui.custom.err.json", "ui.custom.err.object",
                "ui.custom.err.format", "ui.custom.err.name", "ui.custom.err.color",
                "ui.custom.err.range", "ui.custom.err.limit", "ui.custom.err.css",
                "ui.custom.picker_hex", "ui.custom.picker_hue", "ui.custom.picker_sat",
                "ui.custom.picker_light", "ui.custom.picker_alpha", "ui.custom.picker_swatches",
                "ui.custom.vars", "ui.custom.var_rk", "ui.custom.var_tile", "ui.custom.var_row",
                "ui.custom.var_padx", "ui.custom.var_gap", "ui.custom.var_side", "ui.custom.var_bar",
                "ui.custom.var_font", "ui.custom.var_display", "ui.custom.var_weight",
                "ui.custom.var_tracking", "ui.custom.var_cover_opacity", "ui.custom.var_cover_blur",
                "ui.custom.var_ambient_opacity", "ui.custom.var_danger", "ui.custom.var_ok",
                "ui.custom.vars_auto", "ui.custom.css", "ui.custom.css_hint", "ui.custom.css_err",
                "ui.custom.css_ok", "ui.custom.css_preset_compact", "ui.custom.css_preset_bigtext",
                "ui.custom.css_preset_noshadow", "ui.custom.presets", "ui.custom.history",
                "ui.custom.hist_undo", "ui.custom.hist_redo", "ui.custom.hist_revert",
                "ui.custom.hist_reset", "ui.custom.hist_empty", "ui.custom.hist_change")
        for lang in ("ru", "en"):
            for key in keys:
                self.assertIn(key, data[lang], f"{lang}:{key}")

    def test_style_has_editor_rules(self):
        css = (WEB / "style.css").read_text(encoding="utf-8")
        for rule in (".mm-ct-card", ".mm-ct-editor", ".mm-ct-picker", ".mm-ct-swatch",
                     ".mm-ct-css", ".mm-ct-hist", ".mm-ct-toolbar"):
            self.assertIn(rule, css)

    def test_style_has_number_input_rules(self):
        # The bare <input type="number"> fields next to the sliders used to
        # render with the browser's square UA stylesheet (radius 0, 2px
        # inset border). They must share the themed control look.
        css = (WEB / "style.css").read_text(encoding="utf-8")
        rule = '.mm-ct-pair input[type="number"]'
        self.assertIn(rule + " {", css)
        self.assertIn("border-radius: calc(10px * var(--mm-rk))", css)
        self.assertIn("border: 1px solid var(--mm-line)", css)
        self.assertIn("background: var(--mm-panel)", css)
        self.assertIn(rule + ":focus", css)
        self.assertIn(rule + ":hover", css)
        self.assertIn("::-webkit-inner-spin-button", css)
        self.assertIn("::-webkit-outer-spin-button", css)

    def test_style_has_css_highlight_rules(self):
        css = (WEB / "style.css").read_text(encoding="utf-8")
        for rule in (".mm-ct-css-wrap", ".mm-ct-css-hl", ".mm-ct-css-live",
                     ".mm-ct-css-hl .tok-kw", ".mm-ct-css-hl .tok-attr",
                     ".mm-ct-css-hl .tok-num", ".mm-ct-css-hl .tok-com",
                     ".mm-ct-css-hl .tok-type", ".mm-ct-css-hl .tok-str"):
            self.assertIn(rule, css)
        # Both schemes get their own token colours.
        self.assertIn('html[data-mm-scheme="light"] .mm-ct-css-hl .tok-attr', css)

    def test_editor_js_has_css_highlight(self):
        js = (WEB / "theme.js").read_text(encoding="utf-8")
        for marker in ("ctHighlightCss", "ctHighlightCssLocal", "ctPaintCss", "ctSyncCssScroll",
                       "mm-ct-css-wrap", "mm-ct-css-hl", "MemuSyntax.highlight"):
            self.assertIn(marker, js)
        # The local fallback tokenises the same classes MemuSyntax emits
        # (class names are built as "tok-" + cls, so check the parts).
        self.assertIn('class="tok-', js)
        for cls in ('"com"', '"attr"', '"num"', '"type"', '"fn"', '"var"', '"kw"', '"str"'):
            self.assertIn(cls, js)

    def test_module_copy_matches_editor_rules(self):
        module = ROOT.parent / "MemuAI" / "app" / "module_builtins" / "music"
        if not module.is_dir():
            self.skipTest("module copy is not in this checkout")
        css = (module / "style.css").read_text(encoding="utf-8")
        js = (module / "theme.js").read_text(encoding="utf-8")
        for marker in ('.mm-ct-pair input[type="number"]', ".mm-ct-css-wrap", ".mm-ct-css-hl",
                       ".mm-ct-css-hl .tok-attr"):
            self.assertIn(marker, css)
        for marker in ("ctHighlightCss", "ctPaintCss", "mm-ct-css-wrap"):
            self.assertIn(marker, js)
        # The shared theme logic itself is one file in both copies.
        self.assertEqual((WEB / "custom-themes.js").read_bytes(),
                         (module / "custom-themes.js").read_bytes())


    def test_no_native_color_inputs(self):
        for name in WEB.iterdir():
            if name.suffix == ".js":
                self.assertNotIn('type="color"', name.read_text(encoding="utf-8"), name.name)
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertNotIn('[type="color"]', css)

    def test_covertint_hides_cover_for_all_themes(self):
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn('html[data-mm-bg][data-mm-covertint="off"] .mm-coverbg[src]', css)
        self.assertNotIn('not([data-mm-theme="cover"])[data-mm-covertint="off"]', css)

    def test_editor_i18n_keys_used_exist(self):
        js = (WEB / "theme.js").read_text(encoding="utf-8")
        found = set(re.findall(r'custom\.([a-z][a-z0-9_.]+)', js))
        found = {k.rstrip("_.") for k in found}
        found = {k for k in found if k and k != "css_preset"}
        data = json.loads((WEB / "i18n.json").read_text(encoding="utf-8"))
        for lang in ("ru", "en"):
            for key in sorted(found):
                self.assertIn("ui.custom." + key, data[lang], f"{lang}:ui.custom.{key}")

    def test_js_files_parse_np_and_main(self):
        for name in ("np.js", "main.js"):
            result = subprocess.run([NODE, "--check", str(WEB / name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(HAS_SERVER, "fastapi/httpx are required")
class CustomThemesServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name).resolve()
        cls.previous = os.environ.get("MEMUMUSIC_DATA_DIR")
        os.environ["MEMUMUSIC_DATA_DIR"] = str(cls.root / "profile")
        sys.path.insert(0, str(ROOT))
        from memumusic.server import LocalServer
        cls.server = LocalServer().start()
        cls.client = httpx.Client(base_url=cls.server.url, trust_env=False, timeout=30)
        cls.client.get("/")

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.server.stop()
        if cls.previous is None:
            os.environ.pop("MEMUMUSIC_DATA_DIR", None)
        else:
            os.environ["MEMUMUSIC_DATA_DIR"] = cls.previous
        cls.temp.cleanup()

    def test_custom_themes_persist_in_data_dir(self):
        theme = {"format": "memumusic-theme", "schema": 1, "id": "custom:sea", "name": "Sea",
                 "author": "", "description": "", "base": "dark", "extends": "ocean",
                 "h": 200, "s": 50, "acc": ["#1fb2ff", "#3a6bff", "#2fd8c8"],
                 "dyn": False, "mono": False, "light": [95, 99], "dark": [6, 10, 0.5],
                 "tokens": {"dark": {}, "light": {}}}
        response = self.client.post("/api/state", json={"prefs": {"customThemes": [theme],
                                                                 "ui": {"theme": theme["id"]}}})
        self.assertEqual(response.status_code, 200, response.text)
        stored = json.loads((self.root / "profile" / "ui-state.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["prefs"]["customThemes"], [theme])
        self.assertEqual(stored["prefs"]["ui"]["theme"], theme["id"])
        html = self.client.get("/").text
        match = re.search(r"window\.__MUSIC_BOOTSTRAP__ = (.*);</script>", html, re.S)
        self.assertIsNotNone(match)
        saved = json.loads(match.group(1))["saved"]
        self.assertEqual(saved["prefs"]["customThemes"], [theme])

    def test_damaged_stored_themes_do_not_break_the_page(self):
        response = self.client.post("/api/state", json={"prefs": {"customThemes": ["junk", {"name": ""}]}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get("/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
