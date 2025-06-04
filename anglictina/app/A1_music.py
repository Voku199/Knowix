import os
import json
from threading import Lock
from flask import Blueprint, render_template, request, jsonify, current_app, session
from auth import get_db_connection
from difflib import SequenceMatcher
import deepl
import random
import unicodedata
import re
from concurrent.futures import ThreadPoolExecutor

# --- ČTENÍ LYRICS Z JSON SOUBORU ---
LYRICS_JSON_DIR = os.path.join(os.path.dirname(__file__), 'static/music/lyrics_json')


def get_lyrics_from_json(song_info):
    song_title = song_info.get('title')
    if not song_title:
        return None
    safe_title = re.sub(r'[^\w\s-]', '', song_title).replace(' ', '_')
    json_path = os.path.join(LYRICS_JSON_DIR, f"{safe_title}.json")
    if not os.path.exists(json_path):
        return None
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        lyrics_lines = data.get('lyrics')
        if not lyrics_lines or not isinstance(lyrics_lines, list):
            return None
        return lyrics_lines  # Vracíme rovnou pole řádků


exercises_bp = Blueprint('exercises', __name__, template_folder='templates')


@exercises_bp.errorhandler(502)
@exercises_bp.errorhandler(503)
@exercises_bp.errorhandler(504)
@exercises_bp.errorhandler(500)
@exercises_bp.errorhandler(404)
@exercises_bp.errorhandler(Exception)
def server_error(e):
    return render_template('error.html', error_code=e.code), e.code


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


@exercises_bp.route('/exercise/<int:song_id>', methods=['GET'])
def exercise(song_id):
    try:
        song_info = current_app.songs[song_id]
    except IndexError:
        return "Neplatné ID písničky", 404

    # --- ČTI LYRICS Z JSON SOUBORU ---
    lyrics_lines = get_lyrics_from_json(song_info)
    if lyrics_lines is None:
        return "Text písně nebyl nalezen v JSON souboru.", 404

    # 🧽 Filtrace řádků – odstraníme jen opravdu prázdné nebo zjevně nevhodné řádky
    def is_valid_lyric_line(line):
        line = line.strip()
        if not line:
            return False
        if line.startswith('[') and line.endswith(']'):
            return False
        if len(line.split()) < 2:  # povolíme i krátké řádky, ale ne jednoslovné
            return False
        return True

    valid_lines = [line for line in lyrics_lines if is_valid_lyric_line(line)]

    if len(valid_lines) < 3:
        return "Příliš málo validních řádků v textu písně.", 400

    # --- Překlad přes DeepL (paralelně, BEZ current_app v threadu) ---
    def translate_line(translator, line, target_lang='CS'):
        try:
            return translator.translate_text(line, target_lang=target_lang).text
        except Exception as exc:
            print(f"Chyba při překladu řádku '{line}': {exc}")
            return f"[Nepřeloženo] {line}"

    missing_exercises_lines = random.sample(valid_lines, min(3, len(valid_lines)))
    translation_exercises_lines = random.sample(list(set(valid_lines) - set(missing_exercises_lines)),
                                                min(3, len(valid_lines) - len(missing_exercises_lines)))

    all_lines_to_translate = missing_exercises_lines + translation_exercises_lines
    translations = {}

    translator = current_app.translator

    with ThreadPoolExecutor(max_workers=6) as executor:
        future_to_line = {
            executor.submit(translate_line, translator, line, 'CS'): line
            for line in all_lines_to_translate
        }
        for future in future_to_line:
            line = future_to_line[future]
            try:
                translations[line] = future.result()
            except Exception as exc:
                translations[line] = f"[Nepřeloženo] {line}"
                print(f"Chyba při překladu řádku '{line}': {exc}")

    # 🎯 Doplňovačky
    missing_exercises = []
    for line in missing_exercises_lines:
        words = line.split()
        missing_word = random.choice(words)
        missing_exercises.append({
            'original': line,
            'with_blank': line.replace(missing_word, '_____'),
            'missing_word': missing_word,
            'translated': translations.get(line, f"[Nepřeloženo] {line}")
        })

    # 📘 Překlady
    translation_exercises = [
        {
            'original': line,
            'translated': translations.get(line, f"[Nepřeloženo] {line}")
        }
        for line in translation_exercises_lines
    ]

    # 🧠 Slovní páry
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

    # 🎵 LRC synchronizovaný text (volitelné)
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
