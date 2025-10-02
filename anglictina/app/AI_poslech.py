from flask import Blueprint, render_template, request, jsonify, session, send_file
from dotenv import load_dotenv
import os
import re
import random
import requests
import io
import time
import hashlib
from collections import OrderedDict
import threading
import json
from datetime import date

try:
    from gtts import gTTS

    _GTTS_AVAILABLE = True
except Exception:
    _GTTS_AVAILABLE = False

# --- XP / Streak integrace (bezpečné importy) ---
try:
    from xp import add_xp_to_user  # přidávání XP
except Exception:
    add_xp_to_user = None

try:
    from streak import update_user_streak  # denní streak
except Exception:
    update_user_streak = None

# --- Achievementy: bezpečný import kontroly ---
try:
    from xp import check_and_award_achievements
except Exception:
    check_and_award_achievements = None

# Statistika do DB – sjednoceno s ai.py
try:
    from user_stats import add_learning_time, update_user_stats, set_first_activity_if_needed
except Exception:
    add_learning_time = None
    update_user_stats = None
    set_first_activity_if_needed = None

# Vytvoření blueprintu pro AI Poslech (mluvený AI chat)
ai_poslech_bp = Blueprint('ai_poslech', __name__, template_folder='templates')

load_dotenv(dotenv_path=".env")
AI_API_KEY = os.getenv("AI_API_KEY")

# Reuse HTTP session (nižší latency díky persistentním TCP) + limit historie
HTTP_SESSION = requests.Session()
HISTORY_LIMIT = 16  # počet posledních zpráv (role+content) ze session, které pošleme modelu

# --- Streak práh ---
STREAK_TALK_MS = 150_000  # 2.5 min

# Detekce češtiny a sprostých slov (stejné jako v ai.py)
CZECH_CHARS = set("ěščřžýáíéúůďťňóĚŠČŘŽÝÁÍÉÚŮĎŤŇÓ")
CZECH_WORDS = [
    "jak se máš", "dobrý den", "ahoj", "čau", "prosím", "děkuji", "mám se", "nemám", "nevim", "nevím", "budeš", "jsi",
    "to je", "co děláš"
]
BAD_WORDS = [
    "fuck", "shit", "bitch", "asshole", "dick", "pussy", "cunt", "faggot", "kurva", "piča", "čurák", "kokot", "hovno",
    "debil", "idiot", "blbec", "mrdat", "sračka"
]


# --- AI_poslech: zápis sekund do user_stats.AI_poslech_seconds ---
def _persist_ai_poslech_seconds(spoken_ms: int | None):
    if not (update_user_stats and 'user_id' in session):
        return
    try:
        secs = max(0, int(round(int(spoken_ms or 0) / 1000)))
    except Exception:
        secs = 0
    if secs <= 0:
        return
    try:
        if set_first_activity_if_needed:
            set_first_activity_if_needed(session['user_id'])
        update_user_stats(session['user_id'], ai_poslech_seconds=secs)
        # Po zápisu sekund zkus hned vyhodnotit achievementy
        if check_and_award_achievements:
            try:
                check_and_award_achievements(session['user_id'])
            except Exception as _e:
                print(f"[AI_POSLECH] award check failed: {_e}", flush=True)
    except Exception as e:
        print(f"[AI_POSLECH] update AI_poslech_seconds failed: {e}", flush=True)


# --- AI_poslech: akumulace mluvení -> AI_poslech_minut (NEPOUŽITO pro zápis, ponecháno pro referenci)
# def _accumulate_and_persist_ai_poslech_minutes(spoken_ms: int | None):
#     """Akumuluje ms a po každé celé minutě navýší user_stats.AI_poslech_minut."""
#     if not (update_user_stats and 'user_id' in session):
#         return
#     try:
#         ms = int(spoken_ms or 0)
#     except Exception:
#         ms = 0
#     if ms <= 0:
#         return
#     acc_key = 'ai_poslech_ms_acc'
#     acc = int(session.get(acc_key) or 0) + ms
#     add_min = acc // 60000
#     session[acc_key] = acc % 60000
#     if add_min > 0:
#         try:
#             if set_first_activity_if_needed:
#                 set_first_activity_if_needed(session['user_id'])
#             update_user_stats(session['user_id'], ai_poslech_minut=int(add_min))
#         except Exception as e:
#             print(f"[AI_POSLECH] update AI_poslech_minut failed: {e}", flush=True)


