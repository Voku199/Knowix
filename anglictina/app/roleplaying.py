from flask import Blueprint, render_template, request, session, jsonify
import json
import os
import traceback
import random
import time

from xp import add_xp_to_user
from streak import update_user_streak, get_user_streak
from user_stats import update_user_stats

roleplaying_bp = Blueprint('roleplaying', __name__, template_folder='templates')

SCENARIOS_DIR = os.path.join(os.path.dirname(__file__), 'static/speaking/roleplaying')


@roleplaying_bp.errorhandler(502)
@roleplaying_bp.errorhandler(503)
@roleplaying_bp.errorhandler(504)
@roleplaying_bp.errorhandler(500)
@roleplaying_bp.errorhandler(404)
def server_error(e):
    # Pro AJAX požadavky vraťme JSON místo HTML
    if request.is_json or request.path.startswith('/roleplaying/'):
        return jsonify({
            "error": f"Server error {getattr(e, 'code', 500)}",
            "message": getattr(e, 'description', 'Internal server error'),
            "code": getattr(e, 'code', 500),
            "traceback": traceback.format_exc() if getattr(e, 'code', 500) >= 500 else None
        }), getattr(e, 'code', 500)

    # Pro běžné požadavky vraťme HTML error stránku
    return render_template('error.html', error_code=getattr(e, 'code', 500)), getattr(e, 'code', 500)


