from datetime import date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from db import get_db_connection
from xp import get_user_xp_and_level
import random
from xp import add_xp_to_user, get_all_achievements, get_user_achievements, add_achievement_to_user

FREEZE_COST = 50  # XP cena za freeze
XP_BOOSTER_COST = 100  # XP cena za booster
XP_BOOSTER_DURATION_DAYS = 1  # Booster trvá 1 den
FREEZE_MAX_COUNT = 3  # Maximální počet freeze

obchod_bp = Blueprint('obchod', __name__, template_folder='templates')

LEVEL_NAMES = [
    "Začátečník", "Učeň", "Student", "Pokročilý", "Expert", "Mistr", "Legenda"
]


def get_user_key_count(user_id):
    """Získá aktuální počet klíčů uživatele (user_keys.key_count). Zajistí existenci řádku."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT IGNORE INTO user_keys (user_id, key_count) VALUES (%s, 0)", (user_id,))
        conn.commit()
        cur.execute("SELECT key_count FROM user_keys WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        count = int(row[0]) if row else 0
        cur.close()
        conn.close()
        return count
    except Exception:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
        return 0


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


@obchod_bp.context_processor
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


@obchod_bp.route('/obchod')
def obchod():
    user_id = session.get("user_id")
    if not user_id:
        flash("Nejste přihlášeni.", "danger")
        return redirect(url_for("auth.login"))

    status = get_user_shop_status(user_id)

    return render_template(
        "obchod.html",
        shop_status=status,
        FREEZE_COST=FREEZE_COST,
        XP_BOOSTER_COST=XP_BOOSTER_COST
    )


@obchod_bp.route('/buy_item', methods=['POST'])
def buy_item():
    """Route pro nákup položek - s CSRF ochranou"""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({'status': 'error', 'message': 'Nejste přihlášeni'}), 401

    try:
        data = request.get_json()
        item = data.get('item', '').strip()

        if item == "freeze":
            result = buy_freeze(user_id)
        elif item == "xp_booster":
            result = buy_xp_booster(user_id)
        else:
            return jsonify({'status': 'error', 'message': 'Neplatná položka'}), 400

        if "error" in result:
            return jsonify({'status': 'error', 'message': result["error"]}), 400
        else:
            return jsonify({'status': 'success', 'message': result.get("message", "Nákup proběhl úspěšně.")})

    except Exception as e:
        print("Chyba v buy_item route:", str(e))
        return jsonify({'status': 'error', 'message': 'Nastala chyba při zpracování požadavku'}), 500


def get_user_shop_status(user_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT xp, level FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if not user:
        cur.close()
        conn.close()
        return {"error": "User not found"}

    # zajistit existenci záznamu v user_keys a načíst počet klíčů
    try:
        cur2 = conn.cursor()
        cur2.execute("INSERT IGNORE INTO user_keys (user_id, key_count) VALUES (%s, 0)", (user_id,))
        conn.commit()
        cur2.execute("SELECT key_count FROM user_keys WHERE user_id = %s", (user_id,))
        rowk = cur2.fetchone()
        key_count = int(rowk[0]) if rowk else 0
        cur2.close()
    except Exception:
        key_count = 0

    cur.execute(
        "SELECT COUNT(*) AS freeze_count FROM user_freeze WHERE user_id = %s AND used = FALSE AND freeze_date >= %s",
        (user_id, date.today())
    )
    freeze_count = cur.fetchone()["freeze_count"]

    cur.execute(
        "SELECT COUNT(*) AS booster_active FROM user_xp_booster WHERE user_id = %s AND active = TRUE AND start_date <= %s AND end_date >= %s",
        (user_id, date.today(), date.today())
    )
    booster_active = cur.fetchone()["booster_active"] > 0

    cur.close()
    conn.close()
    return {
        "xp": user["xp"],
        "level": user["level"],
        "freeze_count": freeze_count,
        "xp_booster_active": booster_active,
        "key_count": key_count
    }


def buy_freeze(user_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT xp, level FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if not user:
        cur.close()
        conn.close()
        return {"error": "Uživatel nenalezen"}

    # Zjisti počet nevyužitých freeze
    cur.execute(
        "SELECT COUNT(*) AS freeze_count FROM user_freeze WHERE user_id = %s AND used = FALSE AND freeze_date >= %s",
        (user_id, date.today())
    )
    freeze_count = cur.fetchone()["freeze_count"]
    if freeze_count >= FREEZE_MAX_COUNT:
        cur.close()
        conn.close()
        return {"error": f"Nelze koupit více než {FREEZE_MAX_COUNT} freeze. Nejprve nějaký použij."}

    if user["xp"] < FREEZE_COST:
        cur.close()
        conn.close()
        return {"error": "Nedostatek XP"}

    new_level = user["level"] - 1 if user["level"] > 1 else 1

    cur2 = conn.cursor()
    cur2.execute("UPDATE users SET xp = xp - %s, level = %s WHERE id = %s", (FREEZE_COST, new_level, user_id))
    cur2.execute(
        "INSERT INTO user_freeze (user_id, freeze_date, used) VALUES (%s, %s, FALSE)",
        (user_id, date.today())
    )
    conn.commit()
    cur2.close()
    cur.close()
    conn.close()
    return {"success": True, "message": "Freeze aktivován na dnešní den. (Level -1)"}


def buy_xp_booster(user_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT xp, level FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if not user or user["xp"] < XP_BOOSTER_COST:
        cur.close()
        conn.close()
        return {"error": "Nedostatek XP"}

    today = date.today()
    end_date = today + timedelta(days=XP_BOOSTER_DURATION_DAYS - 1)
    new_level = user["level"] - 1 if user["level"] > 1 else 1

    cur2 = conn.cursor()
    cur2.execute("UPDATE users SET xp = xp - %s, level = %s WHERE id = %s", (XP_BOOSTER_COST, new_level, user_id))
    cur2.execute(
        "INSERT INTO user_xp_booster (user_id, start_date, end_date, active) VALUES (%s, %s, %s, TRUE)",
        (user_id, today, end_date)
    )
    conn.commit()
    cur2.close()
    cur.close()
    conn.close()
    return {"success": True, "message": f"XP Booster aktivován do {end_date}. (Level -1)"}


@obchod_bp.route('/spin_wheel', methods=['POST'])
def spin_wheel():
    """Kolo štěstí – spotřebuje 1 klíč a udělí náhodnou odměnu.
    Možné výsledky: freeze, xp_boost, xp_100, achievement, key, nothing, +1 streak
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'status': 'error', 'message': 'Nejste přihlášeni'}), 401

    # Základní pravděpodobnosti (rovnoměrně)
    prizes = ['freeze', 'xp_boost', 'xp_25', 'achievement', 'key', 'nothing', 'streak']
    weights = [1, 1, 1, 1, 1, 1, 1]

    conn = None
    cur = None
    today = date.today()
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        # zajisti existenci řádku v user_keys a pokus o odečtení 1 klíče
        cur.execute("INSERT IGNORE INTO user_keys (user_id, key_count) VALUES (%s, 0)", (user_id,))
        conn.commit()
        cur.execute("UPDATE user_keys SET key_count = key_count - 1 WHERE user_id = %s AND key_count >= 1", (user_id,))
        if cur.rowcount == 0:
            cur.execute("SELECT key_count FROM user_keys WHERE user_id = %s", (user_id,))
            rowk = cur.fetchone()
            remaining = int(rowk['key_count']) if rowk and rowk.get('key_count') is not None else 0
            return jsonify({'status': 'error', 'message': 'Nemáte dostatek klíčů.', 'key_count': remaining}), 400

        # náhodný výběr výhry
        prize = random.choices(prizes, weights=weights, k=1)[0]
        message = ''

        # aplikace výhry
        if prize == 'freeze':
            try:
                cur2 = conn.cursor()
                cur2.execute("INSERT INTO user_freeze (user_id, freeze_date, used) VALUES (%s, %s, FALSE)",
                             (user_id, today))
                conn.commit()
                cur2.close()
                message = 'Získal(a) jsi 1× Freeze na dnešek.'
            except Exception:
                message = 'Získal(a) jsi 1× Freeze (zápis selhal, zkus později).'
        elif prize == 'xp_boost':
            try:
                # pokud je booster aktivní, prodluž o 1 den, jinak založ nový
                cur2 = conn.cursor(dictionary=True)
                cur2.execute(
                    "SELECT id, end_date FROM user_xp_booster WHERE user_id=%s AND active=TRUE AND end_date >= %s ORDER BY end_date DESC LIMIT 1",
                    (user_id, today))
                rowb = cur2.fetchone()
                if rowb:
                    new_end = (rowb['end_date'] + timedelta(days=1)) if rowb.get('end_date') else today
                    cur2.execute("UPDATE user_xp_booster SET end_date=%s WHERE id=%s", (new_end, rowb['id']))
                else:
                    start_date = today
                    end_date = today + timedelta(days=XP_BOOSTER_DURATION_DAYS - 1)
                    cur2.execute(
                        "INSERT INTO user_xp_booster (user_id, start_date, end_date, active) VALUES (%s,%s,%s,TRUE)",
                        (user_id, start_date, end_date))
                conn.commit()
                cur2.close()
                message = 'Získal(a) jsi XP Booster (+1 den).'
            except Exception:
                message = 'Výhra XP Booster – zápis se nepodařil.'
        elif prize == 'xp_25':
            try:
                add_xp_to_user(user_id, 25)
                message = 'Získal(a) jsi +25 XP.'
            except Exception:
                message = 'Výhra +25 XP – nepodařilo se připsat.'
        elif prize == 'achievement':
            try:
                all_ach = get_all_achievements() or []
                owned = {a['id'] for a in (get_user_achievements(user_id) or [])}
                candidates = [a for a in all_ach if a.get('id') not in owned]
                if candidates:
                    chosen = random.choice(candidates)
                    add_achievement_to_user(user_id, chosen.get('id'))
                    message = f"Získal(a) jsi achievement: {chosen.get('name', 'tajný')}!"
                else:
                    add_xp_to_user(user_id, 50)
                    message = 'Všechny achievementy už máš – místo toho +50 XP.'
            except Exception:
                message = 'Výhra achievement – nepodařilo se připsat.'
        elif prize == 'key':
            try:
                cur2 = conn.cursor()
                cur2.execute("UPDATE user_keys SET key_count = key_count + 1 WHERE user_id = %s", (user_id,))
                conn.commit()
                cur2.close()
                message = 'Získal(a) jsi +1 klíč (návrat).'
            except Exception:
                message = 'Výhra klíč – nepodařilo se připsat.'
        elif prize == 'nothing':
            message = 'Tentokrát nic – zkus štěstí znovu.'
        elif prize == 'streak':
            try:
                cur2 = conn.cursor()
                cur2.execute("UPDATE users SET streak = COALESCE(streak,0) + 1, last_streak_date = %s WHERE id = %s",
                             (today, user_id))
                conn.commit()
                cur2.close()
                message = 'Získal(a) jsi +1 k aktuálnímu streaku.'
            except Exception:
                message = 'Výhra +1 streak – nepodařilo se připsat.'
        else:
            message = 'Neznámá výhra.'

        # načti nový počet klíčů
        cur.execute("SELECT key_count FROM user_keys WHERE user_id = %s", (user_id,))
        rowk2 = cur.fetchone()
        remaining = int(rowk2['key_count']) if rowk2 and rowk2.get('key_count') is not None else 0
        return jsonify({'status': 'success', 'prize': prize, 'message': message, 'key_count': remaining})
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        return jsonify({'status': 'error', 'message': 'Chyba při točení kola.'}), 500
    finally:
        try:
            if cur: cur.close()
            if conn: conn.close()
        except Exception:
            pass