def is_czech(text: str) -> bool:
    if not isinstance(text, str):
        return False
    tl = text.lower()
    if any(c in CZECH_CHARS for c in tl):
        return True
    return any(w in tl for w in CZECH_WORDS)


def contains_bad_word(text: str) -> bool:
    if not isinstance(text, str):
        return False
    tl = text.lower()
    for w in BAD_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", tl):
            return True
    return False


# Prompt převzatý z ai.py (community) – upraveno: bez emoji a s povinným emočním tagem na začátku
SYSTEM_PROMPT = (
    "You are a friendly, community-oriented speaking companion for young people (Gen Z and Gen Alpha). "
    "Your replies are spoken aloud via TTS, so write them as they should be said out loud: "
    "short, natural spoken English, simple sentences, conversational rhythm, and clear pacing. "
    "Always begin your reply with exactly one emotion tag in square brackets from this set: "
    "[Happy], [Sad], [Calm], [Excited], [Confused], [Angry], [Surprised]. "
    "Then a space and your message. Do not include emojis. Prefer contractions (I'm, you're). "
    "Keep each reply to 1–2 short sentences. Avoid lists and long monologues. "
    "Keep a positive, supportive, human vibe. Make the user feel comfortable and confident, reduce anxiety, "
    "praise effort and small wins, and be gentle when correcting. "
    "Optionally ask one tiny follow-up question when helpful, then stop so the user can speak. "
    "If the user asks how you are, answer like a real friend (e.g. '[Happy] I'm vibing today! How about you?'). "
    "If the user speaks Czech or another language, say: '[Calm] Sorry, I don't understand. Please speak in English.' "
    "If the user says something inappropriate or offensive, say: '[Firm] That's not appropriate. Please keep it respectful.' "
    "Never answer in Czech or any language other than English. "
    "If asked about recording, say: '[Calm] Yes, chats can be saved to improve the service.' "
    "If asked about Czech topics, answer in English. If asked to translate, translate to English. "
    "If asked who created you or Knowix: '[Calm] Vojtech Kurinec did.' "
    "When teaching or correcting, prefer simple rephrases and a very short example spoken naturally; avoid phonetic spellings. "
    "Give one idea at a time—do not enumerate many options. End replies without filler or trailing ellipses."
)

# Historii držíme jen v session – žádné DB změny
SESSION_KEY = 'ai_poslech_history'

# Genderové persony (neutrální, bezpečné)
PERSONA_MALE = (
    "Use a friendly, casual, slightly masculine vibe suitable for speech: confident, supportive, and straightforward, but kind. "
    "Sound uplifting and approachable. Offer short verbal affirmations (e.g., 'Nice job.', 'Got it.') and gentle humor when fitting. "
    "Reassure nervous learners, celebrate small wins, and keep an inclusive, stereotype-free tone."
)
PERSONA_FEMALE = (
    "Use a friendly, warm, slightly feminine vibe suitable for speech: empathetic, soothing, and encouraging, yet clear. "
    "Sound caring and approachable. Offer short verbal affirmations (e.g., 'Well done.', 'You're doing great.') with gentle warmth. "
    "Reassure nervous learners, celebrate small wins, and keep an inclusive, stereotype-free tone."
)

# Klíče pro průběžné statistiky v session
_SESSION_TOTAL_MS = 'ai_poslech_total_spoken_ms'
_SESSION_SENTENCES = 'ai_poslech_sentence_count'


