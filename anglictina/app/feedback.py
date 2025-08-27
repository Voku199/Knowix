from flask import Blueprint, jsonify, request, session, render_template, redirect, url_for
from datetime import datetime, timedelta
from db import get_db_connection
from xp import get_user_xp_and_level, check_and_award_achievements

feedback_bp = Blueprint('feedback', __name__)

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


@feedback_bp.context_processor
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


@feedback_bp.errorhandler(502)
@feedback_bp.errorhandler(503)
@feedback_bp.errorhandler(504)
@feedback_bp.errorhandler(500)
@feedback_bp.errorhandler(404)
def server_error(e):
    # Pouze pro GET požadavky (stránky), ne pro API
    if request.method == 'GET' and not request.path.startswith('/api/'):
        return render_template('error.html', error_code=e.code), e.code
    # Pro API požadavky vrátit JSON
    return jsonify({
        "status": "error",
        "message": "Interní chyba serveru"
    }), e.code if hasattr(e, 'code') else 500


@feedback_bp.route('/get_feedbacks', methods=['GET'])
def get_feedbacks():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        user_id = session.get('user_id', 0)

        cursor.execute('''
            SELECT 
                f.id,
                f.user_id,
                f.message,
                f.rating,
                f.timestamp,
                f.last_modified,
                f.is_edited,
                COALESCE(u.first_name, 'Anonymní') as user_name,
                COALESCE(u.profile_pic, 'default.jpg') as profile_pic
            FROM feedback f
            LEFT JOIN users u ON f.user_id = u.id
            ORDER BY f.timestamp DESC
        ''')

        feedbacks = cursor.fetchall()
        processed = []

        for fb in feedbacks:
            processed.append({
                'id': fb['id'],
                'user_name': fb['user_name'],
                'profile_pic': fb['profile_pic'],
                'message': fb['message'],
                'rating': fb['rating'],
                'timestamp': fb['timestamp'].strftime('%d.%m.%Y %H:%M'),
                'is_owner': fb['user_id'] == user_id,
                'is_edited': bool(fb['is_edited']),
                'last_modified': fb['last_modified'].strftime('%d.%m.%Y %H:%M') if fb['last_modified'] else None
            })

        return jsonify({
            "status": "success",
            "feedbacks": processed
        })

    except Exception as e:
        print(f"Chyba v get_feedbacks: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Interní chyba serveru",
            "feedbacks": []
        }), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@feedback_bp.route('/feedback/<int:feedback_id>', methods=['PUT', 'DELETE'])
def manage_feedback(feedback_id):
    if 'user_id' not in session:
        return jsonify({
            "status": "error",
            "message": "Nejprve se přihlaste"
        }), 401

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute('''
            SELECT * FROM feedback 
            WHERE id = %s AND user_id = %s
        ''', (feedback_id, session['user_id']))
        feedback = cursor.fetchone()

        if not feedback:
            return jsonify({
                "status": "error",
                "message": "Feedback neexistuje"
            }), 404

        if request.method == 'PUT':
            data = request.get_json()
            new_message = data.get('message', '').strip()
            new_rating = int(data.get('rating', 0))

            if not new_message or new_rating < 1 or new_rating > 5:
                return jsonify({
                    "status": "error",
                    "message": "Neplatná data"
                }), 400

            cursor.execute('''
                        UPDATE feedback 
                        SET message = %s, 
                            rating = %s, 
                            last_modified = NOW(),
                            is_edited = 1
                        WHERE id = %s
                    ''', (new_message, new_rating, feedback_id))

            cursor.execute('''
                        SELECT 
                            timestamp,
                            last_modified 
                        FROM feedback 
                        WHERE id = %s
                    ''', (feedback_id,))
            updated = cursor.fetchone()

            conn.commit()

            # NOVĚ: zkontroluj a případně přidej achievementy po editaci
            unlocked_achievements = check_and_award_achievements(session['user_id'])

            return jsonify({
                "status": "success",
                "message": "Feedback aktualizován",
                "new_message": new_message,
                "new_rating": new_rating,
                "last_modified": updated['last_modified'].strftime('%d.%m.%Y %H:%M'),
                "is_edited": True,
                "new_achievements": unlocked_achievements
            })

        elif request.method == 'DELETE':
            cursor.execute('''
                DELETE FROM feedback 
                WHERE id = %s
            ''', (feedback_id,))
            conn.commit()
            return jsonify({
                "status": "success",
                "message": "Feedback smazán"
            })

    except Exception as e:
        print(f"Chyba v manage_feedback: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Interní chyba serveru"
        }), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@feedback_bp.route('/feedback', methods=['GET'])
