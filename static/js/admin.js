const AP = "/" + document.querySelector('meta[name="admin-path"]').content + "/api";
let tab = "users";
const A = (p, o) => api(AP + p, o);

async function init() {
  try { await A("/me"); showApp(); } catch (e) { $("#login").style.display = "grid"; $("#pw").focus(); }
}
async function login() {
  $("#err").textContent = ""; $("#go").disabled = true;
  try { await A("/login", { method: "POST", body: { password: $("#pw").value } }); $("#login").style.display = "none"; showApp(); }
  catch (e) { $("#err").textContent = e.message; }
  $("#go").disabled = false;
}
$("#go").onclick = login;
$("#pw").addEventListener("keydown", (e) => e.key === "Enter" && login());
$("#out").onclick = async () => { await A("/logout", { method: "POST" }); location.reload(); };

function showApp() { $("#app").style.display = "block"; stats(); render(); }
async function stats() {
  const s = await A("/stats");
  const c = (n, l, g) => `<div class="card stat"><b class="${g || ""}">${n}</b><span>${l}</span></div>`;
  $("#stats").innerHTML = c(s.users, "Users", "grad") + c(s.api_enabled, "API enabled", "grad2") + c(s.keys, "Active keys") + c(`${s.running}<span class="mut" style="font-size:16px"> / ${s.vps}</span>`, "VPS running") ;
}
$$(".tabs button").forEach((b) => (b.onclick = () => { tab = b.dataset.t; $$(".tabs button").forEach((x) => x.classList.toggle("on", x === b)); render(); }));
const td = (v) => `<td>${v}</td>`;
const tbl = (head, rows) => `<div class="tw"><table class="tbl"><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("") || `<tr><td colspan="${head.length}" class="mut" style="text-align:center;padding:30px">Nothing here yet</td></tr>`}</tbody></table></div>`;

async function render() {
  const P = $("#panel");
  try {
    if (tab === "users") {
      const { users } = await A("/users");
      P.innerHTML = tbl(["User", "Telegram", "API", "Fly", "VPS", "Joined", "Actions"], users.map((u) => `<tr>
        ${td(`<b>${esc(u.username)}</b> ${u.blocked ? '<span class="tag r">BLOCKED</span>' : ""}`)}
        ${td(u.telegram ? `<a class="grad2" href="https://t.me/${esc(u.telegram)}" target="_blank" rel="noopener">@${esc(u.telegram)}</a>` : '<span class="mut">—</span>')}
        ${td(`<label class="sw"><input type="checkbox" data-api="${u.id}" ${u.api_enabled ? "checked" : ""}><span></span></label> <span class="tag">${u.keys} key${u.keys === 1 ? "" : "s"}</span>`)}
        ${td(u.fly_linked ? '<span class="tag g">linked</span>' : '<span class="tag">no</span>')}
        ${td(u.vps)}${td(esc(ago(u.created_at)))}
        ${td(`<div class="row" style="gap:6px;flex-wrap:nowrap"><button class="btn sm primary" data-key="${u.id}" data-name="${esc(u.username)}">🔑 Key</button><button class="btn sm" data-block="${u.id}" data-val="${!u.blocked}">${u.blocked ? "Unblock" : "Block"}</button><button class="btn sm" data-pw="${u.id}" data-name="${esc(u.username)}">Reset pw</button><button class="btn sm danger" data-del="${u.id}" data-name="${esc(u.username)}">Delete</button></div>`)}
      </tr>`));
    } else if (tab === "keys") {
      const { keys } = await A("/keys");
      P.innerHTML = tbl(["User", "Key", "Label", "Created", "Last used", "Status", ""], keys.map((k) => `<tr>${td(`<b>${esc(k.username)}</b>`)}${td(`<code class="mono">${esc(k.prefix)}…</code>`)}${td(esc(k.label || "—"))}${td(esc(ago(k.created_at)))}${td(esc(ago(k.last_used)))}${td(k.revoked ? '<span class="tag r">revoked</span>' : '<span class="tag g">active</span>')}${td(k.revoked ? "" : `<button class="btn sm danger" data-revoke="${k.id}">Revoke</button>`)}</tr>`));
    } else if (tab === "vps") {
      const { vps } = await A("/vps");
      P.innerHTML = tbl(["Name", "Owner", "Status", "Region", "Specs", "IPv4", "Created"], vps.map((v) => `<tr>${td(`<code class="mono">${esc(v.name)}</code>`)}${td(esc(v.owner))}${td(`<span class="st ${esc(v.status)}">${esc(v.status)}</span>`)}${td(esc(v.region.toUpperCase()))}${td(`${v.cpus} vCPU · ${v.memory_mb / 1024} GB · ${v.storage_gb} GB`)}${td(`<code class="mono">${esc(v.ipv4 || "—")}</code>`)}${td(esc(ago(v.created_at)))}</tr>`));
    } else {
      const { logs } = await A("/logs");
      P.innerHTML = tbl(["When", "User", "By", "Action", "Result", "Detail"], logs.map((l) => `<tr>${td(esc(ago(l.time)))}${td(esc(l.user || "—"))}${td(`<span class="tag">${esc(l.actor || "")}</span>`)}${td(`<code class="mono">${esc(l.action)}</code>`)}${td(esc(l.result || ""))}${td(`<span class="mut">${esc(l.detail || "")}</span>`)}</tr>`));
    }
  } catch (e) { if (e.status === 401) location.reload(); else toast(e.message, "bad"); }
}

