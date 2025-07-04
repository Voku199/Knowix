from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image
import os
import mysql.connector
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
import string
import time
import random
from xp import get_user_achievements, get_all_achievements, get_top_users, get_user_xp_and_level
from db import get_db_connection

auth_bp = Blueprint('auth', __name__)
user_settings = {}

LEVEL_NAMES = [
    "Začátečník", "Učeň", "Student", "Pokročilý", "Expert", "Mistr", "Legenda"
]


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


@auth_bp.context_processor
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


@auth_bp.errorhandler(502)
@auth_bp.errorhandler(503)
@auth_bp.errorhandler(504)
@auth_bp.errorhandler(500)
@auth_bp.errorhandler(404)
@auth_bp.errorhandler(Exception)
def server_error(e):
    # vrátí stránku error.html s informací o výpadku
    return render_template('error.html', error_code=e.code), e.code


# Pomocné funkce
# def get_db_connection():
#     return mysql.connector.connect(
#         host=os.environ["DB_HOST"],
#         port=int(os.environ["DB_PORT"]),
#         user=os.environ["DB_USER"],
#         password=os.environ["DB_PASS"],
#         database=os.environ["DB_NAME"],
#         connection_timeout=30
#     )


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


def generate_verification_code():
    return ''.join(random.choices(string.digits, k=8))


def send_email(to_email, subject, body):
    from_email = "skolnichat.zib@gmail.com"
    from_password = os.getenv("EMAIL_PASSWORD")
    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(from_email, from_password)
        text = msg.as_string()
        server.sendmail(from_email, to_email, text)
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

    # profile_pic=session['profile_pic'])


@auth_bp.route('/settings', methods=['GET'])
def settings():
    user = session.get('user_id')
    if not user:
        return redirect(url_for('auth.login'))

    db = get_db_connection()
    cur = db.cursor()
    cur.execute("SELECT theme_mode, english_level FROM users WHERE id = %s", (user,))
    row = cur.fetchone()
    theme = row[0] if row and row[0] in ['light', 'dark'] else 'light'
    english_level = row[1] if row else 'A1'
    cur.close()
    db.close()

    user_achievements = get_user_achievements(user)
    all_achievements = get_all_achievements()
    top_users = get_top_users(10)

    return render_template('settings.html',
                           theme=theme,
                           english_level=english_level,
                           profile_pic=session['profile_pic'],
                           user_achievements=user_achievements,
                           all_achievements=all_achievements,
                           top_users=top_users)


@auth_bp.route('/set_english_level', methods=['POST'])
def set_english_level():
    user = session.get('user_id')
    if not user:
        return jsonify({'error': 'Not logged in'}), 401

    data = request.get_json()
    level = data.get('level')

    valid_levels = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']
    if level not in valid_levels:
        return jsonify({'error': 'Neplatná úroveň'}), 400

    db = get_db_connection()
    cur = db.cursor()
    cur.execute("UPDATE users SET english_level = %s WHERE id = %s", (level, user))
    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})


@auth_bp.route('/set_theme', methods=['POST'])
def set_theme():
    user = session.get('user_id')
    if not user:
        return jsonify({'error': 'Not logged in'}), 401

    data = request.get_json()
    theme = data.get('theme')

    if theme not in ['light', 'dark']:
        return jsonify({'error': 'Invalid theme'}), 400

    db = get_db_connection()
    cur = db.cursor()
    cur.execute("UPDATE users SET theme_mode = %s WHERE id = %s", (theme, user))
    db.commit()
    cur.close()
    db.close()

    session['theme'] = theme  # Aktualizace session okamžitě
    return jsonify({'success': True})


