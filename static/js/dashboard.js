let ME = null, OPTS = null, VPS = [], view = "overview", pollTimer = null;
const sel = { name: "", region: "iad", cpus: 1, memory_mb: 2048, storage_gb: 10 };
const gb = (mb) => (mb / 1024) + " GB";

async function boot() {
  try { ME = await api("/api/v1/me"); }
  catch (e) { location.href = "/login"; return; }
  const h = location.hash.replace("#", "");
  go(["overview", "create", "vps", "fly", "api"].includes(h) ? h : "overview");
}

function go(v) {
  view = v; history.replaceState(null, "", "#" + v);
  $$(".side a.nv[data-v]").forEach((a) => a.classList.toggle("on", a.dataset.v === v));
  clearInterval(pollTimer);
  ({ overview: vOverview, create: vCreate, vps: vVps, fly: vFly, api: vApi })[v]();
}
$$(".side a.nv[data-v]").forEach((a) => (a.onclick = () => go(a.dataset.v)));
$("#logout").onclick = async () => { await api("/auth/logout", { method: "POST" }); location.href = "/"; };

async function loadVps() { VPS = (await api("/api/v1/vps")).vps; return VPS; }
async function refreshMe() { ME = await api("/api/v1/me"); }

// ---------- overview ----------
async function vOverview() {
  await Promise.all([loadVps(), refreshMe()]);
  const running = VPS.filter((v) => v.status === "RUNNING").length;
  $("#view").innerHTML = `
    <h1>Hey, <span class="grad">${esc(ME.username)}</span> 👋</h1><p class="sub">Here's what's happening with your servers.</p>
    ${ME.fly.linked ? "" : `<div class="banner">⚠️ Link your Fly.io token to start deploying. <a class="grad2" data-go="fly" style="cursor:pointer;font-weight:600">Link now →</a></div>`}
    <div class="grid g4" style="margin-bottom:22px">
      <div class="card stat"><b class="grad">${VPS.length}<span class="mut" style="font-size:16px"> / ${ME.vps_limit}</span></b><span>Total VPS</span></div>
      <div class="card stat"><b class="grad2">${running}</b><span>Running</span></div>
      <div class="card stat"><b>${ME.fly.linked ? "✅" : "—"}</b><span>Fly.io linked</span></div>
      <div class="card stat"><b>${ME.api_enabled ? "🟢" : "🔒"}</b><span>API access</span></div>
    </div>
    <div class="row" style="margin-bottom:26px"><button class="btn primary" data-go="create">🚀 Create VPS</button><button class="btn" data-go="vps">🖥 My VPS</button></div>
    <div class="card"><h3>💡 What can I run?</h3><p style="margin-top:8px">Every VPS ships with <b>Ubuntu 24.04 + Docker + Compose</b>, root SSH, a persistent <code class="mono">/data</code> disk and ports <code class="mono">22, 80, 443, 2022, 8080</code> open — enough for Pterodactyl, web apps, bots, databases and more. Give it 2 GB+ RAM for Docker workloads.</p></div>`;
}

