from flask import Blueprint, render_template, request, jsonify, current_app, session
from lyricsgenius import Genius
import deepl
import os
import random
import json
import logging
from time import sleep
from requests.exceptions import HTTPError
from typing import Dict, List

exercises_bp = Blueprint('exercises', __name__, template_folder='templates')

# Configure logging
logger = logging.getLogger(__name__)


class ThrottledGenius(Genius):
    """Custom Genius class with request throttling and headers support"""

    def __init__(self, *args, **kwargs):
        self.custom_headers = kwargs.pop('headers', {})
        super().__init__(*args, **kwargs)
        self.session.headers.update(self.custom_headers)

    def search_song(self, *args, **kwargs):
        sleep(random.uniform(0.7, 1.5))  # Random delay between requests
        return super().search_song(*args, **kwargs)


# Initialize APIs when blueprint is registered
@exercises_bp.record_once
def on_load(state):
    # Check required configuration
    required_keys = ['GENIUS_ACCESS_TOKEN', 'DEEPL_API_KEY']
    for key in required_keys:
        if not state.app.config.get(key):
            raise ValueError(f"Missing configuration key: {key}")

    # Initialize Genius API with custom settings
    try:
        genius = ThrottledGenius(
            access_token=state.app.config['GENIUS_ACCESS_TOKEN'],
            timeout=20,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json'
            },
            verbose=state.app.debug
        )
        genius.retries = 3  # Add retries as property
        state.app.genius = genius
        logger.info("Genius API initialized successfully")
    except Exception as e:
        logger.critical("Failed to initialize Genius API: %s", str(e))
        raise

    # Load JSON data with error handling
    try:
        static_folder = state.app.static_folder
        with open(os.path.join(static_folder, 'music/songs.json'), encoding='utf-8') as f:
            state.app.songs = json.load(f)
        with open(os.path.join(static_folder, 'music/word_pairs.json'), encoding='utf-8') as f:
            state.app.word_pairs = json.load(f)
        logger.info("Successfully loaded song data")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error("Error loading data files: %s", str(e))
        state.app.songs = []
        state.app.word_pairs = {}


def get_lyrics(song_info: Dict) -> str:
    """Get lyrics from Genius API with fallback to local data"""
    try:
        song = current_app.genius.search_song(
            title=song_info['title'],
            artist=song_info['artist'],
            get_full_info=False
        )
        if song and song.lyrics:
            return song.lyrics
        return song_info.get('fallback_lyrics', '')
    except Exception as e:
        logger.error("Lyrics fetch error: %s", str(e))
        return song_info.get('fallback_lyrics', 'Lyrics unavailable')


@exercises_bp.route('/song-selection')
def song_selection():
    return render_template('music/index.html', songs=current_app.songs)


