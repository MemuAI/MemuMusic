"use strict";

const App = (() => {
  const data = window.__MUSIC_BOOTSTRAP__;
  const saved = data.saved || {};
  let language = saved.language === "en" ? "en" : saved.language === "ru" ? "ru" : navigator.language.startsWith("ru") ? "ru" : "en";
  const listeners = new Map();
  let pending = {}, timer = 0, saving = false;
  const emit = name => (listeners.get(name) || []).forEach(fn => fn());
  const on = (name, callback) => { if (!listeners.has(name)) listeners.set(name, []); listeners.get(name).push(callback); };
  function t(key, vars = {}) {
    let value = (data.translations[language] || {})[key] ?? data.translations.en[key] ?? vars.fallback ?? key;
    if (value && typeof value === "object") {
      const form = new Intl.PluralRules(language).select(typeof vars.count === "number" ? vars.count : 0);
      value = value[form] ?? value.other ?? "";
    }
    return String(value).replace(/\{(\w+)\}/g, (match, name) => vars[name] ?? match);
  }
  function translate(node = document) {
    if (!node.querySelectorAll) return;
    const selector = "[data-i18n], [data-i18n-title], [data-i18n-aria-label], [data-i18n-placeholder]";
    const nodes = [...node.querySelectorAll(selector)];
    if (node.matches?.(selector)) nodes.unshift(node);
    for (const el of nodes) {
      if (el.dataset.i18n) { const text = t(el.dataset.i18n); if (el.textContent !== text) el.textContent = text; }
      for (const [attr, key] of [["title", "i18nTitle"], ["aria-label", "i18nAriaLabel"], ["placeholder", "i18nPlaceholder"]]) {
        if (el.dataset[key]) { const text = t(el.dataset[key]); if (el.getAttribute(attr) !== text) el.setAttribute(attr, text); }
      }
    }
    document.documentElement.lang = language;
  }
  async function flush() {
    clearTimeout(timer);
    if (saving || !Object.keys(pending).length) return;
    const patch = pending; pending = {}; saving = true;
    try {
      const response = await fetch("/api/state", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
      if (!response.ok) throw new Error("Could not save preferences");
    } catch (error) { pending = Object.assign(patch, pending); console.warn("[storage]", error); }
    finally { saving = false; if (Object.keys(pending).length) timer = setTimeout(flush, 1500); }
  }
  function save(patch) {
    const copy = JSON.parse(JSON.stringify(patch));
    Object.assign(saved, copy); Object.assign(pending, copy);
    clearTimeout(timer); timer = setTimeout(flush, 350);
  }
  function setLanguage(lang) {
    if (!["ru", "en"].includes(lang)) return;
    language = lang; save({ language }); translate(); emit("language");
  }
  async function open({ url }) {
    const parsed = new URL(url);
    if (!["https:", "http:"].includes(parsed.protocol) || parsed.username || parsed.password) throw new Error("Unsupported URL");
    if (window.pywebview?.api) return window.pywebview.api.open_url(parsed.href);
    window.open(parsed.href, "_blank", "noopener,noreferrer");
  }
  function closeState(patch) {
    const final = Object.assign({}, pending, patch);
    if (final.player) { final.player = { ...final.player }; delete final.player.queue; }
    navigator.sendBeacon("/api/state", new Blob([JSON.stringify(final)], { type: "application/json" }));
  }
  window.addEventListener("DOMContentLoaded", () => {
    translate();
    new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(translate)))
      .observe(document.body, { childList: true, subtree: true });
  });
  return { t, saved, save, flush, closeState, open, get lang() { return language; }, setLanguage, translate,
    onTheme: callback => on("theme", callback), onLanguage: callback => on("language", callback), on,
    ready() { document.documentElement.dataset.ready = "true"; translate(); } };
})();

window.addEventListener("DOMContentLoaded", () => {
  const lang = document.getElementById("app-language");
  lang.value = App.lang;
  lang.addEventListener("change", () => App.setLanguage(lang.value));
  const picker = document.getElementById("audio-files");
  picker.addEventListener("change", () => { importFiles([...picker.files]); picker.value = ""; });
  document.getElementById("add-files").addEventListener("click", async () => {
    if (!window.pywebview?.api) return picker.click();
    const paths = await window.pywebview.api.choose_files();
    if (!paths.length) return;
    try {
      const result = await window.MemuMusic.API.call("import.files", { paths });
      await window.MemuMusic.refresh();
      toast(result.failed.length ? App.t("app.import_partial", { n: result.tracks.length, failed: result.failed.length }) : App.t("app.imported", { n: result.tracks.length }));
    } catch (error) { toast(String(error.message || error)); }
  });
  document.getElementById("add-folder").addEventListener("click", async () => {
    if (!window.pywebview?.api) { window.MemuMusic.go("settings", { tab: "library" }); return; }
    const path = await window.pywebview.api.choose_folder();
    if (!path) return;
    try {
      await window.MemuMusic.API.call("import.folder", { path });
      window.MemuMusic.go("download"); window.MemuMusic.pollJobs();
    } catch (error) { toast(String(error.message || error)); }
  });
  document.addEventListener("keydown", event => {
    if (event.code === "F11" && window.pywebview?.api) { event.preventDefault(); window.pywebview.api.toggle_fullscreen(); }
  });
});
