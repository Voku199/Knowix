"""Agregované statistiky uživatele (tabulka user_stats).

Každá aktivita v aplikaci hlásí výsledky přes update_user_stats() — funkce
přičte nenulové inkrementy k příslušným sloupcům a aktualizuje last_active.
Řádek v user_stats se založí automaticky (ensure_user_stats_exists).
"""

from db import get_db_connection


def _ensure_extended_columns():
    """Zajistí nové sloupce pro shadow a podcast statistiky (idempotentně)."""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # MySQL/MariaDB: IF NOT EXISTS je podporováno v novějších verzích; pokud ne, chybu ignorujeme.
        alter_cmds = [
            "ALTER TABLE user_stats ADD COLUMN IF NOT EXISTS shw_cor INT NOT NULL DEFAULT 0",
            "ALTER TABLE user_stats ADD COLUMN IF NOT EXISTS shw_mb INT NOT NULL DEFAULT 0",
            "ALTER TABLE user_stats ADD COLUMN IF NOT EXISTS shw_wr INT NOT NULL DEFAULT 0",
            "ALTER TABLE user_stats ADD COLUMN IF NOT EXISTS pds_cor INT NOT NULL DEFAULT 0",
            "ALTER TABLE user_stats ADD COLUMN IF NOT EXISTS pds_wr INT NOT NULL DEFAULT 0",
            # Nové: AI‑gramatika agregace
            "ALTER TABLE user_stats ADD COLUMN IF NOT EXISTS ai_gram_cor INT NOT NULL DEFAULT 0",
            "ALTER TABLE user_stats ADD COLUMN IF NOT EXISTS ai_gram_wr INT NOT NULL DEFAULT 0",
        ]
        for sql in alter_cmds:
            try:
                cur.execute(sql)
            except Exception:
                # fallback pro starší verze bez IF NOT EXISTS – pokus bez něj, případně ignoruj duplicitní chybu
                try:
                    base_sql = sql.replace(" IF NOT EXISTS", "")
                    cur.execute(base_sql)
                except Exception:
                    pass
        conn.commit()
    except Exception:
        # nechceme zlomit request kvůli chybě v ALTER TABLE
        pass
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def ensure_user_stats_exists(user_id):
    _ensure_extended_columns()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM user_stats WHERE user_id = %s", (user_id,))
    exists = cur.fetchone()
    if not exists:
        cur.execute(
            "INSERT INTO user_stats (user_id, total_lessons_done, correct_answers, wrong_answers, total_learning_time, last_active, total_psani_words, first_activity, AI_poslech_minut) VALUES (%s, 0, 0, 0, 0, NOW(), 0, NULL, 0)",
            (user_id,)
        )
        conn.commit()
    cur.close()
    conn.close()


def add_learning_time(user_id, seconds):
    ensure_user_stats_exists(user_id)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE user_stats SET total_learning_time = total_learning_time + %s, last_active = NOW() WHERE user_id = %s",
        (int(seconds), user_id)
    )
    conn.commit()
    cur.close()
    conn.close()


def set_first_activity_if_needed(user_id):
    """Nastaví first_activity na aktuální čas, pokud ještě není nastaveno."""
    ensure_user_stats_exists(user_id)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT first_activity FROM user_stats WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    if row and row[0] is None:
        cur.execute("UPDATE user_stats SET first_activity = NOW() WHERE user_id = %s", (user_id,))
        conn.commit()
    cur.close()
    conn.close()


def update_user_stats(user_id, correct=0, wrong=0, lesson_done=False, psani_words=0, hangman_words_guessed=0,
                      irregular_verbs_guessed=0, irregular_verbs_wrong=0, pp_wrong=0, pp_maybe=0, pp_correct=0,
                      roleplaying_cr=0, roleplaying_mb=0, roleplaying_wr=0, lis_cor=0, lis_wr=0, at_cor=0, at_wr=0,
                      learning_time=None, set_first_activity=False, ai_poslech_minut=0, ai_poslech_seconds=0,
                      shw_cor=0, shw_mb=0, shw_wr=0, pds_cor=0, pds_wr=0,
                      ai_gram_cor=0, ai_gram_wr=0,
                      lesson_area_key: str | None = None):
    """
    Aktualizuje statistiky uživatele v user_stats.
    Důležité inkrementy: total_learning_time (sekundy), AI_poslech_seconds (sekundy pro AI Poslech), AI_poslech_minut (zpětná kompatibilita).
    Nové sloupce: shw_cor/shw_mb/shw_wr pro Shadow, pds_cor/pds_wr pro Podcast, ai_gram_cor/ai_gram_wr pro AI‑gramatiku.

    Navíc (skill-tree): pokud je předán `lesson_area_key`, zapíše se idempotentně do
    tabulky `user_lessons_completed`.
    """
    _ensure_extended_columns()
    ensure_user_stats_exists(user_id)

    # (hodnota, sloupec) — nenulové hodnoty se přičtou k příslušnému sloupci
    increments = [
        (correct, "correct_answers"),
        (wrong, "wrong_answers"),
        (psani_words, "total_psani_words"),
        (hangman_words_guessed, "hangman_words_guessed"),
        (irregular_verbs_guessed, "irregular_verbs_guessed"),
        (irregular_verbs_wrong, "irregular_verbs_wrong"),
        (pp_wrong, "pp_wrong"),
        (pp_maybe, "pp_maybe"),
        (pp_correct, "pp_correct"),
        (roleplaying_cr, "roleplaying_cr"),
        (roleplaying_mb, "roleplaying_mb"),
        (roleplaying_wr, "roleplaying_wr"),
        (lis_cor, "lis_cor"),
        (lis_wr, "lis_wr"),
        (at_cor, "at_cor"),
        (at_wr, "at_wr"),
        (ai_poslech_seconds, "AI_poslech_seconds"),
        (ai_poslech_minut, "AI_poslech_minut"),
        (shw_cor, "shw_cor"),
        (shw_mb, "shw_mb"),
        (shw_wr, "shw_wr"),
        (pds_cor, "pds_cor"),
        (pds_wr, "pds_wr"),
        (ai_gram_cor, "ai_gram_cor"),
        (ai_gram_wr, "ai_gram_wr"),
    ]

    updates = []
    params = []
    for value, column in increments:
        if value:
            updates.append(f"{column} = {column} + %s")
            params.append(int(value))
    if lesson_done:
        updates.append("total_lessons_done = total_lessons_done + 1")
    if learning_time is not None:
        updates.append("total_learning_time = total_learning_time + %s")
        params.append(int(learning_time))
    updates.append("last_active = NOW()")

    conn = get_db_connection()
    cur = conn.cursor()
    sql = f"UPDATE user_stats SET {', '.join(updates)} WHERE user_id = %s"
    params.append(user_id)
    cur.execute(sql, tuple(params))
    conn.commit()
    cur.close()
    conn.close()

    if lesson_area_key and isinstance(lesson_area_key, str) and lesson_area_key.strip():
        _record_lesson_completion(user_id, lesson_area_key.strip())

    if set_first_activity:
        set_first_activity_if_needed(user_id)


def _record_lesson_completion(user_id, area_key):
    """Skill-tree: idempotentní zápis dokončené lekce do user_lessons_completed."""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT IGNORE INTO user_lessons_completed (user_id, area_key) VALUES (%s, %s)",
            (user_id, area_key),
        )
        conn.commit()
    except Exception:
        # nechceme pokazit request, když se nepovede zapsat completion
        pass
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