@auth_bp.route('/upload_profile_pic', methods=['POST'])
def upload_profile_pic():
    if 'user_name' not in session or 'user_id' not in session:
        flash("Nejdříve se musíte přihlásit.", "warning")
        return redirect(url_for('auth.login'))

    if 'file' not in request.files:
        flash("Žádný soubor nebyl vybrán.", "error")
        return redirect(url_for('auth.settings'))

    file = request.files['file']

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        img = Image.open(filepath)
        img = img.resize((128, 128))
        img.save(filepath)

        session['profile_pic'] = filename

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET profile_pic = %s WHERE id = %s", (filename, session["user_id"]))
            conn.commit()

        flash("Profilová fotka byla úspěšně nahrána.", "success")
        return redirect(url_for('auth.settings'))
    else:
        flash("Podporované formáty jsou pouze PNG, JPG, JPEG nebo GIF.", "error")
        return redirect(url_for('auth.settings'))


# Routy pro autentizaci
@auth_bp.route('/continue')
def continue_lesson():
    if 'user_id' not in session:
        flash("Pro pokračování se musíte přihlásit.", "warning")
        return redirect(url_for('auth.login'))

    # Reset session variables for a new lesson
    session.pop('lesson_complete', None)
    session.pop('verbs_done', None)
    session.pop('used_sentences', None)
    session.pop('current_verb', None)
    session.pop('current_sentence', None)
    session.pop('current_tense', None)
    session.pop('verbs_done', None)  # Reset progress counter

    return redirect(url_for('test'))


# LOGIN/REGISTRACE
# 📌 **Route pro registraci**
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first_name = request.form['first_name'].strip()
        last_name = request.form['last_name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        birthdate = request.form.get('birthdate') or None
        english_level = request.form.get('english_level')

        if not first_name or not last_name or not email or not password:
            flash("Vyplňte všechna povinná pole!", "error")
            return redirect(url_for('auth.register'))

        if not english_level:
            flash("Vyberte prosím úroveň angličtiny.", "error")
            return redirect(url_for('auth.register'))

        hashed_password = generate_password_hash(password)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO users 
                    (first_name, last_name, email, password, birthdate, english_level)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (first_name, last_name, email, hashed_password, birthdate, english_level)
                )
                conn.commit()
                flash("Registrace úspěšná! Nyní se můžete přihlásit.", "success")
                return redirect(url_for('auth.login'))
            except mysql.connector.IntegrityError:
                flash("Tento e-mail je již zaregistrován!", "error")
                return redirect(url_for('auth.register'))

    return render_template('registrace.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, first_name, last_name, password, profile_pic FROM users WHERE email = %s",
                           (email,))
            user = cursor.fetchone()

            if user and check_password_hash(user[3], password):
                session["user_id"] = user[0]
                session["user_name"] = f"{user[1]} {user[2]}"
                session["profile_pic"] = user[4] if user[4] else 'default.jpg'
                return redirect(url_for('main.index'))
            else:
                flash("Nesprávný e-mail nebo heslo!", "error")

    return render_template('login.html')


# 📌 **Route pro odhlášení**
@auth_bp.route('/logout')
def logout():
    session.clear()
    flash("Byli jste úspěšně odhlášeni.", "info")
    return redirect(url_for('main.index'))


