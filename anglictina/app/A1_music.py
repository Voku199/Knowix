from flask import Blueprint, render_template, request, jsonify, current_app, session
from auth import get_db_connection
from lyricsgenius import Genius
import deepl
import os
import random
import json
import unicodedata
import re

exercises_bp = Blueprint('exercises', __name__, template_folder='templates')


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
        print(state.app.word_pairs)


@exercises_bp.route('/song-selection', methods=['GET'])
def song_selection():
    return render_template('music/index.html', songs=current_app.songs)


@exercises_bp.route('/exercise/<int:song_id>', methods=['GET'])
def exercise(song_id):
    try:
        song_info = current_app.songs[song_id]
    except IndexError:
        return "Neplatné ID písničky", 404

    # Získání textu písně
    song = current_app.genius.search_song(song_info['title'], song_info['artist'])
    if not song or not song.lyrics:
        return "Text písně nebyl nalezen", 404

    # Příprava cvičení
    lines = [line for line in song.lyrics.split('\n') if line and not line.startswith('[')]
    valid_lines = [line for line in lines if len(line.split()) >= 3]

    # Generování doplňovaček
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

    # Generování překladů
    translation_exercises = [
        {
            'original': line,
            'translated': current_app.translator.translate_text(line, target_lang='CS').text
        }
        for line in random.sample(list(set(valid_lines) - set([ex['original'] for ex in missing_exercises])), 3)
    ]

    # Příprava slovních párů
    current_word_pairs = current_app.word_pairs.get(song_info['title'], {})
    selected_pairs = random.sample(list(current_word_pairs.items()), min(6, len(current_word_pairs)))

    # Přidejte reverse pairs pro obousměrnou validaci
    bidirectional_pairs = {**dict(selected_pairs), **{v: k for k, v in selected_pairs}}

    # Uložení párů do session jako slovník pro validaci
    session['current_exercise_pairs'] = dict(selected_pairs)

    english_words = [en for en, cs in selected_pairs]
    czech_words = [cs for en, cs in selected_pairs]
    random.shuffle(english_words)
    random.shuffle(czech_words)

    # Zpracování LRC textu
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
        word_pairs=dict(selected_pairs),  # Zajištění formátu slovního slovníku
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

    # Normalizační funkce
    def normalize(text):
        if not text:
            return ''
        text = unicodedata.normalize('NFKD', text)
        text = text.encode('ascii', 'ignore').decode('utf-8')
        text = re.sub(r'[^\w\s]', '', text)
        return text.strip().lower()

    # Validace odpovědí
    results = {
        'missing': [],
        'translations': [],
        'pairs': False
    }

    # 1. Kontrola doplňovaček
    for idx, ex in enumerate(data.get('missing', [])):
        correct = normalize(ex['correct']) == normalize(ex['user'])
        results['missing'].append(correct)

    # 2. Kontrola překladů
    for idx, ex in enumerate(data.get('translations', [])):
        correct = normalize(ex['correct']) == normalize(ex['user'])
        results['translations'].append(correct)

    # 3. Kontrola slovních párů
    correct_pairs = session.get('current_exercise_pairs', {})
    user_pairs = set(tuple(pair) for pair in data.get('pairs', []))

    # Validace všech možných kombinací
    valid_pairs = set()
    for en, cs in correct_pairs.items():
        valid_pairs.add((en, cs))
        valid_pairs.add((cs, en))  # Povolení obousměrných spojení

    # Kontrola zda všechny uživatelské páry jsou platné
    pairs_correct = all(pair in valid_pairs for pair in user_pairs) and \
                    len(user_pairs) == len(correct_pairs)

    results['pairs'] = pairs_correct

    # Celkové vyhodnocení
    all_correct = all(results['missing']) and all(results['translations']) and pairs_correct

    return jsonify({
        'results': results,
        'success': all_correct
    })
