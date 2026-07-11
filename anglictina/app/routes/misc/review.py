from flask import Blueprint, request, session, jsonify
from db import get_db_connection
from xp import check_and_award_achievements

review_bp = Blueprint('review', __name__)


@review_bp.route('/add-review', methods=['POST'])
def add_review():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not logged in'}), 401

    data = request.get_json()
    message = data.get('message')
    rating = data.get('rating', 0)

    if not message or not isinstance(message, str) or len(message.strip()) == 0:
        return jsonify({'error': 'Message is required'}), 400
    if not isinstance(rating, int) or rating < 1 or rating > 5:
        return jsonify({'error': 'Rating must be an integer between 1 and 5'}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO feedback (user_id, message, rating, timestamp, is_edited) VALUES (%s, %s, %s, NOW(), FALSE)",
        (user_id, message.strip(), rating)
    )
    conn.commit()
    cur.close()
    conn.close()

    # Zkontroluj a případně přidej achievement
    new_achievements = check_and_award_achievements(user_id)

    return jsonify({'success': True, 'new_achievements': new_achievements})
