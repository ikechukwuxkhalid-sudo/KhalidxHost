// shared helpers (no inline scripts -> strict CSP)
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, { method = "GET", body } = {}) {
  const r = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-KX": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try { data = await r.json(); } catch (_) {}
  if (!r.ok) {
    let msg = (data && data.detail) || `Request failed (${r.status})`;
    if (Array.isArray(msg)) msg = msg.map((m) => m.msg).join(", ");
    const e = new Error(msg); e.status = r.status; throw e;
  }
  return data;
}

function toast(msg, type = "ok") {
  let box = $("#toasts");
  if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
  const t = document.createElement("div");
  t.className = `toast ${type}`; t.textContent = msg; box.appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast("Copied ✓"); }
  catch (_) {
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); toast("Copied ✓"); } catch (e) { toast("Copy failed", "bad"); }
    ta.remove();
  }
}

function ago(iso) {
  if (!iso) return "—";
  const s = Math.max(1, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
}

function bg() {
  if ($(".bg")) return;
  const d = document.createElement("div"); d.className = "bg";
  d.innerHTML = '<div class="orb o1"></div><div class="orb o2"></div><div class="orb o3"></div>';
  document.body.prepend(d);
}
document.addEventListener("DOMContentLoaded", bg);

// click-to-copy for any element with data-copy
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-copy]");
  if (el) copyText(el.dataset.copy);
});
