"""
Backendový systém pro správu XP a achievementů pro uživatele.
Používá MySQL a je určen pro integraci do Flask aplikace.
"""

from flask import Blueprint, session
from db import get_db_connection
import math
from flask import jsonify, request

xp_bp = Blueprint('xp', __name__)


# =======================
# Pomocné funkce
# =======================

def calculate_level(xp):
    """
    Výpočet levelu na základě XP.
    Můžeš změnit logiku podle potřeby (např. hranice levelů).
    Zde: level = floor(sqrt(xp / 10)) + 1
    """
    return int(math.floor(math.sqrt(xp / 10))) + 1


def get_user_xp_and_level(user_id):
    """
    Získá aktuální XP a level uživatele.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT xp, level FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return {"xp": row[0], "level": row[1]}
    return {"xp": 0, "level": 1}


# --- Seeding AI achievementů (idempotentně) ---
def _ensure_ai_achievements_seeded():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Minimální potřebné sloupce: code, name, description, condition_type, condition_value
        seeds = [
            ("AI_LISTEN_10MIN", "AI posluchač: 10 minut", "Mluv s AI alespoň 10 minut celkem.", "ai_poslech_seconds",
             600),
            ("AI_LISTEN_60MIN", "AI posluchač: 1 hodina", "Mluv s AI alespoň 60 minut celkem.", "ai_poslech_seconds",
             3600),
            ("AI_LISTEN_300MIN", "AI posluchač: 5 hodin", "Mluv s AI alespoň 300 minut celkem.", "ai_poslech_seconds",
             18000),
            ("AI_CHAT_100", "AI kecal: 100 zpráv", "Odešli 100 zpráv v AI chatu.", "ai_chat_messages", 100),
            ("AI_CHAT_500", "AI kecal: 500 zpráv", "Odešli 500 zpráv v AI chatu.", "ai_chat_messages", 500),
        ]
        for code, name, desc, ctype, cval in seeds:
            cur.execute("SELECT id FROM achievements WHERE code = %s", (code,))
            exists = cur.fetchone()
            if not exists:
                try:
                    cur.execute(
                        """
                        INSERT INTO achievements (code, name, description, condition_type, condition_value)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (code, name, desc, ctype, int(cval))
                    )
                except Exception:
                    # Pokud tabulka obsahuje jiné sloupce s NOT NULL bez defaultu, seeding přeskoč
                    conn.rollback()
                    continue
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        # Tichý fallback: pokud DB není k dispozici nebo schéma neodpovídá, nic nesemenuj
        pass


def _ensure_core_achievements_seeded():
    """Seed základních achievementů (XP, streak, obsahové metriky) idempotentně."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        seeds = [
            # XP milníky
            ("XP_100", "100 XP", "Získej celkem 100 XP.", "xp", 100),
            ("XP_500", "500 XP", "Získej celkem 200 XP.", "xp", 200),
            # ("XP_1000", "1000 XP", "Získej celkem 1000 XP.", "xp", 1000),
            # Streak
            ("STRK_3", "Streak 3", "Udrž si streak 3 dny.", "streak", 3),
            ("STRK_7", "Streak 7", "Udrž si streak 7 dní.", "streak", 7),
            ("STRK_30", "Streak 30", "Udrž si streak 1 celý měsíc!", "streak", 30),
            # Obsahové metriky (user_stats)
            ("LESSONS_10", "10 lekcí", "Dokonči 10 lekcí.", "total_lessons_done", 10),
            ("LESSONS_50", "50 lekcí", "Dokonči 50 lekcí.", "total_lessons_done", 50),
            ("HANG_20", "Šibenice: 20 slov", "Uhodni 20 slov v Hangmanu.", "hangman_words_guessed", 20),
            ("WRITE_1000", "Psaní: 1000 slov", "Napiš 1000 slov v Psaní.", "total_psani_words", 1000),
            ("SLOVNI_100", "Slovní Fotbal: 100 bodů", "Získej 100 bodů ve Slovní Fotbale.", "slovni_quick_points", 100),
            # Gramatika (předložky, present perfect) – více úrovní
            ("GRAM_AT_50", "Gramatika: Předložky 15", "Získej 15 správně v At/On/In.", "at_cor", 15),
            # ("GRAM_AT_200", "Gramatika: Předložky 200", "Získej 200 správně v At/On/In.", "at_cor", 200),
            # ("GRAM_AT_500", "Gramatika: Předložky 500", "Získej 500 správně v At/On/In.", "at_cor", 500),
            ("GRAM_PP_50", "Gramatika: Present Perfect 10", "Získej 10 správně v Present Perfect.", "pp_correct", 10),
            # ("GRAM_PP_200", "Gramatika: Present Perfect 200", "Získej 200 správně v Present Perfect.", "pp_correct",
            #  200),
            # Podcast – více úrovní
            ("PODCAST_20", "Podcast: 6 správně", "Získej 6 správně v kvízu u podcastů.", "pds_cor", 6),
            # ("PODCAST_100", "Podcast: 100 správně", "Získej 100 správně v kvízu u podcastů.", "pds_cor", 100),
            # ("PODCAST_300", "Podcast: 300 správně", "Získej 300 správně v kvízu u podcastů.", "pds_cor", 300),
        ]
        for code, name, desc, ctype, cval in seeds:
            try:
                cur.execute("SELECT id FROM achievements WHERE code = %s", (code,))
                exists = cur.fetchone()
                if not exists:
                    cur.execute(
                        """
                        INSERT INTO achievements (code, name, description, condition_type, condition_value)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (code, name, desc, ctype, int(cval))
                    )
            except Exception:
                conn.rollback()
                continue
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


