import os
import json
from threading import Lock

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)

_lyrics_lock = Lock()
_translation_lock = Lock()


def get_lyrics_from_cache(song_title, artist):
    cache_file = os.path.join(CACHE_DIR, f"{song_title}_{artist}_lyrics.json")
    if os.path.exists(cache_file):
        with _lyrics_lock, open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f).get("lyrics")
    return None


def save_lyrics_to_cache(song_title, artist, lyrics):
    cache_file = os.path.join(CACHE_DIR, f"{song_title}_{artist}_lyrics.json")
    with _lyrics_lock, open(cache_file, "w", encoding="utf-8") as f:
        json.dump({"lyrics": lyrics}, f, ensure_ascii=False)


def get_translation_from_cache(text, target_lang):
    cache_file = os.path.join(CACHE_DIR, f"translations_{target_lang}.json")
    if os.path.exists(cache_file):
        with _translation_lock, open(cache_file, "r", encoding="utf-8") as f:
            translations = json.load(f)
            return translations.get(text)
    return None


def save_translation_to_cache(text, target_lang, translation):
    cache_file = os.path.join(CACHE_DIR, f"translations_{target_lang}.json")
    translations = {}
    if os.path.exists(cache_file):
        with _translation_lock, open(cache_file, "r", encoding="utf-8") as f:
            translations = json.load(f)
    translations[text] = translation
    with _translation_lock, open(cache_file, "w", encoding="utf-8") as f:
        json.dump(translations, f, ensure_ascii=False)
