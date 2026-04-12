"""
Database manager – SQLite via aiosqlite.
Compatible Railway (fichier dans le volume) et homelab (fichier local).

Variable d'environnement :
  DB_PATH – chemin vers le fichier SQLite (défaut : /app/data/chained_love.db)

Sur Railway : monter un volume sur /app/data et laisser DB_PATH à sa valeur par défaut,
OU définir DB_PATH manuellement dans les variables d'environnement.
"""
import os
import logging
import aiosqlite

log = logging.getLogger("chained_love.db")

# Par défaut, on écrit dans /app/data/ qui correspond au volume Railway.
# Si DB_PATH est défini dans l'environnement, on l'utilise tel quel.
DB_PATH = os.environ.get("DB_PATH", "/app/data/chained_love.db")

# On s'assure que le dossier parent existe (utile en dev local aussi)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# Connexion globale unique
_db_conn: aiosqlite.Connection = None


async def get_conn() -> aiosqlite.Connection:
    """
    Retourne la connexion globale à la base de données.
    Recrée la connexion si elle est fermée ou invalide.
    """
    global _db_conn
    if _db_conn is None:
        _db_conn = await _open_conn()
    else:
        # Vérifie que la connexion est toujours vivante
        try:
            await _db_conn.execute("SELECT 1")
        except Exception:
            log.warning("Connexion SQLite perdue, reconnexion...")
            try:
                await _db_conn.close()
            except Exception:
                pass
            _db_conn = await _open_conn()
    return _db_conn


async def _open_conn() -> aiosqlite.Connection:
    """Ouvre et configure une nouvelle connexion SQLite."""
    log.info(f"Ouverture de la base de données : {DB_PATH}")
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    return conn


async def close_db():
    """Ferme la connexion à la base de données."""
    global _db_conn
    if _db_conn:
        await _db_conn.close()
        _db_conn = None


# ── Schéma ─────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS pairs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    dom_id      INTEGER NOT NULL,
    sub_id      INTEGER NOT NULL,
    guild_id    INTEGER NOT NULL,
    dom_label   TEXT NOT NULL DEFAULT 'Dominant',
    sub_label   TEXT NOT NULL DEFAULT 'Subordonné',
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(dom_id, sub_id, guild_id)
);

