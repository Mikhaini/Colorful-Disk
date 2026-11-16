const $ = (s, r = document) => r.querySelector(s);
const app = $("#app");
let user = null, authMode = "login", editingId = null;

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const kindLabel = k => (k === "album" ? "Álbum" : "Música");
const stars = n => `<span class="stars" aria-label="${n} de 5">${"★".repeat(Math.round(n))}<span class="off">${"★".repeat(5 - Math.round(n))}</span></span>`;
const fmtDate = d => new Date(d.replace(" ", "T") + "Z").toLocaleDateString("pt-BR");

async function api(path, method = "GET", body) {
  const res = await fetch("/api" + path, {
    method, headers: body ? {"Content-Type": "application/json"} : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Algo deu errado. Tente novamente.");
  return data;
}

// Reduz fotos grandes no navegador antes de enviar (celulares geram arquivos de vários MB)
async function shrink(file, max = 1200) {
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, max / Math.max(bmp.width, bmp.height));
    const cv = document.createElement("canvas");
    cv.width = Math.round(bmp.width * scale); cv.height = Math.round(bmp.height * scale);
    const ctx = cv.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.drawImage(bmp, 0, 0, cv.width, cv.height);
    const blob = await new Promise(r => cv.toBlob(r, "image/jpeg", 0.85));
    return blob && blob.size < file.size ? blob : file;
  } catch { return file; }
}

async function upload(path, file) {
  const fd = new FormData(); fd.append("file", await shrink(file), "foto.jpg");
  let res;
  try { res = await fetch("/api" + path, {method: "POST", body: fd}); }
  catch { throw new Error("Não foi possível enviar. Reinicie o servidor (py app.py) e atualize a página com Ctrl+F5."); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Falha no envio. Reinicie o servidor e atualize a página com Ctrl+F5.");
  return data;
}

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.id); toast.id = setTimeout(() => t.classList.remove("show"), 2400);
}

function hue(it) { let h = 0; for (const c of it.title + it.artist) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }
function cover(it) {
  const ph = `<div class="ph v${hue(it) % 3}"></div>`;
  if (!it.cover) return ph;
  return ph + `<img class="cover" src="${esc(it.cover)}" alt="Capa de ${esc(it.title)}" loading="lazy" onerror="this.remove()">`;
}

/* ---------- navegação / sessão ---------- */
function renderNav() {
  $("#nav").innerHTML = user
    ? `${user.avatar ? `<img class="av" src="${esc(user.avatar)}" alt="">` : ""}<span class="who">@${esc(user.username)}</span><button id="profBtn">Meu perfil</button><button class="primary" id="addBtn">Adicionar</button><button id="outBtn">Sair</button>`
    : `<button id="inBtn" class="primary">Entrar</button>`;
  $("#profBtn")?.addEventListener("click", () => (location.hash = "#/perfil"));
  $("#addBtn")?.addEventListener("click", () => openItemDialog());
  $("#outBtn")?.addEventListener("click", async () => { await api("/logout", "POST"); user = null; renderNav(); route(); toast("Você saiu."); });
  $("#inBtn")?.addEventListener("click", () => openAuth("login"));
}

function openAuth(mode) {
  authMode = mode;
  const reg = mode === "register";
  $("#authTitle").textContent = reg ? "Criar conta" : "Entrar";
  $("#authForm [type=submit]").textContent = reg ? "Criar conta" : "Entrar";
  $("#authSwitch").textContent = reg ? "Já tenho conta" : "Criar conta";
  $("#authErr").textContent = "";
  $("#authDlg").showModal();
}
$("#authSwitch").onclick = () => openAuth(authMode === "login" ? "register" : "login");
document.querySelectorAll("[data-close]").forEach(b => b.onclick = () => b.closest("dialog").close());

$("#authForm").addEventListener("submit", async e => {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  try {
    await api(authMode === "login" ? "/login" : "/register", "POST", f);
    user = (await api("/me")).user;
    $("#authDlg").close(); e.target.reset(); renderNav(); route();
    toast(`Olá, ${user.username}!`);
  } catch (err) { $("#authErr").textContent = err.message; }
});

/* ---------- cadastro / edição ---------- */
function openItemDialog(it) {
  editingId = it?.id ?? null;
  const f = $("#itemForm"); f.reset();
  $("#itemTitle").textContent = it ? "Editar" : "Adicionar";
  $("#itemErr").textContent = "";
  if (it) for (const k of ["kind", "title", "artist", "year", "genre", "cover", "tracks"]) f.elements[k].value = it[k] ?? "";
  $("#itemDlg").showModal();
}
$("#itemForm").addEventListener("submit", async e => {
  e.preventDefault();
  const body = Object.fromEntries([...new FormData(e.target)].filter(([, v]) => typeof v === "string"));
  try {
    const file = e.target.elements.coverFile.files[0];
    if (file) body.cover = (await upload("/upload", file)).url;
    else if (e.target.elements.removeCover.checked) body.cover = "";
    if (editingId) await api(`/items/${editingId}`, "PUT", body);
    else { const r = await api("/items", "POST", body); editingId = r.id; }
    $("#itemDlg").close(); toast("Salvo.");
    location.hash === `#/item/${editingId}` ? route() : (location.hash = `#/item/${editingId}`);
  } catch (err) { $("#itemErr").textContent = err.message; }
});

