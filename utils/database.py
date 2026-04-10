"""
Database manager – PostgreSQL via asyncpg.
Initialise le schéma complet au premier lancement.
"""
import asyncpg
import os


async def get_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"])


SCHEMA = """
CREATE TABLE IF NOT EXISTS pairs (
    id          SERIAL PRIMARY KEY,
    dom_id      BIGINT NOT NULL,
    sub_id      BIGINT NOT NULL,
    guild_id    BIGINT NOT NULL,
    dom_label   TEXT NOT NULL DEFAULT 'Dominant',
    sub_label   TEXT NOT NULL DEFAULT 'Subordonné',
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(dom_id, sub_id, guild_id)
);

CREATE TABLE IF NOT EXISTS wallets (
    pair_id INT PRIMARY KEY REFERENCES pairs(id) ON DELETE CASCADE,
    points  INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tasks (
    id             SERIAL PRIMARY KEY,
    pair_id        INT NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    description    TEXT,
    points         INT NOT NULL DEFAULT 10,
    recurrence     TEXT NOT NULL DEFAULT 'daily',
    requires_proof BOOLEAN NOT NULL DEFAULT FALSE,
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS task_completions (
    id           SERIAL PRIMARY KEY,
    task_id      INT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    pair_id      INT NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    proof_url    TEXT,
    validated    BOOLEAN,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shop_items (
    id          SERIAL PRIMARY KEY,
    pair_id     INT NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    cost        INT NOT NULL DEFAULT 50,
    active      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS purchases (
    id           SERIAL PRIMARY KEY,
    item_id      INT NOT NULL REFERENCES shop_items(id) ON DELETE CASCADE,
    pair_id      INT NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    validated    BOOLEAN,
    purchased_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS limits (
    id          SERIAL PRIMARY KEY,
    pair_id     INT NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    color       TEXT NOT NULL CHECK (color IN ('green','orange','red')),
    description TEXT,
    created_by  BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS safeword_events (
    id           SERIAL PRIMARY KEY,
    pair_id      INT NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    triggered_by BIGINT NOT NULL,
    level        TEXT NOT NULL CHECK (level IN ('YELLOW','RED')),
    resolved     BOOLEAN NOT NULL DEFAULT FALSE,
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS checkins (
    id         SERIAL PRIMARY KEY,
    pair_id    INT NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    sub_id     BIGINT NOT NULL,
    mood       INT NOT NULL CHECK (mood BETWEEN 1 AND 10),
    note       TEXT,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reminder_settings (
    pair_id      INT PRIMARY KEY REFERENCES pairs(id) ON DELETE CASCADE,
    reminders_on BOOLEAN NOT NULL DEFAULT TRUE,
    checkin_hour INT NOT NULL DEFAULT 21
);
"""


async def init_db(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)


# ── Pairs ──────────────────────────────────────────────────────────────────────

async def create_pair(pool, dom_id, sub_id, guild_id) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO pairs (dom_id, sub_id, guild_id)
               VALUES ($1, $2, $3)
               ON CONFLICT (dom_id, sub_id, guild_id) DO UPDATE SET active = TRUE
               RETURNING id""",
            dom_id, sub_id, guild_id,
        )
        pid = row["id"]
        await conn.execute("INSERT INTO wallets (pair_id) VALUES ($1) ON CONFLICT DO NOTHING", pid)
        await conn.execute("INSERT INTO reminder_settings (pair_id) VALUES ($1) ON CONFLICT DO NOTHING", pid)
        return pid


async def get_pair_by_users(pool, user_a, user_b, guild_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT * FROM pairs WHERE guild_id=$3 AND active=TRUE
               AND ((dom_id=$1 AND sub_id=$2) OR (dom_id=$2 AND sub_id=$1))""",
            user_a, user_b, guild_id,
        )


async def get_pairs_for_user(pool, user_id, guild_id):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM pairs WHERE guild_id=$2 AND active=TRUE AND (dom_id=$1 OR sub_id=$1)",
            user_id, guild_id,
        )


async def get_pair(pool, pair_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM pairs WHERE id=$1", pair_id)


async def dissolve_pair(pool, pair_id):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE pairs SET active=FALSE WHERE id=$1", pair_id)


# ── Wallets ────────────────────────────────────────────────────────────────────

async def get_balance(pool, pair_id) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT points FROM wallets WHERE pair_id=$1", pair_id)
        return row["points"] if row else 0


async def add_points(pool, pair_id, amount):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE wallets SET points=points+$1 WHERE pair_id=$2", amount, pair_id)


async def deduct_points(pool, pair_id, amount) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT points FROM wallets WHERE pair_id=$1", pair_id)
        if not row or row["points"] < amount:
            return False
        await conn.execute("UPDATE wallets SET points=points-$1 WHERE pair_id=$2", amount, pair_id)
        return True


# ── Tasks ──────────────────────────────────────────────────────────────────────

async def create_task(pool, pair_id, name, description, points, recurrence, requires_proof) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO tasks (pair_id,name,description,points,recurrence,requires_proof)
               VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
            pair_id, name, description, points, recurrence, requires_proof,
        )
        return row["id"]


