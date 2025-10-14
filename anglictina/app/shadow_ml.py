from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from db import get_db_connection
import random
import json
import os

shadow_ml_bp = Blueprint('shadow_ml', __name__)


def require_login():
    """Kontrola přihlášení uživatele"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    return None


def load_sentences():
    """Načte věty z JSON souboru"""
    try:
        json_path = os.path.join(os.path.dirname(__file__), 'static', 'shadow_ml', 'sentences.json')
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        # Fallback pro případ, že se nepodaří načíst soubor
        return {
            'A1': ["Hello, my name is Sarah.", "I like cats and dogs."],
            'A2': ["I usually wake up at seven o'clock.", "My favorite hobby is reading."],
            'B1': ["Despite the challenging circumstances, she managed to complete the project."],
            'B2': ["The unprecedented technological advancements have transformed communication."],
            'C1': ["The epistemological foundations of modern scientific inquiry are complex."],
            'C2': ["The ineluctable convergence of artificial intelligence portends change."]
        }


# Věty pro různé úrovně obtížnosti
SENTENCES = load_sentences()


def get_user_english_level(user_id):
    """Získání uživatelské jazykové úrovně z databáze"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT english_level FROM users WHERE id = %s', (user_id,))
            result = cursor.fetchone()
            return result[0] if result and result[0] else 'A1'
    except Exception:
        return 'A1'  # Fallback


@shadow_ml_bp.route('/shadow')
def shadow_main():
    """Hlavní stránka pro Shadowing mode"""
    login_check = require_login()
    if login_check:
        return login_check

    user_id = session.get('user_id')
    user_level = get_user_english_level(user_id)
    return render_template('shadow_Mlu/shadow_main.html', user_english_level=user_level)


@shadow_ml_bp.route('/shadow/get_sentence')
def get_sentence():
    """API endpoint pro získání náhodné věty podle uživatelovy úrovně z databáze"""
    login_check = require_login()
    if login_check:
        return jsonify({'error': 'Not authenticated'}), 401

    user_id = session.get('user_id')
    user_level = get_user_english_level(user_id)

    # Používáme POUZE uživatelovu úroveň z databáze, ignorujeme level z requestu
    sentence = random.choice(SENTENCES[user_level])

    return jsonify({
        'sentence': sentence,
        'level': user_level,
        'user_level': user_level
    })


@shadow_ml_bp.route('/shadow/save_result', methods=['POST'])
def save_result():
    """Uložení výsledku shadowing cvičení - pouze XP, bez nové tabulky"""
    login_check = require_login()
    if login_check:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.json
    user_id = session.get('user_id')
    accuracy = data.get('accuracy')
    level = data.get('level')

    if not all([user_id, accuracy, level]):
        return jsonify({'error': 'Missing required data'}), 400

    try:
        # Pouze přidání XP za cvičení
        xp_gained = calculate_xp(accuracy, level)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET xp = xp + %s WHERE id = %s', (xp_gained, user_id))
            conn.commit()

        return jsonify({
            'success': True,
            'xp_gained': xp_gained
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def calculate_xp(accuracy, level):
    """Výpočet XP na základě přesnosti a úrovně"""
    base_xp = {
        'A1': 5,
        'A2': 8,
        'B1': 12,
        'B2': 18,
        'C1': 25,
        'C2': 35
    }

    xp = base_xp.get(level, 5)

    # Bonus za vysokou přesnost
    if accuracy >= 90:
        xp *= 1.5
    elif accuracy >= 80:
        xp *= 1.2
    elif accuracy >= 70:
        xp *= 1.0
    else:
        xp *= 0.7

    return int(xp)
