from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from db import get_db_connection
import random
import json
import os

# Import centrálni XP a streak systém
try:
    from xp import add_xp_to_user
except Exception:
    add_xp_to_user = None

try:
    from streak import update_user_streak
except Exception:
    update_user_streak = None

from user_stats import update_user_stats

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
        # Fallback pro případ, že se nepodaří načíst soubor – rozšířený balíček vět
        return {
            'A1': [
                "Hello, my name is Sarah.",
                "I like cats and dogs.",
                "This is my friend.",
                "I am from Prague.",
                "What is your name?",
                "I am ten years old.",
                "I have a small dog.",
                "It is sunny today.",
                "I can swim and run.",
                "I like pizza and ice cream.",
                "See you later!",
                "Where do you live?",
                "My favorite color is blue.",
                "I go to school every day.",
                "Please, close the door."
            ],
            'A2': [
                "I usually wake up at seven o'clock.",
                "My favorite hobby is reading.",
                "There is a park near my house.",
                "I often go to school by bus.",
                "On weekends, I visit my grandparents.",
                "I have been learning English for two years.",
                "I would like a cup of tea, please.",
                "She is good at playing the piano.",
                "I don't mind walking in the rain.",
                "We are planning a trip next month.",
                "He sometimes helps me with homework.",
                "Could you repeat that, please?",
                "I feel better than yesterday."
            ],
            'B1': [
                "Despite the challenging circumstances, she managed to complete the project.",
                "I find it easier to focus when the room is quiet.",
                "If we leave early, we might avoid the traffic.",
                "He has been working out to improve his health.",
                "They decided to cancel the meeting due to illness.",
                "I'm looking forward to seeing you next week.",
                "By the time we arrived, the show had already started.",
                "We need to come up with a better plan.",
                "She apologized for being late to the interview.",
                "Could you give me a hand with these boxes?"
            ],
            'B2': [
                "The unprecedented technological advancements have transformed communication.",
                "Her argument was compelling, though not entirely convincing.",
                "We should take into account the long-term consequences.",
                "Negotiations broke down after several unproductive rounds.",
                "He excels at conveying complex ideas clearly and concisely.",
                "The policy aims to strike a balance between safety and freedom.",
                "There is growing concern about data privacy and security.",
                "The research sheds light on previously overlooked factors.",
                "Implementing the solution requires careful coordination.",
                "They reached a consensus after extensive discussion."
            ],
            'C1': [
                "The epistemological foundations of modern scientific inquiry are complex.",
                "Her meticulous methodology underpins the study's credibility.",
                "The novel juxtaposes intimacy with sweeping historical forces.",
                "He articulated a nuanced perspective on regulatory frameworks.",
                "The findings are robust, albeit limited by sample size.",
                "Institutional inertia often impedes meaningful reform.",
                "The discourse privileges efficiency over equity, problematically.",
                "They posited a compelling, albeit speculative, hypothesis.",
                "Methodological rigor is paramount in longitudinal analysis.",
                "Ambiguity persists despite ostensibly definitive metrics."
            ],
            'C2': [
                "The ineluctable convergence of artificial intelligence portends change.",
                "Notwithstanding its parsimony, the model exhibits remarkable explanatory power.",
                "His exegesis interrogates the teleology of progress narratives.",
                "Hermeneutic opacity complicates any putatively objective appraisal.",
                "Epistemic humility tempers otherwise categorical prescriptions.",
                "The putative consensus occludes salient dissensus within the field.",
                "Diachronic analyses illuminate contingent socio-technical trajectories.",
                "Contestation over normativity destabilizes the analytic frame.",
                "Problematizing agency refracts through multi-scalar dynamics.",
                "Ontological commitments remain tacit yet structurally determinative."
            ]
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

    # Použij bezpečné získání vět podle úrovně s fallbackem na A1
    sentences_for_level = SENTENCES.get(user_level) or SENTENCES.get('A1') or []
    if not sentences_for_level:
        return jsonify({'error': 'No sentences available'}), 500
    sentence = random.choice(sentences_for_level)

    return jsonify({
        'sentence': sentence,
        'level': user_level,
        'user_level': user_level
    })


@shadow_ml_bp.route('/shadow/save_result', methods=['POST'])
def save_result():
    """Uložení výsledku shadowing cvičení - XP + streak update"""
    login_check = require_login()
    if login_check:
        print('[shadow/save_result] Not authenticated: no user_id in session')
        return jsonify({'error': 'Not authenticated'}), 401

    # Bezpečné načtení JSON (toleruje chybějící/nevalidní Content-Type)
    try:
        raw_body = request.get_data(as_text=True)
        headers = dict(request.headers)
    except Exception:
        raw_body = '<unavailable>'
        headers = {}

    data = request.get_json(silent=True) or {}
    user_id = session.get('user_id')

    # Debug log
    try:
        print('[shadow/save_result] Incoming:', {
            'user_id': user_id,
            'headers': {k: headers.get(k) for k in ['Content-Type', 'Cookie'] if k in headers},
            'raw_body': raw_body[:500],
            'parsed': data
        })
    except Exception:
        pass

    # Přesnost může být 0, proto kontroluj None, ne truthiness
    accuracy_raw = data.get('accuracy')
    if user_id is None:
        print('[shadow/save_result] 400: missing user_id in session')
        return jsonify({'error': 'Missing session user_id'}), 400
    if accuracy_raw is None:
        print('[shadow/save_result] 400: missing accuracy in JSON')
        return jsonify({'error': 'Missing accuracy'}), 400

    # Převod accuracy na číslo a ořez na 0-100
    try:
        accuracy = float(accuracy_raw)
    except (TypeError, ValueError):
        print(f"[shadow/save_result] 400: invalid accuracy value -> {accuracy_raw!r}")
        return jsonify({'error': 'Invalid accuracy value'}), 400
    accuracy = max(0.0, min(100.0, accuracy))

    # Úroveň vždy bereme z DB, ne z requestu
    user_level = get_user_english_level(user_id)

    # Volitelná délka cvičení v sekundách pro statistiky učení
    duration_secs = 0
    try:
        dur_raw = data.get('duration_seconds') if isinstance(data, dict) else None
        if dur_raw is None:
            dur_raw = data.get('duration') if isinstance(data, dict) else None
        if dur_raw is not None:
            duration_secs = int(float(dur_raw))
            if duration_secs < 0:
                duration_secs = 0
            if duration_secs > 7200:
                duration_secs = 7200
    except Exception:
        duration_secs = 0

    try:
        # Výpočet XP dle přesnosti a úrovně
        xp_gained = calculate_xp(accuracy, user_level)
        print(f"[shadow/save_result] Calculated xp_gained={xp_gained} for accuracy={accuracy} level={user_level}")

        # Přidání XP přes centrální systém (s levelem, boostery, achievementy)
        xp_result = None
        if add_xp_to_user:
            xp_result = add_xp_to_user(user_id, xp_gained)
            print('[shadow/save_result] add_xp_to_user result:', xp_result)
            if isinstance(xp_result, dict) and xp_result.get('error'):
                # Fallback: přímá aktualizace XP, pokud centrální systém selže
                with get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute('UPDATE users SET xp = xp + %s WHERE id = %s', (xp_gained, user_id))
                    conn.commit()
                print('[shadow/save_result] XP updated via fallback SQL')
        else:
            # Fallback pokud modul není k dispozici
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute('UPDATE users SET xp = xp + %s WHERE id = %s', (xp_gained, user_id))
                conn.commit()
            print('[shadow/save_result] XP updated via direct SQL (no xp module)')

        # Aktualizace statistik: tri-state (correct/maybe/wrong) dle přesnosti
        try:
            shw_c = 1 if accuracy >= 80.0 else 0
            shw_m = 1 if (accuracy >= 50.0 and accuracy < 80.0) else 0
            shw_w = 1 if accuracy < 50.0 else 0

            # Globální correct/wrong: nepočítat maybe jako chybu
            corr = 1 if accuracy >= 80.0 else 0
            wr = 1 if accuracy < 50.0 else 0

            update_user_stats(
                user_id,
                correct=corr,
                wrong=wr,
                roleplaying_cr=corr,
                roleplaying_wr=wr,
                shw_cor=shw_c,
                shw_mb=shw_m,
                shw_wr=shw_w,
                learning_time=(duration_secs if duration_secs > 0 else None),
                set_first_activity=True
            )
        except Exception as stat_e:
            print('[shadow/save_result] update_user_stats failed:', stat_e)

        # Aktualizace streaku (pokud je systém k dispozici)
        streak_info = update_user_streak(user_id) if update_user_streak else None
        if streak_info is None:
            print('[shadow/save_result] Streak update skipped (no module)')
        else:
            print('[shadow/save_result] Streak info:', streak_info)

        response = {
            'success': True,
            'xp_gained': xp_gained,
            'user_level': user_level
        }
        if isinstance(xp_result, dict) and not xp_result.get('error'):
            response.update({
                'new_xp': xp_result.get('xp'),
                'new_level': xp_result.get('level'),
                'new_achievements': xp_result.get('new_achievements', [])
            })
        if streak_info:
            response['streak'] = streak_info

        return jsonify(response)

    except Exception as e:
        print('[shadow/save_result] 500 exception:', e)
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