CREATE TABLE IF NOT EXISTS wallets (
    pair_id INTEGER PRIMARY KEY REFERENCES pairs(id) ON DELETE CASCADE,
    points  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tasks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id        INTEGER NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    description    TEXT,
    points         INTEGER NOT NULL DEFAULT 10,
    recurrence     TEXT NOT NULL DEFAULT 'daily',
    requires_proof INTEGER NOT NULL DEFAULT 0,
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS task_completions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    pair_id      INTEGER NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    proof_url    TEXT,
    validated    INTEGER,
    completed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS shop_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id     INTEGER NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    cost        INTEGER NOT NULL DEFAULT 50,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS purchases (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      INTEGER NOT NULL REFERENCES shop_items(id) ON DELETE CASCADE,
    pair_id      INTEGER NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    validated    INTEGER,
    purchased_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS limits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id     INTEGER NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    color       TEXT NOT NULL CHECK (color IN ('green','orange','red')),
    description TEXT,
    created_by  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS safeword_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id      INTEGER NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    triggered_by INTEGER NOT NULL,
    level        TEXT NOT NULL CHECK (level IN ('YELLOW','RED')),
    resolved     INTEGER NOT NULL DEFAULT 0,
    triggered_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS checkins (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id    INTEGER NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    sub_id     INTEGER NOT NULL,
    mood       INTEGER NOT NULL CHECK (mood BETWEEN 1 AND 10),
    note       TEXT,
    checked_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reminder_settings (
    pair_id      INTEGER PRIMARY KEY REFERENCES pairs(id) ON DELETE CASCADE,
    reminders_on INTEGER NOT NULL DEFAULT 1,
    checkin_hour INTEGER NOT NULL DEFAULT 21
);
"""


async def init_db():
    conn = await get_conn()
    await conn.executescript(SCHEMA)
    await conn.commit()
    log.info(f"Schéma initialisé. BDD : {DB_PATH}")


# ── Pairs ──────────────────────────────────────────────────────────────────────

async def create_pair(dom_id, sub_id, guild_id) -> int:
    conn = await get_conn()
    await conn.execute(
        """INSERT INTO pairs (dom_id, sub_id, guild_id)
           VALUES (?, ?, ?)
           ON CONFLICT(dom_id, sub_id, guild_id)
           DO UPDATE SET active=1""",
        (dom_id, sub_id, guild_id),
    )
    cur = await conn.execute(
        "SELECT id FROM pairs WHERE dom_id=? AND sub_id=? AND guild_id=?",
        (dom_id, sub_id, guild_id),
    )
    row = await cur.fetchone()
    pid = row["id"]
    await conn.execute("INSERT OR IGNORE INTO wallets (pair_id) VALUES (?)", (pid,))
    await conn.execute("INSERT OR IGNORE INTO reminder_settings (pair_id) VALUES (?)", (pid,))
    await conn.commit()
    return pid


async def get_pair_by_users(user_a, user_b, guild_id):
    conn = await get_conn()
    cur = await conn.execute(
        """SELECT * FROM pairs WHERE guild_id=? AND active=1
           AND ((dom_id=? AND sub_id=?) OR (dom_id=? AND sub_id=?))""",
        (guild_id, user_a, user_b, user_b, user_a),
    )
    return await cur.fetchone()


async def get_pairs_for_user(user_id, guild_id):
    conn = await get_conn()
    cur = await conn.execute(
        "SELECT * FROM pairs WHERE guild_id=? AND active=1 AND (dom_id=? OR sub_id=?)",
        (guild_id, user_id, user_id),
    )
    return await cur.fetchall()


async def get_pair(pair_id):
    conn = await get_conn()
    cur = await conn.execute("SELECT * FROM pairs WHERE id=?", (pair_id,))
    return await cur.fetchone()


async def dissolve_pair(pair_id):
    conn = await get_conn()
    await conn.execute("UPDATE pairs SET active=0 WHERE id=?", (pair_id,))
    await conn.commit()


# ── Wallets ────────────────────────────────────────────────────────────────────

async def get_balance(pair_id) -> int:
    conn = await get_conn()
    cur = await conn.execute("SELECT points FROM wallets WHERE pair_id=?", (pair_id,))
    row = await cur.fetchone()
    return row["points"] if row else 0


async def add_points(pair_id, amount):
    conn = await get_conn()
    await conn.execute("UPDATE wallets SET points=points+? WHERE pair_id=?", (amount, pair_id))
    await conn.commit()


async def deduct_points(pair_id, amount) -> bool:
    conn = await get_conn()
    cur = await conn.execute("SELECT points FROM wallets WHERE pair_id=?", (pair_id,))
    row = await cur.fetchone()
    if not row or row["points"] < amount:
        return False
    await conn.execute("UPDATE wallets SET points=points-? WHERE pair_id=?", (amount, pair_id))
    await conn.commit()
    return True


# ── Tasks ──────────────────────────────────────────────────────────────────────

async def create_task(pair_id, name, description, points, recurrence, requires_proof) -> int:
    conn = await get_conn()
    cur = await conn.execute(
        """INSERT INTO tasks (pair_id,name,description,points,recurrence,requires_proof)
           VALUES (?,?,?,?,?,?)""",
        (pair_id, name, description, points, recurrence, 1 if requires_proof else 0),
    )
    await conn.commit()
    return cur.lastrowid


async def get_tasks(pair_id):
    conn = await get_conn()
    cur = await conn.execute(
        "SELECT * FROM tasks WHERE pair_id=? AND active=1 ORDER BY id", (pair_id,)
    )
    return await cur.fetchall()


async def get_task(task_id):
    conn = await get_conn()
    cur = await conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
    return await cur.fetchone()


async def delete_task(task_id):
    conn = await get_conn()
    await conn.execute("UPDATE tasks SET active=0 WHERE id=?", (task_id,))
    await conn.commit()


async def add_completion(task_id, pair_id, proof_url=None) -> int:
    conn = await get_conn()
    cur = await conn.execute(
        "INSERT INTO task_completions (task_id,pair_id,proof_url) VALUES (?,?,?)",
        (task_id, pair_id, proof_url),
    )
    await conn.commit()
    return cur.lastrowid


async def validate_completion(completion_id, validated: bool):
    conn = await get_conn()
    await conn.execute(
        "UPDATE task_completions SET validated=? WHERE id=?",
        (1 if validated else 0, completion_id),
    )
    await conn.commit()


async def get_weekly_stats(pair_id):
    conn = await get_conn()
    cur = await conn.execute(
        """SELECT
            SUM(CASE WHEN validated=1 THEN 1 ELSE 0 END)  AS done,
            SUM(CASE WHEN validated IS NULL THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN validated=0 THEN 1 ELSE 0 END)  AS refused
           FROM task_completions
           WHERE pair_id=?
           AND completed_at >= datetime('now', '-7 days')""",
        (pair_id,),
    )
    return await cur.fetchone()


# ── Shop ───────────────────────────────────────────────────────────────────────

async def create_shop_item(pair_id, name, description, cost) -> int:
    conn = await get_conn()
    cur = await conn.execute(
        "INSERT INTO shop_items (pair_id,name,description,cost) VALUES (?,?,?,?)",
        (pair_id, name, description, cost),
    )
    await conn.commit()
    return cur.lastrowid


async def get_shop_items(pair_id):
    conn = await get_conn()
    cur = await conn.execute(
        "SELECT * FROM shop_items WHERE pair_id=? AND active=1 ORDER BY cost", (pair_id,)
    )
    return await cur.fetchall()


async def create_purchase(item_id, pair_id) -> int:
    conn = await get_conn()
    cur = await conn.execute(
        "INSERT INTO purchases (item_id,pair_id) VALUES (?,?)", (item_id, pair_id)
    )
    await conn.commit()
    return cur.lastrowid


async def validate_purchase(purchase_id, validated: bool):
    conn = await get_conn()
    await conn.execute(
        "UPDATE purchases SET validated=? WHERE id=?",
        (1 if validated else 0, purchase_id),
    )
    await conn.commit()


async def get_purchase(purchase_id):
    conn = await get_conn()
    cur = await conn.execute(
        """SELECT p.*, si.cost, si.name AS item_name
           FROM purchases p JOIN shop_items si ON si.id=p.item_id
           WHERE p.id=?""",
        (purchase_id,),
    )
    return await cur.fetchone()


# ── Limits ─────────────────────────────────────────────────────────────────────

async def add_limit(pair_id, name, color, description, created_by) -> int:
    conn = await get_conn()
    cur = await conn.execute(
        "INSERT INTO limits (pair_id,name,color,description,created_by) VALUES (?,?,?,?,?)",
        (pair_id, name, color, description, created_by),
    )
    await conn.commit()
    return cur.lastrowid


async def get_limits(pair_id):
    conn = await get_conn()
    cur = await conn.execute(
        "SELECT * FROM limits WHERE pair_id=? ORDER BY color, name", (pair_id,)
    )
    return await cur.fetchall()


async def delete_limit(limit_id):
    conn = await get_conn()
    await conn.execute("DELETE FROM limits WHERE id=?", (limit_id,))
    await conn.commit()


async def get_limit_by_id(limit_id):
    conn = await get_conn()
    cur = await conn.execute("SELECT * FROM limits WHERE id=?", (limit_id,))
    return await cur.fetchone()


# ── Safewords ──────────────────────────────────────────────────────────────────

async def log_safeword(pair_id, triggered_by, level) -> int:
    conn = await get_conn()
    cur = await conn.execute(
        "INSERT INTO safeword_events (pair_id,triggered_by,level) VALUES (?,?,?)",
        (pair_id, triggered_by, level),
    )
    await conn.commit()
    return cur.lastrowid


async def resolve_safeword(event_id):
    conn = await get_conn()
    await conn.execute("UPDATE safeword_events SET resolved=1 WHERE id=?", (event_id,))
    await conn.commit()


async def get_active_safeword(pair_id):
    conn = await get_conn()
    cur = await conn.execute(
        """SELECT * FROM safeword_events
           WHERE pair_id=? AND resolved=0
           ORDER BY triggered_at DESC LIMIT 1""",
        (pair_id,),
    )
    return await cur.fetchone()


# ── Reminders ──────────────────────────────────────────────────────────────────

async def set_reminders(pair_id, on: bool):
    conn = await get_conn()
    await conn.execute(
        "UPDATE reminder_settings SET reminders_on=? WHERE pair_id=?",
        (1 if on else 0, pair_id),
    )
    await conn.commit()


async def get_all_active_pairs_with_reminders():
    conn = await get_conn()
    cur = await conn.execute(
        """SELECT p.*, rs.reminders_on, rs.checkin_hour
           FROM pairs p JOIN reminder_settings rs ON rs.pair_id=p.id
           WHERE p.active=1 AND rs.reminders_on=1"""
    )
    return await cur.fetchall()


# ── Check-ins ──────────────────────────────────────────────────────────────────

async def add_checkin(pair_id, sub_id, mood, note=None) -> int:
    conn = await get_conn()
    cur = await conn.execute(
        "INSERT INTO checkins (pair_id,sub_id,mood,note) VALUES (?,?,?,?)",
        (pair_id, sub_id, mood, note),
    )
    await conn.commit()
    return cur.lastrowid


async def get_recent_checkins(pair_id, limit=7):
    conn = await get_conn()
    cur = await conn.execute(
        "SELECT * FROM checkins WHERE pair_id=? ORDER BY checked_at DESC LIMIT ?",
        (pair_id, limit),
    )
    return await cur.fetchall()


async def get_today_checkin(pair_id, sub_id):
    conn = await get_conn()
    cur = await conn.execute(
        """SELECT * FROM checkins
           WHERE pair_id=? AND sub_id=?
           AND date(checked_at)=date('now')
           ORDER BY checked_at DESC LIMIT 1""",
        (pair_id, sub_id),
    )
    return await cur.fetchone()
