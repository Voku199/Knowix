from flask import Blueprint, render_template, request, session, redirect, url_for
import os
import json
import time
import re
import random
import requests
from dotenv import load_dotenv
import deepl
from xp import add_xp_to_user
from streak import update_user_streak
from user_stats import update_user_stats

# Blueprint
ai_gramatika_bp = Blueprint('ai_gramatika_bp', __name__)

# Načti env (hlavní app už volá load_dotenv, ale nevadí znovu)
load_dotenv(dotenv_path=".env")
AI_API_KEY = os.getenv("AI_API_KEY")
AIML_URL = "https://api.aimlapi.com/v1/chat/completions"

# Nabídka náročnějších témat
SUGGESTED_TOPICS = [
    "Present Perfect vs Past Simple",
    "Articles: a/an/the/zero",
    "Third person -s",
    "Prepositions: at/in/on",
    "Conditionals: zero/first/second",
    "Modal verbs (should, must, have to)",
    "Passive voice",
    "Reported speech",
    "Countable vs uncountable",
]


def _get_user_id():
    # Jednoduchý helper bez závislosti na ai.get_or_create_user
    if 'user_id' not in session:
        session['user_id'] = random.randint(100000, 999999)
    return session['user_id']


# --- Normalizace vět pro porovnání ---
_WORD_APOS = {"’": "'", "`": "'"}


def _normalize_sentence(s: str) -> str:
    if not s:
        return ""
    t = s.strip()
    # sjednotit apostrofy
    for k, v in _WORD_APOS.items():
        t = t.replace(k, v)
    # odstranit okolní uvozovky
    t = t.strip('"'"' ")
    # zmenšit písmena kromě I na začátku věty neřešíme – pro srovnání vše lower-case
    t = t.lower()
    # odstranit závěrečnou tečku/otazník/vykřičník
    t = re.sub(r"[.!?]+$", "", t)
    # zkolabovat whitespace
    t = re.sub(r"\s+", " ", t)
    return t


# --- Adaptivní profil v session ---
PROFILE_KEY = 'ai_gram_profile'
STATE_KEY = 'ai_gram_current'


def _get_profile():
    return session.get(PROFILE_KEY, {})


def _bump_profile(tags, good: bool):
    prof = _get_profile()
    for tag in tags or []:
        try:
            if good:
                prof[tag] = max(0, int(prof.get(tag, 0)) - 1)
            else:
                prof[tag] = int(prof.get(tag, 0)) + 1
        except Exception:
            prof[tag] = 0 if good else 1
    session[PROFILE_KEY] = prof
    session.modified = True


# --- AI volání ---

