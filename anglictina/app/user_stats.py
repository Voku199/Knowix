from db import get_db_connection


def _ensure_extended_columns():
    """Zajistí nové sloupce pro shadow a podcast statistiky (idempotentně)."""
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
        cur.close()
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
                      ai_gram_cor=0, ai_gram_wr=0):
    """
    Aktualizuje statistiky uživatele v user_stats.
    Důležité inkrementy: total_learning_time (sekundy), AI_poslech_seconds (sekundy pro AI Poslech), AI_poslech_minut (zpětná kompatibilita).
    Nové sloupce: shw_cor/shw_mb/shw_wr pro Shadow, pds_cor/pds_wr pro Podcast, ai_gram_cor/ai_gram_wr pro AI‑gramatiku.
    """
    _ensure_extended_columns()
    ensure_user_stats_exists(user_id)
    conn = get_db_connection()
    cur = conn.cursor()
    updates = []
    params = []

    if correct:
        updates.append("correct_answers = correct_answers + %s")
        params.append(int(correct))
    if wrong:
        updates.append("wrong_answers = wrong_answers + %s")
        params.append(int(wrong))
    if lesson_done:
        updates.append("total_lessons_done = total_lessons_done + 1")
    if psani_words:
        updates.append("total_psani_words = total_psani_words + %s")
        params.append(int(psani_words))
    if hangman_words_guessed:
        updates.append("hangman_words_guessed = hangman_words_guessed + %s")
        params.append(int(hangman_words_guessed))
    if irregular_verbs_guessed:
        updates.append("irregular_verbs_guessed = irregular_verbs_guessed + %s")
        params.append(int(irregular_verbs_guessed))
    if irregular_verbs_wrong:
        updates.append("irregular_verbs_wrong = irregular_verbs_wrong + %s")
        params.append(int(irregular_verbs_wrong))
    if pp_wrong:
        updates.append("pp_wrong = pp_wrong + %s")
        params.append(int(pp_wrong))
    if pp_maybe:
        updates.append("pp_maybe = pp_maybe + %s")
        params.append(int(pp_maybe))
    if pp_correct:
        updates.append("pp_correct = pp_correct + %s")
        params.append(int(pp_correct))
    if roleplaying_cr:
        updates.append("roleplaying_cr = roleplaying_cr + %s")
        params.append(int(roleplaying_cr))
    if roleplaying_mb:
        updates.append("roleplaying_mb = roleplaying_mb + %s")
        params.append(int(roleplaying_mb))
    if roleplaying_wr:
        updates.append("roleplaying_wr = roleplaying_wr + %s")
        params.append(int(roleplaying_wr))
    if lis_cor:
        updates.append("lis_cor = lis_cor + %s")
        params.append(int(lis_cor))
    if lis_wr:
        updates.append("lis_wr = lis_wr + %s")
        params.append(int(lis_wr))
    if at_cor:
        updates.append("at_cor = at_cor + %s")
        params.append(int(at_cor))
    if at_wr:
        updates.append("at_wr = at_wr + %s")
        params.append(int(at_wr))
    if ai_poslech_seconds:
        updates.append("AI_poslech_seconds = AI_poslech_seconds + %s")
        params.append(int(ai_poslech_seconds))
    if ai_poslech_minut:
        updates.append("AI_poslech_minut = AI_poslech_minut + %s")
        params.append(int(ai_poslech_minut))

    # Nové: Shadow a Podcast sloupce
    if shw_cor:
        updates.append("shw_cor = shw_cor + %s")
        params.append(int(shw_cor))
    if shw_mb:
        updates.append("shw_mb = shw_mb + %s")
        params.append(int(shw_mb))
    if shw_wr:
        updates.append("shw_wr = shw_wr + %s")
        params.append(int(shw_wr))
    if pds_cor:
        updates.append("pds_cor = pds_cor + %s")
        params.append(int(pds_cor))
    if pds_wr:
        updates.append("pds_wr = pds_wr + %s")
        params.append(int(pds_wr))

    # Nové: AI‑gramatika agregace
    if ai_gram_cor:
        updates.append("ai_gram_cor = ai_gram_cor + %s")
        params.append(int(ai_gram_cor))
    if ai_gram_wr:
        updates.append("ai_gram_wr = ai_gram_wr + %s")
        params.append(int(ai_gram_wr))

    if learning_time is not None:
        updates.append("total_learning_time = total_learning_time + %s")
        params.append(int(learning_time))

    updates.append("last_active = NOW()")

    if not updates:
        cur.execute(
            "UPDATE user_stats SET last_active = NOW() WHERE user_id = %s",
            (user_id,)
        )
    else:
        sql = f"UPDATE user_stats SET {', '.join(updates)} WHERE user_id = %s"
        params.append(user_id)
        cur.execute(sql, tuple(params))
    conn.commit()
    cur.close()
    conn.close()

    if set_first_activity:
        set_first_activity_if_needed(user_id)