/* ---------- páginas ---------- */
const tile = it => `
      <li><a class="tile" href="#/item/${it.id}">
        <div class="sleeve"><div class="art">${cover(it)}<span class="badge">${kindLabel(it.kind)}</span></div></div>
        <h3>${esc(it.title)}</h3>
        <div class="sub">${esc(it.artist)}${it.year ? ", " + it.year : ""}</div>
        <div>${it.votes ? `${stars(it.avg)} <span class="sub">${it.avg} (${it.votes})</span>` : `<span class="sub">Sem notas ainda</span>`}</div>
      </a></li>`;

async function renderHome() {
  app.innerHTML = `
    <section class="hero">
      <div class="slab"><h1>O que está na sua playlist?</h1></div>
      <p>Cadastre álbuns e músicas, dê sua nota de 1 a 5 e converse sobre eles com outras pessoas.</p>
      ${user ? "" : `<button class="primary big-cta" id="heroCta">Criar minha conta</button>`}
    </section>
    <div class="tools">
      <input id="q" type="search" placeholder="Buscar por título, artista ou gênero" aria-label="Buscar">
      <select id="sort" aria-label="Ordenar"><option value="">Mais recentes</option><option value="top">Melhor avaliados</option><option value="comments">Mais comentados</option><option value="az">A–Z</option></select>
      <button type="button" id="rndBtn">Surpreenda-me</button>
      <select id="kind" aria-label="Tipo"><option value="">Todos</option><option value="album">Álbuns</option><option value="musica">Músicas</option></select>
    </div><ul class="grid" id="grid"></ul>`;
  const load = async () => {
    const items = await api(`/items?q=${encodeURIComponent($("#q").value)}&kind=${$("#kind").value}&sort=${$("#sort").value}`);
    $("#grid").innerHTML = items.length ? items.map(tile).join("") : `<li class="empty" style="grid-column:1/-1">Nada por aqui. ${user ? "Use Adicionar para cadastrar o primeiro álbum ou música." : "Entre para cadastrar o primeiro álbum ou música."}</li>`;
  };
  $("#heroCta")?.addEventListener("click", () => openAuth("register"));
  let t; $("#q").oninput = () => { clearTimeout(t); t = setTimeout(load, 250); };
  $("#rndBtn").onclick = async () => { const all = await api("/items"); if (all.length) location.hash = "#/item/" + all[Math.floor(Math.random() * all.length)].id; };
  $("#kind").onchange = load; $("#sort").onchange = load;
  load();
}