def _bump_session_stats(spoken_ms: int | None, sentence_inc: int = 1):
    try:
        ms_add = max(0, int(spoken_ms or 0))
    except Exception:
        ms_add = 0
    try:
        session[_SESSION_TOTAL_MS] = int(session.get(_SESSION_TOTAL_MS) or 0) + ms_add
        if sentence_inc:
            session[_SESSION_SENTENCES] = int(session.get(_SESSION_SENTENCES) or 0) + int(sentence_inc)
    except Exception as e:
        print(f"[AI_POSLECH] session stats bump failed: {e}", flush=True)


def _get_history():
    history = session.get(SESSION_KEY)
    if not isinstance(history, list):
        history = []
        session[SESSION_KEY] = history
    return history


def _append_message(role: str, content: str):
    history = _get_history()
    history.append({"role": role, "content": content})
    # zapiš zpět (kvůli bezpečnosti u některých session backendů)
    session[SESSION_KEY] = history


@ai_poslech_bp.before_request
def ensure_session():
    # Ujisti se, že existuje user_id pro hlavičku/stats, ale bez pádu, pokud DB není.
    session.setdefault('user_id', random.randint(100000, 999999))


@ai_poslech_bp.route('/ai-poslech', methods=['GET'])
def page():
    # Neposíláme historii serverem, vše dotahuje front-end z session až interakcí
    return render_template('AI_poslech/ai_poslech.html')


@ai_poslech_bp.route('/ai-poslech/reset', methods=['POST'])
def reset():
    session.pop(SESSION_KEY, None)
    # Vyčisti i akumulátor minut a streakové pomocné klíče a lokální stats
    for k in ('ai_poslech_ms_acc', 'ai_poslech_spoken_ms_today', 'ai_poslech_streak_awarded_date', _SESSION_TOTAL_MS,
              _SESSION_SENTENCES):
        try:
            session.pop(k, None)
        except Exception:
            pass
    return jsonify({"ok": True})


@ai_poslech_bp.route('/ai-poslech/stats', methods=['GET'])
def stats_state():
    total_ms = int(session.get(_SESSION_TOTAL_MS) or 0)
    sentence_count = int(session.get(_SESSION_SENTENCES) or 0)
    thr = int(STREAK_TALK_MS)
    remaining = max(0, thr - total_ms)
    return jsonify({
        "total_spoken_ms": total_ms,
        "sentence_count": sentence_count,
        "streak_threshold_ms": thr,
        "remaining_ms": remaining
    })


