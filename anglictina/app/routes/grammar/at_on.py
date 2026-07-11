"""Gramatika předložek at/on/in (blueprint `at_on`).

Cvičení ze static/gram/at_on/at_on_exercises.json; správné/špatné odpovědi
se počítají do statistik (at_cor/at_wr), XP a streaku.
"""

import json
import random
from flask import Blueprint, render_template, request, flash, redirect, url_for, session, jsonify
import os
import difflib
import re
import time
from xp import add_xp_to_user, get_user_xp_and_level
from streak import update_user_streak, get_user_streak
from user_stats import update_user_stats
from db import get_db_connection
import logging

at_on_bp = Blueprint("at_on", __name__, template_folder="templates")

LEVEL_NAMES = [
    "Začátečník", "Učeň", "Student", "Pokročilý", "Expert", "Mistr", "Legenda"
]


@at_on_bp.context_processor
def inject_streak():
    user_id = session.get('user_id')
    if user_id:
        streak = get_user_streak(user_id)
        return dict(user_streak=streak)
    return dict(user_streak=0)


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


@at_on_bp.context_processor
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


@at_on_bp.errorhandler(502)
@at_on_bp.errorhandler(503)
@at_on_bp.errorhandler(504)
@at_on_bp.errorhandler(500)
@at_on_bp.errorhandler(404)
@at_on_bp.errorhandler(Exception)
def server_error(e):
    code = getattr(e, 'code', 500)
    return render_template('error.html', error_code=code), code


def load_exercises():
    with open("static/gram/at_on/at_on_exercises.json", encoding="utf-8") as f:
        return json.load(f)


@at_on_bp.route("/at-on", methods=["GET"])
def select_exercise():
    return render_template("gram/at_on/select_at.html")


def is_reasonable_sentence(sentence):
    words = sentence.strip().split()
    if len(words) < 4:
        return False
    prepositions = {"at", "on", "in"}
    if not any(p in [w.lower() for w in words] for p in prepositions):
        return False
    for w in words:
        if not re.match(r"^[a-zA-Z0-9,.!?'-]+$", w):
            return False
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
        for old_sentence in session['sentences']:
            if is_similar(user_input, old_sentence):
                return render_template("gram/at_on/create_sentence.html",
                                       result="Tuhle větu jsi už napsal, zkus něco jinýho!",
                                       correct=False,
                                       user_sentence=user_input,
                                       sentences=session['sentences'])
        if is_reasonable_sentence(user_input):
            result = "Super, tvoje věta vypadá dobře!"
            correct = True
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

    return render_template("gram/at_on/create_sentence.html", sentences=session['sentences'])


