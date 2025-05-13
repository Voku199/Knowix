from flask import Blueprint, jsonify, request, session, render_template, redirect, url_for
from datetime import datetime, timedelta
from auth import get_db_connection

feedback_bp = Blueprint('feedback', __name__)


@feedback_bp.route('/get_feedbacks')
def get_feedbacks():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Získání ID přihlášeného uživatele (pokud existuje)
        user_id = session.get('user_id', 0)

        cursor.execute('''
            SELECT f.id, f.user_id, f.message, f.rating, f.timestamp, 
                   f.last_feedback_time, f.is_edited,
                   u.first_name as user_name, u.profile_pic 
            FROM feedback f
            JOIN users u ON f.user_id = u.id
            ORDER BY f.timestamp DESC
        ''')

        feedbacks = cursor.fetchall()

        for fb in feedbacks:
            fb['timestamp'] = fb['timestamp'].strftime('%d.%m.%Y %H:%M')
            fb['is_owner'] = fb['user_id'] == user_id  # Označení vlastních feedbacků
            if fb['last_modified']:
                fb['last_modified'] = fb['last_modified'].strftime('%d.%m.%Y %H:%M')

        return jsonify({"feedbacks": feedbacks})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@feedback_bp.route('/feedback/<int:feedback_id>', methods=['PUT', 'DELETE'])
def manage_feedback(feedback_id):
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Nejprve se přihlaste"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Ověření vlastnictví feedbacku
        cursor.execute('''
            SELECT * FROM feedback 
            WHERE id = %s AND user_id = %s
        ''', (feedback_id, session['user_id']))
        feedback = cursor.fetchone()

        if not feedback:
            return jsonify({"status": "error", "message": "Feedback neexistuje"}), 404

        if request.method == 'PUT':
            data = request.get_json()
            new_message = data.get('message', '').strip()
            new_rating = int(data.get('rating', 0))

            # Validace
            if not new_message or not 1 <= new_rating <= 5:
                return jsonify({"status": "error", "message": "Neplatná data"}), 400

            # Aktualizace feedbacku
            cursor.execute('''
                UPDATE feedback 
                SET message = %s, 
                    rating = %s, 
                    last_modified = NOW(),
                    is_edited = TRUE
                WHERE id = %s
            ''', (new_message, new_rating, feedback_id))
            conn.commit()

            return jsonify({
                "status": "success",
                "message": "Feedback byl úspěšně aktualizován",
                "new_message": new_message,
                "new_rating": new_rating,
                "last_modified": datetime.now().strftime('%d.%m.%Y %H:%M')
            })

        elif request.method == 'DELETE':
            cursor.execute('DELETE FROM feedback WHERE id = %s', (feedback_id,))
            conn.commit()
            return jsonify({"status": "success", "message": "Feedback byl smazán"})

    except Exception as e:
        return jsonify({"status": "error", "message": f"Chyba: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()


@feedback_bp.route('/feedback', methods=['GET'])
def feedback_page():
    return render_template("feedback.html")  # nebo redirect, nebo jiná logika


@feedback_bp.route('/feedback', methods=['POST'])
def handle_feedback():
    if not request.is_json:
        return jsonify({"status": "error", "message": "Požadavek musí být v JSON formátu"}), 415

    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Nejprve se přihlaste"}), 401

    data = request.get_json()
    message = data.get("message", "").strip()

    try:
        rating = int(float(data.get("rating", 0)))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Hodnocení musí být číslo"}), 400

    validation_errors = []
    if not message:
        validation_errors.append("Zpráva nesmí být prázdná")
    if not 1 <= rating <= 5:
        validation_errors.append("Hodnocení musí být mezi 1 a 5 hvězdičkami")

    if validation_errors:
        return jsonify({
            "status": "error",
            "message": "Neplatné údaje",
            "errors": validation_errors
        }), 400

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
                minutes = int(remaining.seconds // 60)
                return jsonify({
                    "status": "error",
                    "message": f"Můžete poslat další feedback za {minutes} minut"
                }), 429

        # Vložení nového feedbacku
        cursor.execute('''
            INSERT INTO feedback (user_id, message, rating, timestamp, last_feedback_time)
            VALUES (%s, %s, %s, NOW(), NOW())
        ''', (session['user_id'], message, rating))
        feedback_id = cursor.lastrowid
        conn.commit()

        # Získání uživatelských dat
        cursor.execute('''
            SELECT first_name, profile_pic 
            FROM users 
            WHERE id = %s
        ''', (session['user_id'],))
        user = cursor.fetchone()

        return jsonify({
            "status": "success",
            "message": "Děkujeme za zpětnou vazbu!",
            "feedback_id": feedback_id,
            "user_name": user['first_name'],
            "profile_pic": user['profile_pic'] or 'default.jpg',
            "timestamp": datetime.now().strftime('%d.%m.%Y %H:%M'),
            "rating": rating
        })

    except Exception as e:
        return jsonify({"status": "error", "message": f"Chyba: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()
