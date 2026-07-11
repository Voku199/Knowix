from flask import Blueprint, render_template, request, session, redirect, url_for
import random

math_pocitejsam_bp = Blueprint('math_pocitejsam', __name__)

# Povolené operace a jejich popisky/symboly
ALLOWED_OPS = {
    'add': {'label': 'Sčítání', 'symbol': '+'},
    'sub': {'label': 'Odčítání', 'symbol': '-'},
    'mul': {'label': 'Násobení', 'symbol': '×'},
    'div': {'label': 'Dělení', 'symbol': '÷'},
}

RANGES = [10, 50, 100, 200, 500, 1000, 9999]


def _clamp_max_value(value: int) -> int:
    try:
        v = int(value)
    except Exception:
        return 10
    return v if v in RANGES else 10


def generate_problem(op: str, max_value: int) -> dict:
    """
    Vygeneruje náhodný příklad dle zvolené operace a rozsahu.
    Zajišťuje:
      - Odčítání bez záporných výsledků (a >= b)
      - Dělení s celočíselným výsledkem a, b, výsledek v rozsahu do max_value
      - Operandy jsou v rozsahu <0..max_value>
    """
    maxv = max(0, int(max_value))
    op = op if op in ALLOWED_OPS else 'add'

    if op == 'add':
        a = random.randint(0, maxv)
        b = random.randint(0, maxv)
        ans = a + b
    elif op == 'sub':
        a = random.randint(0, maxv)
        b = random.randint(0, a)  # a >= b, aby výsledek nebyl záporný
        ans = a - b
    elif op == 'mul':
        a = random.randint(0, maxv)
        b = random.randint(0, maxv)
        ans = a * b
    elif op == 'div':
        # Chceme a ÷ b = q, vše v rozsahu a,b,q <= maxv a b != 0
        if maxv == 0:
            # Extrémní případ – vrať triviální 0 ÷ 1 = 0
            a, b, ans = 0, 1, 0
        else:
            while True:
                b = random.randint(1, maxv)
                q = random.randint(0, maxv)
                a = b * q
                if a <= maxv:
                    ans = q
                    break
    else:
        # fallback
        a = random.randint(0, maxv)
        b = random.randint(0, maxv)
        ans = a + b
        op = 'add'

    return {
        'a': a,
        'b': b,
        'op': op,
        'symbol': ALLOWED_OPS[op]['symbol'],
        'answer': ans
    }


@math_pocitejsam_bp.route('/math/stupen1/pocitejsam', methods=['GET', 'POST'])
def pocitej_sam():
    # Načti/aktualizuj preference
    prefs = session.get('pocitejsam_prefs', {'op': 'add', 'max': 10})

    result = None  # informace o výsledku poslední odpovědi

    if request.method == 'POST':
        # Nastavení preferencí
        if 'operation' in request.form and 'max_value' in request.form:
            op = request.form.get('operation', 'add')
            max_value = _clamp_max_value(request.form.get('max_value', 10))
            if op not in ALLOWED_OPS:
                op = 'add'
            prefs = {'op': op, 'max': max_value}
            session['pocitejsam_prefs'] = prefs

        # Vyhodnocení odpovědi (pokud přišla)
        if 'answer' in request.form and request.form.get('answer', '').strip() != '':
            try:
                user_answer = int(request.form.get('answer'))
            except Exception:
                user_answer = None
            last_problem = session.get('pocitejsam_problem')
            if last_problem is not None and isinstance(last_problem, dict):
                correct = (user_answer == last_problem.get('answer'))
                result = {
                    'correct': correct,
                    'expected': last_problem.get('answer'),
                    'given': user_answer
                }

        # Po jakémkoliv POSTu vygeneruj nový příklad dle aktuálních preferencí
        problem = generate_problem(prefs['op'], prefs['max'])
        session['pocitejsam_problem'] = problem
        return render_template(
            '__math__/1_stupen/pocitejsam/pocitejsam_main.html',
            prefs=prefs,
            problem=problem,
            result=result,
            ops=ALLOWED_OPS,
            ranges=RANGES,
            user_name=session.get("user_name"),
            profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg")
        )

    # GET: pokud neexistuje aktivní příklad, vytvoř nový
    problem = session.get('pocitejsam_problem')
    if not problem:
        problem = generate_problem(prefs['op'], prefs['max'])
        session['pocitejsam_problem'] = problem

    return render_template(
        '__math__/1_stupen/pocitejsam/pocitejsam_main.html',
        prefs=prefs,
        problem=problem,
        result=result,
        ops=ALLOWED_OPS,
        ranges=RANGES,
        user_name=session.get("user_name"),
        profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg")
    )