@exercises_bp.route('/exercise/<int:song_id>')
def exercise(song_id: int):
    try:
        # Validate song ID
        if song_id < 0 or song_id >= len(current_app.songs):
            raise IndexError("Invalid song ID")

        song_info = current_app.songs[song_id]
        logger.info("Processing song: %s - %s", song_info['artist'], song_info['title'])

        # Get lyrics with fallback
        lyrics = get_lyrics(song_info)
        if not lyrics:
            return render_template('error.html',
                                   message="Text písně nebyl nalezen",
                                   solution="Zkuste jinou skladbu"), 404

        # Process lyrics
        lines = [line.strip() for line in lyrics.split('\n')
                 if line.strip() and not line.startswith('[')]
        valid_lines = [line for line in lines if len(line.split()) >= 3]

        if len(valid_lines) < 6:
            return render_template('error.html',
                                   message="Není dostatek řádků pro cvičení",
                                   solution="Zkuste jinou skladbu"), 400

        # Generate missing word exercises
        missing_lines = random.sample(valid_lines, 3)
        missing_exercises = []
        used_lines = set()

        for line in missing_lines:
            words = line.split()
            missing_word = random.choice(words)
            missing_exercises.append({
                'original': line,
                'with_blank': line.replace(missing_word, '_____'),
                'missing_word': missing_word,
                'translated': current_app.translator.translate_text(line, target_lang='CS').text
            })
            used_lines.add(line)

        # Generate translation exercises
        remaining_lines = [line for line in valid_lines if line not in used_lines]
        if len(remaining_lines) < 3:
            return render_template('error.html',
                                   message="Nedostatek textu pro překlad",
                                   solution="Zkuste jinou skladbu"), 400

        translation_lines = random.sample(remaining_lines, 3)
        translation_exercises = [{
            'original': line,
            'translated': current_app.translator.translate_text(line, target_lang='CS').text
        } for line in translation_lines]

        # Prepare vocabulary pairs
        word_pairs = current_app.word_pairs.get(song_info['title'], {})
        selected_pairs = random.sample(list(word_pairs.items()), min(6, len(word_pairs)))
        english_words = [en for en, cs in selected_pairs]
        czech_words = [cs for en, cs in selected_pairs]
        random.shuffle(english_words)
        random.shuffle(czech_words)

        # Load lyrics file
        lrc_content = ''
        lrc_path = os.path.join(
            current_app.static_folder,
            'music/audio/lyrics',
            song_info.get('lyrics_file', '')
        )
        if os.path.exists(lrc_path):
            try:
                with open(lrc_path, 'r', encoding='utf-8') as f:
                    lrc_content = f.read()
            except IOError as e:
                logger.warning("Error reading LRC file: %s", str(e))

        return render_template('music/exercises.html',
                               missing_exercises=missing_exercises,
                               translation_exercises=translation_exercises,
                               english_words=english_words,
                               czech_words=czech_words,
                               word_pairs=dict(selected_pairs),
                               audio_file=song_info['audio_file'],
                               lrc_lyrics=lrc_content,
                               user_name=session.get("user_name"),
                               profile_pic=session.get("profile_pic", "default.jpg"))

    except IndexError as e:
        logger.error("Invalid song ID: %s", str(e))
        return render_template('error.html',
                               message="Neplatný výběr skladby",
                               solution="Zvolte píseň ze seznamu"), 404
    except HTTPError as e:
        logger.error("Genius API error: %s", str(e))
        return render_template('error.html',
                               message="Problém s připojením k textovému API",
                               solution="Zkuste to prosím později"), 503
    except Exception as e:
        logger.exception("Unexpected error in exercise route")
        return render_template('error.html',
                               message="Interní chyba serveru",
                               solution="Zkuste akci opakovat později"), 500


@exercises_bp.route('/check-answer', methods=['POST'])
def check_answer():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request'}), 400

        def normalize(text: str) -> str:
            return text.strip().lower().translate(
                str.maketrans('', '', ',.!?')
            ) if text else ''

        # Validate missing word
        missing_correct = normalize(data.get('missing_word', '')) == \
                          normalize(data.get('user_missing', ''))

        # Validate translation
        translation_correct = normalize(data.get('translation', '')) == \
                              normalize(data.get('user_translation', ''))

        # Validate word pairs
        user_pairs = data.get('pairs', [])
        valid_pairs = current_app.word_pairs.get(
            current_app.songs[int(data.get('song_id', -1))]['title'], {}
        )
        pairs_correct = all(
            normalize(str(valid_pairs.get(en, ''))) == normalize(str(cs))
            for en, cs in user_pairs
        )

        return jsonify({
            'correct': {
                'missing_word': missing_correct,
                'translation': translation_correct,
                'pairs': pairs_correct
            }
        })

    except Exception as e:
        logger.error("Error checking answers: %s", str(e))
        return jsonify({'error': 'Server error'}), 500


@exercises_bp.route('/api-status')
def api_status():
    """Endpoint pro kontrolu stavu API"""
    try:
        # Test Genius API
        test_song = current_app.genius.search_song("Test", "", retries=1)
        genius_status = "OK" if test_song else "No results"

        # Test DeepL API
        translation = current_app.translator.translate_text("Hello", target_lang="CS")
        deepl_status = "OK" if translation.text == "Dobrý den" else "Unexpected response"

        return jsonify({
            "genius": genius_status,
            "deepl": deepl_status
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "genius": "Error",
            "deepl": "Error"
        }), 500