async def get_tasks(pool, pair_id):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM tasks WHERE pair_id=$1 AND active=TRUE ORDER BY id", pair_id
        )


async def get_task(pool, task_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM tasks WHERE id=$1", task_id)


async def delete_task(pool, task_id):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE tasks SET active=FALSE WHERE id=$1", task_id)


async def add_completion(pool, task_id, pair_id, proof_url=None) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO task_completions (task_id,pair_id,proof_url) VALUES ($1,$2,$3) RETURNING id",
            task_id, pair_id, proof_url,
        )
        return row["id"]


async def validate_completion(pool, completion_id, validated: bool):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE task_completions SET validated=$1 WHERE id=$2", validated, completion_id
        )


async def get_weekly_stats(pool, pair_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT
                COUNT(*) FILTER (WHERE validated=TRUE)  AS done,
                COUNT(*) FILTER (WHERE validated IS NULL) AS pending,
                COUNT(*) FILTER (WHERE validated=FALSE) AS refused
               FROM task_completions
               WHERE pair_id=$1 AND completed_at > NOW() - INTERVAL '7 days'""",
            pair_id,
        )


# ── Shop ───────────────────────────────────────────────────────────────────────

async def create_shop_item(pool, pair_id, name, description, cost) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO shop_items (pair_id,name,description,cost) VALUES ($1,$2,$3,$4) RETURNING id",
            pair_id, name, description, cost,
        )
        return row["id"]


async def get_shop_items(pool, pair_id):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM shop_items WHERE pair_id=$1 AND active=TRUE ORDER BY cost", pair_id
        )


async def create_purchase(pool, item_id, pair_id) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO purchases (item_id,pair_id) VALUES ($1,$2) RETURNING id",
            item_id, pair_id,
        )
        return row["id"]


async def validate_purchase(pool, purchase_id, validated: bool):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE purchases SET validated=$1 WHERE id=$2", validated, purchase_id
        )


async def get_purchase(pool, purchase_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT p.*, si.cost, si.name AS item_name
               FROM purchases p JOIN shop_items si ON si.id=p.item_id
               WHERE p.id=$1""",
            purchase_id,
        )


# ── Limits ─────────────────────────────────────────────────────────────────────

async def add_limit(pool, pair_id, name, color, description, created_by) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO limits (pair_id,name,color,description,created_by) VALUES ($1,$2,$3,$4,$5) RETURNING id",
            pair_id, name, color, description, created_by,
        )
        return row["id"]


async def get_limits(pool, pair_id):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM limits WHERE pair_id=$1 ORDER BY color, name", pair_id
        )


async def delete_limit(pool, limit_id):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM limits WHERE id=$1", limit_id)


# ── Safewords ──────────────────────────────────────────────────────────────────

async def log_safeword(pool, pair_id, triggered_by, level) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO safeword_events (pair_id,triggered_by,level) VALUES ($1,$2,$3) RETURNING id",
            pair_id, triggered_by, level,
        )
        return row["id"]


async def resolve_safeword(pool, event_id):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE safeword_events SET resolved=TRUE WHERE id=$1", event_id)


async def get_active_safeword(pool, pair_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT * FROM safeword_events
               WHERE pair_id=$1 AND resolved=FALSE
               ORDER BY triggered_at DESC LIMIT 1""",
            pair_id,
        )


# ── Reminders ──────────────────────────────────────────────────────────────────

async def set_reminders(pool, pair_id, on: bool):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE reminder_settings SET reminders_on=$1 WHERE pair_id=$2", on, pair_id
        )


async def get_all_active_pairs_with_reminders(pool):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT p.*, rs.reminders_on, rs.checkin_hour
               FROM pairs p JOIN reminder_settings rs ON rs.pair_id=p.id
               WHERE p.active=TRUE AND rs.reminders_on=TRUE"""
        )


# ── Check-ins ──────────────────────────────────────────────────────────────────

async def add_checkin(pool, pair_id, sub_id, mood, note=None) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO checkins (pair_id,sub_id,mood,note) VALUES ($1,$2,$3,$4) RETURNING id",
            pair_id, sub_id, mood, note,
        )
        return row["id"]


async def get_recent_checkins(pool, pair_id, limit=7):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM checkins WHERE pair_id=$1 ORDER BY checked_at DESC LIMIT $2",
            pair_id, limit,
        )
