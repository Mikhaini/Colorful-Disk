"""Colorful Disk - protótipo de diário de música (estilo Letterboxd). Flask + SQLite."""
import os
import sqlite3
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "colorfuldisk.db")

app = Flask(__name__, static_folder=None)
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
CREATE TABLE IF NOT EXISTS comments(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  body TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""


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
    return (kind, title[:150], artist[:150], year,
            (d.get("genre") or "").strip()[:60], (d.get("cover") or "").strip()[:500]), None


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
    return jsonify(user={"id": session["uid"], "username": session["username"]})


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
    rows = db().execute(sql + " ORDER BY i.created_at DESC, i.id DESC", args).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/items")
@login_required
def create_item():
    vals, e = clean_item(request.get_json(silent=True) or {})
    if e:
        return err(e)
    cur = db().execute("INSERT INTO items(user_id,kind,title,artist,year,genre,cover)"
                       " VALUES(?,?,?,?,?,?,?)", (session["uid"], *vals))
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
    db().execute("UPDATE items SET kind=?,title=?,artist=?,year=?,genre=?,cover=? WHERE id=?",
                 (*vals, iid))
    db().commit()
    return jsonify(ok=True)


@app.delete("/api/items/<int:iid>")
@login_required
def delete_item(iid):
    _, e = owned_item(iid)
    if e:
        return e
    db().execute("DELETE FROM items WHERE id=?", (iid,))
    db().commit()
    return jsonify(ok=True)


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
if __name__ == "__main__":
    app.run(debug=True, port=5000)
