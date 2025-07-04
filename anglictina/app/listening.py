from flask import Blueprint, render_template, request, redirect, url_for, jsonify, make_response, session
from xp import get_user_xp_and_level, add_xp_to_user
from streak import update_user_streak, get_user_streak  # <-- Přidáno pro streak
import json
import os

listening_bp = Blueprint('listening_bp', __name__, template_folder='templates', static_folder='static')

DATA_FILE = os.path.join(os.path.dirname(__file__), 'static', 'listening', 'listening_lesson.json')

LEVEL_NAMES = [
    "Začátečník", "Učeň", "Student", "Pokročilý", "Expert", "Mistr", "Legenda"
]


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


@listening_bp.context_processor
def inject_streak():
    user_id = session.get('user_id')
    if user_id:
        streak = get_user_streak(user_id)
        return dict(user_streak=streak)
    return dict(user_streak=0)


@listening_bp.context_processor
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


@listening_bp.errorhandler(502)
@listening_bp.errorhandler(503)
@listening_bp.errorhandler(504)
@listening_bp.errorhandler(500)
@listening_bp.errorhandler(404)
@listening_bp.errorhandler(Exception)
def server_error(e):
    # vrátí stránku error.html s informací o výpadku
    return render_template('error.html', error_code=e.code), e.code


@listening_bp.route('/listening')
def index():
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        lessons = json.load(f)
    return render_template('listening/index.html', lessons=lessons)


@listening_bp.route('/listening/<level>/<lesson_id>')
def lesson(level, lesson_id):
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        lessons = json.load(f)
    lesson_data = next((l for l in lessons[level] if l['id'] == lesson_id), None)
    rendered = render_template('listening/lesson.html', lesson=lesson_data, level=level)
    response = make_response(rendered)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response


@listening_bp.route('/validate_quiz', methods=['POST'])
def validate_quiz():
    """
    Expects form data:
      - level: e.g. "B2"
      - lesson_id: e.g. "b2_lesson_indian_scammer"
      - q0, q1, q2, ...: user's answers
    Returns JSON with score, total, correct_answers, and optionally error.
    """
    level = request.form.get('level')
    lesson_id = request.form.get('lesson_id')
    if not level or not lesson_id:
        return jsonify({'error': 'Missing level or lesson_id'}), 400

    # Load lessons data
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            lessons = json.load(f)
    except Exception as e:
        return jsonify({'error': 'Data file error: {}'.format(str(e))}), 500

    # Find the lesson
    lesson_list = lessons.get(level)
    if not lesson_list:
        return jsonify({'error': 'Level not found'}), 404

    lesson_data = next((l for l in lesson_list if l['id'] == lesson_id), None)
    if not lesson_data:
        return jsonify({'error': 'Lesson not found'}), 404

    questions = lesson_data.get('questions', [])
    correct_answers = []
    user_answers = []
    for idx, q in enumerate(questions):
        correct = q.get('answer')
        if isinstance(correct, list):
            correct = correct[0]
        correct_answers.append(correct)
        user_answer = request.form.get(f'q{idx}', '').strip()
        user_answers.append(user_answer)

    # Compare answers (case-insensitive, trimmed)
    score = sum(
        1 for ua, ca in zip(user_answers, correct_answers)
        if ua.strip().lower() == ca.strip().lower()
    )
    total = len(correct_answers)

    # --- XP & STREAK INTEGRACE ---
    xp_awarded = 0
    new_xp = None
    new_level = None
    new_achievements = []
    xp_error = None
    streak_info = None  # <-- Přidáno pro streak
    all_correct = (score == total and total > 0)
    if all_correct and 'user_id' in session:
        try:
            xp_result = add_xp_to_user(session['user_id'], 15)
            xp_awarded = 15
            new_xp = xp_result.get('xp')
            new_level = xp_result.get('level')
            new_achievements = xp_result.get('new_achievements', [])
            # --- Streak logika ---
            streak_info = update_user_streak(session['user_id'])
        except Exception as e:
            xp_error = str(e)

    return jsonify({
        'score': score,
        'total': total,
        'answers': correct_answers,
        'user_answers': user_answers,
        'all_correct': all_correct,
        'xp_awarded': xp_awarded,
        'new_xp': new_xp,
        'new_level': new_level,
        'new_achievements': new_achievements,
        'xp_error': xp_error,
        'streak_info': streak_info  # <-- Přidáno do odpovědi
    })
