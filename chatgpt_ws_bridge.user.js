// ==UserScript==
// @name         RTSagents ChatGPT -> WS bridge
// @namespace    rtsagents
// @version      0.1.0
// @description  Mirror ChatGPT conversation messages into RTSagents viewer via ws://localhost:8765 (NDJSON)
// @match        https://chatgpt.com/*
// @match        https://chat.openai.com/*
// @grant        none
// ==/UserScript==

(function () {
  "use strict";

  // ---- Config ----
  const WS_URL = "ws://localhost:8765";
  const MAX_DETAIL_CHARS = 240;
  const SEND_ASSISTANT = true;
  const SEND_USER = true;
  const AGENT_USER = "chat:user";
  const AGENT_ASSISTANT = "chat:assistant";

  // ---- State ----
  const t0 = Date.now();
  let ws = null;
  let wsReady = false;
  let reconnectTimer = null;
  const seen = new Set();

  function nowT() {
    return Math.max(0, Date.now() - t0);
  }

  function clampDetail(s) {
    const t = String(s || "").replace(/\s+/g, " ").trim();
    return t.length > MAX_DETAIL_CHARS ? t.slice(0, MAX_DETAIL_CHARS - 1) + "…" : t;
  }

  function hashStr(s) {
    // FNV-1a 32-bit
    let h = 0x811c9dc5;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return (h >>> 0).toString(16);
  }

  function sendEvent(evt) {
    if (!ws || !wsReady) return;
    try {
      ws.send(JSON.stringify(evt));
    } catch {
      // ignore
    }
  }

  function connect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    try {
      ws = new WebSocket(WS_URL);
    } catch (e) {
      scheduleReconnect();
      return;
    }

    wsReady = false;
    ws.onopen = () => {
      wsReady = true;
      sendEvent({ t: nowT(), agent: "chat", action: "web", detail: "ws bridge connected", ok: true });
    };
    ws.onclose = () => {
      wsReady = false;
      scheduleReconnect();
    };
    ws.onerror = () => {
      // close triggers reconnect
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(connect, 1200);
  }

  function classifyAction(role, text) {
    const s = String(text || "").toLowerCase();
    if (role === "user") return "plan";
    if (s.includes("error") || s.includes("failed") || s.includes("exception")) return "test";
    if (s.includes("run ") || s.includes("npm ") || s.includes("pytest") || s.includes("command")) return "run";
    return "edit";
  }

  function extractMessages() {
    // Current ChatGPT DOM typically includes: [data-message-author-role="user"|"assistant"]
    const nodes = document.querySelectorAll("[data-message-author-role]");
    const out = [];
    for (const n of nodes) {
      const role = n.getAttribute("data-message-author-role");
      if (role !== "user" && role !== "assistant") continue;
      if (role === "user" && !SEND_USER) continue;
      if (role === "assistant" && !SEND_ASSISTANT) continue;

      // Use textContent; it's not perfect but stable across layout changes.
      const text = clampDetail(n.textContent || "");
      if (!text) continue;

      const key = hashStr(role + "|" + text);
      out.push({ role, text, key });
    }
    return out;
  }

  function pump() {
    for (const m of extractMessages()) {
      if (seen.has(m.key)) continue;
      seen.add(m.key);

      const agent = m.role === "user" ? AGENT_USER : AGENT_ASSISTANT;
      const action = classifyAction(m.role, m.text);
      sendEvent({ t: nowT(), agent, action, detail: m.text, ok: true });
    }
  }

  function startObserver() {
    const obs = new MutationObserver(() => {
      // Coalesce bursts
      if (pump._t) return;
      pump._t = setTimeout(() => {
        pump._t = null;
        pump();
      }, 120);
    });
    obs.observe(document.documentElement, { childList: true, subtree: true });
  }

  // Boot
  connect();
  startObserver();
  setInterval(pump, 1000);
})();