@at_on_bp.route("/at-on/fill-word", methods=["GET", "POST"])
def fill_word():
    exercises = load_exercises()

    # --- Uložení času vstupu na stránku a nastavení first_activity ---
    user_id = session.get('user_id')
    if request.method == "GET":
        # Při vstupu na stránku uložíme čas začátku lekce
        session['at_on_training_start'] = time.time()
        if user_id:
            _ensure_user_exists_for_session_at_on()
            update_user_stats(user_id, set_first_activity=True)

    # Při prvním načtení nastavíme náhodných 10 otázek a připravíme strukturu pro odpovědi
    if 'selected_questions' not in session:
        session['selected_questions'] = random.sample(range(len(exercises)), 10)
        session['answered'] = []
        session['answers_correct'] = {}  # {question_id: True/False}
        session.modified = True

    selected = session['selected_questions']
    answered = session['answered']
    answers_correct = session.get('answers_correct', {})
    remaining = [i for i in selected if i not in answered]

    if request.method == "POST":
        if not remaining:
            if request.accept_mimetypes['application/json']:
                return jsonify({"done": True})
            return redirect(url_for('at_on.fill_word'))

        question_id = int(request.form["question_id"])
        answer = request.form["answer"].strip().lower()
        correct = exercises[question_id]["correct"]

        is_correct = answer == correct

        # --- STATISTIKY: Uložení správné/špatné odpovědi ---
        if user_id and question_id not in answered:
            _ensure_user_exists_for_session_at_on()
            if is_correct:
                update_user_stats(user_id, at_cor=1)
                # --- OKAMŽITÉ PŘIPSÁNÍ XP a aktualizace streaku při správné odpovědi ---
                try:
                    # Připíšeme 1 XP za správnou odpověď
                    try:
                        add_result = add_xp_to_user(user_id, 1)
                    except Exception:
                        add_result = None
                    # Aktualizujeme streak (pokud modul existuje)
                    try:
                        streak_info = update_user_streak(user_id)
                    except Exception:
                        streak_info = None
                except Exception:
                    # Nezáležitá chyba při přidávání XP/streaku
                    streak_info = None
            else:
                update_user_stats(user_id, at_wr=1)

        if is_correct:
            flash("✅ Správně!", "success")
        else:
            flash(f"❌ Špatně. Správně je {correct}.", "error")

        streak_info = None
        if question_id not in answered:
            answered.append(question_id)
            answers_correct[str(question_id)] = is_correct  # <-- klíč jako string!
            session['answered'] = answered
            session['answers_correct'] = answers_correct
            session.modified = True

        # Pokud uživatel dokončil všechny otázky, přiděluj XP, streak a statistiky za celou lekci
        if not [i for i in selected if i not in answered]:
            correct_count = sum(1 for v in answers_correct.values() if v)
            wrong_count = len(answers_correct) - correct_count

            # --- Výpočet a zápis learning_time ---
            learning_time = None
            if user_id and session.get('at_on_training_start'):
                try:
                    start = float(session.pop('at_on_training_start', None))
                    duration = max(1, int(time.time() - start))  # min. 1 sekunda
                    learning_time = duration
                except Exception as e:
                    print("Chyba při ukládání času tréninku:", e)

            if user_id and (correct_count > 0 or wrong_count > 0):
                _ensure_user_exists_for_session_at_on()
                # Zaznamenej celkový počet správných a špatných odpovědí za lekci + learning_time + lesson_done
                update_user_stats(
                    user_id,
                    at_cor=correct_count,
                    at_wr=wrong_count,
                    lesson_done=True,
                    learning_time=learning_time
                )
                try:
                    result = add_xp_to_user(user_id, correct_count)
                    streak_info = update_user_streak(user_id)
                except Exception:
                    streak_info = None

        # AJAX odpověď
        if request.accept_mimetypes['application/json']:
            return jsonify({
                "correct": is_correct,
                "streak_info": streak_info,
                "flash_message": "✅ Správně!" if is_correct else f"❌ Špatně. Správně je {correct}.",
                "done": not [i for i in selected if i not in answered]
            })
        # Klasický POST
        return redirect(url_for('at_on.fill_word'))

    # GET request
    if not remaining:
        correct_count = sum(1 for v in answers_correct.values() if v)
        wrong_count = len(answers_correct) - correct_count
        streak_info = None  # <-- Přidáno pro streak

        # --- Výpočet a zápis learning_time i při GETu, pokud nebyl zapsán ---
        learning_time = None
        if user_id and session.get('at_on_training_start'):
            try:
                start = float(session.pop('at_on_training_start', None))
                duration = max(1, int(time.time() - start))  # min. 1 sekunda
                learning_time = duration
            except Exception as e:
                print("Chyba při ukládání času tréninku:", e)

        if user_id:
            try:
                if correct_count > 0 or wrong_count > 0:
                    _ensure_user_exists_for_session_at_on()
                    # Zaznamenej celkový počet správných a špatných odpovědí za lekci (pro jistotu i zde)
                    update_user_stats(
                        user_id,
                        at_cor=correct_count,
                        at_wr=wrong_count,
                        lesson_done=True,
                        learning_time=learning_time
                    )
                if correct_count > 0:
                    result = add_xp_to_user(user_id, correct_count)
                    if "error" in result:
                        flash(f"XP se nepodařilo přidat: {result['error']}", "error")
                    else:
                        flash(f"🎉 Získal(a) jsi {correct_count} XP za {correct_count} správných odpovědí!", "success")
                        # --- Streak logika ---
                        streak_info = update_user_streak(user_id)
                        if streak_info and streak_info.get("status") in ("started", "continued"):
                            flash(f"🔥 Máš streak {streak_info['streak']} dní v řadě!", "streak")
                else:
                    flash("Nezískal(a) jsi žádné XP, protože nebyla žádná správná odpověď.", "info")
            except Exception as e:
                flash(f"XP se nepodařilo přidat: {e}", "error")
        else:
            flash("XP nebylo přidáno, protože nejsi přihlášen(a).", "warning")
        session.pop('_flashes', None)
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
    session.pop('answers_correct', None)
    session.pop('at_on_training_start', None)
    flash("♻️ Pokrok byl resetován, můžeš začít znovu!", "info")
    return redirect(url_for('at_on.fill_word'))


def _ensure_user_exists_for_session_at_on():
    """Zajistí, že session['user_id'] existuje v users.

    Pokud ne, ale existuje v guest, vytvoří odpovídající users řádek.
    Specifické pro at_on lekci, aby user_stats/XP nepadaly na FK.
    """
    sid = session.get('user_id')
    if not sid:
        return
    try:
        db = get_db_connection()
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id FROM users WHERE id = %s", (sid,))
        if cur.fetchone():
            return
        cur.execute("SELECT * FROM guest WHERE id = %s", (sid,))
        guest_row = cur.fetchone()
        if not guest_row:
            logging.getLogger("at_on").error(
                "[at_on] user_id=%s neexistuje ani v users, ani v guest",
                sid,
            )
            return
        logging.getLogger("at_on").warning(
            "[at_on] user_id=%s nenalezen v users, ale existuje v guest -> vytvářím users řádek",
            sid,
        )
        insert_sql = (
            "INSERT INTO users (id, first_name, last_name, email, password, school, is_guest, has_seen_onboarding) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        )
        params = (
            guest_row.get('id'),
            guest_row.get('first_name') or 'Guest',
            guest_row.get('last_name') or 'User',
            guest_row.get('email'),
            guest_row.get('password') or '',
            guest_row.get('school') or 'Knowix',
            1,
            guest_row.get('has_seen_onboarding') or 0,
        )
        try:
            cur.execute(insert_sql, params)
            db.commit()
        except Exception as exc:
            logging.getLogger("at_on").error(
                "[at_on] nepodařilo se vytvořit users řádek pro guest.id=%s: %s",
                sid,
                exc,
            )
    except Exception as exc:
        logging.getLogger("at_on").error(
            "[at_on] _ensure_user_exists_for_session_at_on: chyba při kontrole/repair users.id pro user_id=%s: %s",
            session.get('user_id'),
            exc,
        )
    finally:
        try:
            if 'cur' in locals() and cur:
                cur.close()
            if 'db' in locals() and db:
                db.close()
        except Exception:
            pass
