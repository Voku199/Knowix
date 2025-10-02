from flask import Blueprint, render_template, request, session, redirect, url_for
import random

cas_bp = Blueprint('cas', __name__)

# Povolené formáty odpovědí
TIME_FORMATS = {
    'digital': {'label': 'Číselný formát (14:15)', 'example': '14:15'},
    'words': {'label': 'Slovní formát (čtvrt na tři)', 'example': 'čtvrt na tři'},
    'both': {'label': 'Oba formáty', 'example': '14:15 nebo slovně'}
}


# Slovní vyjádření času v češtině
def minutes_to_words(minutes):
    """Převede minuty na slovní vyjádření"""
    if minutes == 0:
        return "přesně"
    elif minutes == 15:
        return "čtvrt na"
    elif minutes == 30:
        return "půl"
    elif minutes == 45:
        return "tři čtvrtě na"
    else:
        return f"{minutes} minut po" if minutes < 30 else f"{60 - minutes} minut do"


def hours_to_words(hour, minutes):
    """Převede hodiny na slovní vyjádření"""
    hour_names = {
        1: "jedna", 2: "dva", 3: "tři", 4: "čtyři", 5: "pět", 6: "šest",
        7: "sedm", 8: "osm", 9: "devět", 10: "deset", 11: "jedenáct", 12: "dvanáct"
    }

    # Pro 24h formát převedeme na 12h
    display_hour = hour if hour <= 12 else hour - 12
    if display_hour == 0:
        display_hour = 12

    # Pro čtvrt na a tři čtvrtě na používáme následující hodinu
    if minutes == 15 or minutes == 45:
        next_hour = display_hour + 1 if display_hour < 12 else 1
        return hour_names.get(next_hour, str(next_hour))

    return hour_names.get(display_hour, str(display_hour))


def generate_time_problem():
    """Vygeneruje náhodný čas a jeho slovní vyjádření"""
    # Generujeme čas s krokem po 5 minutách pro jednoduchost
    hour = random.randint(1, 23)
    minute = random.choice([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])

    # Číselný formát
    digital_time = f"{hour:02d}:{minute:02d}"

    # Slovní formát
    minute_word = minutes_to_words(minute)
    hour_word = hours_to_words(hour, minute)

    if minute == 0:
        words_time = f"{hour_word} hodin přesně"
    elif minute == 30:
        words_time = f"půl {hour_word}"
    elif minute == 15:
        words_time = f"čtvrt na {hour_word}"
    elif minute == 45:
        words_time = f"tři čtvrtě na {hour_word}"
    else:
        if minute < 30:
            words_time = f"{minute} minut po {hour_word}"
        else:
            next_hour_word = hours_to_words(hour + 1 if hour < 23 else 0, 0)
            words_time = f"{60 - minute} minut do {next_hour_word}"

    # Opravené výpočty úhlů pro správné zobrazení času
    # Hodinová ručička: každá hodina = 30°, každá minuta = 0.5°
    hour_12_format = hour % 12  # Převedeme na 12h formát
    angle_hour = (hour_12_format * 30) + (minute * 0.5)

    # Minutová ručička: každá minuta = 6°
    angle_minute = minute * 6

    return {
        'hour': hour,
        'minute': minute,
        'digital': digital_time,
        'words': words_time,
        'angle_hour': angle_hour,  # Úhel hodinové ručičky
        'angle_minute': angle_minute  # Úhel minutové ručičky
    }


def normalize_answer(answer):
    """Normalizuje odpověď pro porovnání"""
    if not answer:
        return ""
    return answer.strip().lower().replace("  ", " ")


def check_time_answer(user_answer, correct_time, format_type):
    """Zkontroluje správnost odpovědi"""
    user_answer = normalize_answer(user_answer)

    if format_type == 'digital':
        return user_answer == correct_time['digital']
    elif format_type == 'words':
        correct_words = normalize_answer(correct_time['words'])
        return user_answer == correct_words
    elif format_type == 'both':
        correct_digital = correct_time['digital']
        correct_words = normalize_answer(correct_time['words'])
        return user_answer == correct_digital or user_answer == correct_words

    return False


@cas_bp.route('/math/stupen1/cas', methods=['GET', 'POST'])
def math():
    # Načti/aktualizuj preference
    prefs = session.get('cas_prefs', {'format': 'digital'})

    result = None  # informace o výsledku poslední odpovědi

    if request.method == 'POST':
        # Nastavení preferencí
        if 'format' in request.form:
            format_type = request.form.get('format', 'digital')
            if format_type not in TIME_FORMATS:
                format_type = 'digital'
            prefs = {'format': format_type}
            session['cas_prefs'] = prefs

        # Vyhodnocení odpovědi
        if 'answer' in request.form and request.form.get('answer', '').strip() != '':
            user_answer = request.form.get('answer', '').strip()
            last_problem = session.get('cas_problem')

            if last_problem is not None and isinstance(last_problem, dict):
                correct = check_time_answer(user_answer, last_problem, prefs['format'])
                expected = last_problem['digital']
                if prefs['format'] == 'words':
                    expected = last_problem['words']
                elif prefs['format'] == 'both':
                    expected = f"{last_problem['digital']} nebo {last_problem['words']}"

                result = {
                    'correct': correct,
                    'expected': expected,
                    'given': user_answer
                }

        # Po jakémkoliv POSTu vygeneruj nový čas
        problem = generate_time_problem()
        session['cas_problem'] = problem

        return render_template(
            '__math__/1_stupen/cas/cas.html',
            prefs=prefs,
            problem=problem,
            result=result,
            formats=TIME_FORMATS,
            user_name=session.get("user_name"),
            profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg")
        )

    # GET: pokud neexistuje aktivní příklad, vytvoř nový
    problem = session.get('cas_problem')
    if not problem:
        problem = generate_time_problem()
        session['cas_problem'] = problem

    return render_template(
        '__math__/1_stupen/cas/cas.html',
        prefs=prefs,
        problem=problem,
        result=result,
        formats=TIME_FORMATS,
        user_name=session.get("user_name"),
        profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg")
    )
