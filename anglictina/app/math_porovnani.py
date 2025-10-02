from flask import Blueprint, render_template, request, session, redirect, url_for
import random

porovnani_bp = Blueprint('porovnani', __name__)

# Povolené operace porovnání
COMPARISON_OPS = {
    'greater': {'label': 'Větší než', 'symbol': '>'},
    'less': {'label': 'Menší než', 'symbol': '<'},
    'equal': {'label': 'Rovno', 'symbol': '='},
    'greater_equal': {'label': 'Větší nebo rovno', 'symbol': '≥'},
    'less_equal': {'label': 'Menší nebo rovno', 'symbol': '≤'},
}

RANGES = [10, 50, 100, 200, 500, 1000, 9999]


def _clamp_max_value(value: int) -> int:
    try:
        v = int(value)
    except Exception:
        return 10
    return v if v in RANGES else 10


def generate_comparison_problem(max_value: int) -> dict:
    """
    Vygeneruje náhodný příklad pro porovnání čísel.
    Vrací dva čísla a správnou operaci porovnání.
    """
    maxv = max(0, int(max_value))

    a = random.randint(0, maxv)
    b = random.randint(0, maxv)

    # Určí správnou operaci porovnání
    if a > b:
        correct_op = 'greater'
    elif a < b:
        correct_op = 'less'
    else:
        correct_op = 'equal'

    return {
        'a': a,
        'b': b,
        'correct_operation': correct_op,
        'correct_symbol': COMPARISON_OPS[correct_op]['symbol']
    }


@porovnani_bp.route('/math/stupen1/porovnani', methods=['GET', 'POST'])
def math():
    # Načti/aktualizuj preference
    prefs = session.get('porovnani_prefs', {'max': 10})

    result = None  # informace o výsledku poslední odpovědi

    if request.method == 'POST':
        # Nastavení preferencí
        if 'max_value' in request.form:
            max_value = _clamp_max_value(request.form.get('max_value', 10))
            prefs = {'max': max_value}
            session['porovnani_prefs'] = prefs

        # Vyhodnocení odpovědi (pokud přišla)
        if 'user_operation' in request.form:
            user_operation = request.form.get('user_operation')
            last_problem = session.get('porovnani_problem')
            if last_problem is not None and isinstance(last_problem, dict):
                correct = (user_operation == last_problem.get('correct_operation'))
                result = {
                    'correct': correct,
                    'expected': last_problem.get('correct_operation'),
                    'expected_symbol': last_problem.get('correct_symbol'),
                    'given': user_operation,
                    'given_symbol': COMPARISON_OPS.get(user_operation, {}).get('symbol', '?')
                }

        # Po jakémkoliv POSTu vygeneruj nový příklad dle aktuálních preferencí
        problem = generate_comparison_problem(prefs['max'])
        session['porovnani_problem'] = problem
        return render_template(
            '__math__/1_stupen/porovnani/porovnani.html',
            prefs=prefs,
            problem=problem,
            result=result,
            comparison_ops=COMPARISON_OPS,
            ranges=RANGES,
            user_name=session.get("user_name"),
            profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg")
        )

    # GET: pokud neexistuje aktivní příklad, vytvoř nový
    problem = session.get('porovnani_problem')
    if not problem:
        problem = generate_comparison_problem(prefs['max'])
        session['porovnani_problem'] = problem

    return render_template(
        '__math__/1_stupen/porovnani/porovnani.html',
        prefs=prefs,
        problem=problem,
        result=result,
        comparison_ops=COMPARISON_OPS,
        ranges=RANGES,
        user_name=session.get("user_name"),
        profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg")
    )
