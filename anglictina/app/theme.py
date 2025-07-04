from flask import Blueprint, session, jsonify, request
from db import get_db_connection

theme_bp = Blueprint("theme", __name__)


@theme_bp.route("/toggle_theme", methods=["POST"])
def toggle_theme():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Nepřihlášen"}), 401

    user_id = session['user_id']
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Zjisti aktuální režim
        cursor.execute("SELECT theme_mode FROM users WHERE id = %s", (user_id,))
        current = cursor.fetchone()["theme_mode"]
        new_mode = "dark" if current == "light" else "light"

        # Ulož nový režim
        cursor.execute("UPDATE users SET theme_mode = %s WHERE id = %s", (new_mode, user_id))
        conn.commit()

        return jsonify({"status": "ok", "theme": new_mode})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