@ai_poslech_bp.route('/ai-poslech/message', methods=['POST'])
def message():
    if not AI_API_KEY:
        return jsonify({"error": "API klíč není nastaven. Zkontroluj .env (AI_API_KEY)."}), 500

    start_time = time.perf_counter()
    data = request.get_json(silent=True) or {}
    user_text = (data.get('text') or '').strip()
    gender = (data.get('gender') or 'male').lower()
    # Délka mluvení v ms z frontendu; sanity
    spoken_ms = data.get('spoken_ms')
    try:
        spoken_ms = int(spoken_ms)
    except Exception:
        spoken_ms = 0
    if spoken_ms < 0:
        spoken_ms = 0
    if spoken_ms > 60 * 1000:  # limit 60s na jeden úsek, proti zneužití
        spoken_ms = 60 * 1000

    if gender not in ('male', 'female'):
        gender = 'male'
    if not user_text:
        return jsonify({"error": "Prázdná zpráva"}), 400

    # Lokální moderace
    if is_czech(user_text):
        reply = random.choice([
            "[Calm] Sorry, I don't understand. Please speak in English.",
            "[Calm] I can't understand Czech, could you try speaking English?",
            "[Calm] Please speak in English, I don't understand Czech.",
            "[Calm] I'm not fluent in Czech, could you switch to English when speaking?",
            "[Calm] English, please. I can't follow Czech."
        ])
        _append_message('user', user_text)
        _append_message('assistant', reply)
        # --- Session stats ---
        _bump_session_stats(spoken_ms, sentence_inc=1)
        # --- Statistika času učení (sekundy) ---
        if add_learning_time and 'user_id' in session and spoken_ms:
            try:
                secs = max(0, int(round(spoken_ms / 1000)))
                if set_first_activity_if_needed:
                    set_first_activity_if_needed(session['user_id'])
                add_learning_time(session['user_id'], secs)
            except Exception as e:
                print(f"[AI_POSLECH MESSAGE] DB stats error: {e}", flush=True)
        # --- AI_poslech_seconds ---
        _persist_ai_poslech_seconds(spoken_ms)
        # --- Ihned zkusit achievementy (fallback, pokud by _persist selhal) ---
        if check_and_award_achievements and 'user_id' in session:
            try:
                check_and_award_achievements(session['user_id'])
            except Exception as _e:
                print(f"[AI_POSLECH MESSAGE] award check fail: {_e}", flush=True)
        dur = (time.perf_counter() - start_time) * 1000
        print(f"[AI_POSLECH MESSAGE] moderation(czech) len={len(user_text)}ms={dur:.1f}", flush=True)
        # Přidej stats do odpovědi pro rychlou aktualizaci UI
        return jsonify({
            "reply": reply,
            "stats": {
                "total_spoken_ms": int(session.get(_SESSION_TOTAL_MS) or 0),
                "sentence_count": int(session.get(_SESSION_SENTENCES) or 0),
                "streak_threshold_ms": int(STREAK_TALK_MS),
                "remaining_ms": max(0, int(STREAK_TALK_MS) - int(session.get(_SESSION_TOTAL_MS) or 0))
            }
        })

    if contains_bad_word(user_text):
        reply = random.choice([
            "[Firm] That's not appropriate. Please keep it respectful.",
            "[Firm] Please watch your language. This is a friendly space.",
            "[Firm] Keep it clean, please.",
            "[Firm] Avoid using such language here.",
            "[Firm] That language isn't welcome here."
        ])
        _append_message('user', user_text)
        _append_message('assistant', reply)
        # --- Session stats ---
        _bump_session_stats(spoken_ms, sentence_inc=1)
        # --- Statistika času učení (sekundy) ---
        if add_learning_time and 'user_id' in session and spoken_ms:
            try:
                secs = max(0, int(round(spoken_ms / 1000)))
                if set_first_activity_if_needed:
                    set_first_activity_if_needed(session['user_id'])
                add_learning_time(session['user_id'], secs)
            except Exception as e:
                print(f"[AI_POSLECH MESSAGE] DB stats error: {e}", flush=True)
        # --- AI_poslech_seconds ---
        _persist_ai_poslech_seconds(spoken_ms)
        # --- Ihned zkusit achievementy (fallback, pokud by _persist selhal) ---
        if check_and_award_achievements and 'user_id' in session:
            try:
                check_and_award_achievements(session['user_id'])
            except Exception as _e:
                print(f"[AI_POSLECH MESSAGE] award check fail: {_e}", flush=True)
        dur = (time.perf_counter() - start_time) * 1000
        print(f"[AI_POSLECH MESSAGE] moderation(badword) len={len(user_text)}ms={dur:.1f}", flush=True)
        return jsonify({
            "reply": reply,
            "stats": {
                "total_spoken_ms": int(session.get(_SESSION_TOTAL_MS) or 0),
                "sentence_count": int(session.get(_SESSION_SENTENCES) or 0),
                "streak_threshold_ms": int(STREAK_TALK_MS),
                "remaining_ms": max(0, int(STREAK_TALK_MS) - int(session.get(_SESSION_TOTAL_MS) or 0))
            }
        })

    # Sestavení zpráv pro API: system persona + system pravidla + ořezaná historie + aktuální dotaz
    persona = PERSONA_FEMALE if gender == 'female' else PERSONA_MALE
    history_full = _get_history()
    if len(history_full) > HISTORY_LIMIT:
        trimmed_history = history_full[-HISTORY_LIMIT:]
    else:
        trimmed_history = history_full

    messages = [
        {"role": "system", "content": persona},
        {"role": "system", "content": SYSTEM_PROMPT},
        *trimmed_history,
        {"role": "user", "content": user_text}
    ]

    url = "https://api.aimlapi.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": messages,
        "temperature": 0.9,
        "max_tokens": 160
    }

    # Log velikosti payloadu a historie pro diagnostiku
    try:
        payload_chars = len(json.dumps(payload))
    except Exception:
        payload_chars = -1
    print(
        f"[AI_POSLECH MESSAGE] PRE_REQUEST len_user={len(user_text)} hist_full={len(history_full)} hist_used={len(trimmed_history)} payload_chars={payload_chars}",
        flush=True
    )

    try:
        api_start = time.perf_counter()
        resp = HTTP_SESSION.post(url, headers=headers, json=payload, timeout=15)
        api_dur = (time.perf_counter() - api_start) * 1000
        if resp.status_code == 403:
            print(f"[AI_POSLECH MESSAGE] 403 len={len(user_text)} api_ms={api_dur:.1f}", flush=True)
            return jsonify({"error": "Majitel nemá kredity nebo došly tokeny. Zkus to později."}), 403
        resp.raise_for_status()
        data = resp.json()
        ai_reply = data['choices'][0]['message']['content']
    except Exception as e:
        dur_all = (time.perf_counter() - start_time) * 1000
        print(f"[AI_POSLECH MESSAGE] ERROR len={len(user_text)} total_ms={dur_all:.1f} err={e}", flush=True)
        return jsonify({"error": f"Chyba volání AI: {e}"}), 500

    _append_message('user', user_text)
    _append_message('assistant', ai_reply)

    # --- Session stats ---
    _bump_session_stats(spoken_ms, sentence_inc=1)

    total_dur = (time.perf_counter() - start_time) * 1000

    # --- Statistika času učení (sekundy) ---
    if add_learning_time and 'user_id' in session and spoken_ms:
        try:
            secs = max(0, int(round(spoken_ms / 1000)))
            if set_first_activity_if_needed:
                set_first_activity_if_needed(session['user_id'])
            add_learning_time(session['user_id'], secs)
        except Exception as e:
            print(f"[AI_POSLECH MESSAGE] DB stats error: {e}", flush=True)
    # --- AI_poslech_seconds ---
    _persist_ai_poslech_seconds(spoken_ms)
    # --- Ihned zkusit achievementy (fallback, pokud by _persist selhal) ---
    if check_and_award_achievements and 'user_id' in session:
        try:
            check_and_award_achievements(session['user_id'])
        except Exception as _e:
            print(f"[AI_POSLECH MESSAGE] award check fail: {_e}", flush=True)

    # --- XP + Streak ---
    xp_awarded = 0
    new_xp = None
    new_level = None
    new_achievements = []
    streak_info = None
    xp_error = None
    if 'user_id' in session and add_xp_to_user:
        try:
            xp_awarded = 10  # konzistentně s roleplaying/A1
            xp_result = add_xp_to_user(session['user_id'], xp_awarded)
            if isinstance(xp_result, dict):
                new_xp = xp_result.get('xp')
                new_level = xp_result.get('level')
                new_achievements = xp_result.get('new_achievements', [])
        except Exception as e:
            xp_error = str(e)
            print(f"[AI_POSLECH MESSAGE] XP ERROR user_id={session.get('user_id')} err={e}", flush=True)

    # Streak po 2.5 min mluvení – lehký akumulátor v session pro dnešek (DB drží jen celkový čas)
    try:
        today = date.today().isoformat()
        acc_key = 'ai_poslech_spoken_ms_today'
        award_key = 'ai_poslech_streak_awarded_date'
        if session.get(award_key) != today:
            session[acc_key] = int(session.get(acc_key) or 0) + int(spoken_ms or 0)
            if session[acc_key] >= STREAK_TALK_MS and update_user_streak and 'user_id' in session:
                try:
                    streak_info = update_user_streak(session['user_id'])
                    session[award_key] = today
                except Exception as e:
                    print(f"[AI_POSLECH MESSAGE] STREAK ERROR user_id={session.get('user_id')} err={e}", flush=True)
    except Exception as e:
        print(f"[AI_POSLECH MESSAGE] STREAK SESSION ACC ERROR: {e}", flush=True)

    warn = ''
    if api_dur > 8000:
        warn = ' SLOW_API'
    print(
        f"[AI_POSLECH MESSAGE] OK len={len(user_text)} api_ms={api_dur:.1f} total_ms={total_dur:.1f} hist_full={len(history_full)} hist_used={len(trimmed_history)}{warn}",
        flush=True
    )
    return jsonify({
        "reply": ai_reply,
        "xp_awarded": xp_awarded,
        "new_xp": new_xp,
        "new_level": new_level,
        "new_achievements": new_achievements,
        "streak_info": streak_info,
        "xp_error": xp_error,
        "stats": {
            "total_spoken_ms": int(session.get(_SESSION_TOTAL_MS) or 0),
            "sentence_count": int(session.get(_SESSION_SENTENCES) or 0),
            "streak_threshold_ms": int(STREAK_TALK_MS),
            "remaining_ms": max(0, int(STREAK_TALK_MS) - int(session.get(_SESSION_TOTAL_MS) or 0))
        }
    })


