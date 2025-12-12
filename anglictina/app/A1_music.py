import os
import json
import time
from threading import Lock
from flask import Blueprint, render_template, request, jsonify, current_app, session
from db import get_db_connection
from difflib import SequenceMatcher
import deepl
import random
import unicodedata
import re
from concurrent.futures import ThreadPoolExecutor
from collections import deque
import traceback
import logging  # přidán logging
from xp import add_xp_to_user, get_user_xp_and_level  # DŮLEŽITÉ: XP systém
from streak import update_user_streak, get_user_streak
from user_stats import add_learning_time, update_user_stats

# --- ČTENÍ LYRICS Z JSON SOUBORU ---
LYRICS_JSON_DIR = os.path.join(os.path.dirname(__file__), 'static/music/lyrics_json')


def parse_lrc_file(path):
    """
    Jednoduchý parser LRC souboru. Vrací list textových řádků podle časových značek.
    Řádky bez textu nebo bez platné časové značky ignoruje.
    """
    lines = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for raw in f:
                raw = raw.strip()
                m = re.match(r'\[(\d+):(\d+(?:\.\d+)?)\](.*)', raw)
                if not m:
                    continue
                text = m.group(3).strip()
                if text:
                    lines.append(text)
    except Exception as e:
        print(f"Chyba při čtení LRC '{path}': {e}")
    return lines


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

LEVEL_NAMES = [
    "Začátečník", "Učeň", "Student", "Pokročilý", "Expert", "Mistr", "Legenda"
]


@exercises_bp.context_processor
def inject_streak():
    user_id = session.get('user_id')
    if user_id:
        streak = get_user_streak(user_id)
        return dict(user_streak=streak)
    return dict(user_streak=0)


def get_level_name(level):
    if level <= 1:
        return LEVEL_NAMES[0]
    elif level <= 2:
        return LEVEL_NAMES[1]
    elif level <= 4:
        return LEVEL_NAMES[2]
    elif level <= 6:
        return LEVEL_NAMES[3]
    elif level <= 8:
        return LEVEL_NAMES[4]
    elif level <= 10:
        return LEVEL_NAMES[5]
    else:
        return LEVEL_NAMES[6]


@exercises_bp.context_processor
def inject_xp_info():
    user_id = session.get('user_id')
    if user_id:
        user_data = get_user_xp_and_level(user_id)
        xp = user_data.get("xp", 0)
        level = user_data.get("level", 1)
        xp_in_level = xp % 50
        percent = int((xp_in_level / 50) * 100)
        level_name = get_level_name(level)
        return dict(
            user_xp=xp,
            user_level=level,
            user_level_name=level_name,
            user_progress_percent=percent,
            user_xp_in_level=xp_in_level
        )
    return {}


