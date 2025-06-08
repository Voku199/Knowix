import os
import json
import time
from threading import Lock
from flask import Blueprint, render_template, request, jsonify, current_app, session
from auth import get_db_connection
from difflib import SequenceMatcher
import deepl
import random
import unicodedata
import re
from concurrent.futures import ThreadPoolExecutor
from collections import deque

# --- ČTENÍ LYRICS Z JSON SOUBORU ---
LYRICS_JSON_DIR = os.path.join(os.path.dirname(__file__), 'static/music/lyrics_json')


def get_lyrics_and_translations_from_json(song_info):
    """
    Načte lyrics a jejich překlady z JSON souboru.
    Vrací tuple (lyrics_lines, translations_lines) nebo (None, None) při chybě.
    """
    song_title = song_info.get('title')

    if not song_title:
        return None, None
    safe_title = re.sub(r'[^\w\s-]', '', song_title).replace(' ', '_')
    json_path = os.path.join(LYRICS_JSON_DIR, f"{safe_title}.json")

    if not os.path.exists(json_path):
        return None, None
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        lyrics_lines = data.get('lyrics')
        translations_lines = data.get('translations')
        if (not lyrics_lines or not isinstance(lyrics_lines, list) or
                not translations_lines or not isinstance(translations_lines, list) or
                len(lyrics_lines) != len(translations_lines)):
            return None, None
        return lyrics_lines, translations_lines


exercises_bp = Blueprint('exercises', __name__, template_folder='templates')


@exercises_bp.errorhandler(502)
@exercises_bp.errorhandler(503)
@exercises_bp.errorhandler(504)
@exercises_bp.errorhandler(500)
@exercises_bp.errorhandler(404)
@exercises_bp.errorhandler(Exception)
def server_error(e):
    # Oprava: bezpečně získat error_code, pokud existuje, jinak 500
    error_code = getattr(e, "code", 500)
    return render_template('error.html', error_code=error_code), error_code


def normalize(text):
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('utf-8').lower()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


@exercises_bp.record_once
def on_load(state):
    state.app.translator = deepl.Translator(state.app.config['DEEPL_API_KEY'])
    with open(os.path.join(state.app.static_folder, 'music/songs.json'), encoding='utf-8') as f:
        state.app.songs = json.load(f)
    with open(os.path.join(state.app.static_folder, 'music/word_pairs.json'), encoding='utf-8') as f:
        state.app.word_pairs = json.load(f)


@exercises_bp.route('/song-selection', methods=['GET'])
def song_selection():
    return render_template('music/index.html', songs=current_app.songs)


# --- FRONTOVÁNÍ uživatelů pro endpoint /exercise/<int:song_id> ---
exercise_lock = Lock()
exercise_queue = deque()


def get_user_id():
    # Vrací unikátní identifikátor pro každého uživatele (přihlášený i anonymní)
    if "user_id" in session:
        return f"user_{session['user_id']}"
    if "user_name" in session:
        return f"name_{session['user_name']}"
    sid = session.get('_id')
    if sid:
        return f"sid_{sid}"
    return f"ip_{request.remote_addr}"


def translate_line_with_retry(translator, line, target_lang='CS', retries=3, delay=2):
    for attempt in range(retries):
        try:
            result = translator.translate_text(line, target_lang=target_lang).text
            print(f"Překlad: '{line}' -> '{result}'")
            return result
        except Exception as exc:
            print(f"Chyba při překladu řádku '{line}': {exc}")
            if "Too many requests" in str(exc) or "high load" in str(exc):
                if attempt < retries - 1:
                    time.sleep(delay)
                    continue
            return f"[Nepřeloženo] {line}"
    return f"[Nepřeloženo] {line}"


