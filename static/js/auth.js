let mode = location.pathname === "/register" ? "reg" : "login";
function setMode(m) {
  mode = m;
  $("#t-login").classList.toggle("on", m === "login"); $("#t-reg").classList.toggle("on", m === "reg");
  $("#tgrow").style.display = m === "reg" ? "block" : "none";
  $("#ttl").textContent = m === "reg" ? "Create your account 🚀" : "Welcome back 👋";
  $("#sub").textContent = m === "reg" ? "Takes 10 seconds. Password must be 8+ characters." : "Sign in to manage your VPS machines.";
  $("#go").textContent = m === "reg" ? "Create account" : "Login";
  $("#p").autocomplete = m === "reg" ? "new-password" : "current-password";
  $("#err").textContent = "";
  history.replaceState(null, "", m === "reg" ? "/register" : "/login");
}
$("#t-login").onclick = () => setMode("login");
$("#t-reg").onclick = () => setMode("reg");
async function submit() {
  const btn = $("#go"); $("#err").textContent = ""; btn.disabled = true;
  try {
    const body = { username: $("#u").value.trim(), password: $("#p").value };
    if (mode === "reg") body.telegram = $("#tg").value.trim() || null;
    await api(mode === "reg" ? "/auth/register" : "/auth/login", { method: "POST", body });
    location.href = "/dashboard";
  } catch (e) { $("#err").textContent = e.message; }
  btn.disabled = false;
}
$("#go").onclick = submit;
["u", "p", "tg"].forEach((id) => $("#" + id).addEventListener("keydown", (e) => e.key === "Enter" && submit()));
setMode(mode);
api("/api/v1/me").then(() => (location.href = "/dashboard")).catch(() => {});