async function renderItem(id) {
  let it;
  try { it = await api(`/items/${id}`); }
  catch (e) { app.innerHTML = `<p class="empty">${esc(e.message)} <a href="#/">Voltar ao início</a></p>`; return; }
  const mine = user && user.id === it.user_id;
  app.innerHTML = `
    <p><a href="#/">← Todos os itens</a></p>
    <div class="detail">
      <div class="sleeve big"><div class="art">${cover(it)}</div></div>
      <div>
        <span class="meta">${kindLabel(it.kind)}${it.genre ? " · " + esc(it.genre) : ""}${it.year ? " · " + it.year : ""}</span>
        <h1>${esc(it.title)}</h1>
        <div class="meta">${esc(it.artist)} — cadastrado por @${esc(it.owner)}</div>
        ${mine ? `<div class="actions"><button id="editBtn">Editar</button><button id="delBtn" class="danger">Excluir</button></div>` : ""}
        ${user ? `<div class="actions"><button id="favBtn" class="${it.my_lists.includes("fav") ? "primary" : ""}">♥ Favorito</button><button id="laterBtn" class="${it.my_lists.includes("later") ? "primary" : ""}">Ouvir depois</button></div>` : ""}
        <div class="panel">
          <h2>Avaliação</h2>
          <div>${it.votes ? `<span class="avg">${it.avg}</span> ${stars(it.avg)} <span class="meta">${it.votes} ${it.votes > 1 ? "avaliações" : "avaliação"}</span>` : `<span class="meta">Ninguém avaliou ainda.</span>`}</div>
          <p class="meta" style="margin:.8rem 0 .2rem">${user ? "Sua nota" : "Entre para avaliar"}</p>
          <div class="rate" role="group" aria-label="Sua nota">${[1,2,3,4,5].map(n => `<button data-n="${n}" class="${it.my_rating >= n ? "on" : ""}" aria-label="${n} estrela${n > 1 ? "s" : ""}">★</button>`).join("")}</div>
          ${it.my_rating ? `<button id="unrate" class="ghost" style="margin-top:.6rem">Remover minha nota</button>` : ""}
        </div>
        ${it.tracks ? `<div class="panel"><h2>Faixas</h2><ol class="tracks">${it.tracks.split("\n").filter(Boolean).map(t => `<li>${esc(t)}</li>`).join("")}</ol></div>` : ""}
        <div class="panel">
          <h2>Comentários (${it.comments_list.length})</h2>
          ${user ? `<textarea id="cBody" maxlength="1000" placeholder="O que você achou?" aria-label="Comentário"></textarea><button id="cSend" class="primary">Publicar comentário</button>` : `<p class="meta">Entre para comentar.</p>`}
          <div id="cList">${it.comments_list.map(c => `
            <div class="comment"><small><strong>@${esc(c.username)}</strong> em ${fmtDate(c.created_at)}</small>
            ${user && user.id === c.user_id ? `<button class="danger" data-del="${c.id}">Excluir</button>` : ""}
            <p>${esc(c.body)}</p></div>`).join("") || `<p class="meta">Seja a primeira pessoa a comentar.</p>`}</div>
        </div>
      </div>
    </div>`;
  const guard = fn => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message); } };
  for (const [btn, kind] of [["#favBtn", "fav"], ["#laterBtn", "later"]])
    $(btn)?.addEventListener("click", guard(async () => { await api(`/items/${id}/list`, "POST", {kind}); renderItem(id); }));
  $("#editBtn")?.addEventListener("click", () => openItemDialog(it));
  $("#delBtn")?.addEventListener("click", guard(async () => {
    if (!confirm(`Excluir "${it.title}"? Notas e comentários também serão apagados.`)) return;
    await api(`/items/${id}`, "DELETE"); toast("Excluído."); location.hash = "#/";
  }));
  document.querySelectorAll(".rate button").forEach(b => b.onclick = guard(async () => {
    if (!user) return openAuth("login");
    await api(`/items/${id}/rating`, "POST", {stars: +b.dataset.n}); renderItem(id); toast("Nota salva.");
  }));
  $("#unrate")?.addEventListener("click", guard(async () => {
    await api(`/items/${id}/rating`, "DELETE"); renderItem(id); toast("Nota removida.");
  }));
  $("#cSend")?.addEventListener("click", guard(async () => {
    await api(`/items/${id}/comments`, "POST", {body: $("#cBody").value}); renderItem(id); toast("Comentário publicado.");
  }));
  document.querySelectorAll("[data-del]").forEach(b => b.onclick = guard(async () => {
    await api(`/comments/${b.dataset.del}`, "DELETE"); renderItem(id); toast("Comentário excluído.");
  }));
}

async function renderProfile() {
  if (!user) { location.hash = "#/"; return openAuth("login"); }
  const d = await api("/me/lists");
  const tabs = [["fav", "♥ Favoritos"], ["later", "Ouvir depois"], ["rated", "Minhas notas"], ["mine", "Cadastrados por mim"]];
  app.innerHTML = `
    <section class="hero">
      <div class="who-row">${user.avatar ? `<img class="av big" src="${esc(user.avatar)}" alt="Sua foto">` : `<div class="av big">${esc(user.username[0].toUpperCase())}</div>`}
        <label class="photo-btn">Trocar foto<input type="file" id="avFile" accept="image/png,image/jpeg,image/gif,image/webp" hidden></label></div>
      <div class="slab"><h1>@${esc(user.username)}</h1></div>
      <p class="stats">${d.rated.length} avaliações · nota média ${d.avg ?? "—"} · ${d.fav.length} favoritos · ${d.later.length} para ouvir depois</p></section>
    <div class="tabs" role="tablist">${tabs.map(([k, l], i) => `<button role="tab" data-tab="${k}" class="${i ? "" : "on"}">${l} (${d[k].length})</button>`).join("")}</div>
    <ul class="grid" id="grid"></ul>`;
  $("#avFile").onchange = async e => {
    try { await upload("/me/avatar", e.target.files[0]); user = (await api("/me")).user; renderNav(); renderProfile(); toast("Foto atualizada."); }
    catch (err) { toast(err.message); }
  };
  const show = k => {
    document.querySelectorAll(".tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === k));
    $("#grid").innerHTML = d[k].length ? d[k].map(tile).join("") : `<li class="empty" style="grid-column:1/-1">Nada aqui ainda. Abra um álbum ou música e use os botões de favorito, ouvir depois ou a avaliação.</li>`;
  };
  document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => show(b.dataset.tab));
  show("fav");
}

function route() {
  const m = location.hash.match(/^#\/item\/(\d+)/);
  if (m) renderItem(m[1]); else if (location.hash === "#/perfil") renderProfile(); else renderHome();
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
(async () => { user = (await api("/me")).user; renderNav(); route(); })();
