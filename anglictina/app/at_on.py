import json
import random
from flask import Blueprint, render_template, request, flash, redirect, url_for, session, app
import os
import difflib
import re

at_on_bp = Blueprint("at_on", __name__, template_folder="templates")
app.secret_key = os.getenv("SECRET_KEY")


def load_exercises():
    with open("static/gram/at_on/at_on_exercises.json", encoding="utf-8") as f:
        return json.load(f)


# Výběr typu cvičení
@at_on_bp.route("/at-on", methods=["GET"])
def select_exercise():
    return render_template("gram/at_on/select_at.html")


# Cvičení: poskládej větu ze slova
def is_reasonable_sentence(sentence):
    # 1) Délka
    words = sentence.strip().split()
    if len(words) < 4:
        return False

    # 2) Přítomnost předložky
    prepositions = {"at", "on", "in"}
    if not any(p in [w.lower() for w in words] for p in prepositions):
        return False

    # 3) Slova musí být z písmen, čísla nebo pár interpunkčních znaků (čárka, tečka, vykřičník, otazník, apostrof, pomlčka)
    for w in words:
        if not re.match(r"^[a-zA-Z0-9,.!?'-]+$", w):
            return False

    # 4) Minimalní počet smysluplných slov (např. aspoň 2 slova delší než 2 znaky)
    long_words = [w for w in words if len(w) > 2]
    if len(long_words) < 2:
        return False

    return True


def is_similar(a, b, threshold=0.8):
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() > threshold


@at_on_bp.route("/at-on/create-sentence", methods=["GET", "POST"])
def create_sentence():
    if 'sentences' not in session:
        session['sentences'] = []

    if request.method == "POST":
        user_input = request.form["sentence"].strip()

        # Kontrola opakování vět
        for old_sentence in session['sentences']:
            if is_similar(user_input, old_sentence):
                return render_template("gram/at_on/create_sentence.html",
                                       result="Tuhle větu jsi už napsal, zkus něco jinýho!",
                                       correct=False,
                                       user_sentence=user_input,
                                       sentences=session['sentences'])

        # Kontrola smysluplnosti věty
        if is_reasonable_sentence(user_input):
            result = "Super, tvoje věta vypadá dobře!"
            correct = True
            # Uložíme větu do session, pokud je validní a neopakovaná
            session['sentences'].append(user_input)
            session.modified = True
        else:
            result = "Ta věta nevypadá jako smysluplná nebo neobsahuje správnou předložku."
            correct = False

        return render_template("gram/at_on/create_sentence.html",
                               result=result,
                               correct=correct,
                               user_sentence=user_input,
                               sentences=session['sentences'])

    # GET request
    return render_template("gram/at_on/create_sentence.html", sentences=session['sentences'])


# Cvičení: doplň správnou předložku
@at_on_bp.route("/at-on/fill-word", methods=["GET", "POST"])
def fill_word():
    exercises = load_exercises()

    # Při prvním načtení nastavíme náhodných 10 otázek
    if 'selected_questions' not in session:
        session['selected_questions'] = random.sample(range(len(exercises)), 10)
        session['answered'] = []
        session.modified = True

    selected = session['selected_questions']
    answered = session['answered']
    remaining = [i for i in selected if i not in answered]

    if request.method == "POST":
        if not remaining:
            return redirect(url_for('at_on.fill_word'))

        question_id = int(request.form["question_id"])
        answer = request.form["answer"].strip().lower()
        correct = exercises[question_id]["correct"]

        if answer == correct:
            flash("✅ Správně!", "success")
        else:
            flash(f"❌ Špatně. Správně je {correct}.", "error")

        if question_id not in answered:
            answered.append(question_id)
            session['answered'] = answered
            session.modified = True

        return redirect(url_for('at_on.fill_word'))

    # GET request
    if not remaining:
        session.pop('_flashes', None)  # smaže všechny flash zprávy
        return render_template(
            "gram/at_on/fill_word.html",
            remaining_count=0,
            answered_count=len(answered),
            total_questions=len(selected)
        )

    question_id = random.choice(remaining)
    return render_template(
        "gram/at_on/fill_word.html",
        question=exercises[question_id]["sentence"],
        question_id=question_id,
        remaining_count=len(remaining),
        answered_count=len(answered),
        total_questions=len(selected)
    )


@at_on_bp.route("/reset-progress")
def reset_progress():
    session.pop('answered', None)
    session.pop('selected_questions', None)
    flash("♻️ Pokrok byl resetován, můžeš začít znovu!", "info")
    return redirect(url_for('at_on.fill_word'))