// ---------- create ----------
async function vCreate() {
  await refreshMe();
  if (!ME.fly.linked) {
    $("#view").innerHTML = `<h1>Create VPS</h1><p class="sub">Deploy a new machine.</p><div class="empty"><div class="big">🔐</div>Link your Fly.io token first.<br><br><button class="btn primary" data-go="fly">Link Fly.io token</button></div>`;
    return;
  }
  $("#view").innerHTML = `<h1>Create VPS</h1><p class="sub">Choose your specs. A random suffix is added to the name so it's unique on Fly.io.</p><div class="mut">Loading options…</div>`;
  try { OPTS = await api("/api/v1/options"); } catch (e) { toast(e.message, "bad"); return; }
  if (!OPTS.regions.some((r) => r.code === sel.region)) sel.region = OPTS.regions[0].code;
  const chips = (arr, key, fmt) => arr.map((x) => `<span class="chip ${sel[key] === x ? "on" : ""}" data-k="${key}" data-val="${x}">${fmt(x)}</span>`).join("");
  $("#view").innerHTML = `
    <h1>Create VPS</h1><p class="sub">Choose your specs. A random suffix is added to the name so it's unique on Fly.io.</p>
    <div class="card" style="max-width:760px">
      <label class="f" style="margin-top:0">Name</label><input id="c-name" maxlength="40" placeholder="my-panel" value="${esc(sel.name)}">
      <label class="f">Region</label><select id="c-region">${OPTS.regions.map((r) => `<option value="${esc(r.code)}" ${r.code === sel.region ? "selected" : ""}>${esc(r.code.toUpperCase())} — ${esc(r.name)}</option>`).join("")}</select>
      <label class="f">CPU</label><div class="chips">${chips(OPTS.cpus, "cpus", (x) => x + " vCPU")}</div>
      <label class="f">RAM <span class="mut">(2 GB+ recommended for Docker / Pterodactyl)</span></label><div class="chips">${chips(OPTS.memory_mb, "memory_mb", gb)}</div>
      <label class="f">Disk volume <span class="mut">(mounted at /data)</span></label><div class="chips">${chips(OPTS.storage_gb, "storage_gb", (x) => x + " GB")}</div>
      <div class="banner" style="margin:22px 0 0">💳 Billed by Fly.io to <b>your</b> account (pay-as-you-go). A dedicated IPv4 may cost extra on Fly.</div>
      <button class="btn primary lg" id="c-go" style="margin-top:20px;width:100%">🚀 Deploy VPS</button>
    </div>`;
  $("#c-name").oninput = (e) => (sel.name = e.target.value);
  $("#c-region").onchange = (e) => (sel.region = e.target.value);
  $("#c-go").onclick = async () => {
    if (!sel.name.trim()) return toast("Give your VPS a name", "bad");
    const b = $("#c-go"); b.disabled = true; b.textContent = "Starting deployment…";
    try {
      await api("/api/v1/vps", { method: "POST", body: { name: sel.name, region: sel.region, cpus: sel.cpus, memory_mb: sel.memory_mb, storage_gb: sel.storage_gb } });
      toast("Deployment started 🚀"); sel.name = ""; go("vps");
    } catch (e) { toast(e.message, "bad"); b.disabled = false; b.textContent = "🚀 Deploy VPS"; }
  };
}

// ---------- my vps ----------
function vpsCard(v) {
  const ip = v.ipv4 ? `<span>IP <b>${esc(v.ipv4)}</b></span>` : "";
  const busy = v.status === "DEPLOYING";
  const last = (v.progress || []).slice(-1)[0] || "";
  return `<div class="card vcard" data-id="${v.id}">
    <h3>${esc(v.name)} <span class="st ${esc(v.status)}">${esc(v.status)}</span></h3>
    <div class="specs"><span><b>${v.cpus}</b> vCPU</span><span><b>${gb(v.memory_mb)}</b> RAM</span><span><b>${v.storage_gb} GB</b> disk</span><span>📍 <b>${esc(v.region.toUpperCase())}</b></span>${ip}</div>
    ${busy ? `<div class="mut mono" style="font-size:12.5px;margin-bottom:14px">${esc(last)}</div>` : ""}
    ${v.status === "FAILED" && v.error ? `<div class="banner" style="border-color:rgba(255,84,112,.4);background:rgba(255,84,112,.07)">${esc(v.error)}</div>` : ""}
    <div class="row">
      <button class="btn sm primary" data-act="details" data-id="${v.id}">Details</button>
      ${busy || v.status === "FAILED" ? "" : `<button class="btn sm" data-act="start" data-id="${v.id}">▶ Start</button><button class="btn sm" data-act="stop" data-id="${v.id}">⏹ Stop</button><button class="btn sm" data-act="restart" data-id="${v.id}">🔄 Restart</button><button class="btn sm ghost" data-act="refresh" data-id="${v.id}">↻</button>`}
      ${busy ? "" : `<button class="btn sm danger" data-act="del" data-id="${v.id}">🗑 Delete</button>`}
    </div></div>`;
}

