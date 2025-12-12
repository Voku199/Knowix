from dotenv import load_dotenv
from flask import Flask, request, render_template, Blueprint, session, jsonify
import requests
import os
import re
import json
import random
import time
import traceback
import unicodedata
from difflib import SequenceMatcher
from db import get_db_connection
import logging

vlastni_music_bp = Blueprint("vlastni_music_bp", __name__)

# --- Stats / XP kontext (přidáno) ---
try:
    from xp import get_user_xp_and_level  # noqa
    from streak import get_user_streak  # noqa
except Exception:  # pragma: no cover
    get_user_xp_and_level = None
    get_user_streak = None

LEVEL_NAMES = ["Začátečník", "Učeň", "Student", "Pokročilý", "Expert", "Mistr", "Legenda"]


def _lvl_name(l: int) -> str:
    if l <= 1: return LEVEL_NAMES[0]
    if l <= 2: return LEVEL_NAMES[1]
    if l <= 4: return LEVEL_NAMES[2]
    if l <= 6: return LEVEL_NAMES[3]
    if l <= 8: return LEVEL_NAMES[4]
    if l <= 10: return LEVEL_NAMES[5]
    return LEVEL_NAMES[6]


@vlastni_music_bp.context_processor
def inject_stats():
    uid = session.get('user_id')
    out = {}
    # streak
    if uid and get_user_streak:
        try:
            out['user_streak'] = get_user_streak(uid) or 0
        except Exception:
            out['user_streak'] = 0
    else:
        out['user_streak'] = 0
    # xp
    if uid and get_user_xp_and_level:
        try:
            data = get_user_xp_and_level(uid) or {}
            xp = data.get('xp', 0)
            level = data.get('level', 1)
            xp_in_level = xp % 50
            out.update(
                user_xp=xp,
                user_level=level,
                user_level_name=_lvl_name(level),
                user_progress_percent=int((xp_in_level / 50) * 100),
                user_xp_in_level=xp_in_level
            )
        except Exception:
            pass
    return out


# ===== ÚPRAVA NORMALIZACE: ignorujeme diakritiku + velikost písmen =====
def _strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', s) if not unicodedata.combining(c))


def _normalize(text: str) -> str:
    if text is None:
        return ""
    s = str(text).strip()
    # odstranění diakritiky
    s = _strip_accents(s)
    # lower-case
    s = s.lower()
    # odstranění všeho krom alfanumerik a mezer
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _collect_video_candidates(data: dict, out: list):
    """Collect tuples of (videoId, title, seconds) from ytInitialData into out list."""
    if isinstance(data, dict):
        vr = data.get('videoRenderer')
        if isinstance(vr, dict):
            vid = vr.get('videoId')
            title_obj = vr.get('title', {})
            title_runs = title_obj.get('runs') or []
            title_text = ''.join([r.get('text', '') for r in title_runs]) if title_runs else title_obj.get('simpleText',
                                                                                                           '') or ''
            # délka – může být v lengthText.simpleText např. "3:45" nebo "1:02:10"
            length_text = ''
            lt = vr.get('lengthText') or {}
            if isinstance(lt, dict):
                length_text = lt.get('simpleText') or ''
            seconds = None
            if length_text:
                parts = length_text.split(':')
                try:
                    if len(parts) == 2:
                        m, s = parts
                        seconds = int(m) * 60 + int(s)
                    elif len(parts) == 3:
                        h, m, s = parts
                        seconds = int(h) * 3600 + int(m) * 60 + int(s)
                except ValueError:
                    seconds = None
            out.append((vid, title_text, seconds))
        for v in data.values():
            _collect_video_candidates(v, out)
    elif isinstance(data, list):
        for item in data:
            _collect_video_candidates(item, out)


