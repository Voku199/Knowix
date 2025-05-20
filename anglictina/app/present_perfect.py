from flask import Blueprint, request, jsonify, session, render_template, current_app
import random  # nezapomeň mít navrchu
import json
import unicodedata
from difflib import SequenceMatcher
import re
import os

chat_bp = Blueprint("chat_bp", __name__)


# Načtení lekce z JSON


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

    # Náhodný výběr pro lekci 'relationship_path'
    if lesson_id == "relationship_path":
        selected_filename = random.choice([
            "love_ending_good.json",
            "love_ending_bad.json",
            "love_ending_weird.json"
        ])
    elif lesson_id == "social_media":
        # Tohle si můžeš přizpůsobit podle potřeby – tady ponechávám 50/48/2%
        roll = random.randint(1, 100)
        if roll <= 33:
            selected_filename = "media.json"
        elif roll <= 66:
            selected_filename = "media2.json"
        else:
            selected_filename = "media3.json"

    elif lesson_id == "mental_health":
        # Tohle si můžeš přizpůsobit podle potřeby – tady ponechávám 50/48/2%
        roll = random.randint(1, 100)
        if roll <= 33:
            selected_filename = "mental_chat.json"
        elif roll <= 66:
            selected_filename = "mental_chat2.json"
        else:
            selected_filename = "mental_chat3.json"

    elif lesson_id == "vr_gaming":
        # Tohle si můžeš přizpůsobit podle potřeby – tady ponechávám 50/48/2%
        roll = random.randint(1, 100)
        if roll <= 33:
            selected_filename = "vr_world.json"
        elif roll <= 66:
            selected_filename = "vr_world2.json"
        else:
            selected_filename = "vr_wolrd3.json"

    elif lesson_id == "school_future":
        # Tohle si můžeš přizpůsobit podle potřeby – tady ponechávám 50/48/2%
        roll = random.randint(1, 100)
        if roll <= 33:
            selected_filename = "school.json"
        elif roll <= 66:
            selected_filename = "school2.json"
        else:
            selected_filename = "school3.json"

    else:
        # Pro ostatní lekce normálně přidáme _chat.json
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

    # Session
    session.clear()
    session['chat_data'] = chat_data
    session['chat_index'] = 0
    session['current_lesson'] = selected_filename

    return render_template('gram/present_perfect/chat.html', chat_lessons=chat_lessons)


@chat_bp.route('/chat/start', methods=['GET'])
def start_chat():
    chat_data = session.get('chat_data', [])
    session['chat_index'] = 0
    if not chat_data:
        return jsonify({"error": "No chat loaded"})

    first_message = chat_data[0]
    return jsonify({
        "alex": first_message["alex"],
        "cz_reply": first_message["cz_reply"]
    })


def similarity(a, b):
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


@chat_bp.route('/chat/next', methods=['POST'])
def next_step():
    data = request.get_json()
    user_answer = data.get("answer", "")
    current_index = session.get("chat_index", 0)
    chat_data = session.get("chat_data", [])

    if current_index >= len(chat_data):
        return jsonify({"done": True})

    accepted = chat_data[current_index]["accepted_answers"]
    normalized_user = normalize_text(user_answer)

    best_match = None
    best_similarity = 0

    for correct in accepted:
        sim = similarity(user_answer, correct)
        if sim > best_similarity:
            best_similarity = sim
            best_match = correct

    if best_similarity >= 1.0:
        # 100% správná odpověď
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
            return jsonify({"correct": True, "done": True})

    elif best_similarity >= 0.8:
        # Skoro správně – uznáme, ale upozorníme na chybu
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
            return jsonify({
                "correct": True,
                "almost": True,
                "expected": best_match,
                "done": True
            })

    else:
        # Špatně
        return jsonify({"correct": False})
