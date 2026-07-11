"""Databázová vrstva s dvojím backendem.

Produkce: MySQL přes mysql.connector (env: DB_HOST/DB_PORT/DB_USER/DB_PASS/DB_NAME).
Lokální vývoj: automatický fallback na SQLite soubor `knowix_local.db`, pokud
DB_HOST není nastaveno nebo se MySQL nepodaří připojit při startu.

_SQLiteCursor/_SQLiteConnection emulují API mysql.connectoru (cursor(dictionary=True),
%s placeholdery, NOW()), takže feature moduly píšou MySQL-style SQL bez větvení.
Na backend se větví výhradně přes is_sqlite_mode().

Při přidání sloupce/tabulky aktualizuj OBOJE: MySQL ALTER/CREATE na call-site
i _SQLITE_SCHEMA_STMTS níže (+ ad-hoc migrace v _ensure_sqlite_schema()).
"""

import logging
import os
import re
import sqlite3

from _paths import APP_DIR

logger = logging.getLogger('db')

# ---------------------------------------------------------------------------
# Cesta k SQLite fallback souboru
# ---------------------------------------------------------------------------

_SQLITE_PATH = os.path.join(APP_DIR, 'knowix_local.db')
_USE_SQLITE = False  # nastaví se při importu přes _detect_backend()


def is_sqlite_mode() -> bool:
    """Vrací True, pokud aplikace běží na SQLite (MySQL nedostupné)."""
    return _USE_SQLITE


# ---------------------------------------------------------------------------
# SQL překladač  MySQL → SQLite
# ---------------------------------------------------------------------------

