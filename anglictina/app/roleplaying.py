from flask import Blueprint, render_template, request, session, jsonify
import json
import os
import traceback
import random

from xp import add_xp_to_user
from streak import update_user_streak, get_user_streak

roleplaying_bp = Blueprint('roleplaying', __name__, template_folder='templates')

# Cesta ke složce s konverzačními scénáři
SCENARIOS_DIR = os.path.join(os.path.dirname(__file__), 'static/speaking/roleplaying')


def load_scenario(filename):
    """Načte JSON scénář podle názvu souboru."""
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
    # Simple Levenshtein similarity (normalized)
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

            # ... další témata
        ]
        return render_template('speaking/roleplaying/select_topic.html', topics=topics)
    # Začátek konverzace
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
                           cz=scenario['dialogue'][0]['cz'])


@roleplaying_bp.route('/roleplaying/next', methods=['POST'])
def roleplaying_next():
    """Zpracuje odpověď uživatele a posune konverzaci dál."""
    data = request.get_json()
    user_translation = data.get('preklad', '').strip()
    index = session.get('roleplaying_index', 0)
    dialogue = session.get('roleplaying_dialogue')
    topic = session.get('roleplaying_topic')

    if not dialogue or index >= len(dialogue):
        return jsonify({'error': 'Konec konverzace.'})

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
        correct = similarity >= 0.70
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

    if next_index < len(dialogue):
        next_line = dialogue[next_index]
        return jsonify({
            'correct': correct,
            'similarity': round(similarity * 100, 1) if is_user_turn else None,
            'history': dialogue[:next_index + 1],
            'correct_answer': best_match if is_user_turn else None,
            'speaker': next_line['speaker'],
            'cz': next_line['cz'],
            'en': next_line['en'],
            'is_user_turn': next_line['speaker'].lower() == 'uživatel',
            'xp_awarded': xp_awarded,
            'new_xp': new_xp,
            'new_level': new_level,
            'new_achievements': new_achievements,
            'xp_error': xp_error,
            'streak_info': streak_info,
            'end': False
        })
    else:
        # Přidání matching_pairs do odpovědi po skončení konverzace - pouze 5 náhodných dvojic
        matching_pairs = []
        for line in dialogue:
            if line['speaker'].lower() == 'alex':
                if isinstance(line['en'], list):
                    en = line['en'][0]
                else:
                    en = line['en']
                matching_pairs.append({'en': en, 'cz': line['cz']})

        # Vyber náhodných 5 (nebo méně, pokud je méně replik)
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