@exercises_bp.errorhandler(502)
@exercises_bp.errorhandler(503)
@exercises_bp.errorhandler(504)
@exercises_bp.errorhandler(500)
@exercises_bp.errorhandler(404)
@exercises_bp.errorhandler(Exception)
def server_error(e):
    """Lokální error handler pro blueprint A1_music.

    Loguje chybu pomocí logging modulů, aby bylo vidět v serverových logách,
    co přesně se pokazilo v rámci tohoto blueprintu.
    """
    logger = logging.getLogger("A1_music")
    error_code = getattr(e, "code", 500)
    tb = traceback.format_exc()
    try:
        path = request.path
    except Exception:
        path = "<no-path>"
    try:
        uid = session.get("user_id")
    except Exception:
        uid = None

    logger.error(
        "[A1_music] server_error: code=%s type=%s msg=%s path=%s user_id=%s\n%s",
        error_code,
        type(e).__name__,
        str(e),
        path,
        uid,
        tb
    )
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
    """Inicializace překladače a dat písniček/word_pairs při registraci blueprintu.

    Na produkci může chybět DEEPL_API_KEY nebo soubory songs.json/word_pairs.json,
    proto zde přidáváme defenzivní logiku, aby aplikace nespadla 500 při startu.
    """
    # --- DeepL překladač (volitelný) ---
    deepl_key = state.app.config.get('DEEPL_API_KEY')
    translator = None
    if deepl_key:
        try:
            translator = deepl.Translator(deepl_key)
        except Exception as exc:
            # Nechceme, aby kvůli špatnému klíči spadla celá appka
            print(f"[A1_music] Nepodařilo se inicializovat DeepL překladač: {exc}")
            translator = None
    else:
        print("[A1_music] DEEPL_API_KEY není nastaven, překlady textů písní budou vypnuté.")
    state.app.translator = translator

    # --- Načtení songs.json ---
    songs_path = os.path.join(state.app.static_folder, 'music/songs.json')
    try:
        with open(songs_path, encoding='utf-8') as f:
            state.app.songs = json.load(f)
    except FileNotFoundError:
        print(f"[A1_music] Soubor {songs_path} nenalezen, seznam písní bude prázdný.")
        state.app.songs = []
    except Exception as exc:
        print(f"[A1_music] Chyba při načítání {songs_path}: {exc}")
        state.app.songs = []

    # --- Načtení word_pairs.json ---
    word_pairs_path = os.path.join(state.app.static_folder, 'music/word_pairs.json')
    try:
        with open(word_pairs_path, encoding='utf-8') as f:
            state.app.word_pairs = json.load(f)
    except FileNotFoundError:
        print(f"[A1_music] Soubor {word_pairs_path} nenalezen, párovací cvičení budou vypnutá.")
        state.app.word_pairs = {}
    except Exception as exc:
        print(f"[A1_music] Chyba při načítání {word_pairs_path}: {exc}")
        state.app.word_pairs = {}