def _translate_sql(sql: str) -> str:
    """Přeloží MySQL SQL na SQLite kompatibilní SQL (DML operace)."""
    sql = sql.replace('%s', '?')
    sql = re.sub(r'\bNOW\(\)', 'CURRENT_TIMESTAMP', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bCURRENT_TIMESTAMP\(\)', 'CURRENT_TIMESTAMP', sql, flags=re.IGNORECASE)
    return sql


# ---------------------------------------------------------------------------
# SQLite cursor/connection wrapper (emuluje mysql.connector API)
# ---------------------------------------------------------------------------

class _SQLiteCursor:
    def __init__(self, cursor: sqlite3.Cursor, dictionary: bool = False):
        self._cur = cursor
        self._dictionary = dictionary

    def _row_to_dict(self, row):
        if row is None:
            return None
        cols = [d[0] for d in (self._cur.description or [])]
        return dict(zip(cols, row))

    def execute(self, sql: str, params=None):
        sql = _translate_sql(sql)
        try:
            if params is not None:
                self._cur.execute(sql, params)
            else:
                self._cur.execute(sql)
        except sqlite3.Error as e:
            logger.debug("[SQLite] execute chyba: %s | SQL: %.200s", e, sql)
            raise

    def executemany(self, sql: str, params):
        self._cur.executemany(_translate_sql(sql), params)

    def fetchone(self):
        row = self._cur.fetchone()
        if self._dictionary:
            return self._row_to_dict(row)
        return row

    def fetchall(self):
        rows = self._cur.fetchall()
        if self._dictionary:
            cols = [d[0] for d in (self._cur.description or [])]
            return [dict(zip(cols, r)) for r in rows]
        return rows

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def __iter__(self):
        if self._dictionary:
            cols = [d[0] for d in (self._cur.description or [])]
            for row in self._cur:
                yield dict(zip(cols, row))
        else:
            yield from self._cur

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        # False = případná výjimka se má propagovat dál
        return False


class _SQLiteConnection:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def cursor(self, dictionary: bool = False, **kwargs):
        return _SQLiteCursor(self._conn.cursor(), dictionary=dictionary)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ---------------------------------------------------------------------------
# SQLite schéma – všechny klíčové tabulky
# ---------------------------------------------------------------------------

_SQLITE_SCHEMA_STMTS = [
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT,
        provider_id TEXT,
        email TEXT NOT NULL UNIQUE,
        first_name TEXT,
        last_name TEXT,
        avatar_url TEXT,
        password TEXT NOT NULL DEFAULT '',
        english_level TEXT DEFAULT 'A1',
        school TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP,
        xp INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1,
        streak INTEGER DEFAULT 0,
        last_streak_date DATE,
        inventory TEXT,
        subject TEXT,
        role TEXT DEFAULT 'student',
        verified INTEGER DEFAULT 0,
        receive_reminder_emails INTEGER DEFAULT 0,
        last_reminder_sent DATETIME,
        reminder_token TEXT,
        theme_mode TEXT DEFAULT 'light',
        profile_pk TEXT DEFAULT 'default.jpg',
        is_guest INTEGER DEFAULT 0,
        has_seen_onboarding INTEGER DEFAULT 0,
        last_email_stage INTEGER,
        last_push_reminder_sent DATETIME,
        last_push_stage INTEGER,
        last_email_day DATE,
        email_sends_today INTEGER DEFAULT 0,
        last_push_day DATE,
        push_sends_today INTEGER DEFAULT 0,
        last_email_date DATE,
        last_push_date DATE
    )""",
    """CREATE TABLE IF NOT EXISTS guest (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        first_name TEXT,
        last_name TEXT,
        email TEXT NOT NULL UNIQUE,
        password TEXT,
        birthdate DATE,
        profile_pk TEXT DEFAULT 'default.jpg',
        theme_mode TEXT DEFAULT 'light',
        english_level TEXT DEFAULT 'A1',
        xp INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1,
        streak INTEGER DEFAULT 0,
        last_streak_date DATE,
        inventory TEXT,
        school TEXT,
        subject TEXT,
        role TEXT DEFAULT 'student',
        verified INTEGER,
        receive_reminder_emails INTEGER,
        last_reminder_sent DATETIME,
        reminder_token TEXT,
        is_guest INTEGER DEFAULT 1,
        has_seen_onboarding INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        provider TEXT,
        provider_id TEXT,
        avatar_url TEXT,
        last_login TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS user_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        total_lessons_done INTEGER DEFAULT 0,
        correct_answers INTEGER DEFAULT 0,
        wrong_answers INTEGER DEFAULT 0,
        total_learning_time INTEGER DEFAULT 0,
        last_active DATETIME,
        total_psani_words INTEGER DEFAULT 0,
        first_activity DATETIME,
        hangman_words_guessed INTEGER DEFAULT 0,
        irregular_verbs_guessed INTEGER DEFAULT 0,
        irregular_verbs_wrong INTEGER DEFAULT 0,
        pp_wrong INTEGER DEFAULT 0,
        pp_maybe INTEGER DEFAULT 0,
        pp_correct INTEGER DEFAULT 0,
        roleplaying_cr INTEGER DEFAULT 0,
        roleplaying_mb INTEGER DEFAULT 0,
        roleplaying_wr INTEGER DEFAULT 0,
        lis_cor INTEGER DEFAULT 0,
        lis_wr INTEGER DEFAULT 0,
        at_cor INTEGER DEFAULT 0,
        at_wr INTEGER DEFAULT 0,
        AI_poslech_minut INTEGER DEFAULT 0,
        AI_poslech_seconds INTEGER DEFAULT 0,
        slovni_best_time REAL DEFAULT 0,
        slovni_quick_points INTEGER DEFAULT 0,
        slovni_timer_pref TEXT,
        wordle_last_key TEXT,
        wordle_guesses TEXT,
        wordle_completed INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS achievements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        name TEXT,
        description TEXT,
        condition_type TEXT,
        condition_value INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS user_achievements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        achievement_id INTEGER NOT NULL,
        achieved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, achievement_id)
    )""",
    """CREATE TABLE IF NOT EXISTS user_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        key_count INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS user_daily_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        snapshot_date DATE NOT NULL,
        xp INTEGER DEFAULT 0,
        UNIQUE(user_id, snapshot_date)
    )""",
    """CREATE TABLE IF NOT EXISTS user_daily_quests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        quest_date DATE NOT NULL,
        quest_type TEXT NOT NULL,
        target INTEGER DEFAULT 1,
        progress INTEGER DEFAULT 0,
        completed INTEGER DEFAULT 0,
        UNIQUE(user_id, quest_date, quest_type)
    )""",
    """CREATE TABLE IF NOT EXISTS user_lessons_completed (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        lesson_key TEXT NOT NULL,
        completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, lesson_key)
    )""",
    """CREATE TABLE IF NOT EXISTS push_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        endpoint TEXT UNIQUE,
        p256dh TEXT,
        auth TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        installed INTEGER DEFAULT 0,
        last_seen DATETIME
    )""",
    """CREATE TABLE IF NOT EXISTS chat_message (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        user_id INTEGER,
        sender TEXT,
        content TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS chat_session (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS dnd_message (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        sender TEXT,
        content TEXT,
        story_id INTEGER DEFAULT 1,
        title TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS psani (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        obsah TEXT,
        public INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS app_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key_name TEXT UNIQUE,
        value TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS user_xp_booster (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        multiplier REAL DEFAULT 1.5,
        valid_until DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
]


def _ensure_sqlite_schema():
    """Vytvoří všechny tabulky v SQLite databázi, pokud neexistují."""
    try:
        conn = sqlite3.connect(_SQLITE_PATH)
        cur = conn.cursor()
        for stmt in _SQLITE_SCHEMA_STMTS:
            cur.execute(stmt)

        # Lehká migrace pro starší lokální DB bez nových sloupců.
        cur.execute("PRAGMA table_info(chat_message)")
        chat_msg_cols = {row[1] for row in cur.fetchall()}
        if 'chat_id' not in chat_msg_cols:
            cur.execute("ALTER TABLE chat_message ADD COLUMN chat_id INTEGER")

        cur.execute("PRAGMA table_info(users)")
        user_cols = {row[1] for row in cur.fetchall()}
        if 'profile_pic' not in user_cols:
            cur.execute("ALTER TABLE users ADD COLUMN profile_pic TEXT DEFAULT 'default.jpg'")

        cur.execute("PRAGMA table_info(psani)")
        psani_cols = {row[1] for row in cur.fetchall()}
        if 'public' not in psani_cols:
            cur.execute("ALTER TABLE psani ADD COLUMN public INTEGER DEFAULT 0")
        if 'created_at' not in psani_cols:
            cur.execute("ALTER TABLE psani ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP")

        conn.commit()
        cur.close()
        conn.close()
        print(f"[db] SQLite schema OK: {_SQLITE_PATH}")
    except Exception as e:
        print(f"[db] CHYBA pri vytvareni SQLite schematu: {e}")
        logger.exception("[db] SQLite schema error")


# ---------------------------------------------------------------------------
# Detekce backendu (spouští se při importu modulu)
# ---------------------------------------------------------------------------

def _detect_backend():
    global _USE_SQLITE

    # Pokud není vůbec nastavena env proměnná DB_HOST, rovnou jdi na SQLite
    if not os.environ.get("DB_HOST"):
        _USE_SQLITE = True
        print(f"[db] DB_HOST neni nastaveno - pouzivam SQLite: {_SQLITE_PATH}")
        _ensure_sqlite_schema()
        return

    try:
        import mysql.connector
        conn = mysql.connector.connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", 3306)),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASS"],
            database=os.environ["DB_NAME"],
            connection_timeout=5,
        )
        conn.close()
        _USE_SQLITE = False
        print("[db] Backend: MySQL OK")
    except Exception as e:
        _USE_SQLITE = True
        print(f"[db] MySQL nedostupne ({e}) - fallback na SQLite: {_SQLITE_PATH}")
        _ensure_sqlite_schema()


def initialize_database_backend(force: bool = False):
    """Re-inicializuje backend DB (užitečné po load_dotenv v main.py).

    force=True: vždy znovu detekuje backend podle aktuálních env proměnných.
    """
    # force je připravené pro případné budoucí cachování; nyní vždy provádíme detekci.
    _ = force
    _detect_backend()


initialize_database_backend()


# ---------------------------------------------------------------------------
# Veřejné API
# ---------------------------------------------------------------------------

def get_db_connection():
    """Vrátí připojení k databázi (MySQL nebo SQLite wrapper)."""
    if _USE_SQLITE:
        conn = sqlite3.connect(_SQLITE_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return _SQLiteConnection(conn)
    else:
        import mysql.connector
        return mysql.connector.connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ["DB_PORT"]),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASS"],
            database=os.environ["DB_NAME"],
            connection_timeout=30,
        )


def ensure_users_table_guest():
    """Zajistí existenci tabulky guest.
    V SQLite režimu je schéma již vytvořeno v _ensure_sqlite_schema().
    """
    if _USE_SQLITE:
        return  # SQLite schema je kompletni

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
CREATE TABLE IF NOT EXISTS guest (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NULL,
  first_name VARCHAR(50) NULL,
  last_name VARCHAR(50) NULL,
  email VARCHAR(100) NOT NULL,
  password VARCHAR(255) NULL,
  birthdate DATE NULL,
  profile_pk VARCHAR(255) NULL DEFAULT 'default.jpg',
  theme_mode VARCHAR(45) NULL DEFAULT 'light',
  english_level VARCHAR(3) NULL DEFAULT 'A1',
  xp INT NULL DEFAULT 0,
  level INT NULL DEFAULT 1,
  streak INT NULL DEFAULT 0,
  last_streak_date DATE NULL,
  inventory TEXT NULL,
  school VARCHAR(100) NULL,
  subject VARCHAR(100) NULL,
  role VARCHAR(45) NULL DEFAULT 'student',
  verified TINYINT(1) NULL,
  receive_reminder_emails TINYINT(1) NULL,
  last_reminder_sent DATETIME NULL,
  reminder_token VARCHAR(128) NULL,
  last_email_stage TINYINT NULL,
  last_push_reminder_sent DATETIME NULL,
  last_push_stage TINYINT NULL,
  last_email_day DATE NULL,
  email_sends_today INT NULL,
  last_push_day DATE NULL,
  push_sends_today INT NULL,
  last_email_date DATE NULL,
  last_push_date DATE NULL,
  is_guest TINYINT(1) NULL,
  has_seen_onboarding TINYINT(1) NULL,
  created_at TIMESTAMP NULL,
  provider VARCHAR(32) NULL,
  provider_id VARCHAR(128) NULL,
  avatar_url VARCHAR(5512) NULL,
  last_login TIMESTAMP NULL,
  UNIQUE KEY uniq_email (email),
  KEY idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )

        # Pokud tabulka již existovala bez sloupce user_id, pokusíme se ho bezpečně přidat
        try:
            cur.execute("ALTER TABLE guest ADD COLUMN user_id INT NULL")
        except Exception as e:
            # Pokud sloupec existuje, MySQL vrátí chybu 1060 (Duplicate column name) -> ignoruj
            msg = str(getattr(e, 'msg', e))
            if 'Duplicate column' in msg or '1060' in msg:
                pass
            else:
                raise

        # Stejně tak přidej index pokud chybí
        try:
            cur.execute("CREATE INDEX idx_user_id ON guest (user_id)")
        except Exception as e:
            msg = str(getattr(e, 'msg', e))
            if 'Duplicate key name' in msg or '1061' in msg or 'already exists' in msg:
                pass
            else:
                raise

        conn.commit()
    except Exception:
        logging.exception("[DB] Chyba pri zajistovani tabulky guest")
    finally:
        cur.close()
        conn.close()
