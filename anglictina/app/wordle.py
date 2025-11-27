from flask import Blueprint, render_template, session, jsonify, request
import json
import os
import random
from datetime import date

from xp import add_xp_to_user
from streak import update_user_streak
from db import get_db_connection

wordle_bp = Blueprint('wordle', __name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORD_LIST_PATH = os.path.join(BASE_DIR, 'static', 'wordle', 'wordle.json')


def load_words():
    with open(WORD_LIST_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_daily_key():
    """Jednoznačný klíč pro dnešní Wordle (stejný pro všechny)."""
    return f"wordle-{date.today().toordinal()}"


def get_daily_word():
    words = load_words()
    today = date.today().toordinal()
    random.seed(today)
    return random.choice(words).lower()


def get_user_id():
    return session.get('user_id')


def ensure_user_stats_wordle_columns():
    """Zajistí existenci sloupců pro Wordle v tabulce user_stats (idempotentně)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            db_name = os.environ.get('DB_NAME')
            # Získej existující sloupce
            cur.execute(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'user_stats'",
                (db_name,)
            )
            cols = {row[0] for row in cur.fetchall()}
            altered = False
            if 'wordle_last_key' not in cols:
                cur.execute("ALTER TABLE user_stats ADD COLUMN wordle_last_key VARCHAR(64) NULL")
                altered = True
            if 'wordle_guesses' not in cols:
                cur.execute("ALTER TABLE user_stats ADD COLUMN wordle_guesses INT DEFAULT 0")
                altered = True
            if 'wordle_completed' not in cols:
                cur.execute("ALTER TABLE user_stats ADD COLUMN wordle_completed TINYINT(1) DEFAULT 0")
                altered = True
            if altered:
                conn.commit()
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        # Pokud se nepodaří, necháme fallback do session v logice volající funkce
        pass


def get_or_create_wordle_state():
    """Vrátí stav Wordle pro aktuálního uživatele (i anonymního).

    Přihlášený uživatel: stav se uloží do DB tabulky user_stats (do sloupců
    wordle_last_key, wordle_guesses, wordle_completed).
    Nepřihlášený: stav se drží v session pod klíčem 'wordle_state'.
    """
    daily_key = get_daily_key()
    uid = get_user_id()

    # Přihlášený uživatel -> DB (s fallbackem do session, když DB selže)
    if uid:
        try:
            ensure_user_stats_wordle_columns()
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            try:
                cur.execute(
                    "SELECT wordle_last_key, wordle_guesses, wordle_completed FROM user_stats WHERE user_id = %s",
                    (uid,))
                row = cur.fetchone()
                if not row:
                    cur.execute(
                        "INSERT INTO user_stats (user_id, wordle_last_key, wordle_guesses, wordle_completed) "
                        "VALUES (%s, %s, %s, %s)",
                        (uid, daily_key, 0, False)
                    )
                    conn.commit()
                    state = {"key": daily_key, "guesses": 0, "completed": False}
                else:
                    if row.get('wordle_last_key') != daily_key:
                        # nový den -> reset pokusů
                        cur.execute(
                            "UPDATE user_stats SET wordle_last_key = %s, wordle_guesses = %s, wordle_completed = %s "
                            "WHERE user_id = %s",
                            (daily_key, 0, False, uid)
                        )
                        conn.commit()
                        state = {"key": daily_key, "guesses": 0, "completed": False}
                    else:
                        state = {
                            "key": row.get('wordle_last_key'),
                            "guesses": int(row.get('wordle_guesses') or 0),
                            "completed": bool(row.get('wordle_completed')),
                        }
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
            return state
        except Exception as ex:
            try:
                print(f"[wordle] DB selhala, přepínám na session: {ex}")
            except Exception:
                pass

    # Nepřihlášený uživatel -> session (nebo fallback pro přihlášeného, když DB selže)
    sess_state = session.get('wordle_state') or {}
    if sess_state.get('key') != daily_key:
        sess_state = {"key": daily_key, "guesses": 0, "completed": False}
        session['wordle_state'] = sess_state
    return sess_state


def save_wordle_state(state):
    """Persistuje stav Wordle (DB nebo session)."""
    daily_key = get_daily_key()
    uid = get_user_id()

    if uid:
        try:
            ensure_user_stats_wordle_columns()
            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE user_stats SET wordle_last_key = %s, wordle_guesses = %s, wordle_completed = %s "
                    "WHERE user_id = %s",
                    (daily_key, int(state.get('guesses') or 0), bool(state.get('completed')), uid)
                )
                conn.commit()
                return
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as ex:
            try:
                print(f"[wordle] Uložení do DB selhalo, ukládám do session: {ex}")
            except Exception:
                pass

    # Session fallback
    session['wordle_state'] = state


@wordle_bp.route('/wordle')
def wordle_page():
    return render_template('wordle/wordle.html')


@wordle_bp.route('/wordle/word', methods=['GET'])
def get_wordle_word():
    word = get_daily_word()
    state = get_or_create_wordle_state()
    return jsonify({
        "length": len(word),
        "completed": state.get('completed', False),
        "guesses": state.get('guesses', 0)
    })


@wordle_bp.route('/wordle/guess', methods=['POST'])
def check_guess():
    state = get_or_create_wordle_state()

    # Pokud už dnešní Wordle dokončil (výhra nebo prohra), nepustíme dál
    if state.get('completed'):
        return jsonify({
            "error": "already_completed",
            "message": "Dnešní Wordle už máš dohraný. Zkus to zase zítra!"
        }), 400

    data = request.get_json() or {}
    guess = (data.get('guess') or '').strip().lower()
    if len(guess) != 5:
        return jsonify({"error": "length"}), 400

    target = get_daily_word()

    result = []
    target_chars = list(target)

    for i, ch in enumerate(guess):
        if ch == target[i]:
            result.append({"letter": ch, "status": "correct"})
            target_chars[i] = None
        else:
            result.append({"letter": ch, "status": "absent"})

    for i, item in enumerate(result):
        if item["status"] == "absent" and item["letter"] in target_chars:
            item["status"] = "present"
            target_chars[target_chars.index(item["letter"])] = None

    # aktualizace stavu
    state['guesses'] = int(state.get('guesses') or 0) + 1

    win = (guess == target)
    xp_awarded = 0
    streak_info = None

    if win or state['guesses'] >= 6:
        state['completed'] = True

        # XP + streak jen při prvním dokončení dne a jen pro přihlášené
        uid = get_user_id()
        if uid:
            try:
                xp_awarded = 5 if win else 2
                add_xp_to_user(uid, xp_awarded, reason='wordle')
            except Exception:
                xp_awarded = 0
            try:
                streak_info = update_user_streak(uid)
            except Exception:
                streak_info = None

    save_wordle_state(state)

    return jsonify({
        "result": result,
        "win": win,
        "completed": state.get('completed', False),
        "guesses": state.get('guesses', 0),
        "xp_awarded": xp_awarded,
        "streak": streak_info
    })
