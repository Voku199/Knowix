from flask import Blueprint, request, jsonify, session, render_template, current_app
import random  # nezapomeň mít navrchu
import json
import unicodedata
from difflib import SequenceMatcher
import re
import os
from xp import add_xp_to_user
from streak import update_user_streak, get_user_streak
from user_stats import update_user_stats
import time

chat_bp = Blueprint("chat_bp", __name__)


@chat_bp.errorhandler(502)
@chat_bp.errorhandler(503)
@chat_bp.errorhandler(504)
@chat_bp.errorhandler(500)
@chat_bp.errorhandler(404)
def server_error(e):
    # Pro AJAX požadavky vraťme JSON místo HTML
    if request.is_json or request.path.startswith('/chat/'):
        return jsonify({
            "error": f"Server error {getattr(e, 'code', 500)}",
            "message": getattr(e, 'description', 'Internal server error')
        }), getattr(e, 'code', 500)

    # Pro běžné požadavky vraťme HTML error stránku
    return render_template('error.html', error_code=getattr(e, 'code', 500)), getattr(e, 'code', 500)


# Načtení lekce z JSON

@chat_bp.context_processor
def inject_streak():
    user_id = session.get('user_id')
    if user_id:
        streak = get_user_streak(user_id)
        return dict(user_streak=streak)
    return dict(user_streak=0)


def normalize_text(text):
    # malá písmena
    text = text.lower()
    # odstraní diakritiku
    text = ''.join(
        c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c)
    )
    # odstraní tečky, čárky, víc mezer apod.
    text = re.sub(r'[^a-z0-9\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


@chat_bp.route('/gramatika')
def chat_page():
    return render_template('gram/gram_select.html')


@chat_bp.route('/sl_chat')
def sl_chat():
    with open('static/gram/present_perfect/chat_lessons.json', encoding='utf-8') as f:
        chat_lessons = json.load(f)

    return render_template('gram/present_perfect/select_chat.html', chat_lessons=chat_lessons)


@chat_bp.route('/chat')
def chat():
    lesson_id = request.args.get('lesson_id', '')

    # --- Nastavení first_activity a začátek měření času při vstupu do lekce ---
    user_id = session.get('user_id')
    if user_id:
        update_user_stats(user_id, set_first_activity=True)
    session['pp_training_start'] = time.time()

    # Náhodný výběr pro lekci 'relationship_path'
    if lesson_id == "relationship_path":
        selected_filename = random.choice([
            "love_ending_good.json",
            "love_ending_bad.json",
            "love_ending_weird.json"
        ])
    elif lesson_id == "social_media":
        roll = random.randint(1, 100)
        if roll <= 33:
            selected_filename = "media.json"
        elif roll <= 66:
            selected_filename = "media2.json"
        else:
            selected_filename = "media3.json"

    elif lesson_id == "mental_health":
        roll = random.randint(1, 100)
        if roll <= 33:
            selected_filename = "mental_chat.json"
        elif roll <= 66:
            selected_filename = "mental_chat2.json"
        else:
            selected_filename = "mental_chat3.json"

    elif lesson_id == "vr_gaming":
        roll = random.randint(1, 100)
        if roll <= 33:
            selected_filename = "vr_world.json"
        elif roll <= 66:
            selected_filename = "vr_world2.json"
        else:
            selected_filename = "vr_world3.json"

    elif lesson_id == "school_future":
        roll = random.randint(1, 100)
        if roll <= 33:
            selected_filename = "school.json"
        elif roll <= 66:
            selected_filename = "school2.json"
        else:
            selected_filename = "school3.json"

    else:
        if lesson_id.endswith(".json"):
            selected_filename = lesson_id
        else:
            selected_filename = f"{lesson_id}_chat.json"

    # Načtení souboru
    chat_file = os.path.join(
        current_app.root_path,
        'static', 'gram', 'present_perfect',
        selected_filename
    )

    print(f"Attempting to load: {chat_file}")

    try:
        with open(chat_file, 'r', encoding='utf-8') as f:
            chat_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading chat data: {str(e)}")
        chat_data = []

    # Načtení seznamu lekcí
    lessons_file = os.path.join(
        current_app.root_path,
        'static', 'gram', 'present_perfect',
        'chat_lessons.json'
    )
    try:
        with open(lessons_file, 'r', encoding='utf-8') as f:
            chat_lessons = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading lessons: {str(e)}")
        chat_lessons = []

    session.pop('chat_data', None)
    session.pop('chat_index', None)
    session.pop('current_lesson', None)
    session['chat_data'] = chat_data
    session['chat_index'] = 0
    session['current_lesson'] = selected_filename

    return render_template('gram/present_perfect/chat.html', chat_lessons=chat_lessons)


@chat_bp.route('/chat/start', methods=['GET'])
def start_chat():
    try:
        print("DEBUG: start_chat called")
        chat_data = session.get('chat_data', [])
        print(f"DEBUG: chat_data length: {len(chat_data)}")

        if not chat_data:
            print("ERROR: No chat data in session for start_chat")
            return jsonify({"error": "No chat loaded"}), 400

        session['chat_index'] = 0
        first_message = chat_data[0]

        print(f"DEBUG: Returning first message: {first_message.get('alex', '')[:50]}...")
        return jsonify({
            "alex": first_message["alex"],
            "cz_reply": first_message["cz_reply"]
        })
    except Exception as e:
        print(f"ERROR in start_chat: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Error starting chat: {str(e)}"}), 500