def feedback_page():
    return render_template("feedback.html")


@feedback_bp.route('/feedback-post', methods=['POST'])
def handle_feedback():
    if 'user_id' not in session:
        return jsonify({
            "status": "error",
            "message": "Nejprve se přihlaste"
        }), 401

    data = request.get_json()
    if not data:
        return jsonify({
            "status": "error",
            "message": "Neplatná data"
        }), 400

    message = data.get("message", "").strip()

    try:
        rating = int(data.get("rating", 0))
    except (ValueError, TypeError):
        return jsonify({
            "status": "error",
            "message": "Neplatný formát hodnocení"
        }), 400

    # Validace vstupů
    if not message or len(message) > 500:
        return jsonify({
            "status": "error",
            "message": "Zpráva musí mít 1-500 znaků"
        }), 400

    if rating < 1 or rating > 5:
        return jsonify({
            "status": "error",
            "message": "Hodnocení musí být mezi 1-5"
        }), 400

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Kontrola časového limitu
        cursor.execute('''
            SELECT MAX(timestamp) AS last_feedback 
            FROM feedback 
            WHERE user_id = %s
        ''', (session['user_id'],))
        last_feedback = cursor.fetchone()

        if last_feedback and last_feedback['last_feedback']:
            time_diff = datetime.now() - last_feedback['last_feedback']
            if time_diff < timedelta(hours=2):
                remaining = timedelta(hours=2) - time_diff
                minutes = remaining.seconds // 60
                return jsonify({
                    "status": "error",
                    "message": f"Můžete poslat další feedback za {minutes} minut"
                }), 429

        # Vložení nového feedbacku
        cursor.execute('''
            INSERT INTO feedback (user_id, message, rating)
            VALUES (%s, %s, %s)
        ''', (session['user_id'], message, rating))
        feedback_id = cursor.lastrowid

        # Získání kompletních dat
        cursor.execute('''
            SELECT 
                f.id,
                f.message,
                f.rating,
                f.timestamp,
                f.is_edited,
                COALESCE(u.first_name, 'Anonymní') as user_name,
                COALESCE(u.profile_pic, 'default.jpg') as profile_pic
            FROM feedback f
            LEFT JOIN users u ON f.user_id = u.id
            WHERE f.id = %s
        ''', (feedback_id,))
        new_feedback = cursor.fetchone()

        conn.commit()

        # Kontrola a přidělení achievementů
        unlocked_achievements = check_and_award_achievements(session['user_id'])

        return jsonify({
            "status": "success",
            "message": "Děkujeme za zpětnou vazbu!",
            "feedback": {
                "id": new_feedback['id'],
                "user_name": new_feedback['user_name'],
                "profile_pic": new_feedback['profile_pic'],
                "message": new_feedback['message'],
                "rating": new_feedback['rating'],
                "timestamp": new_feedback['timestamp'].strftime('%d.%m.%Y %H:%M'),
                "is_owner": True,
                "is_edited": False
            },
            "new_achievements": unlocked_achievements
        })

    except Exception as e:
        print(f"Chyba při ukládání feedbacku: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Interní chyba serveru"
        }), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