@exercises_bp.route('/exercise/<int:song_id>', methods=['GET'])
def exercise(song_id):
    user_id = get_user_id()
    queue_timeout = 30
    wait_interval = 0.5

    exercise_queue.append(user_id)
    start_time = time.time()

    try:
        while True:
            if exercise_queue and exercise_queue[0] == user_id and exercise_lock.acquire(blocking=False):
                break
            if time.time() - start_time > queue_timeout:
                if user_id in exercise_queue:
                    try:
                        exercise_queue.remove(user_id)
                    except ValueError:
                        pass
                return render_template('music/wait.html', wait=True,
                                       message="Je tu hodně lidí, zkus to za chvíli znovu."), 429
            time.sleep(wait_interval)

        try:
            song_info = current_app.songs[song_id]
        except IndexError:
            return "Neplatné ID písničky", 404

        # Nově načítáme lyrics i překlady
        lyrics_lines, translations_lines = get_lyrics_and_translations_from_json(song_info)
        if lyrics_lines is None or translations_lines is None:
            return "Text písně nebo překlad nebyl nalezen v JSON souboru.", 404

        def is_valid_lyric_line(line):
            line = line.strip()
            if not line:
                return False
            if line.startswith('[') and line.endswith(']'):
                return False
            return True

        valid_indices = [i for i, line in enumerate(lyrics_lines) if is_valid_lyric_line(line)]
        if len(valid_indices) < 3:
            return "Příliš málo validních řádků v textu písně.", 400

        # Vybereme náhodné řádky pro missing a translation cvičení
        missing_indices = random.sample(valid_indices, min(3, len(valid_indices)))
        remaining_indices = list(set(valid_indices) - set(missing_indices))
        translation_indices = random.sample(remaining_indices,
                                            min(3, len(remaining_indices))) if remaining_indices else []

        missing_exercises = []
        for idx in missing_indices:
            line = lyrics_lines[idx]
            translation = translations_lines[idx]
            words = line.split()
            missing_word = random.choice(words)
            missing_exercises.append({
                'original': line,
                'with_blank': line.replace(missing_word, '_____'),
                'missing_word': missing_word,
                'translated': translation
            })

        translation_exercises = [
            {
                'original': lyrics_lines[idx],
                'translated': translations_lines[idx]
            }
            for idx in translation_indices
        ]

        current_word_pairs = current_app.word_pairs.get(song_info['title'], {})
        selected_pairs = random.sample(list(current_word_pairs.items()), min(6, len(current_word_pairs)))
        bidirectional_pairs = {**dict(selected_pairs), **{v: k for k, v in selected_pairs}}

        session['missing_exercises'] = missing_exercises
        session['translation_exercises'] = translation_exercises
        session['current_exercise_pairs'] = dict(selected_pairs)
        english_words = [en for en, cs in selected_pairs]
        czech_words = [cs for en, cs in selected_pairs]
        random.shuffle(english_words)
        random.shuffle(czech_words)

        lrc_content = ''
        lrc_path = os.path.join(current_app.static_folder, 'music/audio/lyrics', song_info.get('lyrics_file', ''))
        if os.path.exists(lrc_path):
            with open(lrc_path, 'r', encoding='utf-8') as f:
                lrc_content = f.read()

        return render_template(
            'music/exercises.html',
            missing_exercises=missing_exercises,
            translation_exercises=translation_exercises,
            english_words=english_words,
            czech_words=czech_words,
            word_pairs=dict(selected_pairs),
            audio_file=song_info['audio_file'],
            song_title=song_info["title"],
            lrc_lyrics=lrc_content,
            user_name=session.get("user_name"),
            profile_pic=session.get("profile_pic", "default.jpg"),
            config={
                'song_title': song_info['title'],
                'word_pairs': bidirectional_pairs,
                'missing_exercises': [ex['missing_word'] for ex in missing_exercises],
                'translation_exercises': [ex['translated'] for ex in translation_exercises]
            }
        )
    finally:
        if user_id in exercise_queue:
            try:
                exercise_queue.remove(user_id)
            except ValueError:
                pass
        if exercise_lock.locked():
            try:
                exercise_lock.release()
            except RuntimeError:
                pass


@exercises_bp.route('/check-answer', methods=['POST'])
def check_answer():
    data = request.json
    results = {
        'missing': [],
        'translations': [],
        'pairs': False,
        'details': {
            'missing': [],
            'translations': []
        }
    }

    stored_missing = session.get('missing_exercises', [])
    for idx, ex in enumerate(data.get('missing', [])):
        user_answer = normalize(ex.get('user', ''))
        correct_answer = stored_missing[idx]['missing_word'] if idx < len(stored_missing) else ''
        correct_normalized = normalize(correct_answer)
        ratio = similarity(user_answer, correct_normalized)
        results['details']['missing'].append({
            'user': ex.get('user'),
            'correct': correct_answer,
            'similarity': ratio
        })
        if ratio >= 0.9:
            results['missing'].append(True)
        elif ratio >= 0.7:
            results['missing'].append('almost')
        else:
            results['missing'].append(False)

    stored_translations = session.get('translation_exercises', [])
    for idx, ex in enumerate(data.get('translations', [])):
        user_answer = normalize(ex.get('user', ''))
        original_text = stored_translations[idx]['original'] if idx < len(stored_translations) else ''
        correct_translation = stored_translations[idx]['translated'] if idx < len(stored_translations) else ''
        ratio_to_translation = similarity(user_answer, normalize(correct_translation))
        ratio_to_original = similarity(user_answer, normalize(original_text))
        ratio = max(ratio_to_translation, ratio_to_original)
        detail_result = {
            'user': ex.get('user'),
            'correct': correct_translation,
            'similarity': ratio,
            'feedback': None
        }
        if ratio >= 0.85:
            results['translations'].append(True)
        elif ratio >= 0.8:
            results['translations'].append('almost')
            detail_result[
                'feedback'] = f"Tvoje odpověď není úplně přesná. Správná odpověď by byla: '{correct_translation}'."
        else:
            results['translations'].append(False)
        results['details']['translations'].append(detail_result)

    correct_pairs = session.get('current_exercise_pairs', {})
    user_pairs = set(tuple(pair) for pair in data.get('pairs', []))
    valid_pairs = set((en, cs) for en, cs in correct_pairs.items()) | set((cs, en) for en, cs in correct_pairs.items())
    results['pairs'] = all(pair in valid_pairs for pair in user_pairs) and len(user_pairs) == len(correct_pairs)

    all_correct = (
            all(x in (True, 'almost') for x in results['missing']) and
            all(x in (True, 'almost') for x in results['translations']) and
            results['pairs']
    )

    return jsonify({
        'results': results,
        'success': all_correct,
        'feedback': {
            'thresholds': {
                'missing': 0.9,
                'translations': 0.85
            }
        }
    })
