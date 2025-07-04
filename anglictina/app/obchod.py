from datetime import date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from db import get_db_connection

FREEZE_COST = 50  # XP cena za freeze
XP_BOOSTER_COST = 100  # XP cena za booster
XP_BOOSTER_DURATION_DAYS = 1  # Booster trvá 1 den
FREEZE_MAX_COUNT = 3  # Maximální počet freeze

obchod_bp = Blueprint('obchod', __name__, template_folder='templates')


@obchod_bp.route('/obchod', methods=['GET', 'POST'])
def obchod():
    user_id = session.get("user_id")
    if not user_id:
        flash("Nejste přihlášeni.", "danger")
        return redirect(url_for("auth.login"))  # nebo jiná vaše login route

    status = get_user_shop_status(user_id)
    message = None
    message_type = "success"

    if request.method == "POST":
        item = request.form.get("item")
        if item == "freeze":
            result = buy_freeze(user_id)
        elif item == "xp_booster":
            result = buy_xp_booster(user_id)
        else:
            result = {"error": "Neplatná položka"}

        if "error" in result:
            message = result["error"]
            message_type = "danger"
        else:
            message = result.get("message", "Nákup proběhl úspěšně.")
        # Po nákupu znovu načteme stav
        status = get_user_shop_status(user_id)

    return render_template(
        "obchod.html",
        shop_status=status,
        message=message,
        message_type=message_type,
        FREEZE_COST=FREEZE_COST,
        XP_BOOSTER_COST=XP_BOOSTER_COST
    )


def get_user_shop_status(user_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT xp, level FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if not user:
        cur.close()
        conn.close()
        return {"error": "User not found"}

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
        "xp_booster_active": booster_active
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
