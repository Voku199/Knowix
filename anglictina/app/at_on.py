import json
import random
from flask import Blueprint, render_template, request

at_on_bp = Blueprint("at_on", __name__, template_folder="templates")


def load_exercises():
    with open("static/gram/at_on/at_on_exercises.json", encoding="utf-8") as f:
        return json.load(f)


# Výběr typu cvičení
@at_on_bp.route("/at-on", methods=["GET"])
def select_exercise():
    return render_template("gram/at_on/select_at.html")


# Cvičení: poskládej větu ze slova
@at_on_bp.route("/at-on/create-sentence", methods=["GET", "POST"])
def create_sentence():
    word = "house"  # můžeš později náhodně
    correct_answer = "I am at the house."  # pro porovnání

    if request.method == "POST":
        user_input = request.form["sentence"].strip()

        # Jednoduché porovnání – později můžeš použít fuzzy match
        if user_input.lower() == correct_answer.lower():
            return render_template("gram/at_on/create_sentence.html", word=word,
                                   result="Správně!", correct=True,
                                   correct_sentence=correct_answer)
        else:
            return render_template("gram/at_on/create_sentence.html", word=word,
                                   result="Špatně!", correct=False,
                                   correct_sentence=correct_answer)

    return render_template("gram/at_on/create_sentence.html", word=word)


# Cvičení: doplň správnou předložku
@at_on_bp.route("/at-on/fill-word", methods=["GET", "POST"])
def fill_word():
    exercises = load_exercises()

    if request.method == "POST":
        question = request.form["question"]
        correct = request.form["correct"]
        answer = request.form["answer"].strip().lower()
        result = answer == correct

        return render_template(
            "gram/at_on/fill_word.html",
            question=question,
            result=result,
            correct_preposition=correct,
            user_answer=answer
        )

    selected = random.choice(exercises)
    return render_template(
        "gram/at_on/fill_word.html",
        question=selected["sentence"],
        correct=selected["correct"]
    )
