from flask import Blueprint, render_template, request, jsonify, current_app, session
from auth import get_db_connection
from lyricsgenius import Genius
from difflib import SequenceMatcher
import deepl
import os
import random
import json
import unicodedata
import re

exercises_bp = Blueprint('exercises', __name__, template_folder='templates')


@exercises_bp.errorhandler(502)
@exercises_bp.errorhandler(503)
@exercises_bp.errorhandler(504)
@exercises_bp.errorhandler(500)
@exercises_bp.errorhandler(404)
@exercises_bp.errorhandler(Exception)
def server_error(e):
    # vrátí stránku error.html s informací o výpadku
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
    # Inicializace API klientů
    state.app.genius = Genius(state.app.config['GENIUS_ACCESS_TOKEN'], timeout=15)
    state.app.genius.verbose = False
    state.app.translator = deepl.Translator(state.app.config['DEEPL_API_KEY'])

    # Načtení datových souborů
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

    # Získání textu písně z Genius
    song = current_app.genius.search_song(song_info['title'], song_info['artist'])
    if not song or not song.lyrics:
        return "Text písně nebyl nalezen", 404

    # 🧽 Filtrace řádků – odstraníme balast (úvody, Contributors, Translations, atd.)
    def is_valid_lyric_line(line):
        line = line.strip()
        if not line:
            return False
        if line.startswith('['):  # [Chorus], [Verse], atd.
            return False
        if re.search(r'Contributors|Translations|Lyrics|^\d+\s+Contributors', line):
            print("Našel jsem to, ale nedám to! Jsem silný!")
            return False
        if re.search(r'(Deutsch|Español|Türkçe|Русский|Português|Ελληνικά|Français)', line):
            print("Jsi myslíš doopravdy?")
            return False
        if re.search(r'Pharrell|made the world|anthem|#\d+', line, re.IGNORECASE):
            print("Phe")
            return False
        if len(line.split()) < 3:
            print("gg")
            return False
        return True

    # Zpracování textu
    lyrics_lines = song.lyrics.split('\n')
    print(lyrics_lines)

    # Najdi první validní řádek a odřízni balast před ním
    for idx, line in enumerate(lyrics_lines):
        if is_valid_lyric_line(line):
            lyrics_lines = lyrics_lines[idx:]
            break

    # Použij jen validní řádky
    valid_lines = [line for line in lyrics_lines if is_valid_lyric_line(line)]

    if len(valid_lines) < 6:
        return "Příliš málo validních řádků v textu písně.", 400

    # 🎯 Doplňovačky
    missing_exercises = []
    for line in random.sample(valid_lines, 3):
        words = line.split()
        missing_word = random.choice(words)
        missing_exercises.append({
            'original': line,
            'with_blank': line.replace(missing_word, '_____'),
            'missing_word': missing_word,
            'translated': current_app.translator.translate_text(line, target_lang='CS').text
        })

    # 📘 Překlady
    used_lines = [ex['original'] for ex in missing_exercises]
    translation_exercises = [
        {
            'original': line,
            'translated': current_app.translator.translate_text(line, target_lang='CS').text
        }
        for line in random.sample(list(set(valid_lines) - set(used_lines)), 3)
    ]
    print(translation_exercises)

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

    # 🎵 LRC synchronizovaný text
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

    # 1. Kontrola doplňovaček
    stored_missing = session.get('missing_exercises', [])
    for idx, ex in enumerate(data.get('missing', [])):
        user_answer = normalize(ex.get('user', ''))

        # Získání správné odpovědi z session
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

    # 2. Kontrola překladů
    stored_translations = session.get('translation_exercises', [])
    for idx, ex in enumerate(data.get('translations', [])):
        user_answer = normalize(ex.get('user', ''))

        # Získání originálu z session pro přesnější validaci
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
            print(detail_result)
        else:
            results['translations'].append(False)

        results['details']['translations'].append(detail_result)

    # 3. Kontrola párů (zůstává stejné)
    correct_pairs = session.get('current_exercise_pairs', {})
    user_pairs = set(tuple(pair) for pair in data.get('pairs', []))
    valid_pairs = set((en, cs) for en, cs in correct_pairs.items()) | set((cs, en) for en, cs in correct_pairs.items())
    results['pairs'] = all(pair in valid_pairs for pair in user_pairs) and len(user_pairs) == len(correct_pairs)

    # Celkové vyhodnocení
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