def _call_aiml(messages, temperature=0.7, max_tokens=400):
    if not AI_API_KEY:
        raise RuntimeError("API key missing")
    headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
    data = {"model": "gpt-4o-mini", "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    resp = requests.post(AIML_URL, headers=headers, json=data, timeout=30)
    resp.raise_for_status()
    return resp.json()['choices'][0]['message']['content']


def _generate_items(topic: str, count: int, profile: dict):
    """Vygeneruje položky: [{incorrect, correct, explanation, tags}]"""
    count = max(5, min(10, int(count or 5)))
    # seřadit top slabiny pro prompt
    weak_tags = sorted(profile.items(), key=lambda kv: kv[1], reverse=True)[:3]
    weak_hint = ", ".join([f"{t}:{v}" for t, v in weak_tags]) if weak_tags else "none"

    sys = (
        "You are an English grammar tutor. Generate short practice items with typical mistakes for a given topic. "
        "Return strict JSON only: {\"items\":[{\"incorrect\":str,\"correct\":str,\"explanation\":str,\"tags\":[str,...]}...]} without any extra text. "
        "Sentences should be simple and student-level."
    )
    usr = (
        f"Topic: {topic}. Number of items: {count}. Focus more on these weak aspects if relevant: {weak_hint}. "
        "Keep each explanation under 120 characters."
    )

    try:
        content = _call_aiml([
            {"role": "system", "content": sys},
            {"role": "user", "content": usr}
        ], temperature=0.8, max_tokens=800)
        data = json.loads(content)
        items = data.get('items') or []
    except Exception:
        # Fallback: prosté řádky bez JSON
        items = []

    # Sanitizace a fallback když JSON selže
    norm_items = []
    for it in items:
        inc = str(it.get('incorrect', '')).strip()
        cor = str(it.get('correct', '')).strip()
        exp = str(it.get('explanation', '')).strip()
        tags = it.get('tags') or []
        if inc and cor:
            norm_items.append({"incorrect": inc, "correct": cor, "explanation": exp, "tags": tags})
    # Pokud je málo, vytvoř pár placeholderů
    while len(norm_items) < count:
        i = len(norm_items) + 1
        norm_items.append({
            "incorrect": f"I have saw him yesterday {i}",
            "correct": "I saw him yesterday",
            "explanation": "Use past simple with yesterday, not present perfect.",
            "tags": ["past simple vs present perfect"]
        })
    return norm_items[:count]


_translator = None


def _get_translator():
    global _translator
    if _translator is not None:
        return _translator
    try:
        key = os.getenv('DEEPL_API_KEY')
        if not key:
            return None
        _translator = deepl.Translator(key)
        return _translator
    except Exception:
        return None


def _translate_cs(text: str) -> str | None:
    t = (text or '').strip()
    if not t:
        return None
    translator = _get_translator()
    if not translator:
        return None
    try:
        res = translator.translate_text(t, target_lang='CS')
        return res.text
    except Exception:
        return None


# --- Routy ---
@ai_gramatika_bp.route('/ai-gramatika', methods=['GET'])
def ai_gramatika_home():
    _get_user_id()
    state = session.get(STATE_KEY)
    return render_template('AI_gramatika/AI_gramatika.html',
                           suggested_topics=SUGGESTED_TOPICS,
                           state=state,
                           results=None,
                           xp_gain=None,
                           passed=None)


@ai_gramatika_bp.route('/ai-gramatika/start', methods=['POST'])
def ai_gramatika_start():
    user_id = _get_user_id()
    topic = (request.form.get('topic_custom') or request.form.get('topic') or '').strip()
    if not topic:
        topic = random.choice(SUGGESTED_TOPICS)
    try:
        count = int(request.form.get('count') or 5)
    except Exception:
        count = 5

    explain_cs = bool(request.form.get('explain_cs'))

    profile = _get_profile()

    try:
        items = _generate_items(topic, count, profile)
    except Exception as e:
        # Fallback bez AI klíče
        items = _generate_items(topic, count, profile={})

    # Ulož stav do session
    session[STATE_KEY] = {
        'topic': topic,
        'count': count,
        'items': items,
        'start_ts': int(time.time()),
        'explain_cs': explain_cs
    }
    session.modified = True

    return redirect(url_for('ai_gramatika_bp.ai_gramatika_home'))


@ai_gramatika_bp.route('/ai-gramatika/submit', methods=['POST'])
def ai_gramatika_submit():
    user_id = _get_user_id()
    state = session.get(STATE_KEY)
    if not state:
        return redirect(url_for('ai_gramatika_bp.ai_gramatika_home'))

    items = state.get('items', [])
    count = int(state.get('count', 5))

    results = []
    correct_total = 0
    explain_cs_pref = bool(state.get('explain_cs'))
    for idx, it in enumerate(items):
        user_ans = request.form.get(f'answer_{idx}', '').strip()
        gold = it.get('correct', '')
        ok = _normalize_sentence(user_ans) == _normalize_sentence(gold)
        if ok:
            correct_total += 1
        # uprav adaptivní profil
        _bump_profile(it.get('tags'), good=ok)
        exp_en = it.get('explanation') or ''
        exp_cs = _translate_cs(exp_en) if (exp_en and explain_cs_pref) else None
        results.append({
            'incorrect': it.get('incorrect'),
            'user_answer': user_ans,
            'expected': gold,
            'ok': ok,
            'explanation': exp_en,
            'explanation_cs': exp_cs
        })

    # XP a streak
    base_xp_per_correct = 5
    boost = 1.0 + max(0, count - 5) * 0.1  # 5->1.0, 10->1.5
    xp_gain = int(round(correct_total * base_xp_per_correct * boost))
    if xp_gain > 0:
        try:
            add_xp_to_user(user_id, xp_gain, reason='ai_gramatika')
        except Exception:
            pass

    # user_stats
    try:
        update_user_stats(
            user_id,
            correct=correct_total,
            wrong=len(items) - correct_total,
            lesson_done=(correct_total * 2 >= len(items)),
            ai_gram_cor=correct_total,
            ai_gram_wr=(len(items) - correct_total)
        )
    except Exception:
        pass

    passed = (correct_total * 2 >= len(items))
    if passed:
        try:
            update_user_streak(user_id)
        except Exception:
            pass

    # Po odeslání výsledků necháme v session poslední state a navíc results, aby šly vypsat
    session[STATE_KEY]['results'] = results
    session[STATE_KEY]['xp_gain'] = xp_gain
    session[STATE_KEY]['passed'] = passed
    session.modified = True

    return redirect(url_for('ai_gramatika_bp.ai_gramatika_home'))
