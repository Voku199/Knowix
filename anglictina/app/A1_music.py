from flask import Blueprint, render_template, request, jsonify, current_app, session
from lyricsgenius import Genius
import deepl
import os
import random
import json

exercises_bp = Blueprint('exercises', __name__, template_folder='templates')


# Initialize APIs when blueprint is registered
@exercises_bp.record_once
def on_load(state):
    # Initialize Genius API
    state.app.genius = Genius(state.app.config['GENIUS_ACCESS_TOKEN'], timeout=15)
    state.app.genius.verbose = False

    # Initialize DeepL API
    state.app.translator = deepl.Translator(state.app.config['DEEPL_API_KEY'])

    # Load JSON data
    with open(os.path.join(state.app.static_folder, 'music//songs.json'), encoding='utf-8') as f:
        state.app.songs = json.load(f)

    with open(os.path.join(state.app.static_folder, 'music//word_pairs.json'), encoding='utf-8') as f:
        state.app.word_pairs = json.load(f)


@exercises_bp.route('/song-selection')
def song_selection():
    return render_template('music/index.html', songs=current_app.songs)


@exercises_bp.route('/exercise/<int:song_id>')
def exercise(song_id):
    try:
        song_info = current_app.songs[song_id]
    except IndexError:
        return "Neplatné ID písničky", 404

    song = current_app.genius.search_song(song_info['title'], song_info['artist'])

    if not song or not song.lyrics:
        return "Text písně nebyl nalezen", 404

    lines = [line for line in song.lyrics.split('\n') if line and not line.startswith('[')]
    valid_lines = [line for line in lines if len(line.split()) >= 3]

    if len(valid_lines) < 6:
        return "Není dostatek řádků pro cvičení", 404

    missing_lines = random.sample(valid_lines, 3)
    missing_exercises = []
    used_lines = set()

    for line in missing_lines:
        words = line.split()
        missing_word = random.choice(words)
        line_with_blank = line.replace(missing_word, '_____')
        missing_exercises.append({
            'original': line,
            'with_blank': line_with_blank,
            'missing_word': missing_word,
            'translated': current_app.translator.translate_text(line, target_lang='CS').text
        })
        used_lines.add(line)

    remaining_lines = list(set(valid_lines) - used_lines)
    if len(remaining_lines) < 3:
        return "Není dostatek unikátních řádků pro překlady", 404

    translation_lines = random.sample(remaining_lines, 3)
    translation_exercises = [
        {
            'original': line,
            'translated': current_app.translator.translate_text(line, target_lang='CS').text
        }
        for line in translation_lines
    ]

    current_word_pairs = current_app.word_pairs.get(song_info['title'], {})
    selected_pairs = random.sample(list(current_word_pairs.items()), min(6, len(current_word_pairs)))
    english_words = [en for en, cs in selected_pairs]
    czech_words = [cs for en, cs in selected_pairs]
    random.shuffle(english_words)
    random.shuffle(czech_words)

    audio_file = song_info['audio_file']
    lrc_file_path = os.path.join(current_app.static_folder, 'music', 'audio', 'lyrics', song_info.get('lyrics_file'))

    lrc_content = ''
    if os.path.exists(lrc_file_path):
        with open(lrc_file_path, 'r', encoding='utf-8') as f:
            lrc_content = f.read()

    return render_template('music/exercises.html',
                           missing_exercises=missing_exercises,
                           translation_exercises=translation_exercises,
                           english_words=english_words,
                           czech_words=czech_words,
                           word_pairs=dict(selected_pairs),
                           audio_file=audio_file,
                           lrc_lyrics=lrc_content,
                           user_name=session.get("user_name"),
                           profile_pic=session.get("profile_pic", "default.jpg"))


@exercises_bp.route('/check-answer', methods=['POST'])
def check_answer():
    data = request.json

    def normalize(text):
        return text.strip().lower() if text else ''

    missing_word_correct = normalize(data.get('missing_word')) == normalize(data.get('user_missing'))
    translation_correct = normalize(data.get('translation')) == normalize(data.get('user_translation'))

    user_pairs = data.get('pairs', [])
    pairs_correct = all(
        current_app.word_pairs.get(en) == cs for en, cs in user_pairs
    )

    correct = {
        'missing_word': missing_word_correct,
        'translation': translation_correct,
        'pairs': pairs_correct
    }

    return jsonify({'correct': correct})