def search_youtube_first_video_id(query: str) -> str | None:
    """Search YouTube a vrať první ID videa, které pravděpodobně představuje plnou píseň (>=60s a <=10min)."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115 Safari/537.36'}
        resp = requests.get('https://www.youtube.com/results', params={'search_query': query}, headers=headers,
                            timeout=10)
        if resp.status_code != 200:
            print(f"YouTube search failed: {resp.status_code}")
            return None
        html = resp.text
        m = re.search(r"var ytInitialData = (\{.*?\});", html, re.DOTALL)
        if not m:
            m = re.search(r"ytInitialData" + r"\s*=\s*(\{.*?\});", html, re.DOTALL)
        if not m:
            print("ytInitialData not found in YouTube HTML")
            return None
        json_str = m.group(1)
        data = json.loads(json_str)
        candidates: list[tuple[str, str, int | None]] = []
        _collect_video_candidates(data, candidates)
        if not candidates:
            return None
        title_blacklist = [
            'lyrics', 'lyric', 'with lyrics', 'lyric video', 'official lyric', 'karaoke', '#shorts', 'shorts',
            '字幕', 'текст', 'tekst', 'subtitles', 'cc', 'text', 'texte', 'paroles', 'interview', 'podcast'
        ]

        def looks_like_song(title: str, seconds: int | None) -> bool:
            t = (title or '').lower()
            if any(b in t for b in title_blacklist):
                return False
            # délka: mezi 60s a 600s (10 minut). Pokud nevíme, pustíme jen pokud není zjevně krátké slovo typu shorts.
            if seconds is not None and not (60 <= seconds <= 600):
                return False
            return True

        # upřednostni kandidáty s platnou délkou
        for vid, title, seconds in candidates:
            if looks_like_song(title, seconds):
                return vid
        # fallback: najdi první s délkou >=60
        for vid, title, seconds in candidates:
            if seconds and seconds >= 60:
                return vid
        # poslední fallback
        return candidates[0][0]
    except Exception as e:
        print(f"YouTube parsing error: {e}")
        return None


# ---------- Genius + DeepL helpers ----------

def _get_genius_token() -> str | None:
    load_dotenv(dotenv_path=".env")
    return os.getenv('GENIUS_API_KEY')


def _get_deepl_key() -> str | None:
    load_dotenv(dotenv_path=".env")
    return os.getenv('DEEPL_API_KEY')


def _deepl_api_base(_: str) -> str:
    # Default to standard; functions will auto-fallback to free on 403 "Wrong endpoint"
    return "https://api.deepl.com"


def deepl_detect_language(text: str) -> str | None:
    api_key = _get_deepl_key()
    if not api_key:
        return None

    def _call(base: str):
        url = f"{base}/v2/translate"
        return requests.post(url, data={
            'auth_key': api_key,
            'text': text[:4500],
            'target_lang': 'EN'
        }, timeout=10)

    try:
        resp = _call("https://api.deepl.com")
        if resp.status_code == 403 and 'Wrong endpoint' in (resp.text or ''):
            resp = _call("https://api-free.deepl.com")
        if resp.status_code != 200:
            print('DeepL detect error', resp.status_code, resp.text)
            return None
        data = resp.json()
        translations = data.get('translations', [])
        if translations:
            return translations[0].get('detected_source_language')
        return None
    except Exception as e:
        print('DeepL exception', e)
        return None


def _deepl_post(params: list[tuple[str, str]]):
    """Low-level volání DeepL s fallbackem na free endpoint. Vrací JSON dict nebo None."""
    api_key = _get_deepl_key()
    if not api_key:
        return None
    payload = params + [('auth_key', api_key)]
    try:
        resp = requests.post("https://api.deepl.com/v2/translate", data=payload, timeout=15)
        if resp.status_code == 403 and 'Wrong endpoint' in (resp.text or ''):
            resp = requests.post("https://api-free.deepl.com/v2/translate", data=payload, timeout=15)
        if resp.status_code != 200:
            print('DeepL _post error', resp.status_code, resp.text)
            return None
        return resp.json()
    except Exception as e:
        print('DeepL _post exception', e)
        return None


def deepl_translate(texts: list[str], target_lang: str = 'CS') -> list[str]:
    api_key = _get_deepl_key()
    if not api_key or not texts:
        return []
    payload = [('text', t) for t in texts]
    payload.extend([
        ('auth_key', api_key),
        ('target_lang', target_lang),
        ('source_lang', 'EN')
    ])
    try:
        resp = requests.post("https://api.deepl.com/v2/translate", data=payload, timeout=15)
        if resp.status_code == 403 and 'Wrong endpoint' in (resp.text or ''):
            resp = requests.post("https://api-free.deepl.com/v2/translate", data=payload, timeout=15)
        if resp.status_code != 200:
            print('DeepL translate error', resp.status_code, resp.text)
            return []
        data = resp.json()
        trs = data.get('translations', [])
        return [t.get('text', '') for t in trs]
    except Exception as e:
        print('DeepL translate exception', e)
        return []


def deepl_translate_variants(text: str, target_lang: str = 'CS', source_lang: str | None = 'EN',
                             include_default: bool = True) -> list[str]:
    """
    Vrátí několik variant překladu jednoho textu pomocí různých nastavení (formality).
    Není garantováno, že DeepL vrátí odlišné výstupy, ale deduplikujeme a zachováme pořadí.
    """
    if not text:
        return []
    variants: list[str] = []
    # Různé varianty formality
    formalities = ['default', 'prefer_more', 'prefer_less']
    seen = set()

    for formality in formalities:
        params: list[tuple[str, str]] = [('text', text), ('target_lang', target_lang)]
        if source_lang:
            params.append(('source_lang', source_lang))
        if formality != 'default':
            params.append(('formality', formality))
        data = _deepl_post(params)
        if not data:
            continue
        trs = data.get('translations') or []
        if not trs:
            continue
        out = trs[0].get('text') or ''
        norm = _normalize(out)
        if out and norm not in seen:
            seen.add(norm)
            variants.append(out)

    # Pokud nic nevyšlo a chceme zahrnout i defaultní cestu přes standardní helper
    if include_default and not variants:
        try:
            base = deepl_translate([text], target_lang=target_lang)
            for t in base:
                norm = _normalize(t)
                if t and norm not in seen:
                    seen.add(norm)
                    variants.append(t)
        except Exception:
            pass
    return variants


def deepl_back_translate(text_cs: str, pivot_lang: str = 'EN') -> str | None:
    """Přeloží text z libovolného jazyka do pivot_lang (typicky EN). Využito pro back-translation."""
    if not text_cs:
        return None
    data = _deepl_post([('text', text_cs), ('target_lang', pivot_lang)])
    if not data:
        return None
    trs = data.get('translations') or []
    return trs[0].get('text') if trs else None


# === OpenAI (AI hodnocení překladu) ===
try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None  # fallback, pokud knihovna není


def _get_openai_key() -> str | None:
    load_dotenv(dotenv_path=".env")
    return os.getenv('OPENAI_API_KEY')


def _get_openai_model() -> str:
    load_dotenv(dotenv_path=".env")
    return os.getenv('OPENAI_MODEL') or 'gpt-4o-mini'


def ai_judge_translation(original_en: str, user_cs: str) -> dict | None:
    """
    AI rozhodčí pro EN->CS překlady. Vrátí {verdict: correct|almost|incorrect, reason: str} nebo None při chybě.
    """
    key = _get_openai_key()
    if not key or OpenAI is None:
        return None
    if not original_en or not user_cs:
        return None
    try:
        client = OpenAI(api_key=key)
        sys_msg = (
            "You are a strict bilingual evaluator for English->Czech translations. "
            "Decide if the Czech candidate means the same as the English source. "
            "Allow minor style/word-order differences. If mostly correct but with minor issues, use 'almost'. "
            "If key meaning is wrong or missing, use 'incorrect'. Return strict JSON: {verdict, reason}."
        )
        user_msg = (
            "Evaluate the Czech translation. Return JSON only.\n"
            f"EN: {original_en}\n"
            f"CS: {user_cs}"
        )
        completion = client.chat.completions.create(
            model=_get_openai_model(),
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg},
            ],
        )
        content = completion.choices[0].message.content if completion and completion.choices else None
        if not content:
            return None
        try:
            data = json.loads(content)
        except Exception:
            m = re.search(r"\{.*\}", content, re.DOTALL)
            data = json.loads(m.group(0)) if m else None
        if not isinstance(data, dict):
            return None
        verdict = str(data.get('verdict', '')).lower().strip()
        if verdict not in ('correct', 'almost', 'incorrect'):
            return None
        reason = str(data.get('reason') or '')
        return {"verdict": verdict, "reason": reason}
    except Exception as e:
        print('AI judge error:', e)
        return None


def genius_search_song(query: str) -> dict | None:
    token = _get_genius_token()
    logger = logging.getLogger("vlastni_music")
    if not token:
        logger.error('[vlastni_music] Missing GENIUS_ACCESS_TOKEN při hledání "%s"', query)
        return None
    try:
        resp = requests.get(
            'https://api.genius.com/search',
            params={'q': query},
            headers={'Authorization': f'Bearer {token}'},
            timeout=10
        )
        if resp.status_code != 200:
            logger.error('[vlastni_music] Genius search error %s pro "%s": %s',
                         resp.status_code, query, resp.text[:300])
            return None
        data = resp.json()
        hits = data.get('response', {}).get('hits', [])
        logger.info('[vlastni_music] Genius search "%s" -> %d hits', query, len(hits))
        if not hits:
            return None
        # return the best hit
        return hits[0].get('result')
    except Exception as e:
        logger.error('[vlastni_music] Genius exception pro "%s": %s', query, e)
        logger.error(traceback.format_exc())
        return None


def genius_fetch_lyrics(song_url: str) -> str | None:
    logger = logging.getLogger("vlastni_music")
    try:
        logger.info('[vlastni_music] Fetching lyrics from Genius URL=%r', song_url)
        r = requests.get(song_url, timeout=10)
        if r.status_code != 200:
            logger.error('[vlastni_music] Genius page error %s pro URL=%r: %s',
                         r.status_code, song_url, r.text[:300])
            return None
        html = r.text
        logger.info('[vlastni_music] Genius HTML length=%d chars', len(html))
        # Extract lyrics from data-lyrics-container sections
        parts = re.findall(r'<div[^>]*data-lyrics-container="true"[^>]*>(.*?)</div>', html, re.DOTALL)
        logger.info('[vlastni_music] data-lyrics-container blocks found: %d', len(parts))
        if not parts:
            # fallback to older selector
            parts = re.findall(r'<div class="lyrics">(.*?)</div>', html, re.DOTALL)
            logger.info('[vlastni_music] fallback <div class="lyrics"> blocks found: %d', len(parts))
        if not parts:
            logger.error('[vlastni_music] Žádné lyrics bloky nenalezeny v HTML pro URL=%r', song_url)
            return None

        def strip_tags(s: str) -> str:
            s = re.sub(r'<br\s*/?>', '\n', s)
            s = re.sub(r'<.*?>', '', s)
            return s

        text = '\n'.join(strip_tags(p) for p in parts)
        logger.info('[vlastni_music] Parsed lyrics length=%d chars', len(text))
        return text
    except Exception as e:
        logger.error('[vlastni_music] Genius scrape exception pro URL=%r: %s', song_url, e)
        logger.error(traceback.format_exc())
        return None


def clean_lyrics_lines(raw: str) -> list[str]:
    lines = [ln.strip() for ln in raw.splitlines()]
    cleaned = []
    ban_substrings = [
        'contributed', 'contributet', 'embed', 'you might also like', 'genius', 'copyright', 'all rights',
        'writer', 'produced by', 'feat.', 'featuring'
    ]
    for ln in lines:
        if not ln:
            continue
        if ln.startswith('[') and ln.endswith(']'):
            continue
        low = ln.lower()
        if any(b in low for b in ban_substrings):
            continue
        # Filtruj řádky obsahující čísla, hashtags a speciální symboly
        if filter_unwanted_content(ln):
            continue
        cleaned.append(ln)
    return cleaned


def filter_unwanted_content(text: str) -> bool:
    """
    Vrací True, pokud text obsahuje nežádoucí obsah (čísla, hashtags, speciální symboly).
    Takový text bude odfiltrován.
    """
    # Kontrola na čísla
    if re.search(r'\d', text):
        return True

    # Kontrola na hashtags a speciální symboly
    unwanted_symbols = ['#', '@', '&', '%', '$', '€', '£', '¥', '₽', '+', '=', '<', '>', '|', '\\', '/', '*', '^', '~',
                        '`']
    if any(symbol in text for symbol in unwanted_symbols):
        return True

    # Kontrola na nadměrné množství speciálních znaků
    special_chars = re.findall(r'[^\w\s\'\-\.\,\!\?\:\;\(\)]', text)
    if len(special_chars) > 2:  # Povolit maximálně 2 speciální znaky na řádek
        return True

    return False


def build_exercises_from_lyrics(lines: list[str]) -> tuple[list[dict], list[dict]]:
    # pick candidate lines of reasonable length and filter unwanted content
    candidates = [ln for ln in lines if 20 <= len(ln) <= 120 and not filter_unwanted_content(ln)]
    random.shuffle(candidates)

    def make_cloze(ln: str) -> dict | None:
        words = re.findall(r"[A-Za-z']+", ln)
        # exclude very short/common words
        stop = set(
            ['the', 'a', 'an', 'and', 'or', 'but', 'of', 'to', 'in', 'on', 'for', 'with', 'at', 'by', 'is', 'it', 'i',
             'you', 'he', 'she', 'we', 'they', 'be'])
        good = [w for w in words if len(w) >= 3 and w.lower() not in stop]
        if not good:
            return None
        target = random.choice(good)
        pattern = re.compile(rf"\b{re.escape(target)}\b")
        with_blank = pattern.sub('___', ln, count=1)
        return {'with_blank': with_blank, 'answer': target}

    missing = []
    for ln in candidates:
        c = make_cloze(ln)
        if c:
            missing.append(c)
        if len(missing) >= 3:
            break

    # translation exercises – select different lines if possible
    remaining = [ln for ln in candidates if ln not in [m['with_blank'] for m in missing]]
    translations_src = remaining[:3] if len(remaining) >= 3 else candidates[:3]
    # Optionally prepare solutions (not displayed yet)
    translations_out = deepl_translate(translations_src, target_lang='CS') if translations_src else []
    translation = []
    for i, ln in enumerate(translations_src):
        item = {'original': ln}
        if i < len(translations_out):
            item['translated'] = translations_out[i]
        translation.append(item)

    return missing, translation


# --- Přidání kontextu pro XP / streak jako v A1 ---
try:
    from xp import get_user_xp_and_level  # noqa
    from streak import get_user_streak  # noqa
except Exception:  # pragma: no cover
    get_user_xp_and_level = None
    get_user_streak = None

LEVEL_NAMES = ["Začátečník", "Učeň", "Student", "Pokročilý", "Expert", "Mistr", "Legenda"]


def _level_name(lvl: int) -> str:
    if lvl <= 1: return LEVEL_NAMES[0]
    if lvl <= 2: return LEVEL_NAMES[1]
    if lvl <= 4: return LEVEL_NAMES[2]
    if lvl <= 6: return LEVEL_NAMES[3]
    if lvl <= 8: return LEVEL_NAMES[4]
    if lvl <= 10: return LEVEL_NAMES[5]
    return LEVEL_NAMES[6]


@vlastni_music_bp.context_processor
def inject_meta():
    uid = session.get('user_id')
    out = {}
    if get_user_streak and uid:
        try:
            out['user_streak'] = get_user_streak(uid)
        except Exception:
            out['user_streak'] = 0
    else:
        out['user_streak'] = 0
    if get_user_xp_and_level and uid:
        try:
            data = get_user_xp_and_level(uid)
            xp = data.get('xp', 0)
            level = data.get('level', 1)
            xp_in_level = xp % 50
            out.update(
                user_xp=xp,
                user_level=level,
                user_level_name=_level_name(level),
                user_progress_percent=int((xp_in_level / 50) * 100),
                user_xp_in_level=xp_in_level
            )
        except Exception:
            pass
    return out


def _ensure_user_exists_for_session_vlastni():
    """Zajistí, že session['user_id'] existuje v tabulce users.

    Pokud neexistuje users.id, ale existuje záznam v guest s tímto id,
    vytvoří odpovídající řádek v users (shadow user) a tím opraví stará data.
    Používá se před voláním update_user_stats/add_learning_time/add_xp_to_user.
    """
    sid = session.get('user_id')
    if not sid:
        return
    try:
        db = get_db_connection()
        cur = db.cursor(dictionary=True)
        # 1) Zkus users
        cur.execute("SELECT id FROM users WHERE id = %s", (sid,))
        if cur.fetchone():
            return
        # 2) Zkus guest
        cur.execute("SELECT * FROM guest WHERE id = %s", (sid,))
        guest_row = cur.fetchone()
        if not guest_row:
            logging.getLogger("vlastni_music").error(
                "[vlastni_music] user_id=%s neexistuje ani v users, ani v guest",
                sid,
            )
            return
        logging.getLogger("vlastni_music").warning(
            "[vlastni_music] user_id=%s nenalezen v users, ale existuje v guest -> vytvářím users řádek",
            sid,
        )
        insert_sql = (
            "INSERT INTO users (id, first_name, last_name, email, password, school, is_guest, has_seen_onboarding) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        )
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
            logging.getLogger("vlastni_music").error(
                "[vlastni_music] nepodařilo se vytvořit users řádek pro guest.id=%s: %s",
                sid,
                exc,
            )
    except Exception as exc:
        logging.getLogger("vlastni_music").error(
            "[vlastni_music] _ensure_user_exists_for_session_vlastni: chyba při kontrole/repair users.id pro user_id=%s: %s",
            session.get('user_id'),
            exc,
        )
    finally:
        try:
            if 'cur' in locals() and cur:
                cur.close()
            if 'db' in locals() and db:
                db.close()
        except Exception:
            pass


@vlastni_music_bp.route("/vlastni_music/check-answer", methods=["POST"])  # změněno namespace
def check_answer():
    """
    Vyhodnocení odpovědí pro vlastni_music.
    - Prahy pro missing: >=0.9 True, >=0.7 'almost'
    - Prahy pro translations: >=0.85 True, >=0.8 'almost'
    - Využívá podobnost stejně jako A1_music
    - Vrací kompatibilní strukturu (results, success, streak_info)
    """
    try:
        try:
            from user_stats import add_learning_time, update_user_stats  # noqa
        except Exception:
            add_learning_time = None
            update_user_stats = None
        try:
            from xp_system import add_xp_to_user, update_user_streak  # noqa
        except Exception:
            try:
                from xp import add_xp_to_user, update_user_streak  # type: ignore  # noqa
            except Exception:
                add_xp_to_user = None
                update_user_streak = None

        data = request.get_json(silent=True) or {}

        results = {
            "missing": [],
            "translations": [],
            "pairs": False,
            "details": {"missing": [], "translations": [], "pairs": []}
        }

        # Čas učení
        if "user_id" in session and session.get("training_start"):
            try:
                start = float(session.pop("training_start", None) or 0)
                if start:
                    duration = max(1, int(time.time() - start))
                    if add_learning_time:
                        _ensure_user_exists_for_session_vlastni()
                        add_learning_time(session["user_id"], duration)
            except Exception as e:
                print("Chyba při ukládání času tréninku:", e)

        # Missing (s podobností)
        stored_missing = session.get("missing_exercises", []) or []
        for idx, ex in enumerate(data.get("missing", [])):
            user_raw = (ex.get("user") or "").strip()
            correct_raw = ''
            if idx < len(stored_missing):
                # podporujeme oba klíče
                correct_raw = stored_missing[idx].get('missing_word') or stored_missing[idx].get('answer') or ''
            sim = _similarity(user_raw, correct_raw) if correct_raw else 0.0
            if sim >= 0.9:
                flag = True
            elif sim >= 0.7:
                flag = 'almost'
            else:
                flag = False
            results['missing'].append(flag)
            results['details']['missing'].append({
                'user': user_raw,
                'correct': correct_raw,
                'similarity': sim
            })

        # Translations
        stored_translations = session.get("translation_exercises", []) or []
        stored_alts = session.get('translation_alternatives', []) or []
        for idx, ex in enumerate(data.get("translations", [])):
            # pre-init kvůli linteru
            flag = False
            sim = 0.0
            feedback = None
            user_raw = (ex.get("user") or "").strip()
            correct_translation = stored_translations[idx].get('translated', '') if idx < len(
                stored_translations) else ''
            original = stored_translations[idx].get('original', '') if idx < len(stored_translations) else ''

            # Nejprve: rychlé zamítnutí, pokud opisuje originál EN
            if correct_translation and _normalize(user_raw) == _normalize(original):
                flag = False
                sim = 0.0
                feedback = f"Nemůžeš jen opsat anglickou větu. Správný překlad: '{correct_translation}'."
                results['translations'].append(flag)
                results['details']['translations'].append({
                    'user': user_raw,
                    'correct': correct_translation,
                    'similarity': sim,
                    'feedback': feedback,
                    'ai': None
                })
                continue

            # AI hodnocení jako primární
            ai_res = None
            try:
                ai_res = ai_judge_translation(original, user_raw) if original and user_raw else None
            except Exception:
                ai_res = None

            if ai_res:
                verdict = ai_res.get('verdict')
                reason = ai_res.get('reason')
                if verdict == 'correct':
                    flag = True
                    sim = 1.0
                    feedback = None
                elif verdict == 'almost':
                    flag = 'almost'
                    sim = 0.82
                    prefer = correct_translation
                    # Zkus použít nejbližší alternativu pro lepší feedback
                    alts = stored_alts[idx] if idx < len(stored_alts) else []
                    if alts:
                        best_alt = max(alts, key=lambda c: _similarity(user_raw, c) if c else 0)
                        if best_alt and _normalize(best_alt) != _normalize(prefer or ''):
                            prefer = best_alt
                    feedback = f"Skoro. {reason or ''} Správně např.: '{prefer}'.".strip()
                else:  # incorrect
                    # Přejdeme na fallback heuristiku, aby byl výsledek konzistentní
                    ai_note = reason or 'AI: incorrect'
                    # Fallback níže
                    pass
                if verdict in ('correct', 'almost'):
                    results['translations'].append(flag)
                    results['details']['translations'].append({
                        'user': user_raw,
                        'correct': correct_translation,
                        'similarity': sim,
                        'feedback': feedback,
                        'ai': ai_res
                    })
                    continue  # AI už rozhodla pozitivně, další logika není třeba
            # === Fallback: původní heuristika (alternativy + back-translation) ===
            ratio_to_tr = _similarity(user_raw, correct_translation) if correct_translation else 0.0
            ratio_to_orig = _similarity(user_raw, original) if original else 0.0
            alts = stored_alts[idx] if idx < len(stored_alts) else []
            ratio_to_any_alt = 0.0
            matched_alt = None
            for cand in alts:
                r = _similarity(user_raw, cand)
                if r > ratio_to_any_alt:
                    ratio_to_any_alt = r
                    matched_alt = cand
            sim = max(ratio_to_tr, ratio_to_orig, ratio_to_any_alt)
            back_info = None
            if sim < 0.8 and original:
                try:
                    bt = deepl_back_translate(user_raw, pivot_lang='EN')
                    if bt:
                        r_bt = _similarity(bt, original)
                        if r_bt > sim:
                            sim = r_bt
                            back_info = bt
                except Exception:
                    pass
            if sim >= 0.85:
                flag = True
                feedback = None
            elif sim >= 0.8:
                flag = 'almost'
                prefer = matched_alt or correct_translation
                feedback = f"Tvoje odpověď není úplně přesná. Správně: '{prefer}'."
            else:
                flag = False
                feedback = f"Správný překlad: '{correct_translation}'."
                if matched_alt and _normalize(matched_alt) != _normalize(correct_translation):
                    feedback += f" Alternativně: '{matched_alt}'."
                if back_info:
                    feedback += " (Podobný význam dle back-translation, ale pod prahem.)"
            results['translations'].append(flag)
            results['details']['translations'].append({
                'user': user_raw,
                'correct': correct_translation,
                'similarity': sim,
                'feedback': feedback,
                'ai': ai_res or None,
                'matched_alt': matched_alt
            })

        # Pairs
        def normalize_pair(p):
            return tuple(_normalize(w) for w in p)

        correct_pairs_dict = session.get('current_exercise_pairs', {}) or {}
        user_pairs = [normalize_pair(p) for p in data.get('pairs', []) if isinstance(p, (list, tuple)) and len(p) == 2]
        correct_pairs_set = set(normalize_pair((en, cs)) for en, cs in correct_pairs_dict.items())
        correct_pairs_set |= set(normalize_pair((cs, en)) for en, cs in correct_pairs_dict.items())
        pair_results = [(p in correct_pairs_set) for p in user_pairs]
        results['details']['pairs'] = pair_results
        results['pairs'] = all(pair_results) and len(user_pairs) == len(correct_pairs_dict) and len(
            correct_pairs_dict) > 0

        # Celkové skóre (almost se počítá jako splněno)
        total_pairs = len(correct_pairs_dict)
        correct_missing_cnt = sum(1 for x in results['missing'] if x in (True, 'almost'))
        correct_trans_cnt = sum(1 for x in results['translations'] if x in (True, 'almost'))
        correct_pairs_cnt = sum(1 for ok in pair_results if ok)
        total_items = len(session.get('missing_exercises', [])) + len(
            session.get('translation_exercises', [])) + total_pairs
        if total_items <= 0:
            total_items = 1
        score = (correct_missing_cnt + correct_trans_cnt + correct_pairs_cnt) / total_items
        success = score >= 0.70

        # Statistiky
        if 'user_id' in session and update_user_stats:
            try:
                correct_count = sum(1 for x in results['missing'] if x is True) + \
                                sum(1 for x in results['translations'] if x is True) + \
                                sum(1 for x in pair_results if x is True)
                wrong_count = len([x for x in results['missing'] if x is False]) + \
                              len([x for x in results['translations'] if x is False]) + \
                              len([x for x in pair_results if x is False])
                _ensure_user_exists_for_session_vlastni()
                update_user_stats(session['user_id'], correct=correct_count, wrong=wrong_count, lesson_done=success)
            except Exception as e:
                print('Chyba při update_user_stats:', e)

        # XP & streak
        xp_awarded = 0
        new_xp = None
        new_level = None
        new_achievements = []
        xp_error = None
        streak_info = None
        streak_message = None
        if success and 'user_id' in session and add_xp_to_user and update_user_streak:
            try:
                _ensure_user_exists_for_session_vlastni()
                xp_result = add_xp_to_user(session['user_id'], 10)
                streak_info = update_user_streak(session['user_id'])
                xp_awarded = 10
                if isinstance(xp_result, dict):
                    new_xp = xp_result.get('xp')
                    new_level = xp_result.get('level')
                    new_achievements = xp_result.get('new_achievements', [])
                if streak_info and streak_info.get('status') in ('started', 'continued'):
                    streak_message = f"🔥 Máš streak {streak_info['streak']} dní v řadě!"
            except Exception as e:
                xp_error = str(e)
                print('XP ERROR:', e)
                print(traceback.format_exc())

        debug_payload = {
            'session_keys': {
                'missing_exercises': bool(session.get('missing_exercises')),
                'translation_exercises': bool(session.get('translation_exercises')),
                'current_exercise_pairs': bool(correct_pairs_dict),
            },
            'missing_session_corrects': [m.get('missing_word') or m.get('answer') for m in
                                         session.get('missing_exercises', [])],
            'translations_session': {
                'originals': [t.get('original', '') for t in session.get('translation_exercises', [])],
                'translated': [t.get('translated', '') for t in session.get('translation_exercises', [])],
            },
            'pairs_expected': list(correct_pairs_dict.items()),
            'pairs_user_count': len(user_pairs),
            'pairs_expected_count': len(correct_pairs_dict),
        }

        return jsonify({
            'results': results,
            'success': success,
            'score': round(score, 3),
            'required_percent': 0.80,
            'missing': results['missing'],
            'translations': results['translations'],
            'pairs': results['pairs'],
            'details': results['details'],
            'all_correct': success,
            'xp_awarded': xp_awarded,
            'new_xp': new_xp,
            'new_level': new_level,
            'new_achievements': new_achievements,
            'streak_info': streak_info,
            'streak_message': streak_message,
            'xp_error': xp_error,
            'debug': debug_payload
        })

    except Exception as e:
        print('CHECK_ANSWER UNCAUGHT ERROR:', e)
        print(traceback.format_exc())
        return jsonify({'error': 'internal_error', 'message': str(e)}), 500

    # end check_answer


@vlastni_music_bp.route('/vlastni_music', methods=['GET', 'POST'])
def index():
    video_id = None
    logger = logging.getLogger("vlastni_music")
    if request.method == 'POST':
        song_name = request.form['song']
        logger.info("[vlastni_music] index POST song_name='%s' user_id=%s", song_name, session.get('user_id'))
        # --- STAT START (shodne s A1) ---
        if 'user_id' in session:
            session['training_start'] = time.time()
            try:
                from user_stats import update_user_stats  # noqa
                _ensure_user_exists_for_session_vlastni()
                update_user_stats(session['user_id'], set_first_activity=True)
            except Exception as e:  # pragma: no cover
                print('Nelze inicializovat user_stats (vlastni_music start):', e)
        # --- /STAT START ---
        video_id = search_youtube_first_video_id(song_name)
        hit = genius_search_song(song_name)
        if not hit:
            return render_template('vlastni_music/vlastni_music.html', video_id=None,
                                   error='Píseň nebyla nalezena na Genius.')
        song_url = hit.get('url')
        lyrics_raw = genius_fetch_lyrics(song_url)
        if not lyrics_raw:
            logger.error("[vlastni_music] genius_fetch_lyrics vrátil prázdný text pro URL=%r", song_url)
            return render_template('vlastni_music/vlastni_music.html', video_id=None,
                                   error='Text písně se nepodařilo načíst.')
        logger.info("[vlastni_music] lyrics_raw length=%d chars", len(lyrics_raw))
        # Jazyková kontrola – povoleny jen anglické písně (pokud selže detekce, pokračujeme)
        try:
            sample_for_lang = '\n'.join(lyrics_raw.splitlines()[:40])[:4000]
            lang = deepl_detect_language(sample_for_lang) or 'EN'
            logger.info('[vlastni_music] detected language for "%s" -> %s', song_name, lang)
            if lang.upper() != 'EN':
                logger.warning('[vlastni_music] Píseň "%s" detekována jako %s, zamítá se.', song_name, lang)
                return render_template('vlastni_music/vlastni_music.html', video_id=None,
                                       error=f'Píseň není v angličtině (detekováno {lang}). Zkus jinou skladbu.')
        except Exception as e:
            logger.error('[vlastni_music] Chyba při detekci jazyka pro "%s": %s', song_name, e)
            logger.error(traceback.format_exc())
        lines = clean_lyrics_lines(lyrics_raw)
        logger.info('[vlastni_music] clean_lyrics_lines: %d řádků po filtrování', len(lines))
        if not lines:
            logger.error('[vlastni_music] Po clean_lyrics_lines žádné použitelné řádky pro "%s"', song_name)
            return render_template('vlastni_music/vlastni_music.html', video_id=video_id,
                                   error='Text písně je prázdný nebo nečitelný.')

        # --- GENEROVÁNÍ CVIČENÍ ---
        def good_line(ln: str) -> bool:
            return (bool(ln) and
                    3 <= len(ln.split()) <= 16 and
                    not ln.endswith(':') and
                    not filter_unwanted_content(ln))  # Přidána kontrola nežádoucího obsahu

        candidates = [ln for ln in lines if good_line(ln)]
        random.shuffle(candidates)
        # Cloze (missing) – unikátní řádky
        missing_exercises = []
        used_lines_for_cloze = set()
        for ln in candidates:
            if len(missing_exercises) >= 3:
                break
            if ln in used_lines_for_cloze:
                continue
            words = re.findall(r"[A-Za-z']+", ln)
            words = [w for w in words if len(w) > 3]
            if not words:
                continue
            target = random.choice(words)
            blanked = re.sub(rf"\b{re.escape(target)}\b", '_____', ln, count=1)
            if blanked == ln:
                continue
            missing_exercises.append({'original': ln, 'with_blank': blanked, 'missing_word': target, 'answer': target})
            used_lines_for_cloze.add(ln)
        # Translation – zajistit žádné překryvy s missing a mezi sebou
        trans_pool = [ln for ln in candidates if ln not in used_lines_for_cloze]
        random.shuffle(trans_pool)
        seen_trans = set()
        trans_pick = []
        TARGET_TRANSLATIONS = 2  # sníženo na 2 překladové věty
        for ln in trans_pool:
            if len(trans_pick) >= TARGET_TRANSLATIONS:
                break
            if ln in seen_trans:
                continue
            seen_trans.add(ln)
            trans_pick.append(ln)
        translations_cs = deepl_translate(trans_pick, target_lang='CS') if trans_pick else []
        # Oprava prázdných nebo chybných překladů
        if trans_pick and (len(translations_cs) != len(trans_pick) or any(not t for t in translations_cs)):
            fixed = []
            for i, original in enumerate(trans_pick):
                t = translations_cs[i] if i < len(translations_cs) else ''
                if not t:
                    single = deepl_translate([original], target_lang='CS')
                    t = single[0] if single else ''
                fixed.append(t)
            translations_cs = fixed
        translation_exercises = []
        # NOVĚ: k jednotlivým překladům předpočítáme alternativy (formality) a uložíme do session
        translation_alternatives: list[list[str]] = []
        for i, p in enumerate(trans_pick):
            main_tr = translations_cs[i] if i < len(translations_cs) else ''
            # předpočítej alternativy (bez duplicit, včetně hlavní pokud odlišná)
            alts = []
            try:
                alts = deepl_translate_variants(p, target_lang='CS', source_lang='EN', include_default=False)
            except Exception:
                alts = []
            # vlož i hlavní překlad na začátek, pokud není
            all_opts = []
            seen_norm = set()
            for cand in [main_tr, *alts]:
                n = _normalize(cand)
                if cand and n not in seen_norm:
                    seen_norm.add(n)
                    all_opts.append(cand)
            translation_alternatives.append(all_opts)
            translation_exercises.append({'original': p, 'translated': main_tr})

        # Matching vocab – promíchat pořadí EN i CS sloupců nezávisle
        def extract_candidate_words(text_lines: list[str]) -> list[str]:
            words = []
            for ln in text_lines:
                for w in re.findall(r"[A-Za-z']+", ln):
                    lw = w.strip("'")
                    if 4 <= len(lw) <= 12 and lw.isalpha():
                        words.append(lw.lower())
            return words

        vocab_all = list(dict.fromkeys(extract_candidate_words(candidates)))
        random.shuffle(vocab_all)
        vocab = vocab_all[:5]
        matching_cs = deepl_translate(vocab, target_lang='CS') if vocab else []
        matching_pairs = []
        for i, en in enumerate(vocab):
            matching_pairs.append({'en': en, 'cs': matching_cs[i] if i < len(matching_cs) else ''})
        # Promíchání pořadí EN párů
        random.shuffle(matching_pairs)
        # Oddělené promíchání české strany pro zobrazení
        matching_cs_shuffled = [p['cs'] for p in matching_pairs]
        random.shuffle(matching_cs_shuffled)
        # Session
        try:
            session['training_start'] = time.time()
            session['missing_exercises'] = missing_exercises
            session['translation_exercises'] = translation_exercises
            session['translation_alternatives'] = translation_alternatives  # uložit varianty
            session['current_exercise_pairs'] = {p['en']: p['cs'] for p in matching_pairs if
                                                 p.get('en') and p.get('cs')}
        except Exception as e:
            print('Chyba při ukládání do session (vlastni_music):', e)
        bidir = {**{p['en']: p['cs'] for p in matching_pairs},
                 **{p['cs']: p['en'] for p in matching_pairs if p.get('cs')}}
        config = {
            'song_title': song_name,
            'word_pairs': bidir,
            'missing_exercises': [ex['missing_word'] for ex in missing_exercises],
            'translation_exercises': [ex['translated'] for ex in translation_exercises]
        }
        youtube_url = None
        if video_id:
            youtube_url = f"https://www.youtube-nocookie.com/embed/{video_id}?cc_load_policy=0&iv_load_policy=3&modestbranding=1&rel=0&controls=1&fs=1&playsinline=1&disablekb=0"
        return render_template('vlastni_music/exercise.html',
                               missing_exercises=missing_exercises,
                               translation_exercises=translation_exercises,
                               matching_pairs=matching_pairs,
                               matching_cs_shuffled=matching_cs_shuffled,
                               youtube_url=youtube_url,
                               config=config)
    return render_template('vlastni_music/vlastni_music.html', video_id=video_id)