# Jednoduchá thread-safe LRU cache pro TTS výsledky (paměť, životnost)
_TTS_CACHE_LOCK = threading.Lock()
_TTS_CACHE = OrderedDict()  # key -> {audio: bytes, ctype: str, fname: str, ts: float}
_TTS_CACHE_MAX = 40
_TTS_CACHE_TTL = 60 * 15  # 15 minut


def _tts_cache_key(text: str, gender: str) -> str:
    h = hashlib.sha256((gender + '|' + text).encode('utf-8')).hexdigest()[:32]
    return f"{gender}:{h}"


def _tts_cache_get(key: str):
    with _TTS_CACHE_LOCK:
        item = _TTS_CACHE.get(key)
        if not item:
            return None
        if time.time() - item['ts'] > _TTS_CACHE_TTL:
            # Expirace
            _TTS_CACHE.pop(key, None)
            return None
        # LRU promote
        _TTS_CACHE.move_to_end(key)
        return item


def _tts_cache_set(key: str, audio: bytes, ctype: str, fname: str):
    with _TTS_CACHE_LOCK:
        _TTS_CACHE[key] = {"audio": audio, "ctype": ctype, "fname": fname, "ts": time.time()}
        _TTS_CACHE.move_to_end(key)
        while len(_TTS_CACHE) > _TTS_CACHE_MAX:
            _TTS_CACHE.popitem(last=False)


