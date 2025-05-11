from flask import Blueprint, jsonify, request, session, render_template, redirect, url_for
from datetime import datetime
from auth import get_db_connection

feedback_bp = Blueprint('feedback', __name__)


@feedback_bp.route('/get_feedbacks')
def get_feedbacks():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute('''
            SELECT f.message, f.rating, f.timestamp, 
                   u.first_name as user_name, u.profile_pic 
            FROM feedback f
            JOIN users u ON f.user_id = u.id
            ORDER BY f.timestamp DESC
        ''')

        feedbacks = cursor.fetchall()

        for fb in feedbacks:
            fb['timestamp'] = fb['timestamp'].strftime('%d.%m.%Y %H:%M')

        return jsonify({"feedbacks": feedbacks})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@feedback_bp.route('/feedback', methods=['GET'])
def feedback_form():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute('''
            SELECT f.message, f.rating, f.timestamp, 
                   u.first_name as user_name, u.profile_pic 
            FROM feedback f
            JOIN users u ON f.user_id = u.id
            ORDER BY f.timestamp DESC
        ''')

        feedbacks = cursor.fetchall()

        for fb in feedbacks:
            fb['timestamp'] = fb['timestamp'].strftime('%d.%m.%Y %H:%M')

        return render_template('feedback.html', feedbacks=feedbacks)

    except Exception as e:
        return render_template('feedback.html', feedbacks=[], error=str(e))
    finally:
        cursor.close()
        conn.close()


@feedback_bp.route('/feedback', methods=['POST'])
def handle_feedback():
    """Zpracuje API požadavek s JSON daty"""
    if not request.is_json:
        return jsonify({"status": "error", "message": "Požadavek musí být v JSON formátu"}), 415

    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Nejprve se přihlaste"}), 401

    data = request.get_json()
    message = data.get("message", "").strip()

    try:
        # Konverze ratingu na integer s ošetřením různých formátů
        rating = int(float(data.get("rating", 0)))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Hodnocení musí být číslo"}), 400

    # Rozšířená validace
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

        cursor.execute('''
            INSERT INTO feedback (user_id, message, rating, timestamp)
            VALUES (%s, %s, %s, NOW())
        ''', (session['user_id'], message, rating))
        conn.commit()

        cursor.execute('''
            SELECT first_name, profile_pic 
            FROM users 
            WHERE id = %s
        ''', (session['user_id'],))
        user = cursor.fetchone()

        return jsonify({
            "status": "success",
            "message": "Děkujeme za zpětnou vazbu!",
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
