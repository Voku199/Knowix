from flask import Blueprint, render_template, request, session, redirect, url_for
import random

prevodky_bp = Blueprint('prevodky', __name__)

# Definice převodních úloh s různými jednotkami
CONVERSION_TYPES = {
    'weight': {
        'label': 'Hmotnost',
        'conversions': [
            {'from': 'kg', 'to': 'g', 'factor': 1000, 'label_from': 'kilogramů', 'label_to': 'gramů'},
            {'from': 'g', 'to': 'kg', 'factor': 0.001, 'label_from': 'gramů', 'label_to': 'kilogramů'},
            {'from': 't', 'to': 'kg', 'factor': 1000, 'label_from': 'tun', 'label_to': 'kilogramů'},
            {'from': 'kg', 'to': 't', 'factor': 0.001, 'label_from': 'kilogramů', 'label_to': 'tun'},
        ]
    },
    'volume': {
        'label': 'Objem',
        'conversions': [
            {'from': 'l', 'to': 'ml', 'factor': 1000, 'label_from': 'litrů', 'label_to': 'mililitrů'},
            {'from': 'ml', 'to': 'l', 'factor': 0.001, 'label_from': 'mililitrů', 'label_to': 'litrů'},
            {'from': 'hl', 'to': 'l', 'factor': 100, 'label_from': 'hektolitrů', 'label_to': 'litrů'},
            {'from': 'l', 'to': 'hl', 'factor': 0.01, 'label_from': 'litrů', 'label_to': 'hektolitrů'},
        ]
    },
    'time': {
        'label': 'Čas',
        'conversions': [
            {'from': 'h', 'to': 'min', 'factor': 60, 'label_from': 'hodin', 'label_to': 'minut'},
            {'from': 'min', 'to': 'h', 'factor': 1 / 60, 'label_from': 'minut', 'label_to': 'hodin'},
            {'from': 'min', 'to': 's', 'factor': 60, 'label_from': 'minut', 'label_to': 'sekund'},
            {'from': 's', 'to': 'min', 'factor': 1 / 60, 'label_from': 'sekund', 'label_to': 'minut'},
            {'from': 'h', 'to': 's', 'factor': 3600, 'label_from': 'hodin', 'label_to': 'sekund'},
            {'from': 's', 'to': 'h', 'factor': 1 / 3600, 'label_from': 'sekund', 'label_to': 'hodin'},
        ]
    },
    'length': {
        'label': 'Délka',
        'conversions': [
            {'from': 'm', 'to': 'cm', 'factor': 100, 'label_from': 'metrů', 'label_to': 'centimetrů'},
            {'from': 'cm', 'to': 'm', 'factor': 0.01, 'label_from': 'centimetrů', 'label_to': 'metrů'},
            {'from': 'km', 'to': 'm', 'factor': 1000, 'label_from': 'kilometrů', 'label_to': 'metrů'},
            {'from': 'm', 'to': 'km', 'factor': 0.001, 'label_from': 'metrů', 'label_to': 'kilometrů'},
            {'from': 'm', 'to': 'mm', 'factor': 1000, 'label_from': 'metrů', 'label_to': 'milimetrů'},
            {'from': 'mm', 'to': 'm', 'factor': 0.001, 'label_from': 'milimetrů', 'label_to': 'metrů'},
        ]
    }
}

VALUE_RANGES = [10, 50, 100, 500, 1000]


def _clamp_max_value(value: int) -> int:
    try:
        v = int(value)
    except Exception:
        return 10
    return v if v in VALUE_RANGES else 10


def generate_conversion_problem(conversion_type: str, max_value: int) -> dict:
    """
    Vygeneruje náhodný příklad pro převod jednotek.
    """
    maxv = max(1, int(max_value))

    if conversion_type not in CONVERSION_TYPES:
        conversion_type = 'weight'

    # Vyber náhodný převod z dané kategorie
    conversions = CONVERSION_TYPES[conversion_type]['conversions']
    conversion = random.choice(conversions)

    # Vygeneruj hodnotu pro převod
    if conversion['factor'] >= 1:
        # Převod na větší jednotky (např. kg -> g)
        value = random.randint(1, maxv)
    else:
        # Převod na menší jednotky (např. g -> kg)
        # Zajisti, aby výsledek byl rozumný
        min_val = int(1 / conversion['factor'])
        value = random.randint(min_val, maxv * int(1 / conversion['factor']))

    correct_answer = value * conversion['factor']

    # Pro některé převody může být výsledek desetinné číslo
    if correct_answer != int(correct_answer):
        correct_answer = round(correct_answer, 3)
    else:
        correct_answer = int(correct_answer)

    return {
        'value': value,
        'unit_from': conversion['from'],
        'unit_to': conversion['to'],
        'label_from': conversion['label_from'],
        'label_to': conversion['label_to'],
        'correct_answer': correct_answer,
        'conversion_type': conversion_type
    }


@prevodky_bp.route('/math/stupen1/prevody', methods=['GET', 'POST'])
def math():
    # Načti/aktualizuj preference
    prefs = session.get('prevodky_prefs', {'type': 'weight', 'max': 10})

    result = None  # informace o výsledku poslední odpovědi

    if request.method == 'POST':
        # Nastavení preferencí
        if 'conversion_type' in request.form and 'max_value' in request.form:
            conversion_type = request.form.get('conversion_type', 'weight')
            max_value = _clamp_max_value(request.form.get('max_value', 10))
            if conversion_type not in CONVERSION_TYPES:
                conversion_type = 'weight'
            prefs = {'type': conversion_type, 'max': max_value}
            session['prevodky_prefs'] = prefs

        # Vyhodnocení odpovědi (pokud přišla)
        if 'answer' in request.form and request.form.get('answer', '').strip() != '':
            try:
                user_answer = float(request.form.get('answer'))
            except Exception:
                user_answer = None
            last_problem = session.get('prevodky_problem')
            if last_problem is not None and isinstance(last_problem, dict):
                expected = last_problem.get('correct_answer')
                # Tolerace pro desetinná čísla
                if isinstance(expected, float):
                    correct = abs(user_answer - expected) < 0.001 if user_answer is not None else False
                else:
                    correct = (user_answer == expected) if user_answer is not None else False
                result = {
                    'correct': correct,
                    'expected': expected,
                    'given': user_answer
                }

        # Po jakémkoliv POSTu vygeneruj nový příklad dle aktuálních preferencí
        problem = generate_conversion_problem(prefs['type'], prefs['max'])
        session['prevodky_problem'] = problem
        return render_template(
            '__math__/1_stupen/prevodky/prevodky.html',
            prefs=prefs,
            problem=problem,
            result=result,
            conversion_types=CONVERSION_TYPES,
            ranges=VALUE_RANGES,
            user_name=session.get("user_name"),
            profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg")
        )

    # GET: pokud neexistuje aktivní příklad, vytvoř nový
    problem = session.get('prevodky_problem')
    if not problem:
        problem = generate_conversion_problem(prefs['type'], prefs['max'])
        session['prevodky_problem'] = problem

    return render_template(
        '__math__/1_stupen/prevodky/prevodky.html',
        prefs=prefs,
        problem=problem,
        result=result,
        conversion_types=CONVERSION_TYPES,
        ranges=VALUE_RANGES,
        user_name=session.get("user_name"),
        profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg")
    )