@exercises_bp.route('/song-selection', methods=['GET'])
def song_selection():
    """Výběr písničky pro cvičení.

    Přidáno podrobné logování, aby bylo vidět, že se route volá i na serveru
    a v jakém stavu je seznam písniček.
    """
    try:
        # Základní log o volání endpointu
        user_id = session.get('user_id')
        print(f"[A1_music] /song-selection called, user_id={user_id}")

        # Ověření, že songs jsou načtené
        songs = getattr(current_app, 'songs', None)
        if songs is None:
            print("[A1_music] current_app.songs is None – songs.json se pravděpodobně nenačetl v on_load.")
            songs = []
        else:
            try:
                print(f"[A1_music] songs loaded, count={len(songs)}")
            except Exception as exc:
                print(f"[A1_music] Nelze zjistit počet písniček: {exc}")

        # Logujeme první položku pro debug (bez přetěžování logů)
        if songs:
            first = songs[0]
            print(f"[A1_music] first song in list: {first}")
        else:
            print("[A1_music] songs list is empty.")
        # return render_template('omluva.html', songs=songs)
        return render_template('music/index.html', songs=songs)
    except Exception as exc:
        # Zachytíme neočekávané chyby a zalogujeme je, aby byly viditelné v Railway logu
        print(f"[A1_music] ERROR in /song-selection: {exc}")
        import traceback as _tb
        print(_tb.format_exc())
        # Necháme globální error handler vrátit 500/HTML, ale log máme
        raise


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
    if 'user_id' in session:
        session['training_start'] = time.time()
        # Nastavíme first_activity pokud ještě není
        # Ošetření starých session: pokud session['user_id'] neexistuje v users,
        # ale existuje v guest, vytvoříme pro něj záznam v users a tím opravíme FK.
        try:
            db = get_db_connection()
            cur = db.cursor(dictionary=True)
            sid = session.get('user_id')
            # 1) existuje users.id?
            cur.execute("SELECT id FROM users WHERE id = %s", (sid,))
            row = cur.fetchone()
            if not row:
                # 2) zkusíme najít v guest
                cur.execute("SELECT * FROM guest WHERE id = %s", (sid,))
                guest_row = cur.fetchone()
                if guest_row:
                    logging.getLogger("A1_music").warning(
                        "[A1_music] exercise: user_id=%s nenalezen v users, ale existuje v guest -> vytvářím users řádek",
                        sid,
                    )
                    # Vytvoříme users záznam se stejným id jako guest.id, aby seděl FK v user_stats
                    insert_sql = (
                        "INSERT INTO users (id, first_name, last_name, email, password, school, is_guest, has_seen_onboarding) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                    )
                    # guest_row je dict díky cursoru dictionary=True
                    params = (
                        guest_row.get('id'),
                        guest_row.get('first_name') or 'Guest',
                        guest_row.get('last_name') or 'User',
                        guest_row.get('email'),
                        guest_row.get('password') or '',
                        guest_row.get('school') or 'Knowix',
                        1,
                        guest_row.get('has_seen_onboarding') or 0,
                    )
                    try:
                        cur.execute(insert_sql, params)
                        db.commit()
                    except Exception as exc:
                        logging.getLogger("A1_music").error(
                            "[A1_music] exercise: nepodařilo se vytvořit users řádek pro guest.id=%s: %s",
                            sid,
                            exc,
                        )
                else:
                    logging.getLogger("A1_music").error(
                        "[A1_music] exercise: session user_id=%s neexistuje ani v users, ani v guest",
                        sid,
                    )
            # Po případné opravě zkusíme normálně nastavit first_activity
            update_user_stats(session['user_id'], set_first_activity=True)
        except Exception as exc:
            logging.getLogger("A1_music").error(
                "[A1_music] exercise: chyba při kontrole/repair users.id pro user_id=%s: %s",
                session.get('user_id'),
                exc,
            )
        finally:
            try:
                if cur:
                    cur.close()
                if db:
                    db.close()
            except Exception:
                pass

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

        # Nově načítáme lyrics i překlady (JSON); pokud chybí, použij LRC fallback
        lyrics_lines, translations_lines = get_lyrics_and_translations_from_json(song_info)
        print(f"Lyrics: {lyrics_lines}, Translations: {translations_lines}")

        lrc_path = os.path.join(current_app.static_folder, 'music/audio/lyrics', song_info.get('lyrics_file', ''))
        lrc_fallback = False
        if lyrics_lines is None or translations_lines is None:
            lrc_lines = parse_lrc_file(lrc_path)
            if not lrc_lines:
                return "Text písně nebyl nalezen (chybí JSON i LRC).", 404
            lyrics_lines = lrc_lines
            translations_lines = [None] * len(lyrics_lines)
            lrc_fallback = True

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

        # Pokud používáme LRC fallback, přelož pouze nezbytné řádky pro aktuální cvičení
        if lrc_fallback and getattr(current_app, 'translator', None) is not None:
            indices_to_translate = set(missing_indices + translation_indices)
            for idx in indices_to_translate:
                if 0 <= idx < len(lyrics_lines) and not translations_lines[idx]:
                    try:
                        translations_lines[idx] = translate_line_with_retry(
                            current_app.translator,
                            lyrics_lines[idx],
                            target_lang='CS'
                        )
                    except Exception as exc:
                        print(f"[A1_music] Chyba při překladu LRC řádku index {idx}: {exc}")
                        translations_lines[idx] = f"[Nepřeloženo] {lyrics_lines[idx]}"
        elif lrc_fallback:
            # Není k dispozici překladač – necháme překlady None nebo zkopírujeme originál
            indices_to_fill = set(missing_indices + translation_indices)
            for idx in indices_to_fill:
                if 0 <= idx < len(lyrics_lines) and not translations_lines[idx]:
                    translations_lines[idx] = lyrics_lines[idx]

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
    from user_stats import add_learning_time, update_user_stats  # Import uvnitř kvůli cyklickým závislostem

    data = request.json
    results = {
        'missing': [],
        'translations': [],
        'pairs': False,
        'details': {
            'missing': [],
            'translations': [],
            'pairs': []
        }
    }

    # Vyhodnocení missing exercises
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

    # Vyhodnocení translation exercises
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

    # Uložení času tréninku
    if 'user_id' in session and session.get('training_start'):
        try:
            start = float(session.pop('training_start', None))
            duration = max(1, int(time.time() - start))  # min. 1 sekunda
            add_learning_time(session['user_id'], duration)
        except Exception as e:
            print("Chyba při ukládání času tréninku:", e)

    # Vyhodnocení pairs (word-matching) - POČÍTÁME KAŽDÝ PÁR
    def normalize_pair(pair):
        return tuple(normalize(w) for w in pair)

    correct_pairs_dict = session.get('current_exercise_pairs', {})
    user_pairs = [normalize_pair(pair) for pair in data.get('pairs', [])]
    correct_pairs_set = set(normalize_pair((en, cs)) for en, cs in correct_pairs_dict.items())
    correct_pairs_set |= set(normalize_pair((cs, en)) for en, cs in correct_pairs_dict.items())

    pair_results = []
    for pair in user_pairs:
        if pair in correct_pairs_set:
            pair_results.append(True)
        else:
            pair_results.append(False)
    results['details']['pairs'] = pair_results

    # Pro úspěch je nutné, aby všechny páry byly správné a počet odpovídal zadání
    results['pairs'] = all(pair_results) and len(user_pairs) == len(correct_pairs_dict)

    # Celkový výsledek
    all_correct = (
            all(x in (True, 'almost') for x in results['missing']) and
            all(x in (True, 'almost') for x in results['translations']) and
            results['pairs'] and
            len(results['missing']) == len(stored_missing) and
            len(results['translations']) == len(stored_translations)
    )

    # --- Ukládání statistik uživatele ---
    if 'user_id' in session:
        # Spočítat správné/špatné odpovědi včetně jednotlivých párů
        correct_count = sum(1 for x in results['missing'] if x is True) + \
                        sum(1 for x in results['translations'] if x is True) + \
                        sum(1 for x in pair_results if x is True)
        wrong_count = (
                len([x for x in results['missing'] if x is False]) +
                len([x for x in results['translations'] if x is False]) +
                len([x for x in pair_results if x is False])
        )
        update_user_stats(
            session['user_id'],
            correct=correct_count,
            wrong=wrong_count,
            lesson_done=all_correct
        )

    # --- XP INTEGRACE ---
    xp_awarded = 0
    new_xp = None
    new_level = None
    new_achievements = []
    xp_error = None
    streak_info = None
    if all_correct and 'user_id' in session:
        try:
            xp_result = add_xp_to_user(session['user_id'], 10)
            streak_info = update_user_streak(session['user_id'])
            xp_awarded = 10
            new_xp = xp_result.get('xp')
            new_level = xp_result.get('level')
            new_achievements = xp_result.get('new_achievements', [])
            # Přidej informaci o streaku do odpovědi pouze pokud byl streak prodloužen nebo začal
            streak_message = None
            if streak_info and streak_info.get("status") in ("started", "continued"):
                streak_message = f"🔥 Máš streak {streak_info['streak']} dní v řadě!"
        except Exception as e:
            xp_error = str(e)
            print("XP ERROR:", e)
            print(traceback.format_exc())

    return jsonify({
        'results': results,
        'success': all_correct,
        'feedback': {
            'thresholds': {
                'missing': 0.9,
                'translations': 0.85
            }
        },
        'xp_awarded': xp_awarded,
        'new_xp': new_xp,
        'new_level': new_level,
        'new_achievements': new_achievements,
        'xp_error': xp_error,
        'streak_info': streak_info,
    })