def similarity(a, b):
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


@chat_bp.route('/chat/next', methods=['POST'])
def next_step():
    try:
        # Kontrola Content-Type
        if not request.is_json:
            print(f"ERROR: Invalid Content-Type: {request.content_type}")
            return jsonify({"error": "Content-Type must be application/json"}), 400

        data = request.get_json()
        if not data:
            print("ERROR: No JSON data received")
            print(f"Raw data: {request.get_data()}")
            return jsonify({"error": "No JSON data received"}), 400

        user_answer = data.get("answer", "")
        print(f"DEBUG: Received answer: '{user_answer}'")

        current_index = session.get("chat_index", 0)
        chat_data = session.get("chat_data", [])

        print(f"DEBUG: Current index: {current_index}, Chat data length: {len(chat_data)}")

        if not chat_data:
            print("ERROR: No chat data in session")
            print(f"Session keys: {list(session.keys())}")
            return jsonify({"error": "No chat data in session"}), 400

        # Speciální testovací heslo pro okamžité dokončení lekce
        if normalize_text(user_answer) == "abraka dabra bum":
            try:
                xp_awarded = 10  # nebo jiná logika
                xp_result = None
                streak_info = None
                user_id = session.get('user_id')
                learning_time = None
                if user_id:
                    # Výpočet learning_time
                    if session.get('pp_training_start'):
                        try:
                            start = float(session.pop('pp_training_start', None))
                            duration = max(1, int(time.time() - start))
                            learning_time = duration
                        except Exception as e:
                            print("Chyba při ukládání času tréninku:", e)
                    # lesson_done + learning_time + first_activity
                    update_user_stats(user_id, lesson_done=True, learning_time=learning_time, set_first_activity=True)
                    xp_result = add_xp_to_user(user_id, xp_awarded)
                    streak_info = update_user_streak(user_id)
                session['chat_index'] = len(chat_data)
                return jsonify({
                    "correct": True,
                    "done": True,
                    "xp": xp_awarded,
                    "xp_result": xp_result,
                    "streak_info": streak_info,
                    "test_magic": True
                })
            except Exception as e:
                print(f"Error in magic password handler: {str(e)}")
                return jsonify({"error": f"Magic password error: {str(e)}"}), 500

        if current_index >= len(chat_data):
            try:
                # Lekce je dokončena
                xp_awarded = 10  # nebo jiná logika
                xp_result = None
                streak_info = None
                user_id = session.get('user_id')
                learning_time = None
                if user_id:
                    # Výpočet learning_time
                    if session.get('pp_training_start'):
                        try:
                            start = float(session.pop('pp_training_start', None))
                            duration = max(1, int(time.time() - start))
                            learning_time = duration
                        except Exception as e:
                            print("Chyba při ukládání času tréninku:", e)
                    # lesson_done + learning_time + first_activity
                    update_user_stats(user_id, lesson_done=True, learning_time=learning_time, set_first_activity=True)
                    xp_result = add_xp_to_user(user_id, xp_awarded)
                    streak_info = update_user_streak(user_id)
                return jsonify({
                    "done": True,
                    "xp": xp_awarded,
                    "xp_result": xp_result,
                    "streak_info": streak_info
                })
            except Exception as e:
                print(f"Error in lesson completion handler: {str(e)}")
                return jsonify({"error": f"Lesson completion error: {str(e)}"}), 500

        try:
            accepted = chat_data[current_index]["accepted_answers"]
        except (KeyError, IndexError) as e:
            print(f"ERROR: Invalid chat data structure at index {current_index}: {str(e)}")
            return jsonify({"error": "Invalid chat data structure"}), 400

        normalized_user = normalize_text(user_answer)

        best_match = None
        best_similarity = 0

        for correct in accepted:
            sim = similarity(user_answer, correct)
            if sim > best_similarity:
                best_similarity = sim
                best_match = correct

        user_id = session.get('user_id')

        if best_similarity >= 1.0:
            try:
                # 100% správná odpověď
                if user_id:
                    update_user_stats(user_id, pp_correct=1)
                current_index += 1
                session['chat_index'] = current_index
                if current_index < len(chat_data):
                    next_message = chat_data[current_index]
                    return jsonify({
                        "correct": True,
                        "alex": next_message["alex"],
                        "cz_reply": next_message["cz_reply"]
                    })
                else:
                    # Lekce dokončena
                    xp_awarded = 10
                    xp_result = None
                    streak_info = None
                    learning_time = None
                    if user_id:
                        if session.get('pp_training_start'):
                            try:
                                start = float(session.pop('pp_training_start', None))
                                duration = max(1, int(time.time() - start))
                                learning_time = duration
                            except Exception as e:
                                print("Chyba při ukládání času tréninku:", e)
                        update_user_stats(user_id, lesson_done=True, learning_time=learning_time,
                                          set_first_activity=True)
                        xp_result = add_xp_to_user(user_id, xp_awarded)
                        streak_info = update_user_streak(user_id)
                    return jsonify({
                        "correct": True,
                        "done": True,
                        "xp": xp_awarded,
                        "xp_result": xp_result,
                        "streak_info": streak_info
                    })
            except Exception as e:
                print(f"Error in perfect answer handler: {str(e)}")
                return jsonify({"error": f"Perfect answer error: {str(e)}"}), 500

        elif best_similarity >= 0.8:
            try:
                # Skoro správně – uznáme, ale upozorníme na chybu
                if user_id:
                    update_user_stats(user_id, pp_maybe=1)
                current_index += 1
                session['chat_index'] = current_index
                if current_index < len(chat_data):
                    next_message = chat_data[current_index]
                    return jsonify({
                        "correct": True,
                        "almost": True,
                        "expected": best_match,
                        "alex": next_message["alex"],
                        "cz_reply": next_message["cz_reply"]
                    })
                else:
                    xp_awarded = 10
                    xp_result = None
                    streak_info = None
                    learning_time = None
                    if user_id:
                        if session.get('pp_training_start'):
                            try:
                                start = float(session.pop('pp_training_start', None))
                                duration = max(1, int(time.time() - start))
                                learning_time = duration
                            except Exception as e:
                                print("Chyba při ukládání času tréninku:", e)
                        update_user_stats(user_id, lesson_done=True, learning_time=learning_time,
                                          set_first_activity=True)
                        xp_result = add_xp_to_user(user_id, xp_awarded)
                        streak_info = update_user_streak(user_id)
                    return jsonify({
                        "correct": True,
                        "almost": True,
                        "expected": best_match,
                        "done": True,
                        "xp": xp_awarded,
                        "xp_result": xp_result,
                        "streak_info": streak_info
                    })
            except Exception as e:
                print(f"Error in almost correct handler: {str(e)}")
                return jsonify({"error": f"Almost correct error: {str(e)}"}), 500

        else:
            try:
                # Špatně
                if user_id:
                    update_user_stats(user_id, pp_wrong=1)
                return jsonify({"correct": False})
            except Exception as e:
                print(f"Error in wrong answer handler: {str(e)}")
                return jsonify({"error": f"Wrong answer error: {str(e)}"}), 500

    except Exception as e:
        print(f"Unexpected error in next_step: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500


@chat_bp.route('/chat/test', methods=['GET'])
def test_endpoint():
    """Testovací endpoint pro ověření, že routing funguje"""
    return jsonify({
        "status": "ok",
        "message": "Chat endpoint funguje",
        "session_keys": list(session.keys()) if session else [],
        "has_chat_data": bool(session.get('chat_data', [])),
        "chat_data_length": len(session.get('chat_data', []))
    })