def load_scenario(filename):
    path = os.path.join(SCENARIOS_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


@roleplaying_bp.context_processor
def inject_streak():
    user_id = session.get('user_id')
    if user_id:
        streak = get_user_streak(user_id)
        return dict(user_streak=streak)
    return dict(user_streak=0)


def normalize(s):
    return ''.join(c for c in s if c.isalnum() or c.isspace()).lower().strip()


def levenshtein_similarity(a, b):
    if not a or not b:
        return 0.0
    len_a, len_b = len(a), len(b)
    dp = [[0] * (len_b + 1) for _ in range(len_a + 1)]
    for i in range(len_a + 1):
        dp[i][0] = i
    for j in range(len_b + 1):
        dp[0][j] = j
    for i in range(1, len_a + 1):
        for j in range(1, len_b + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,
                dp[i][j - 1] + 1,
                dp[i - 1][j - 1] + cost
            )
    distance = dp[len_a][len_b]
    max_len = max(len_a, len_b)
    similarity = 1 - distance / max_len if max_len > 0 else 1.0
    return similarity


@roleplaying_bp.route('/roleplaying', methods=['GET'])
def select_topic():
    topic = request.args.get('topic')
    user_id = session.get('user_id')
    if user_id:
        # Nastavíme first_activity pokud ještě není a uložíme čas začátku lekce
        update_user_stats(user_id, set_first_activity=True)
        session['roleplaying_training_start'] = time.time()
    if not topic:
        topics = [
            {
                "key": "directions",
                "name": "Directions",
                "desc": "Zeptej se na cestu...",
                "img": "pic/directions.png",
                "filename": "directions.json"
            },
            {
                "key": "restaurant",
                "name": "Restaurant",
                "desc": "Objednej si v restauraci...",
                "img": "pic/restaurant.png",
                "filename": "ordering_food.json"
            },
            {
                "key": "complaining",
                "name": "Complaining",
                "desc": "Stěžuj si na něco...",
                "img": "pic/complaining.png",
                "filename": "complaining.json"
            },
            {
                "key": "advice",
                "name": "Giving advice",
                "desc": "Dávat rady...",
                "img": "pic/advice.png",
                "filename": "giving_advice.json"
            },
        ]
        return render_template('speaking/roleplaying/select_topic.html', topics=topics)
    scenario = load_scenario(topic)
    if not scenario:
        return "Téma nenalezeno.", 404
    session['roleplaying_topic'] = topic
    session['roleplaying_index'] = 0
    session['roleplaying_dialogue'] = scenario['dialogue']
    return render_template('speaking/roleplaying/roleplaying.html',
                           topic=topic,
                           dialogue=scenario['dialogue'],
                           current_index=0,
                           speaker=scenario['dialogue'][0]['speaker'],
                           cz=scenario['dialogue'][0]['cz'],
                           en=scenario['dialogue'][0].get('en', ''))


@roleplaying_bp.route('/roleplaying/next', methods=['POST'])
def roleplaying_next():
    """Zpracuje odpověď uživatele a posune konverzaci dál."""
    import time as _time

    try:
        data = request.get_json()
        if data is None:
            data = {}
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        data = {}

    user_translation = data.get('preklad', '').strip()
    index = session.get('roleplaying_index', 0)
    dialogue = session.get('roleplaying_dialogue')
    topic = session.get('roleplaying_topic')

    if not dialogue:
        return jsonify({'error': 'Konverzace nenalezena. Začněte znovu.'}), 400

    if index >= len(dialogue):
        return jsonify({'error': 'Konec konverzace.'}), 400

    current = dialogue[index]
    is_user_turn = current['speaker'].lower() == 'uživatel'

    correct = True
    similarity = 1.0
    xp_awarded = 0
    streak_info = None
    new_xp = None
    new_level = None
    new_achievements = []
    xp_error = None
    best_match = None
    best_similarity = 0.0

    # --- STATISTIKY: počítání správných/špatných/blízkých odpovědí ---
    roleplaying_cr = 0
    roleplaying_wr = 0
    roleplaying_mb = 0

    if is_user_turn:
        correct_answers = current['en']
        if isinstance(correct_answers, str):
            correct_answers = [correct_answers]
        user_answer = normalize(user_translation)
        for ans in correct_answers:
            sim = levenshtein_similarity(normalize(ans), user_answer)
            if sim > best_similarity:
                best_similarity = sim
                best_match = ans
        similarity = best_similarity

        # Rozhodnutí o typu odpovědi
        if similarity >= 0.90:
            correct = True
            roleplaying_cr = 1
        elif similarity >= 0.65:
            correct = True
            roleplaying_mb = 1  # "blízko"
        else:
            correct = False
            roleplaying_wr = 1

        # --- Ukládání statistik ---
        if 'user_id' in session:
            update_user_stats(
                session['user_id'],
                roleplaying_cr=roleplaying_cr,
                roleplaying_wr=roleplaying_wr,
                roleplaying_mb=roleplaying_mb,
                lesson_done=False
            )

        if correct and 'user_id' in session:
            try:
                xp_result = add_xp_to_user(session['user_id'], 10)
                streak_info = update_user_streak(session['user_id'])
                xp_awarded = 10
                new_xp = xp_result.get('xp')
                new_level = xp_result.get('level')
                new_achievements = xp_result.get('new_achievements', [])
            except Exception as e:
                xp_error = str(e)
                print("XP/STREAK ERROR:", e)
                print(traceback.format_exc())

    # Posuň index na další repliku
    next_index = index + 1
    session['roleplaying_index'] = next_index

    # --- Pokud je to poslední replika, spočítej lesson_done a learning_time ---
    end_of_dialogue = next_index >= len(dialogue)
    if end_of_dialogue and 'user_id' in session:
        learning_time = None
        if session.get('roleplaying_training_start'):
            try:
                start = float(session.pop('roleplaying_training_start', None))
                duration = max(1, int(_time.time() - start))
                learning_time = duration
            except Exception as e:
                print("Chyba při ukládání času tréninku:", e)
        update_user_stats(
            session['user_id'],
            roleplaying_cr=0,
            roleplaying_wr=0,
            roleplaying_mb=0,
            lesson_done=True,
            learning_time=learning_time,
            set_first_activity=True  # pro jistotu
        )

    if next_index < len(dialogue):
        next_line = dialogue[next_index]
        return jsonify({
            'correct': correct,
            'similarity': round(similarity * 100, 1) if is_user_turn else None,
            'history': dialogue[:next_index + 1],
            'correct_answer': best_match if is_user_turn else None,
            'speaker': next_line.get('speaker', 'Alex'),  # Fallback pro případ chybějícího speaker
            'cz': next_line.get('cz', ''),
            'en': next_line.get('en', ''),
            'is_user_turn': next_line.get('speaker', 'Alex').lower() == 'uživatel',
            'already_in_history': False,  # Nová zpráva, není v historii
            'xp_awarded': xp_awarded,
            'new_xp': new_xp,
            'new_level': new_level,
            'new_achievements': new_achievements,
            'xp_error': xp_error,
            'streak_info': streak_info,
            'end': False
        })
    else:
        matching_pairs = []
        for line in dialogue:
            if line['speaker'].lower() == 'alex':
                if isinstance(line['en'], list):
                    en = line['en'][0]
                else:
                    en = line['en']
                matching_pairs.append({'en': en, 'cz': line['cz']})

        if len(matching_pairs) > 5:
            matching_pairs = random.sample(matching_pairs, 5)

        return jsonify({
            'correct': correct,
            'similarity': round(similarity * 100, 1) if is_user_turn else None,
            'history': dialogue[:next_index + 1],
            'correct_answer': best_match if is_user_turn else None,
            'end': True,
            'xp_awarded': xp_awarded,
            'new_xp': new_xp,
            'new_level': new_level,
            'new_achievements': new_achievements,
            'xp_error': xp_error,
            'streak_info': streak_info,
            'matching_pairs': matching_pairs
        })
