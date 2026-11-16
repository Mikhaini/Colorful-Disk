"""Colorful Disk - protótipo de diário de música (estilo Letterboxd). Flask + SQLite."""
import os
import sqlite3
import uuid
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "colorfuldisk.db")

app = Flask(__name__, static_folder=None)
UPLOADS = os.path.join(BASE, "uploads")
os.makedirs(UPLOADS, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB por imagem
app.secret_key = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  kind TEXT NOT NULL CHECK(kind IN ('musica','album')),
  title TEXT NOT NULL, artist TEXT NOT NULL, year INTEGER, genre TEXT, cover TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS ratings(
  user_id INTEGER NOT NULL, item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5),
  PRIMARY KEY(user_id, item_id));
CREATE TABLE IF NOT EXISTS lists(
  user_id INTEGER NOT NULL, item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK(kind IN ('fav','later')),
  PRIMARY KEY(user_id, item_id, kind));
CREATE TABLE IF NOT EXISTS comments(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  body TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""


SEED = [
 ("album","Abbey Road","The Beatles",1969,"Rock"),
 ("album","Thriller","Michael Jackson",1982,"Pop"),
 ("album","OK Computer","Radiohead",1997,"Rock alternativo"),
 ("album","Kind of Blue","Miles Davis",1959,"Jazz"),
 ("album","Clube da Esquina","Milton Nascimento e Lô Borges",1972,"MPB"),
 ("album","Elis & Tom","Elis Regina e Tom Jobim",1974,"MPB"),
 ("album","Tropicália: ou Panis et Circencis","Vários artistas",1968,"Tropicália"),
 ("album","To Pimp a Butterfly","Kendrick Lamar",2015,"Hip hop"),
 ("album","Random Access Memories","Daft Punk",2013,"Eletrônica"),
 ("album","Rumours","Fleetwood Mac",1977,"Rock"),
 ("album","Persona 5 Original Soundtrack","Shoji Meguro",2016,"Trilha sonora"),
 ("musica","Bohemian Rhapsody","Queen",1975,"Rock"),
 ("musica","Billie Jean","Michael Jackson",1982,"Pop"),
 ("musica","Garota de Ipanema","Tom Jobim e Vinicius de Moraes",1962,"Bossa nova"),
 ("musica","Smells Like Teen Spirit","Nirvana",1991,"Grunge"),
 ("musica","Águas de Março","Tom Jobim",1972,"MPB"),
 ("musica","Last Surprise","Lyn",2016,"Trilha sonora"),
]


def seed():
    """Cadastra itens de exemplo uma única vez, em nome do usuário 'Colorful Disk'."""
    with sqlite3.connect(DB) as c:
        if c.execute("SELECT 1 FROM users WHERE username='Colorful Disk'").fetchone():
            return
        uid = c.execute("INSERT INTO users(username,password) VALUES(?,?)",
                        ("Colorful Disk", generate_password_hash(os.urandom(16).hex()))).lastrowid
        c.executemany("INSERT INTO items(user_id,kind,title,artist,year,genre,cover) VALUES(?,?,?,?,?,?,'')",
                      [(uid, *row) for row in SEED])


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def init_db():
    with sqlite3.connect(DB) as c:
        c.executescript(SCHEMA)
        for stmt in ("ALTER TABLE items ADD COLUMN tracks TEXT", "ALTER TABLE users ADD COLUMN avatar TEXT"):
            try:  # migração: ignora se a coluna já existe
                c.execute(stmt)
            except sqlite3.OperationalError:
                pass


def save_image(f):
    """Salva a imagem enviada (confere o conteúdo, não só a extensão) e devolve a URL."""
    head = f.stream.read(12)
    f.stream.seek(0)
    if head.startswith(b"\xff\xd8\xff"):
        ext = ".jpg"
    elif head.startswith(b"\x89PNG"):
        ext = ".png"
    elif head.startswith(b"GIF8"):
        ext = ".gif"
    elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        ext = ".webp"
    else:
        return None
    name = uuid.uuid4().hex + ext
    f.save(os.path.join(UPLOADS, name))
    return "/uploads/" + name


def remove_upload(url):
    if url and url.startswith("/uploads/"):
        try:
            os.remove(os.path.join(UPLOADS, os.path.basename(url)))
        except OSError:
            pass


@app.errorhandler(413)
def too_big(_):
    return jsonify(error="Imagem muito grande (máximo 8 MB)."), 413


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if "uid" not in session:
            return jsonify(error="Faça login para continuar."), 401
        return fn(*a, **kw)
    return wrapper


def err(msg, code=400):
    return jsonify(error=msg), code


def clean_item(d):
    title, artist = (d.get("title") or "").strip(), (d.get("artist") or "").strip()
    kind = d.get("kind")
    if kind not in ("musica", "album"):
        return None, "Escolha o tipo: música ou álbum."
    if not title or not artist:
        return None, "Título e artista são obrigatórios."
    try:
        year = int(d["year"]) if d.get("year") else None
    except ValueError:
        return None, "Ano inválido."
    if year is not None and not 1900 <= year <= 2100:
        return None, "Ano deve estar entre 1900 e 2100."
    cover = (d.get("cover") or "").strip()[:500]
    if cover and not cover.startswith(("http://", "https://", "/uploads/")):
        cover = ""
    return (kind, title[:150], artist[:150], year, (d.get("genre") or "").strip()[:60],
            cover, (d.get("tracks") or "").strip()[:3000]), None


# ---------- autenticação ----------
@app.post("/api/register")
def register():
    d = request.get_json(silent=True) or {}
    u, p = (d.get("username") or "").strip(), d.get("password") or ""
    if len(u) < 3 or len(p) < 6:
        return err("Usuário: mín. 3 caracteres. Senha: mín. 6.")
    try:
        cur = db().execute("INSERT INTO users(username,password) VALUES(?,?)",
                           (u, generate_password_hash(p)))
        db().commit()
    except sqlite3.IntegrityError:
        return err("Este nome de usuário já existe.", 409)
    session["uid"], session["username"] = cur.lastrowid, u
    return jsonify(id=cur.lastrowid, username=u), 201


@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    row = db().execute("SELECT * FROM users WHERE username=?",
                       ((d.get("username") or "").strip(),)).fetchone()
    if not row or not check_password_hash(row["password"], d.get("password") or ""):
        return err("Usuário ou senha incorretos.", 401)
    session["uid"], session["username"] = row["id"], row["username"]
    return jsonify(id=row["id"], username=row["username"])


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def me():
    if "uid" not in session:
        return jsonify(user=None)
    row = db().execute("SELECT avatar FROM users WHERE id=?", (session["uid"],)).fetchone()
    return jsonify(user={"id": session["uid"], "username": session["username"],
                         "avatar": row["avatar"] if row else None})


# ---------- músicas / álbuns ----------
ITEM_SQL = """
SELECT i.*, u.username AS owner,
  (SELECT ROUND(AVG(stars),1) FROM ratings WHERE item_id=i.id) AS avg,
  (SELECT COUNT(*) FROM ratings WHERE item_id=i.id) AS votes,
  (SELECT COUNT(*) FROM comments WHERE item_id=i.id) AS comments
FROM items i JOIN users u ON u.id=i.user_id"""


@app.get("/api/items")
def list_items():
    q, kind = f"%{request.args.get('q', '').strip()}%", request.args.get("kind", "")
    sql = ITEM_SQL + " WHERE (i.title LIKE ? OR i.artist LIKE ? OR i.genre LIKE ?)"
    args = [q, q, q]
    if kind in ("musica", "album"):
        sql += " AND i.kind=?"
        args.append(kind)
    order = {"top": "avg DESC, votes DESC", "comments": "comments DESC",
             "az": "i.title COLLATE NOCASE"}.get(request.args.get("sort"), "i.id DESC")
    rows = db().execute(sql + " ORDER BY " + order, args).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/items")
@login_required
def create_item():
    vals, e = clean_item(request.get_json(silent=True) or {})
    if e:
        return err(e)
    cur = db().execute("INSERT INTO items(user_id,kind,title,artist,year,genre,cover,tracks)"
                       " VALUES(?,?,?,?,?,?,?,?)", (session["uid"], *vals))
    db().commit()
    return jsonify(id=cur.lastrowid), 201


@app.get("/api/items/<int:iid>")
def get_item(iid):
    row = db().execute(ITEM_SQL + " WHERE i.id=?", (iid,)).fetchone()
    if not row:
        return err("Item não encontrado.", 404)
    item = dict(row)
    item["my_rating"] = None
    if "uid" in session:
        r = db().execute("SELECT stars FROM ratings WHERE user_id=? AND item_id=?",
                         (session["uid"], iid)).fetchone()
        item["my_rating"] = r["stars"] if r else None
    item["my_lists"] = [r["kind"] for r in db().execute(
        "SELECT kind FROM lists WHERE user_id=? AND item_id=?", (session["uid"], iid))] if "uid" in session else []
    item["comments_list"] = [dict(c) for c in db().execute(
        "SELECT c.id,c.user_id,c.body,c.created_at,u.username FROM comments c "
        "JOIN users u ON u.id=c.user_id WHERE c.item_id=? ORDER BY c.id DESC", (iid,))]
    return jsonify(item)


def owned_item(iid):
    row = db().execute("SELECT user_id FROM items WHERE id=?", (iid,)).fetchone()
    if not row:
        return None, err("Item não encontrado.", 404)
    if row["user_id"] != session["uid"]:
        return None, err("Só quem cadastrou pode alterar este item.", 403)
    return row, None


@app.put("/api/items/<int:iid>")
@login_required
def update_item(iid):
    _, e = owned_item(iid)
    if e:
        return e
    vals, msg = clean_item(request.get_json(silent=True) or {})
    if msg:
        return err(msg)
    old = db().execute("SELECT cover FROM items WHERE id=?", (iid,)).fetchone()["cover"]
    db().execute("UPDATE items SET kind=?,title=?,artist=?,year=?,genre=?,cover=?,tracks=? WHERE id=?",
                 (*vals, iid))
    db().commit()
    if old != vals[5]:
        remove_upload(old)
    return jsonify(ok=True)


@app.delete("/api/items/<int:iid>")
@login_required
def delete_item(iid):
    _, e = owned_item(iid)
    if e:
        return e
    old = db().execute("SELECT cover FROM items WHERE id=?", (iid,)).fetchone()["cover"]
    db().execute("DELETE FROM items WHERE id=?", (iid,))
    db().commit()
    remove_upload(old)
    return jsonify(ok=True)


# ---------- envio de fotos ----------
@app.get("/uploads/<name>")
def uploaded(name):
    return send_from_directory(UPLOADS, name)


def read_upload():
    f = request.files.get("file")
    url = save_image(f) if f else None
    return url, (None if url else "Envie uma imagem JPG, PNG, GIF ou WEBP.")


@app.post("/api/upload")
@login_required
def upload():
    url, e = read_upload()
    return (err(e), 400)[0] if e else jsonify(url=url)


@app.post("/api/me/avatar")
@login_required
def set_avatar():
    url, e = read_upload()
    if e:
        return err(e)
    old = db().execute("SELECT avatar FROM users WHERE id=?", (session["uid"],)).fetchone()["avatar"]
    db().execute("UPDATE users SET avatar=? WHERE id=?", (url, session["uid"]))
    db().commit()
    remove_upload(old)
    return jsonify(url=url)


# ---------- favoritos, "ouvir depois" e perfil ----------
@app.post("/api/items/<int:iid>/list")
@login_required
def toggle_list(iid):
    kind = (request.get_json(silent=True) or {}).get("kind")
    if kind not in ("fav", "later"):
        return err("Lista inválida.")
    if not db().execute("SELECT 1 FROM items WHERE id=?", (iid,)).fetchone():
        return err("Item não encontrado.", 404)
    cur = db().execute("DELETE FROM lists WHERE user_id=? AND item_id=? AND kind=?", (session["uid"], iid, kind))
    if cur.rowcount == 0:
        db().execute("INSERT INTO lists(user_id,item_id,kind) VALUES(?,?,?)", (session["uid"], iid, kind))
    db().commit()
    return jsonify(on=cur.rowcount == 0)


@app.get("/api/me/lists")
@login_required
def my_lists():
    uid = session["uid"]

    def get(join, where, *args):
        return [dict(r) for r in db().execute(ITEM_SQL + join + " WHERE " + where + " ORDER BY i.id DESC", args)]
    j = " JOIN lists l ON l.item_id=i.id"
    rated = get(" JOIN ratings r ON r.item_id=i.id", "r.user_id=?", uid)
    avg = db().execute("SELECT ROUND(AVG(stars),1) a FROM ratings WHERE user_id=?", (uid,)).fetchone()["a"]
    return jsonify(fav=get(j, "l.user_id=? AND l.kind='fav'", uid),
                   later=get(j, "l.user_id=? AND l.kind='later'", uid),
                   rated=rated, mine=get("", "i.user_id=?", uid), avg=avg)


# ---------- avaliações e comentários ----------
@app.post("/api/items/<int:iid>/rating")
@login_required
def rate(iid):
    try:
        stars = int((request.get_json(silent=True) or {}).get("stars"))
    except (TypeError, ValueError):
        return err("Nota inválida.")
    if not 1 <= stars <= 5:
        return err("A nota vai de 1 a 5.")
    if not db().execute("SELECT 1 FROM items WHERE id=?", (iid,)).fetchone():
        return err("Item não encontrado.", 404)
    db().execute("INSERT INTO ratings(user_id,item_id,stars) VALUES(?,?,?) "
                 "ON CONFLICT(user_id,item_id) DO UPDATE SET stars=excluded.stars",
                 (session["uid"], iid, stars))
    db().commit()
    return jsonify(ok=True)


@app.delete("/api/items/<int:iid>/rating")
@login_required
def unrate(iid):
    cur = db().execute("DELETE FROM ratings WHERE user_id=? AND item_id=?", (session["uid"], iid))
    db().commit()
    if cur.rowcount == 0:
        return err("Você ainda não avaliou este item.", 404)
    return jsonify(ok=True)


@app.post("/api/items/<int:iid>/comments")
@login_required
def add_comment(iid):
    body = ((request.get_json(silent=True) or {}).get("body") or "").strip()
    if not body:
        return err("Escreva algo antes de publicar.")
    if not db().execute("SELECT 1 FROM items WHERE id=?", (iid,)).fetchone():
        return err("Item não encontrado.", 404)
    db().execute("INSERT INTO comments(user_id,item_id,body) VALUES(?,?,?)",
                 (session["uid"], iid, body[:1000]))
    db().commit()
    return jsonify(ok=True), 201


@app.delete("/api/comments/<int:cid>")
@login_required
def delete_comment(cid):
    row = db().execute("SELECT user_id FROM comments WHERE id=?", (cid,)).fetchone()
    if not row:
        return err("Comentário não encontrado.", 404)
    if row["user_id"] != session["uid"]:
        return err("Você só pode excluir seus próprios comentários.", 403)
    db().execute("DELETE FROM comments WHERE id=?", (cid,))
    db().commit()
    return jsonify(ok=True)


@app.get("/")
@app.get("/<any(style.css, app.js):name>")
def static_files(name="index.html"):
    return send_from_directory(BASE, name)


init_db()
seed()
if __name__ == "__main__":
    app.run(debug=True, port=5000)
