from datetime import date, timedelta
from db import get_db_connection
from obchod import get_user_shop_status


def use_freeze_if_available(user_id):
    """
    Pokud má uživatel dnes aktivní freeze, označí ho jako použitý a vrátí True.
    Jinak vrátí False.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id FROM user_freeze WHERE user_id = %s AND used = FALSE AND freeze_date = %s",
        (user_id, date.today())
    )
    freeze = cur.fetchone()
    if freeze:
        cur2 = conn.cursor()
        cur2.execute("UPDATE user_freeze SET used = TRUE WHERE id = %s", (freeze["id"],))
        conn.commit()
        cur2.close()
        cur.close()
        conn.close()
        return True
    cur.close()
    conn.close()
    return False


def update_user_streak(user_id):
    """
    Aktualizuje streak uživatele po splnění lekce.
    Vrací nový streak a informaci, zda byl streak prodloužen, restartován, freeze použit nebo už dnes splněn.
    """
    today = date.today()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT streak, last_streak_date FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()

    if not row:
        cur.close()
        conn.close()
        return {"error": "User not found"}

    last_date = row['last_streak_date']
    streak = row['streak'] or 0

    if last_date is None:
        # První lekce vůbec
        new_streak = 1
        status = "started"
    else:
        if isinstance(last_date, str):
            last_date = date.fromisoformat(last_date)
        elif hasattr(last_date, "date"):
            last_date = last_date.date()
        if last_date == today:
            # Už dnes splnil, streak se nemění
            new_streak = streak
            status = "already_done"
        elif last_date == today - timedelta(days=1):
            # Pokračuje streak
            new_streak = streak + 1
            status = "continued"
        else:
            # Vynechal den, streak začíná znovu, ale zkus použít freeze
            if use_freeze_if_available(user_id):
                # Freeze použit, streak se neresetuje, zůstává původní hodnota
                new_streak = streak
                status = "freeze_used"
            else:
                # Vynechal den, streak začíná znovu
                new_streak = 0
                status = "reset"

    # Uložení do DB pouze pokud se streak změnil nebo je první lekce nebo freeze použit
    if last_date != today or status == "freeze_used":
        cur2 = conn.cursor()
        cur2.execute("UPDATE users SET streak = %s, last_streak_date = %s WHERE id = %s", (new_streak, today, user_id))
        conn.commit()
        cur2.close()

    cur.close()
    conn.close()
    return {"streak": new_streak, "status": status}


def get_user_streak(user_id):
    """
    Vrací aktuální streak uživatele.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT streak FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else 0
