$("#yr").textContent = new Date().getFullYear();
// counters
const io = new IntersectionObserver((es) => es.forEach((e) => {
  if (!e.isIntersecting) return; io.unobserve(e.target);
  const t = +e.target.dataset.n; let n = 0; const step = Math.max(1, Math.ceil(t / 30));
  const id = setInterval(() => { n = Math.min(t, n + step); e.target.textContent = n + (t >= 30 ? "+" : ""); if (n >= t) clearInterval(id); }, 30);
}), { threshold: .5 });
$$("[data-n]").forEach((el) => io.observe(el));

// typing terminal
const lines = [
  ["pr", "$ khalidxhost deploy --region iad --cpu 2 --ram 4GB --disk 20GB"],
  ["", ""],
  ["ok", "✓ Validating Fly token"],
  ["ok", "✓ App created"],
  ["ok", "✓ Volume mounted at /data"],
  ["ok", "✓ Machine: 148e3d5f9a1e08"],
  ["ok", "✓ IPv4: 66.241.xxx.xxx"],
  ["", "… Installing OpenSSH + Docker"],
  ["ok", "✓ SSH is answering"],
  ["hi", "🚀 HEY THERE GAY VPS READY  →  ssh root@66.241.xxx.xxx"],
];
const out = $("#term"); let li = 0;
function typeLine() {
  if (li >= lines.length) { out.insertAdjacentHTML("beforeend", '<span class="cur"></span>'); setTimeout(() => { out.innerHTML = ""; li = 0; typeLine(); }, 5000); return; }
  const [cls, text] = lines[li++]; const span = document.createElement("span"); if (cls) span.className = cls;
  out.appendChild(span); let i = 0; const fast = cls !== "pr";
  const id = setInterval(() => { span.textContent += text[i++] || ""; if (i >= text.length) { clearInterval(id); out.appendChild(document.createTextNode("\n")); setTimeout(typeLine, fast ? 380 : 500); } }, fast ? 8 : 28);
}
typeLine();