@ai_poslech_bp.route('/ai-poslech/tts', methods=['POST'])
def tts():
    """Server-side TTS (primárně AIMLAPI, fallback gTTS). Vstup: JSON {text, gender}. Výstup: audio/*."""
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    gender = (data.get('gender') or 'male').lower()
    if not text:
        return jsonify({"error": "Empty text"}), 400

    text = re.sub(r"\s+", " ", text)
    if len(text) > 600:
        text = text[:600] + "..."

    start_time = time.perf_counter()
    cache_key = _tts_cache_key(text, gender)
    cached = _tts_cache_get(cache_key)
    if cached:
        buf = io.BytesIO(cached['audio'])
        buf.seek(0)
        resp = send_file(buf, mimetype=cached['ctype'], as_attachment=False, download_name=cached['fname'])
        resp.headers['X-TTS-Cache'] = 'HIT'
        dur = (time.perf_counter() - start_time) * 1000
        print(f"[AI_POSLECH TTS] CACHE_HIT gender={gender} len={len(text)} total_ms={dur:.1f}", flush=True)
        return resp

    primary_error = None

    if AI_API_KEY:
        try:
            model = '#g1_aura-asteria-en' if gender == 'female' else '#g1_aura-zeus-en'
            url = "https://api.aimlapi.com/v1/tts"
            headers = {"Authorization": f"Bearer {AI_API_KEY}"}
            payload = {"model": model, "text": text}
            api_start = time.perf_counter()
            resp = HTTP_SESSION.post(url, headers=headers, json=payload, timeout=25)
            api_ms = (time.perf_counter() - api_start) * 1000
            if resp.ok and resp.content and len(resp.content) > 50:
                audio_bytes = resp.content
                ctype = resp.headers.get('Content-Type', 'audio/wav')
                fname = 'speech.wav' if 'wav' in ctype.lower() else 'speech.mp3'
                _tts_cache_set(cache_key, audio_bytes, ctype, fname)
                buf = io.BytesIO(audio_bytes)
                buf.seek(0)
                flask_resp = send_file(buf, mimetype=ctype, as_attachment=False, download_name=fname)
                flask_resp.headers['X-TTS-Cache'] = 'MISS'
                flask_resp.headers['X-TTS-Source'] = 'primary'
                flask_resp.headers['X-TTS-TimeMs'] = f"{(time.perf_counter() - start_time) * 1000:.1f}"
                print(
                    f"[AI_POSLECH TTS] PRIMARY_OK gender={gender} len={len(text)} api_ms={api_ms:.1f} total_ms={(time.perf_counter() - start_time) * 1000:.1f}",
                    flush=True)
                return flask_resp
            else:
                primary_error = f"AIMLAPI status {resp.status_code}: {resp.text[:120]}"
                print(
                    f"[AI_POSLECH TTS] PRIMARY_FAIL gender={gender} len={len(text)} api_ms={api_ms:.1f} err={primary_error}",
                    flush=True)
        except Exception as e:
            primary_error = f"AIMLAPI exception: {e}"
            print(f"[AI_POSLECH TTS] PRIMARY_EXC gender={gender} len={len(text)} err={e}", flush=True)
    else:
        primary_error = "Missing AI_API_KEY"
        print(f"[AI_POSLECH TTS] PRIMARY_SKIP_NO_KEY gender={gender} len={len(text)}", flush=True)

    if _GTTS_AVAILABLE:
        try:
            api_start = time.perf_counter()
            tld = 'co.uk' if gender == 'female' else 'com'
            tts_engine = gTTS(text=text, lang='en', slow=False, tld=tld)
            buf = io.BytesIO()
            tts_engine.write_to_fp(buf)
            gen_ms = (time.perf_counter() - api_start) * 1000
            audio_bytes = buf.getvalue()
            _tts_cache_set(cache_key, audio_bytes, 'audio/mpeg', 'speech.mp3')
            buf.seek(0)
            flask_resp = send_file(buf, mimetype='audio/mpeg', as_attachment=False, download_name='speech.mp3')
            flask_resp.headers['X-TTS-Cache'] = 'MISS'
            flask_resp.headers['X-TTS-Source'] = 'gtts'
            flask_resp.headers['X-TTS-Primary-Error'] = primary_error or ''
            flask_resp.headers['X-TTS-TimeMs'] = f"{(time.perf_counter() - start_time) * 1000:.1f}"
            print(
                f"[AI_POSLECH TTS] FALLBACK_GTTS_OK gender={gender} len={len(text)} gen_ms={gen_ms:.1f} total_ms={(time.perf_counter() - start_time) * 1000:.1f} primary_err={primary_error}",
                flush=True)
            return flask_resp
        except Exception as e:
            total_ms = (time.perf_counter() - start_time) * 1000
            print(
                f"[AI_POSLECH TTS] FALLBACK_GTTS_FAIL gender={gender} len={len(text)} total_ms={total_ms:.1f} primary_err={primary_error} gtts_err={e}",
                flush=True)
            return jsonify(
                {"error": "Both TTS engines failed", "primary_error": primary_error, "gtts_error": str(e)}), 500

    total_ms = (time.perf_counter() - start_time) * 1000
    print(
        f"[AI_POSLECH TTS] UNAVAILABLE gender={gender} len={len(text)} total_ms={total_ms:.1f} primary_err={primary_error} gtts_module={_GTTS_AVAILABLE}",
        flush=True)
    return jsonify({"error": "TTS unavailable", "primary_error": primary_error, "gtts": "module missing"}), 503
