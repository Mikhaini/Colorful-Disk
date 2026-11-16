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

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.id); toast.id = setTimeout(() => t.classList.remove("show"), 2400);
}

function hue(it) { let h = 0; for (const c of it.title + it.artist) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }
function cover(it) {
  if (it.cover) return `<img class="cover" src="${esc(it.cover)}" alt="Capa de ${esc(it.title)}" loading="lazy">`;
  const h = hue(it);
  return `<div class="ph" style="background:linear-gradient(135deg,hsl(${h} 80% 58%),hsl(${(h + 70) % 360} 80% 42%))"></div>`;
}

/* ---------- navegação / sessão ---------- */
function renderNav() {
  $("#nav").innerHTML = user
    ? `<span class="who">@${esc(user.username)}</span><button class="primary" id="addBtn">Adicionar</button><button id="outBtn">Sair</button>`
    : `<button id="inBtn" class="primary">Entrar</button>`;
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
    user = await api(authMode === "login" ? "/login" : "/register", "POST", f);
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
  if (it) for (const k of ["kind", "title", "artist", "year", "genre", "cover"]) f.elements[k].value = it[k] ?? "";
  $("#itemDlg").showModal();
}
$("#itemForm").addEventListener("submit", async e => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target));
  try {
    if (editingId) await api(`/items/${editingId}`, "PUT", body);
    else { const r = await api("/items", "POST", body); editingId = r.id; }
    $("#itemDlg").close(); toast("Salvo.");
    location.hash === `#/item/${editingId}` ? route() : (location.hash = `#/item/${editingId}`);
  } catch (err) { $("#itemErr").textContent = err.message; }
});

/* ---------- páginas ---------- */
async function renderHome() {
  app.innerHTML = `
    <section class="hero"><div><h1>O que está girando no seu toca-discos?</h1>
    <p>Cadastre álbuns e músicas, dê sua nota de 1 a 5 e converse sobre eles com outras pessoas.</p>
    ${user ? "" : `<button class="primary big-cta" id="heroCta">Criar minha conta</button>`}</div>
    <div class="hero-disc" aria-hidden="true"></div></section>
    <div class="tools">
      <input id="q" type="search" placeholder="Buscar por título, artista ou gênero" aria-label="Buscar">
      <select id="kind" aria-label="Tipo"><option value="">Todos</option><option value="album">Álbuns</option><option value="musica">Músicas</option></select>
    </div><ul class="grid" id="grid"></ul>`;
  const load = async () => {
    const items = await api(`/items?q=${encodeURIComponent($("#q").value)}&kind=${$("#kind").value}`);
    $("#grid").innerHTML = items.length ? items.map(it => `
      <li><a class="tile" href="#/item/${it.id}">
        <div class="sleeve"><span class="disc" style="--h:${hue(it)}"></span><div class="art">${cover(it)}<span class="badge">${kindLabel(it.kind)}</span></div></div>
        <h3>${esc(it.title)}</h3>
        <div class="sub">${esc(it.artist)}${it.year ? ", " + it.year : ""}</div>
        <div>${it.votes ? `${stars(it.avg)} <span class="sub">${it.avg} (${it.votes})</span>` : `<span class="sub">Sem notas ainda</span>`}</div>
      </a></li>`).join("") : `<li class="empty" style="grid-column:1/-1">Nada por aqui. ${user ? "Use Adicionar para cadastrar o primeiro álbum ou música." : "Entre para cadastrar o primeiro álbum ou música."}</li>`;
  };
  $("#heroCta")?.addEventListener("click", () => openAuth("register"));
  let t; $("#q").oninput = () => { clearTimeout(t); t = setTimeout(load, 250); };
  $("#kind").onchange = load;
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
      <div class="sleeve big"><span class="disc" style="--h:${hue(it)}"></span><div class="art">${cover(it)}</div></div>
      <div>
        <span class="meta">${kindLabel(it.kind)}${it.genre ? " · " + esc(it.genre) : ""}${it.year ? " · " + it.year : ""}</span>
        <h1>${esc(it.title)}</h1>
        <div class="meta">${esc(it.artist)} — cadastrado por @${esc(it.owner)}</div>
        ${mine ? `<div class="actions"><button id="editBtn">Editar</button><button id="delBtn" class="danger">Excluir</button></div>` : ""}
        <div class="panel">
          <h2>Avaliação</h2>
          <div>${it.votes ? `<span class="avg">${it.avg}</span> ${stars(it.avg)} <span class="meta">${it.votes} ${it.votes > 1 ? "avaliações" : "avaliação"}</span>` : `<span class="meta">Ninguém avaliou ainda.</span>`}</div>
          <p class="meta" style="margin:.8rem 0 .2rem">${user ? "Sua nota" : "Entre para avaliar"}</p>
          <div class="rate" role="group" aria-label="Sua nota">${[1,2,3,4,5].map(n => `<button data-n="${n}" class="${it.my_rating >= n ? "on" : ""}" aria-label="${n} estrela${n > 1 ? "s" : ""}">★</button>`).join("")}</div>
        </div>
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
  $("#editBtn")?.addEventListener("click", () => openItemDialog(it));
  $("#delBtn")?.addEventListener("click", guard(async () => {
    if (!confirm(`Excluir "${it.title}"? Notas e comentários também serão apagados.`)) return;
    await api(`/items/${id}`, "DELETE"); toast("Excluído."); location.hash = "#/";
  }));
  document.querySelectorAll(".rate button").forEach(b => b.onclick = guard(async () => {
    if (!user) return openAuth("login");
    await api(`/items/${id}/rating`, "POST", {stars: +b.dataset.n}); renderItem(id); toast("Nota salva.");
  }));
  $("#cSend")?.addEventListener("click", guard(async () => {
    await api(`/items/${id}/comments`, "POST", {body: $("#cBody").value}); renderItem(id); toast("Comentário publicado.");
  }));
  document.querySelectorAll("[data-del]").forEach(b => b.onclick = guard(async () => {
    await api(`/comments/${b.dataset.del}`, "DELETE"); renderItem(id); toast("Comentário excluído.");
  }));
}

function route() {
  const m = location.hash.match(/^#\/item\/(\d+)/);
  m ? renderItem(m[1]) : renderHome();
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
(async () => { user = (await api("/me")).user; renderNav(); route(); })();
