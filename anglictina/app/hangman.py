from flask import Blueprint, session, render_template, request, jsonify
import json
import random

hangman_bp = Blueprint("hangman", __name__, template_folder="templates")


def load_words():
    with open("static/hangman/hangman_words.json", "r", encoding="utf-8") as f:
        return json.load(f)


def get_random_word(used_words):
    words = load_words()
    available_words = [word for word in words if word["word"] not in used_words]

    if not available_words:
        return None  # Všechna slova použita

    return random.choice(available_words)


@hangman_bp.route("/hangman")
def hangman_game():
    session.setdefault("used_words", [])
    return render_template("hangman/hangman.html")


@hangman_bp.route("/hangman/start", methods=["GET"])
def start_game():
    used = session.get("used_words", [])
    word_data = get_random_word(used)

    if not word_data:
        return jsonify({
            "status": "done",
            "message": "Vyřešil jsi všechna slova!",
            "allow_restart": True  # ⬅️ říká frontendu, že může nabídnout restart
        })

    session["current_word"] = word_data["word"]
    session.setdefault("used_words", []).append(word_data["word"])
    session["guessed_letters"] = []
    session["remaining_attempts"] = 6

    return jsonify({
        "status": "ok",
        "word_length": len(word_data["word"]),
        "hint": word_data["hint"],
        "hint_cz": word_data["hint_cz"],  # ⬅️ TOHLE DOPLŇ
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

    if letter not in word:
        session["remaining_attempts"] -= 1

    masked_word = "".join([l if l in guessed else "_" for l in word])
    status = "win" if "_" not in masked_word else ("lose" if session["remaining_attempts"] <= 0 else "playing")

    words = load_words()
    word_data = next((w for w in words if w["word"] == word), None)

    return jsonify({
        "masked_word": masked_word,
        "guessed_letters": guessed,
        "remaining_attempts": session["remaining_attempts"],
        "status": status,
        "original_word": word if status != "playing" else None,
        "translation": word_data["translation"] if word_data and status != "playing" else None
    })
