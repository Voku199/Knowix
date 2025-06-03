from flask import Blueprint, render_template, request, redirect, url_for, jsonify, make_response
import json
import os

listening_bp = Blueprint('listening_bp', __name__, template_folder='templates', static_folder='static')

DATA_FILE = os.path.join(os.path.dirname(__file__), 'static', 'listening', 'listening_lesson.json')


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
        # Some answers in your JSON are lists, some are strings
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

    return jsonify({
        'score': score,
        'total': total,
        'answers': correct_answers,
        'user_answers': user_answers
    })