def get_all_achievements():
    """
    Vrátí všechna achievementy jako seznam slovníků.
    """
    # Zajisti seed obou sad (AI i core)
    _ensure_ai_achievements_seeded()
    _ensure_core_achievements_seeded()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM achievements")
    achievements = cur.fetchall()
    cur.close()
    conn.close()
    return achievements


def get_user_achievements(user_id):
    """
    Vrátí seznam achievementů, které uživatel získal.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT a.* FROM achievements a
        JOIN user_achievements ua ON a.id = ua.achievement_id
        WHERE ua.user_id = %s
    """,
        (user_id,)
    )
    achievements = cur.fetchall()
    cur.close()
    conn.close()
    return achievements


def add_achievement_to_user(user_id, achievement_id):
    """
    Přidá achievement uživateli, pokud ho ještě nemá.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM user_achievements WHERE user_id = %s AND achievement_id = %s
    """,
        (user_id, achievement_id),
    )
    exists = cur.fetchone()
    if not exists:
        cur.execute(
            """
            INSERT INTO user_achievements (user_id, achievement_id, achieved_at)
            VALUES (%s, %s, NOW())
        """,
            (user_id, achievement_id),
        )
        conn.commit()
    cur.close()
    conn.close()


# =======================
# Hlavní funkce pro XP a achievementy
# =======================

def check_and_award_achievements(user_id, new_xp=None):
    """
    Zkontroluje, zda uživatel splnil podmínky pro nové achievementy.
    Vrací seznam nově získaných achievementů.
    """
    unlocked = []
    user_xp_level = get_user_xp_and_level(user_id)
    user_achievements = get_user_achievements(user_id)
    user_achievement_codes = {a['code'] for a in user_achievements}
    all_achievements = get_all_achievements()

    # Získání dalších údajů o uživateli pro různé typy achievementů
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user_row = cur.fetchone()
    cur.close()
    conn.close()

    # Načti user_stats jednou (pro obsahové metriky)
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM user_stats WHERE user_id = %s", (user_id,))
        stats_row = cur.fetchone() or {}
        cur.close()
        conn.close()
    except Exception:
        stats_row = {}

    for ach in all_achievements:
        if ach['code'] in user_achievement_codes:
            continue  # Už má

        ctype = ach.get('condition_type')
        cval = int(ach.get('condition_value') or 0)

        # XP achievement
        if ctype == 'xp':
            xp_value = new_xp if new_xp is not None else user_xp_level['xp']
            if xp_value >= cval:
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        # --- AI-specific: nasbírané sekundy z AI Poslech ---
        elif ctype == 'ai_poslech_seconds':
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT AI_poslech_seconds FROM user_stats WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
                cur.close()
                conn.close()
                secs = int(row[0]) if row and row[0] is not None else 0
            except Exception:
                secs = 0
            if secs >= cval:
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        # --- AI-specific: počet zpráv v komunitních AI chatech ---
        elif ctype == 'ai_chat_messages':
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                # Počítej uživatelské zprávy v tabulce chat_message (komunitní chat)
                cur.execute(
                    "SELECT COUNT(*) FROM chat_message WHERE user_id = %s AND (sender = 'user' OR sender = 'users')",
                    (user_id,),
                )
                count = int(cur.fetchone()[0])
                cur.close()
                conn.close()
            except Exception:
                count = 0
            if count >= cval:
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        # --- Streak ---
        elif ctype == 'streak':
            try:
                s = int(user_row.get('streak') or 0)
            except Exception:
                s = 0
            if s >= cval:
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        # --- Obecně: libovolný sloupec v user_stats ---
        else:
            try:
                val = int(stats_row.get(ctype) or 0)
            except Exception:
                val = 0
            if val >= cval:
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

    return unlocked


# Level jména (můžeš upravit podle libosti)
LEVEL_NAMES = [
    "Začátečník", "Učeň", "Student", "Pokročilý", "Expert", "Mistr", "Legenda"
]


def get_level_name(level):
    if level <= 1:
        return LEVEL_NAMES[0]
    elif level <= 2:
        return LEVEL_NAMES[1]
    elif level <= 4:
        return LEVEL_NAMES[2]
    elif level <= 6:
        return LEVEL_NAMES[3]
    elif level <= 8:
        return LEVEL_NAMES[4]
    elif level <= 10:
        return LEVEL_NAMES[5]
    else:
        return LEVEL_NAMES[6]


