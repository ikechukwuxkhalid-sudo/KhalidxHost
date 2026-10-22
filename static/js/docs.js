$("#base").textContent = location.origin;
$$(".u").forEach((el) => (el.textContent = location.origin));
// make the placeholder-relative curl examples show the real base URL
$$("pre.code").forEach((p) => { p.innerHTML = p.innerHTML.replace(/curl -X POST \/api/g, "curl -X POST " + location.origin + "/api"); });
