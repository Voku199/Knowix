"""
Backendový systém pro správu XP, levelů a achievementů pro uživatele.
Používá MySQL a je určen pro integraci do Flask aplikace.
"""

from flask import Blueprint, jsonify, request, session
from db import get_db_connection
import math
from datetime import date
from streak import update_user_streak

# streak_info = {"streak": 5, "status": "continued"}

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


def get_all_achievements():
    """
    Vrátí všechna achievementy jako seznam slovníků.
    """
    # Zajisti, že AI achievementy jsou nasemínované (bezpečně a idempotentně)
    _ensure_ai_achievements_seeded()
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

    # Získání pořadí v žebříčku (pro leaderboard achievement)
    def is_first_in_leaderboard(user_id):
        top_users = get_top_users(1)
        return top_users and top_users[0]['id'] == user_id

    for ach in all_achievements:
        if ach['code'] in user_achievement_codes:
            continue  # Už má

        # XP achievement
        if ach['condition_type'] == 'xp':
            xp_value = new_xp if new_xp is not None else user_xp_level['xp']
            if xp_value >= ach['condition_value']:
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        # Level achievement
        elif ach['condition_type'] == 'lvl':
            level_value = user_xp_level['level']
            if level_value >= ach['condition_value']:
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        # --- AI-specific: nasbírané sekundy z AI Poslech ---
        elif ach['condition_type'] == 'ai_poslech_seconds':
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
            if secs >= int(ach['condition_value'] or 0):
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        # --- AI-specific: počet zpráv v komunitních AI chatech ---
        elif ach['condition_type'] == 'ai_chat_messages':
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
            if count >= int(ach['condition_value'] or 0):
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        elif ach['condition_type'] == 'feedback':
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM feedback WHERE user_id = %s", (user_id,))
            count = cur.fetchone()[0]
            print(
                f"DEBUG: Uživatel {user_id} má {count} feedbacků, potřebuje {ach['condition_value']} pro achievement {ach['code']}")
            cur.close()
            conn.close()
            if count >= ach['condition_value']:
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        # Feedback rating achievement (uživatel napsal recenzi s určitým ratingem, např. 5 hvězd)
        elif ach['condition_type'] == 'feedback_rating':
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM feedback WHERE user_id = %s AND rating = %s",
                        (user_id, ach['condition_value']))
            count = cur.fetchone()[0]
            cur.close()
            conn.close()
            if count >= 1:
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        elif ach['condition_type'] == 'feedback_edited':
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM feedback WHERE user_id = %s AND is_edited = 1", (user_id,))
            count = cur.fetchone()[0]
            cur.close()
            conn.close()
            if count >= ach['condition_value']:
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        # Profil achievement (uživatel nahrál profilovku)
        elif ach['condition_type'] == 'profile':
            if user_row and user_row.get('profile_pic') and user_row['profile_pic'] != 'default.jpg':
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        # Theme achievement (uživatel nastavil tmavý režim)
        elif ach['condition_type'] == 'theme':
            if user_row and user_row.get('theme_mode') == 'dark':
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        # Leaderboard achievement (uživatel je první v žebříčku)
        elif ach['condition_type'] == 'leaderboard':
            if is_first_in_leaderboard(user_id):
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        # Easter egg: datum narození shodné s majitelem (např. 2010-10-15)
        elif ach['condition_type'] == 'easter_birthday':
            if user_row and str(user_row.get('birthdate')) == '2010-10-15':
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        # Easter egg: profilovka houdek.jpg
        elif ach['condition_type'] == 'easter_houdek':
            if user_row and user_row.get('profile_pic') == 'houdek.jpg':
                add_achievement_to_user(user_id, ach['id'])
                unlocked.append(ach)

        # Další typy lze přidat zde...
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
        level = user_data.get("level", 1)
        xp_in_level = xp % 50
        percent = int((xp_in_level / 50) * 100)
        level_name = get_level_name(level)
        return dict(
            user_xp=xp,
            user_level=level,
            user_level_name=level_name,
            user_progress_percent=percent,
            user_xp_in_level=xp_in_level
        )
    return {}


def add_xp_to_user(user_id, amount):
    """
    Přidá XP uživateli, aktualizuje level a zkontroluje achievementy.
    Pokud má uživatel aktivní XP booster, XP se násobí dvěma.
    Vrací nový stav XP, level a případné nové achievementy.
    """
    # Zjisti, zda má uživatel aktivní booster
    if is_xp_booster_active(user_id):
        amount = amount * 2

    conn = get_db_connection()
    cur = conn.cursor()
    # Získání aktuálních XP
    cur.execute("SELECT xp FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return {"error": "User not found"}

    old_xp = row[0]
    new_xp = old_xp + amount
    new_level = calculate_level(new_xp)

    # Aktualizace XP a levelu
    cur.execute("UPDATE users SET xp = %s, level = %s WHERE id = %s", (new_xp, new_level, user_id))
    conn.commit()
    cur.close()
    conn.close()

    # Kontrola achievementů
    unlocked = check_and_award_achievements(user_id, new_xp=new_xp)

    return {
        "xp": new_xp,
        "level": new_level,
        "new_achievements": unlocked
    }


def is_xp_booster_active(user_id):
    """
    Vrací True, pokud má uživatel dnes aktivní XP booster.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) FROM user_xp_booster
        WHERE user_id = %s AND active = TRUE AND start_date <= %s AND end_date >= %s
    """,
        (user_id, date.today(), date.today()),
    )
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result[0] > 0


def get_top_users(limit=10):
    """
    Vrátí seznam top uživatelů podle XP, včetně streaku.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT id, first_name, last_name, xp, level, profile_pic, streak
        FROM users
        ORDER BY xp DESC, id ASC
        LIMIT %s
    """,
        (limit,),
    )
    users = cur.fetchall()
    cur.close()
    conn.close()
    return users


@xp_bp.route('/api/top-users', methods=['GET'])
def api_top_users():
    """
    Vrátí top 10 uživatelů podle XP.
    """
    users = get_top_users(10)
    # Sestavíme display_name a profilovku
    for u in users:
        u['display_name'] = f"{u['first_name']} {u['last_name']}"
        u['profile_pic'] = u.get('profile_pic') or 'default.jpg'
    return jsonify({"top_users": users})


# =======================
# API endpointy (volitelné)
# =======================


@xp_bp.route('/api/user/xp', methods=['POST'])
def api_add_xp():
    """
    Přidá XP uživateli (vyžaduje user_id v session).
    JSON: { "amount": 50 }
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json()
    amount = int(data.get('amount', 0))
    if amount <= 0:
        return jsonify({"error": "Invalid XP amount"}), 400

    result = add_xp_to_user(user_id, amount)
    return jsonify(result)


@xp_bp.route('/api/user/achievements', methods=['GET'])
def api_get_achievements():
    """
    Vrátí seznam achievementů uživatele.
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401

    achievements = get_user_achievements(user_id)
    return jsonify({"achievements": achievements})


@xp_bp.route('/api/achievements', methods=['GET'])
def api_all_achievements():
    """
    Vrátí všechna achievementy v systému.
    """
    return jsonify({"achievements": get_all_achievements()})

# =======================
# Příklad použití v aplikaci:
# =======================
# from xp_system import xp_bp
# app.register_blueprint(xp_bp)
#
# # Přidání XP uživateli:
# add_xp_to_user(user_id, 50)
#
# # Získání achievementů:
# get_user_achievements(user_id)
#
# # Přidání XP přes API:
# POST /api/user/xp  { "amount": 50 }
#
# # Získání achievementů uživatele:
# GET /api/user/achievements