@xp_bp.context_processor
def inject_xp_info():
    user_id = session.get('user_id')
    if user_id:
        user_data = get_user_xp_and_level(user_id)
        xp = user_data.get("xp", 0)
        # Levely skrýváme: nevracíme je do kontextu, aby se v UI nezobrazovaly
        return dict(
            user_xp=xp
        )
    return {}


def add_xp_to_user(user_id, amount, reason=None):
    """
    Přidá XP uživateli a zkontroluje achievementy.
    Parametr `reason` je volitelný (pro kompatibilitu), aktuálně pouze ignorován.
    Pokud má uživatel aktivní XP booster, XP se násobí dvěma.
    Vrací nový stav XP a případné nové achievementy.
    """
    # Zjisti, zda má uživatel aktivní booster
    if is_xp_booster_active(user_id):
        amount = amount * 2

    current_level = 1
    current_xp = 0
    new_xp = None

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Načti aktuální XP a level
        cur.execute("SELECT xp, level FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return {"error": "user_not_found"}
        current_xp, current_level = int(row[0] or 0), int(row[1] or 1)
        gain = int(amount or 0)
        if gain <= 0:
            return {"xp": current_xp, "level": current_level, "new_achievements": []}

        new_xp = current_xp + gain
        # Levely již neřešíme – ponecháme beze změny
        cur.execute("UPDATE users SET xp = %s WHERE id = %s", (new_xp, user_id))
        conn.commit()
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass

    # Zkontroluj a uděl nově splněné achievementy
    newly_unlocked = check_and_award_achievements(user_id, new_xp=new_xp if new_xp is not None else current_xp) or []
    return {
        "xp": new_xp if new_xp is not None else current_xp,
        "level": current_level,  # pro kompatibilitu vracíme beze změny
        "new_achievements": newly_unlocked
    }


def is_xp_booster_active(user_id, on_date=None):
    """Vrátí True, pokud má uživatel aktivní XP booster k danému dni (default dnes)."""
    from datetime import date as _date
    conn = None
    cur = None
    on_date = on_date or _date.today()
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT COUNT(*) AS c FROM user_xp_booster
            WHERE user_id = %s AND active = TRUE AND start_date <= %s AND end_date >= %s
            """,
            (user_id, on_date, on_date)
        )
        row = cur.fetchone()
        return (row and int(row.get('c', 0)) > 0)
    except Exception:
        return False
    finally:
        try:
            if cur:
                cur.close()
            if conn:
                conn.close()
        except Exception:
            pass


def get_top_users(limit=10):
    """Vrátí top uživatele podle XP jako list dictů: id, first_name, last_name, xp."""
    limit = int(limit or 10)
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, first_name, last_name, xp FROM users ORDER BY xp DESC LIMIT %s",
            (limit,)
        )
        rows = cur.fetchall() or []
        return rows
    except Exception:
        return []
    finally:
        try:
            if cur:
                cur.close()
            if conn:
                conn.close()
        except Exception:
            pass


def get_user_keys(user_id: int) -> int:
    """Vrátí aktuální počet klíčů uživatele z tabulky user_keys (sloupec key_count)."""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT key_count FROM user_keys WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if not row or row[0] is None:
            return 0
        return int(row[0])
    except Exception:
        return 0
    finally:
        try:
            if cur:
                cur.close()
            if conn:
                conn.close()
        except Exception:
            pass


def add_user_keys(user_id: int, amount: int) -> int:
    """Navýší key_count v user_keys o amount a vrátí nový počet (při chybě vrací odhad)."""
    amount = int(amount or 0)
    if amount == 0:
        return get_user_keys(user_id)
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Zkus update; pokud nic neaktualizuje, vlož nový řádek
        cur.execute("UPDATE user_keys SET key_count = COALESCE(key_count,0) + %s WHERE user_id = %s",
                    (amount, user_id))
        if cur.rowcount == 0:
            cur.execute("INSERT INTO user_keys (user_id, key_count) VALUES (%s, %s)", (user_id, amount))
        conn.commit()
        return get_user_keys(user_id)
    except Exception:
        # fallback – vrať aktuální známý stav, i když se update nepovedl
        return get_user_keys(user_id)
    finally:
        try:
            if cur:
                cur.close()
            if conn:
                conn.close()
        except Exception:
            pass


@xp_bp.route('/grant_keys', methods=['POST'])
def grant_keys():
    """Backend endpoint pro přidání klíčů ke kolu štěstí.

    Očekává JSON body {"amount": <int>} (volitelné, default 5).
    Vrací JSON {status, key_count} pro aktuálně přihlášeného uživatele.
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"status": "error", "message": "Nejprve se přihlaste."}), 401

    data = request.get_json(silent=True) or {}
    try:
        amount = int(data.get('amount', 5))
    except Exception:
        amount = 5
    # bezpečnostní limit, aby někdo neposlal extrémní číslo
    if amount > 50:
        amount = 50
    if amount < 1:
        amount = 1

    new_count = add_user_keys(user_id, amount)
    return jsonify({
        "status": "success",
        "message": f"Přidáno {amount} klíčů.",
        "key_count": new_count
    })