async function vVps() {
  const draw = async () => {
    if (view !== "vps") return;
    await loadVps();
    $("#view").innerHTML = `<div class="row between"><div><h1>My VPS</h1><p class="sub" style="margin-bottom:18px">${VPS.length} machine${VPS.length === 1 ? "" : "s"}</p></div><button class="btn primary" data-go="create">🚀 New VPS</button></div>
      <div class="grid" style="gap:16px">${VPS.length ? VPS.map(vpsCard).join("") : `<div class="empty"><div class="big">🖥</div>No servers yet.<br><br><button class="btn primary" data-go="create">Create your first VPS</button></div>`}</div>`;
    if (!VPS.some((v) => v.status === "DEPLOYING") && pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  };
  await draw();
  if (VPS.some((v) => v.status === "DEPLOYING")) pollTimer = setInterval(draw, 5000);
}

function openModal(html) { $("#modalbox").innerHTML = html; $("#modal").classList.add("on"); }
function closeModal() { $("#modal").classList.remove("on"); clearInterval(window._mt); }
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal" || e.target.closest("[data-close]")) closeModal(); });

function kv(k, val, copy = true) {
  return `<div class="k">${k}</div><code>${esc(val ?? "—")}</code>${copy && val ? `<button class="btn sm" data-copy="${esc(val)}">Copy</button>` : "<span></span>"}`;
}
async function showDetails(id) {
  const draw = async () => {
    let v; try { v = await api("/api/v1/vps/" + id); } catch (e) { toast(e.message, "bad"); closeModal(); return; }
    const ready = v.status !== "DEPLOYING" && v.status !== "FAILED";
    openModal(`<div class="row between"><h2 class="mono">${esc(v.name)} <span class="st ${esc(v.status)}">${esc(v.status)}</span></h2><button class="btn sm ghost" data-close>✕</button></div>
      ${ready ? `<div class="kv">${kv("Host", v.ssh.host)}${kv("Port", String(v.ssh.port))}${kv("User", v.ssh.user)}${kv("Password", v.ssh.password)}${kv("SSH command", v.ssh_command)}${kv("IPv6", v.ipv6)}${kv("Region", v.region.toUpperCase(), false)}${kv("Machine", v.machine_id)}</div>
      <div class="banner good" style="margin-top:18px">🐳 Docker is preinstalled. First boot installs packages for 2–5 min — if SSH refuses, wait a minute and retry. Disk is mounted at <b class="mono">/data</b> (Docker data lives there). Open ports: 22, 80, 443, 2022, 8080.</div>` : ""}
      ${v.error ? `<div class="banner" style="border-color:rgba(255,84,112,.4)">${esc(v.error)}</div>` : ""}
      <h3 style="margin:18px 0 8px;font-size:15px">Deployment log</h3><div class="log" id="logbox">${esc((v.progress || []).join("\n"))}</div>`);
    const lb = $("#logbox"); if (lb) lb.scrollTop = lb.scrollHeight;
    if (v.status === "DEPLOYING") window._mt = setTimeout(draw, 4000);
  };
  clearInterval(window._mt); await draw();
}

document.addEventListener("click", async (e) => {
  const g = e.target.closest("[data-go]"); if (g) return go(g.dataset.go);
  const b = e.target.closest("[data-act]"); if (!b) return;
  const id = +b.dataset.id, act = b.dataset.act;
  if (act === "details") return showDetails(id);
  if (act === "del") {
    if (!confirm("Delete this VPS and its Fly.io app, machine and volume? This cannot be undone.")) return;
    b.disabled = true;
    try { await api("/api/v1/vps/" + id, { method: "DELETE" }); toast("VPS deleted"); vVps(); } catch (er) { toast(er.message, "bad"); b.disabled = false; }
    return;
  }
  b.disabled = true;
  try {
    await api(`/api/v1/vps/${id}/${act}`, { method: "POST" });
    toast(act === "refresh" ? "Refreshed" : act[0].toUpperCase() + act.slice(1) + " sent ✓");
    if (act !== "refresh") await new Promise((r) => setTimeout(r, 3500)), await api(`/api/v1/vps/${id}/refresh`, { method: "POST" }).catch(() => {});
    vVps();
  } catch (er) { toast(er.message, "bad"); b.disabled = false; }
});

// ---------- fly account ----------
async function vFly() {
  await refreshMe(); const f = ME.fly;
  $("#view").innerHTML = `<h1>Fly.io Account</h1><p class="sub">Your machines are created on <b>your</b> Fly.io account using your token.</p>
    ${f.linked ? `<div class="banner good">✅ Linked — <b>${esc(f.email || "unknown email")}</b> · org <b>${esc(f.organization || "—")}</b> (<span class="mono">${esc(f.org_slug || "—")}</span>)</div>` : `<div class="banner">No token linked yet.</div>`}
    <div class="card" style="max-width:700px">
      <h3>${f.linked ? "Replace token" : "Link your token"}</h3>
      <p style="margin:8px 0 4px">Create a token at <a class="grad2" href="https://fly.io/user/personal_access_tokens" target="_blank" rel="noopener">fly.io/user/personal_access_tokens</a> (or run <code class="mono">fly tokens create org</code>). It needs permission to create apps &amp; machines.</p>
      <label class="f">Fly.io API token</label><input id="ft" type="password" autocomplete="off" placeholder="FlyV1 fm2_… or fo1_…">
      <div class="row" style="margin-top:16px"><button class="btn primary" id="ft-go">Validate &amp; save</button>${f.linked ? `<button class="btn danger" id="ft-del">Unlink token</button>` : ""}</div>
      <p class="mut" style="font-size:12.5px;margin-top:14px">🔒 Encrypted at rest, never displayed again, and never available through the API.</p>
    </div>`;
  $("#ft-go").onclick = async () => {
    const t = $("#ft").value.trim(); if (!t) return toast("Paste your token", "bad");
    const b = $("#ft-go"); b.disabled = true; b.textContent = "Validating…";
    try { await api("/api/v1/fly/token", { method: "POST", body: { token: t } }); toast("Fly.io linked ✓"); vFly(); }
    catch (e) { toast(e.message, "bad"); b.disabled = false; b.textContent = "Validate & save"; }
  };
  const d = $("#ft-del"); if (d) d.onclick = async () => { if (confirm("Unlink your Fly.io token? Existing machines keep running on Fly.")) { await api("/api/v1/fly", { method: "DELETE" }); toast("Unlinked"); vFly(); } };
}

// ---------- api ----------
async function vApi() {
  await refreshMe(); const base = location.origin;
  const locked = !ME.api_enabled;
  $("#view").innerHTML = `<h1>API Access</h1><p class="sub">Build your own VPS creation app on top of this platform.</p>
    ${locked ? `<div class="banner">🔒 <b>API access is locked for your account.</b> Message the owner <a class="grad2" href="https://t.me/${esc(ME.owner_telegram)}" target="_blank" rel="noopener"><b>@${esc(ME.owner_telegram)}</b></a> on Telegram with your username <span class="mono">${esc(ME.username)}</span> to request access. You'll receive an API key.</div>`
      : `<div class="banner good">🟢 <b>API access enabled.</b> Use the API key the owner gave you. ${ME.api_keys.length ? "" : `You don't have a key yet — ask <b>@${esc(ME.owner_telegram)}</b>.`}</div>`}
    ${ME.api_keys.length ? `<div class="card" style="margin-bottom:18px"><h3>Your keys</h3>${ME.api_keys.map((k) => `<div class="row between" style="margin-top:10px"><code class="mono">${esc(k.prefix)}…</code><span class="mut" style="font-size:13px">${esc(k.label || "")} · last used ${esc(ago(k.last_used))}</span></div>`).join("")}<p class="mut" style="font-size:12.5px;margin-top:12px">Full keys are shown only once, when the owner creates them.</p></div>` : ""}
    <div class="card"><h3>Quick start</h3><p style="margin:6px 0 14px">Link your Fly token in the dashboard first — the API deploys with it.</p>
<pre class="code"><span class="c"># who am I</span>
curl ${esc(base)}/api/v1/me -H <span class="s">"Authorization: Bearer kx_YOUR_KEY"</span>

<span class="c"># create a VPS</span>
curl -X POST ${esc(base)}/api/v1/vps \\
  -H <span class="s">"Authorization: Bearer kx_YOUR_KEY"</span> -H <span class="s">"Content-Type: application/json"</span> \\
  -d <span class="s">'{"name":"my-panel","region":"iad","cpus":2,"memory_mb":4096,"storage_gb":20}'</span></pre>
      <div class="row" style="margin-top:16px"><a class="btn primary" href="/docs">Full API reference →</a></div></div>`;
}

boot();
