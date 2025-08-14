from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from langdetect import detect, LangDetectException
from db import get_db_connection
import re
from bs4 import BeautifulSoup

# --- Přidáno: importy pro XP, streak a statistiky ---
from xp import add_xp_to_user
from streak import update_user_streak
from user_stats import update_user_stats

psani_bp = Blueprint('psani', __name__)

CESKE_ZNAKY = "ěščřžýáíéůúňďťó"


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
        SELECT p.obsah, p.created_at, u.first_name, u.profile_pic 
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
                    uloz_psani_do_db(user_id, obsah, public)
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
                    xp_awarded = 5
                    try:
                        add_xp_to_user(user_id, xp_awarded)
                        update_user_streak(user_id)
                    except Exception as e:
                        print("XP/STREAK ERROR:", e)
                    flash(f"Text byl úspěšně uložen! ({word_count} slov, +{xp_awarded} XP)", "success")
                    return redirect(url_for('psani.psani_page'))
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