@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        input_data = request.form['email_or_username']

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, first_name, email 
                    FROM users 
                    WHERE email = %s OR first_name = %s
                """, (input_data, input_data))
                user = cursor.fetchone()

            if user:
                verification_code = generate_verification_code()

                # Uložení informací do session
                session['reset_user_id'] = user[0]  # ID uživatele
                session['reset_email'] = user[2]  # Email uživatele
                session['reset_code'] = verification_code
                session['code_timestamp'] = time.time()

                # Odeslání emailu
                subject = "Obnovení hesla - ověřovací kód"
                body = f"""
                Váš ověřovací kód je: {verification_code}

                Kód je platný 15 minut. Pokud jste tento kód nevyžádali, ignorujte tento email.
                """

                if send_email(user[2], subject, body):
                    flash("Ověřovací kód byl odeslán na váš e-mail.", "success")
                    return redirect(url_for('auth.verify_code'))
                else:
                    flash("Nepodařilo se odeslat ověřovací email.", "error")
                    return redirect(url_for('auth.login'))
            else:
                flash("Uživatel s tímto emailem nebo jménem nebyl nalezen.", "error")
                return redirect(url_for('auth.forgot_password'))

        except Exception as e:
            print(f"Chyba při obnově hesla: {str(e)}")
            flash("Došlo k neočekávané chybě. Zkuste to prosím později.", "error")

    return render_template('forgot_password.html')


@auth_bp.route('/verify_code', methods=['GET', 'POST'])
def verify_code():
    if request.method == 'POST':
        input_code = request.form.get('verification_code')
        stored_code = session.get('reset_code')
        code_time = session.get('code_timestamp')

        # Kontrola platnosti kódu (15 minut)
        if code_time and (time.time() - code_time) > 900:  # 900 sekund = 15 minut
            flash("Ověřovací kód expiroval. Žádejte nový.", "error")
            return redirect(url_for('auth.forgot_password'))

        if input_code and stored_code == input_code:
            session['verified'] = True
            flash("Ověření proběhlo úspěšně! Nyní můžete změnit heslo.", "success")
            return redirect(url_for('auth.reset_password'))
        else:
            flash("Zadaný kód není správný. Zkuste to prosím znovu.", "error")
            return redirect(url_for('auth.verify_code'))

    return render_template('verify_code.html')


@auth_bp.route("/terms")
def terms():
    return render_template("terms.html")


@auth_bp.route("/cookies")
def cookies():
    return render_template("cookie.html")


@auth_bp.route('/resend_code', methods=['POST'])
def resend_code():
    if 'reset_email' not in session:
        flash("Nejprve zadejte svůj email na stránce pro obnovení hesla.", "error")
        return redirect(url_for('forgot_password'))

    try:
        verification_code = generate_verification_code()

        # Aktualizace session
        session['reset_code'] = verification_code
        session['code_timestamp'] = time.time()

        subject = "Nový ověřovací kód pro obnovení hesla"
        body = f"""
        Váš nový ověřovací kód je: {verification_code}

        Kód je platný 15 minut. Pokud jste tento kód nevyžádali, ignorujte tento email.
        """

        if send_email(session['reset_email'], subject, body):
            flash("Nový ověřovací kód byl odeslán na váš email.", "success")
        else:
            flash("Nepodařilo se odeslat nový ověřovací kód.", "error")

    except Exception as e:
        print(f"Chyba při opětovném odeslání kódu: {str(e)}")
        flash("Došlo k chybě při generování nového kódu.", "error")

    return redirect(url_for('auth.verify_code'))


# 3. Route pro nastavení nového hesla
@auth_bp.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    # Ujisti se, že byl uživatel ověřen
    if not session.get('verified'):
        flash("Nejprve musíte ověřit svou totožnost.", "error")
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not new_password or not confirm_password:
            flash("Vyplňte obě pole.", "error")
            return redirect(url_for('reset_password'))

        if new_password != confirm_password:
            flash("Hesla se neshodují.", "error")
            return redirect(url_for('auth.reset_password'))

        hashed_password = generate_password_hash(new_password)

        user_id = session.get('reset_user_id')  # Oprava: správné získání ID uživatele
        if not user_id:
            flash("Došlo k chybě, zkuste to znovu.", "error")
            return redirect(url_for('auth.forgot_password'))

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET password = %s WHERE id = %s", (hashed_password, user_id))
            conn.commit()

        # Vyčistíme session pro reset hesla
        session.pop('reset_code', None)
        session.pop('reset_user', None)
        session.pop('verified', None)

        flash("Vaše heslo bylo úspěšně změněno, nyní se přihlaste.", "success")
        return redirect(url_for('auth.login'))

    return render_template('reset_password.html')
