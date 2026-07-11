from flask import Blueprint, render_template, request, session, current_app
import json
import os
import random

math_ulohy_bp = Blueprint('math_ulohy', __name__)

# Klíče tříd a štítky pro select
GRADES = [
    ("1_class", "1. třída"),
    ("2_class", "2. třída"),
    ("3_class", "3. třída"),
    ("4_class", "4. třída"),
    ("5_class", "5. třída"),
]

_TASKS_CACHE = None


def _tasks_path() -> str:
    # Statický JSON v repu
    return os.path.join(current_app.root_path, 'static', '__math__', '1_stupen', 'ulohy', 'slovni_ulohy.json')


def _load_tasks() -> dict:
    global _TASKS_CACHE
    if _TASKS_CACHE is not None:
        return _TASKS_CACHE
    path = _tasks_path()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            _TASKS_CACHE = json.load(f)
    except Exception:
        _TASKS_CACHE = {k: [] for k, _ in GRADES}
    return _TASKS_CACHE


def _pick_random_task(grade_key: str) -> dict | None:
    tasks = _load_tasks().get(grade_key, [])
    if not tasks:
        return None
    return random.choice(tasks)


@math_ulohy_bp.route('/math/stupen1/slovni-ulohy', methods=['GET', 'POST'])
def slovni_ulohy():
    # Preference třídy v session
    prefs = session.get('slovni_ulohy_prefs', {'grade': '1_class'})

    result = None  # výsledek poslední odpovědi

    if request.method == 'POST':
        # Uložení zvolené třídy
        if 'grade' in request.form:
            grade = request.form.get('grade', '1_class')
            if grade not in {k for k, _ in GRADES}:
                grade = '1_class'
            prefs = {'grade': grade}
            session['slovni_ulohy_prefs'] = prefs

        # Vyhodnocení odpovědi
        if 'answer' in request.form and request.form.get('answer', '').strip() != '':
            try:
                user_answer = int(request.form.get('answer'))
            except Exception:
                user_answer = None
            last = session.get('slovni_ulohy_problem')
            if isinstance(last, dict):
                correct_val = last.get('correct')
                result = {
                    'correct': (user_answer == correct_val),
                    'expected': correct_val,
                    'given': user_answer
                }

        # Po POSTu vždy vygenerujeme novou náhodnou úlohu pro aktuální třídu
        task = _pick_random_task(prefs['grade'])
        session['slovni_ulohy_problem'] = task
        return render_template(
            '__math__/1_stupen/slovni_ulohy/slovni_ulohy.html',
            grades=GRADES,
            prefs=prefs,
            task=task,
            result=result,
            user_name=session.get("user_name"),
            profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg")
        )

    # GET – pokud není uložená úloha, vyber jednu
    task = session.get('slovni_ulohy_problem')
    if not task:
        task = _pick_random_task(prefs['grade'])
        session['slovni_ulohy_problem'] = task

    return render_template(
        '__math__/1_stupen/slovni_ulohy/slovni_ulohy.html',
        grades=GRADES,
        prefs=prefs,
        task=task,
        result=result,
        user_name=session.get("user_name"),
        profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg")
    )