function modal(html) { $("#modalbox").innerHTML = html; $("#modal").classList.add("on"); }
const closeModal = () => $("#modal").classList.remove("on");
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal" || e.target.closest("[data-close]")) closeModal(); });

document.addEventListener("change", async (e) => {
  const t = e.target.closest("[data-api]"); if (!t) return;
  try { await A(`/users/${t.dataset.api}/api`, { method: "POST", body: { value: t.checked } }); toast(t.checked ? "API access granted ✓" : "API access revoked"); stats(); }
  catch (er) { toast(er.message, "bad"); t.checked = !t.checked; }
});

document.addEventListener("click", async (e) => {
  const b = e.target.closest("button"); if (!b) return;
  try {
    if (b.dataset.key) {
      modal(`<h2>🔑 Generate API key</h2><p class="mut">For <b>${esc(b.dataset.name)}</b>. This also enables API access for the account.</p><label class="f">Label (optional)</label><input id="kl" maxlength="64" placeholder="e.g. panel-bot"><div class="row" style="margin-top:18px"><button class="btn primary" id="kgo" data-uid="${b.dataset.key}">Generate</button><button class="btn" data-close>Cancel</button></div>`);
    } else if (b.id === "kgo") {
      const r = await A(`/users/${b.dataset.uid}/keys`, { method: "POST", body: { label: $("#kl").value.trim() || null } });
      modal(`<h2>✅ Key created for ${esc(r.username)}</h2><div class="banner">⚠️ Copy it now — it will <b>never be shown again</b>. Send it to the user privately (Telegram).</div><div class="codebox" style="word-break:break-all;user-select:all">${esc(r.key)}</div><div class="row" style="margin-top:16px"><button class="btn primary" data-copy="${esc(r.key)}">Copy key</button><button class="btn" data-close>Done</button></div>`);
      stats(); render();
    } else if (b.dataset.block) {
      await A(`/users/${b.dataset.block}/block`, { method: "POST", body: { value: b.dataset.val === "true" } }); toast("Updated"); stats(); render();
    } else if (b.dataset.pw) {
      modal(`<h2>Reset password</h2><p class="mut">New password for <b>${esc(b.dataset.name)}</b> (min 8 chars).</p><input id="np" type="text" placeholder="new password"><div class="row" style="margin-top:18px"><button class="btn primary" id="pwgo" data-uid="${b.dataset.pw}">Save</button><button class="btn" data-close>Cancel</button></div>`);
    } else if (b.id === "pwgo") {
      await A(`/users/${b.dataset.uid}/password`, { method: "POST", body: { password: $("#np").value } }); toast("Password reset ✓"); closeModal();
    } else if (b.dataset.del) {
      if (!confirm(`Delete user "${b.dataset.name}"?\nTheir keys and records are removed. Their Fly.io machines are NOT touched.`)) return;
      await A(`/users/${b.dataset.del}`, { method: "DELETE" }); toast("User deleted"); stats(); render();
    } else if (b.dataset.revoke) {
      if (!confirm("Revoke this API key?")) return;
      await A(`/keys/${b.dataset.revoke}`, { method: "DELETE" }); toast("Key revoked"); stats(); render();
    }
  } catch (er) { toast(er.message, "bad"); }
});

init();
