from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from langdetect import detect, LangDetectException
from db import get_db_connection
import re
from bs4 import BeautifulSoup
import os
import requests

# --- Přidáno: importy pro XP, streak a statistiky ---
from xp import add_xp_to_user
from streak import update_user_streak
from user_stats import update_user_stats

psani_bp = Blueprint('psani', __name__)
# Reuse the AI API key as in ai.py
AI_API_KEY = os.getenv("AI_API_KEY")

CESKE_ZNAKY = "ěščřžýáíéůúňďťó"


def ai_check_english_text(text: str) -> dict | None:
    """Použije stejné AI API jako v ai.py a vrátí vyhodnocení psaného textu.
    Výstup: { correct: bool, feedback: str }
    """
    try:
        if not AI_API_KEY:
            return None
        prompt_system = (
            "You are an English writing checker for students. Given the student's text, "
            "return a JSON object with two fields: 'correct' (true if the text is overall grammatically acceptable for casual writing, otherwise false) "
            "and 'feedback' (a very short one-sentence suggestion in English, under one hundred and fifty characters). "
            "Do not include markdown, quotes, backticks, or any extra commentary. Return ONLY valid JSON."
        )
        url = "https://api.aimlapi.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
        data = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": text.strip()}
            ],
            "temperature": 0.2,
            "max_tokens": 120
        }
        resp = requests.post(url, headers=headers, json=data, timeout=20)
        if resp.status_code not in (200, 201):
            return None
        content = resp.json().get('choices', [{}])[0].get('message', {}).get('content', '').strip()
        # Pokus o parse JSONu z modelu
        import json
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and 'correct' in parsed and 'feedback' in parsed:
                return {"correct": bool(parsed.get('correct')), "feedback": str(parsed.get('feedback'))}
        except Exception:
            pass
        # Fallback: když to není JSON, tak hrubé heuristické vyhodnocení
        lower = content.lower()
        is_ok = any(k in lower for k in ["ok", "looks good", "no issues", "fine"]) and not any(k in lower for k in ["error", "incorrect", "wrong", "issue"])
        return {"correct": is_ok, "feedback": content[:150]}
    except Exception:
        return None


def uloz_psani_do_db(user_id, obsah, public=False):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO psani (user_id, obsah, public) VALUES (%s, %s, %s)",
        (user_id, obsah, public)
    )
    conn.commit()
    cur.close()
    conn.close()


def nacti_psani_uzivatele(user_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, obsah, created_at, public FROM psani WHERE user_id = %s ORDER BY created_at DESC",
        (user_id,)
    )
    psani = cur.fetchall()
    cur.close()
    conn.close()
    return psani


def smaz_psani(pribeh_id, user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM psani WHERE id = %s AND user_id = %s", (pribeh_id, user_id))
    conn.commit()
    cur.close()
    conn.close()


def uprav_psani(pribeh_id, user_id, obsah, public):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE psani SET obsah = %s, public = %s WHERE id = %s AND user_id = %s",
        (obsah, public, pribeh_id, user_id)
    )
    conn.commit()
    cur.close()
    conn.close()


def nacti_jedno_psani(pribeh_id, user_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, obsah, public FROM psani WHERE id = %s AND user_id = %s",
        (pribeh_id, user_id)
    )
    pribeh = cur.fetchone()
    cur.close()
    conn.close()
    return pribeh


