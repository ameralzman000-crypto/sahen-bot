import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

import config
from config import (
    ADMIN_DISPLAY,
    ADMIN_ID,
    ROLE_ADMIN,
    ROLE_MEMBER,
    ROLE_MODERATOR,
    STATUS_APPROVED,
    STATUS_BANNED,
    STATUS_PENDING,
    STATUS_REJECTED,
)


_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def get_conn():
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                real_name TEXT,
                alias TEXT UNIQUE,
                username TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                role TEXT NOT NULL DEFAULT 'member',
                moderator_number INTEGER,
                can_reveal INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS message_map (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                original_id INTEGER,
                relayed_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(chat_id, relayed_id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS violations (
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                last_at TEXT NOT NULL,
                PRIMARY KEY (user_id, kind)
            );

            CREATE TABLE IF NOT EXISTS mutes (
                user_id INTEGER PRIMARY KEY,
                until_ts INTEGER NOT NULL,
                reason TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
            CREATE INDEX IF NOT EXISTS idx_users_alias ON users(alias);
            CREATE INDEX IF NOT EXISTS idx_map_original ON message_map(chat_id, original_id);
            CREATE INDEX IF NOT EXISTS idx_map_sender ON message_map(sender_id);
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "direct_write" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN direct_write INTEGER NOT NULL DEFAULT 0")


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    if "can_reveal" in data:
        data["can_reveal"] = bool(data["can_reveal"])
    if "direct_write" in data:
        data["direct_write"] = bool(data["direct_write"])
    else:
        data["direct_write"] = False
    return data


def get_user(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return _row_to_dict(row)


def get_user_by_alias(alias: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE alias = ?", (alias,)).fetchone()
        return _row_to_dict(row)


def upsert_registration(user_id: int, real_name: str, alias: str, username: str | None) -> dict:
    now = _now()
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE users
                SET real_name = ?, alias = ?, username = ?, status = ?,
                    role = CASE WHEN role = ? THEN role ELSE ? END,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (
                    real_name,
                    alias,
                    username,
                    STATUS_PENDING if existing["role"] != ROLE_ADMIN else STATUS_APPROVED,
                    ROLE_ADMIN,
                    ROLE_MEMBER,
                    now,
                    user_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO users (
                    user_id, real_name, alias, username, status, role,
                    moderator_number, can_reveal, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, 0, ?, ?)
                """,
                (user_id, real_name, alias, username, STATUS_PENDING, ROLE_MEMBER, now, now),
            )
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return _row_to_dict(row)


def update_username(user_id: int, username: str | None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET username = ?, updated_at = ? WHERE user_id = ?",
            (username, _now(), user_id),
        )


def set_status(user_id: int, status: str) -> dict | None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET status = ?, updated_at = ? WHERE user_id = ?",
            (status, _now(), user_id),
        )
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return _row_to_dict(row)


def set_role(user_id: int, role: str, moderator_number: int | None = None, can_reveal: int | None = None) -> dict | None:
    with get_conn() as conn:
        if can_reveal is None:
            conn.execute(
                """
                UPDATE users
                SET role = ?, moderator_number = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (role, moderator_number, _now(), user_id),
            )
        else:
            conn.execute(
                """
                UPDATE users
                SET role = ?, moderator_number = ?, can_reveal = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (role, moderator_number, int(can_reveal), _now(), user_id),
            )
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return _row_to_dict(row)


def set_direct_write(user_id: int, enabled: bool) -> dict | None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET direct_write = ?, updated_at = ? WHERE user_id = ?",
            (1 if enabled else 0, _now(), user_id),
        )
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return _row_to_dict(row)


def allows_direct_write(user_id: int) -> bool:
    user = get_user(user_id)
    return bool(user and user.get("status") == STATUS_APPROVED and user.get("direct_write"))


def set_can_reveal(user_id: int, enabled: bool) -> dict | None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET can_reveal = ?, updated_at = ? WHERE user_id = ?",
            (1 if enabled else 0, _now(), user_id),
        )
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return _row_to_dict(row)


def next_moderator_number() -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(moderator_number) AS m FROM users WHERE role = ?",
            (ROLE_MODERATOR,),
        ).fetchone()
        current = row["m"] if row and row["m"] is not None else 0
        return int(current) + 1


def list_by_status(status: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE status = ? ORDER BY created_at ASC",
            (status,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def list_members() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY role ASC, moderator_number ASC, alias ASC"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def save_message(chat_id: int, original_id: int | None, relayed_id: int, sender_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO message_map (chat_id, original_id, relayed_id, sender_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, original_id, relayed_id, sender_id, _now()),
        )


def get_by_relayed(chat_id: int, relayed_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM message_map WHERE chat_id = ? AND relayed_id = ?",
            (chat_id, relayed_id),
        ).fetchone()
        return _row_to_dict(row)


def get_by_original(chat_id: int, original_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM message_map WHERE chat_id = ? AND original_id = ?",
            (chat_id, original_id),
        ).fetchone()
        return _row_to_dict(row)


def list_message_ids(chat_id: int | None = None) -> list[dict]:
    with get_conn() as conn:
        if chat_id is None:
            rows = conn.execute(
                "SELECT chat_id, original_id, relayed_id FROM message_map"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT chat_id, original_id, relayed_id FROM message_map WHERE chat_id = ?",
                (chat_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


def clear_message_map(chat_id: int | None = None) -> int:
    with get_conn() as conn:
        if chat_id is None:
            cur = conn.execute("DELETE FROM message_map")
        else:
            cur = conn.execute("DELETE FROM message_map WHERE chat_id = ?", (chat_id,))
        return int(cur.rowcount or 0)


def get_setting(key: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_group_chat_id() -> int | None:
    value = get_setting("group_chat_id")
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def set_group_chat_id(chat_id: int) -> None:
    set_setting("group_chat_id", str(chat_id))


def set_bound_chat(chat_id: int, chat_type: str = "supergroup") -> None:
    set_group_chat_id(chat_id)
    set_setting("bound_chat_type", chat_type or "supergroup")


def get_bound_chat_type() -> str:
    return get_setting("bound_chat_type") or "supergroup"


def is_channel_bound() -> bool:
    return get_bound_chat_type() == "channel"


def get_rules() -> str:
    value = get_setting("group_rules")
    if value:
        return value
    return config.DEFAULT_RULES


def set_rules(text: str) -> None:
    set_setting("group_rules", text)


def is_paused() -> bool:
    return get_setting("bot_paused") == "1"


def set_paused(paused: bool) -> None:
    set_setting("bot_paused", "1" if paused else "0")


def stats() -> dict:
    with get_conn() as conn:
        def count(status: str | None = None, role: str | None = None) -> int:
            if status:
                row = conn.execute("SELECT COUNT(*) AS c FROM users WHERE status = ?", (status,)).fetchone()
            elif role:
                row = conn.execute("SELECT COUNT(*) AS c FROM users WHERE role = ?", (role,)).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
            return int(row["c"])

        return {
            "total": count(),
            "pending": count(status=STATUS_PENDING),
            "approved": count(status=STATUS_APPROVED),
            "rejected": count(status=STATUS_REJECTED),
            "banned": count(status=STATUS_BANNED),
            "moderators": count(role=ROLE_MODERATOR),
            "messages": int(conn.execute("SELECT COUNT(*) AS c FROM message_map").fetchone()["c"]),
        }


def ensure_admin(admin_id: int) -> dict:
    now = _now()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (admin_id,)).fetchone()
        if row:
            conn.execute(
                """
                UPDATE users
                SET role = ?, status = ?, can_reveal = 1, updated_at = ?
                WHERE user_id = ?
                """,
                (ROLE_ADMIN, STATUS_APPROVED, now, admin_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO users (
                    user_id, real_name, alias, username, status, role,
                    moderator_number, can_reveal, created_at, updated_at
                ) VALUES (?, ?, ?, NULL, ?, ?, NULL, 1, ?, ?)
                """,
                (admin_id, ADMIN_DISPLAY, ADMIN_DISPLAY, STATUS_APPROVED, ROLE_ADMIN, now, now),
            )
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (admin_id,)).fetchone()
        return _row_to_dict(row)


def reset_all_data(admin_id: int) -> dict:
    with get_conn() as conn:
        conn.execute("DELETE FROM message_map")
        conn.execute("DELETE FROM settings")
        conn.execute("DELETE FROM violations")
        conn.execute("DELETE FROM mutes")
        conn.execute("DELETE FROM users")
    init_db()
    return ensure_admin(admin_id)


def add_violation(user_id: int, kind: str) -> int:
    now = _now()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT count FROM violations WHERE user_id = ? AND kind = ?",
            (user_id, kind),
        ).fetchone()
        if row:
            count = int(row["count"]) + 1
            conn.execute(
                "UPDATE violations SET count = ?, last_at = ? WHERE user_id = ? AND kind = ?",
                (count, now, user_id, kind),
            )
        else:
            count = 1
            conn.execute(
                "INSERT INTO violations (user_id, kind, count, last_at) VALUES (?, ?, 1, ?)",
                (user_id, kind, now),
            )
        return count


def get_violation_count(user_id: int, kind: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT count FROM violations WHERE user_id = ? AND kind = ?",
            (user_id, kind),
        ).fetchone()
        return int(row["count"]) if row else 0


def set_mute(user_id: int, until_ts: int, reason: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO mutes (user_id, until_ts, reason) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET until_ts = excluded.until_ts, reason = excluded.reason
            """,
            (user_id, until_ts, reason),
        )


def clear_mute(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM mutes WHERE user_id = ?", (user_id,))


def is_muted(user_id: int) -> bool:
    now = int(datetime.now(timezone.utc).timestamp())
    with get_conn() as conn:
        row = conn.execute("SELECT until_ts FROM mutes WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return False
        until_ts = int(row["until_ts"])
        if until_ts <= now:
            conn.execute("DELETE FROM mutes WHERE user_id = ?", (user_id,))
            return False
        return True


def find_user_by_shown_name(name: str) -> dict | None:
    from utils import display_name as shown_name

    target = (name or "").strip()
    if not target:
        return None
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users").fetchall()
    for row in rows:
        user = _row_to_dict(row)
        if not user:
            continue
        if shown_name(user) == target or (user.get("alias") or "") == target:
            return user
    return None


def list_approved_members() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE status = ? ORDER BY created_at ASC",
            (STATUS_APPROVED,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def alias_taken(alias: str, exclude_user_id: int | None = None) -> bool:
    with get_conn() as conn:
        if exclude_user_id is None:
            row = conn.execute("SELECT user_id FROM users WHERE alias = ?", (alias,)).fetchone()
        else:
            row = conn.execute(
                "SELECT user_id FROM users WHERE alias = ? AND user_id != ?",
                (alias, exclude_user_id),
            ).fetchone()
        return row is not None


def set_alias(user_id: int, alias: str) -> dict | None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET alias = ?, updated_at = ? WHERE user_id = ?",
            (alias, _now(), user_id),
        )
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return _row_to_dict(row)


def delete_user(user_id: int) -> bool:
    if int(user_id) == int(ADMIN_ID):
        return False
    with get_conn() as conn:
        row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM mutes WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        return True



