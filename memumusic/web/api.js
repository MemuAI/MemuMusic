

const API = (() => {
  async function call(op, args = {}) {
    const response = await fetch("/api/music/call", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op, args, lang: App.lang }) });
    const body = await response.json();
    if (!response.ok || body.error) throw new Error(body.error || `HTTP ${response.status}`);
    return body.result;
  }
  async function soft(op, args, fallback) {
    try { return await call(op, args); } catch (error) { console.warn("[music]", op, error && error.message || error); return fallback; }
  }
  return { call, soft, mocked: false };
})();