@psani_bp.route('/psani/verejne')
def verejne_psani():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT p.obsah, p.created_at, 
               CONCAT(u.first_name, ' ', u.last_name) AS user_name, 
               u.profile_pic 
        FROM psani p
        JOIN users u ON p.user_id = u.id
        WHERE p.public = 1 
        ORDER BY p.created_at DESC
    """)
    verejna_psani = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('psani/verejne_psani.html', verejna_psani=verejna_psani)


@psani_bp.route('/psani', methods=['GET', 'POST'])
def psani_page():
    import time
    obsah = ""
    user_id = session.get('user_id')
    if not user_id:
        flash("Musíš se přihlásit, jinak to nejde", "danger")
        return redirect(url_for('auth.login'))

    # --- Měření času vstupu na stránku ---
    if request.method == 'GET':
        session['psani_training_start'] = time.time()
        # Nastavíme first_activity pokud ještě není
        update_user_stats(user_id, set_first_activity=True)

    if request.method == 'POST':
        obsah = request.form.get('obsah', '')
        public = bool(request.form.get('public'))
        if re.search(f"[{CESKE_ZNAKY}]", obsah, re.IGNORECASE):
            flash("Text nesmí obsahovat české znaky s diakritikou. Piš pouze anglicky.", "danger")
        else:
            try:
                plain_text = BeautifulSoup(obsah, "html.parser").get_text()
                jazyk = detect(plain_text)
                if jazyk != 'en':
                    flash("Text musí být napsán v angličtině.", "danger")
                else:
                    # AI analýza po větách, zůstaneme na stránce a nic neukládáme
                    ai_feedback = None
                    if AI_API_KEY and plain_text.strip():
                        try:
                            url = "https://api.aimlapi.com/v1/chat/completions"
                            headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
                            system = (
                                "You are an English writing assistant. Split the student's text into sentences. "
                                "For each sentence, return an array item as a JSON object: {sentence, ok, issue, suggestion}. "
                                "- sentence: the original sentence\n- ok: true if acceptable grammar and usage for casual writing, else false\n"
                                "- issue: if ok=false, a very short explanation\n- suggestion: if ok=false, a short corrected version\n"
                                "Return ONLY valid JSON array, no markdown."
                            )
                            data = {
                                "model": "gpt-4o-mini",
                                "messages": [
                                    {"role": "system", "content": system},
                                    {"role": "user", "content": plain_text}
                                ],
                                "temperature": 0.2,
                                "max_tokens": 400
                            }
                            r = requests.post(url, headers=headers, json=data, timeout=25)
                            if r.status_code in (200, 201):
                                content = r.json().get('choices', [{}])[0].get('message', {}).get('content', '').strip()
                                import json
                                try:
                                    parsed = json.loads(content)
                                    if isinstance(parsed, list):
                                        # normalizace položek
                                        norm = []
                                        for it in parsed:
                                            if not isinstance(it, dict):
                                                continue
                                            norm.append({
                                                'sentence': str(it.get('sentence', '')).strip(),
                                                'ok': bool(it.get('ok', False)),
                                                'issue': str(it.get('issue', '')).strip(),
                                                'suggestion': str(it.get('suggestion', '')).strip(),
                                            })
                                        ai_feedback = norm
                                except Exception:
                                    pass
                        except Exception as e:
                            print("AI psani analysis error:", e)
                    if not ai_feedback:
                        flash("AI analýza dočasně nedostupná.", "warning")
                    # Neukládáme, pouze zobrazíme výsledek a ponecháme obsah
                    vsechna_psani = nacti_psani_uzivatele(user_id)
                    return render_template('psani/psani.html', obsah=obsah, vsechna_psani=vsechna_psani, ai_feedback=ai_feedback)
            except LangDetectException:
                flash("Text je příliš krátký nebo nečitelný pro detekci jazyka.", "danger")
    vsechna_psani = nacti_psani_uzivatele(user_id)
    return render_template('psani/psani.html', obsah=obsah, vsechna_psani=vsechna_psani)


@psani_bp.route('/psani/delete/<int:pribeh_id>', methods=['POST'])
def smazat_psani(pribeh_id):
    user_id = session.get('user_id')
    if not user_id:
        flash("Musíš být přihlášený.", "danger")
        return redirect(url_for('auth.login'))
    smaz_psani(pribeh_id, user_id)
    flash("Příběh byl smazán.", "success")
    return redirect(url_for('psani.psani_page'))


@psani_bp.route('/psani/edit/<int:pribeh_id>', methods=['GET', 'POST'])
def upravit_psani(pribeh_id):
    import time
    user_id = session.get('user_id')
    if not user_id:
        flash("Musíš být přihlášený.", "danger")
        return redirect(url_for('auth.login'))
    pribeh = nacti_jedno_psani(pribeh_id, user_id)
    if not pribeh:
        flash("Příběh nenalezen.", "danger")
        return redirect(url_for('psani.psani_page'))
    # --- Měření času vstupu na stránku při editaci ---
    if request.method == 'GET':
        session['psani_training_start'] = time.time()
        update_user_stats(user_id, set_first_activity=True)
    if request.method == 'POST':
        obsah = request.form.get('obsah', '')
        public = bool(request.form.get('public'))
        if re.search(f"[{CESKE_ZNAKY}]", obsah, re.IGNORECASE):
            flash("Text nesmí obsahovat české znaky s diakritikou. Piš pouze anglicky.", "danger")
        else:
            try:
                plain_text = BeautifulSoup(obsah, "html.parser").get_text()
                jazyk = detect(plain_text)
                if jazyk != 'en':
                    flash("Text musí být napsán v angličtině.", "danger")
                else:
                    uprav_psani(pribeh_id, user_id, obsah, public)
                    # --- STATISTIKY, XP, STREAK ---
                    word_count = len(plain_text.split())
                    learning_time = None
                    if session.get('psani_training_start'):
                        try:
                            start = float(session.pop('psani_training_start', None))
                            duration = max(1, int(time.time() - start))
                            learning_time = duration
                        except Exception as e:
                            print("Chyba při ukládání času tréninku:", e)
                    try:
                        update_user_stats(
                            user_id,
                            psani_words=word_count,
                            lesson_done=True,
                            learning_time=learning_time,
                            set_first_activity=True
                        )
                    except Exception as e:
                        print("Chyba při ukládání statistik psaní:", e)
                    xp_awarded = 2
                    try:
                        add_xp_to_user(user_id, xp_awarded)
                        update_user_streak(user_id)
                    except Exception as e:
                        print("XP/STREAK ERROR:", e)
                    flash(f"Příběh byl upraven. (+{word_count} slov, +{xp_awarded} XP)", "success")
                    return redirect(url_for('psani.psani_page'))
            except LangDetectException:
                flash("Text je příliš krátký nebo nečitelný pro detekci jazyka.", "danger")
    return render_template('psani/edit_psani.html', pribeh=pribeh)
