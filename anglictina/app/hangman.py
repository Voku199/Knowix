from flask import Blueprint, session, render_template, request, jsonify
import json
import random
from auth import get_db_connection

hangman_bp = Blueprint("hangman", __name__, template_folder="templates")


def load_words():
    with open("static/hangman/hangman_words.json", "r", encoding="utf-8") as f:
        return json.load(f)


def get_random_word(used_words, user_level):
    words = load_words()
    levels = allowed_levels(user_level)

    filtered_words = [w for w in words if w["level"] in levels and w["word"] not in used_words]

    if not filtered_words:
        return None

    return random.choice(filtered_words)


def allowed_levels(level):
    if level is None:
        return ["A1", "A2", "B1", "B2"]

    level = level.upper()

    if level == "A1":
        return ["A1", "A2"]
    elif level == "A2":
        return ["A1", "A2", "B1"]
    elif level == "B1":
        return ["A2", "B1", "B2"]
    elif level == "B2":
        return ["B1", "B2", "C1"]
    elif level in ["C1", "C2"]:
        return ["A1", "A2", "B1", "B2", "C1", "C2"]
    else:
        return ["A1", "A2", "B1", "B2", "C1", "C2"]


@hangman_bp.route("/hangman")
def hangman_game():
    session.setdefault("used_words", [])
    return render_template("hangman/hangman.html")


def get_masked_word(word, guessed_letters):
    return ' '.join(
        ''.join(
            c if not c.isalpha() or c.lower() in guessed_letters else '_'
            for c in part
        )
        for part in word.split(' ')
    )


@hangman_bp.route("/hangman/start", methods=["GET"])
def start_game():
    user_id = session.get("user_id")

    if user_id:
        # Připojení k DB a načtení english_level
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT english_level FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        conn.close()

        user_level = row[0] if row else None
    else:
        user_level = None  # není přihlášený

    used = session.get("used_words", [])

    levels = allowed_levels(user_level)

    words = load_words()
    filtered_words = [w for w in words if w["level"] in levels and w["word"] not in used]

    if not filtered_words:
        return jsonify({
            "status": "done",
            "message": "Vyřešil jsi všechna slova!",
            "allow_restart": True
        })

    word_data = random.choice(filtered_words)

    session["current_word"] = word_data["word"]
    session.setdefault("used_words", []).append(word_data["word"])
    session["guessed_letters"] = []
    session["remaining_attempts"] = 6

    return jsonify({
        "status": "ok",
        "word_length": len(word_data["word"]),
        "hint": word_data["hint"],
        "hint_cz": word_data["hint_cz"],
        "level": word_data["level"]
    })


@hangman_bp.route("/hangman/reset", methods=["POST"])
def reset_game():
    session.pop("used_words", None)
    session.pop("current_word", None)
    session.pop("guessed_letters", None)
    session.pop("remaining_attempts", None)
    return jsonify({"status": "reset_ok"})


@hangman_bp.route("/hangman/guess", methods=["POST"])
def guess_letter():
    data = request.get_json()
    letter = data["letter"].lower()

    word = session["current_word"]
    guessed = session.get("guessed_letters", [])
    if letter in guessed:
        return jsonify({"message": "already_guessed"})

    guessed.append(letter)
    session["guessed_letters"] = guessed

    if letter not in word.lower():
        session["remaining_attempts"] -= 1

    # Funkce na porovnání výhry – ignoruje znaky, co nejsou písmena
    def has_won(word, guessed_letters):
        return all(
            c.lower() in guessed_letters or not c.isalpha()
            for c in word
        )

    status = (
        "win" if has_won(word, guessed)
        else "lose" if session["remaining_attempts"] <= 0
        else "playing"
    )

    words = load_words()
    word_data = next((w for w in words if w["word"] == word), None)

    masked_word = get_masked_word(word, guessed)

    return jsonify({
        "masked_word": masked_word,
        "guessed_letters": guessed,
        "remaining_attempts": session["remaining_attempts"],
        "status": status,
        "original_word": word if status != "playing" else None,
        "translation": word_data["translation"] if word_data and status != "playing" else None
    })
