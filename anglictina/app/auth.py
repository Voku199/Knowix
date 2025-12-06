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
import secrets
from xp import get_user_achievements, get_all_achievements, get_top_users, get_user_xp_and_level
from db import get_db_connection
from authlib.integrations.flask_client import OAuth
from datetime import datetime

# Pomocné importy pro e‑mailové odesílání
import socket
import requests

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
        return dict(user_xp=xp)
    return {}


@auth_bp.errorhandler(502)
@auth_bp.errorhandler(503)
@auth_bp.errorhandler(504)
@auth_bp.errorhandler(500)
@auth_bp.errorhandler(404)
@auth_bp.errorhandler(Exception)
def server_error(e):
    # Bezpečně zjisti kód chyby, pokud existuje, jinak použij 500
    code = getattr(e, 'code', 500)
    return render_template('error.html', error_code=code), code


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
    """Odešle prostý textový e‑mail přes SMTP/Resend podle dostupné konfigurace."""
    # Preferovaná adresa odesílatele a přihlašovací údaje z env
    from_email = os.getenv("EMAIL_FROM", "knowixcz@gmail.com")
    # Reuse HTML odesílače s textem jako fallbackem
    return send_email_html(to_email, subject, body or "",
                           f"<pre>{(body or '').replace('&', '&amp;').replace('<', '&lt;')}</pre>")


# Nové: odeslání e-mailu s HTML i textovou částí (multipart/alternative)
def send_email_html(to_email, subject, text_body, html_body):
    """Odešle e‑mail. Pořadí pokusů:
    1) Resend API (pokud RESEND_API_KEY)
    2) SMTP (konfigurovatelné env proměnnými; default Gmail 587 TLS)
    Vrací True/False.
    Env:
      RESEND_API_KEY
      EMAIL_FROM (např. "Knowix <hello@knowix.cz>")
      SMTP_HOST, SMTP_PORT, SMTP_SSL (1/0), SMTP_TLS (1/0), SMTP_TIMEOUT
      EMAIL_USER, EMAIL_PASSWORD (nebo pouze EMAIL_PASSWORD pro Gmail)
      SMTP_FORCE_IPV4 (1/0)
    """
    # Ignoruj testovací adresy a anonymní identifikátory
    try:
        _to = (to_email or '').strip().lower()
        local, _, domain = _to.partition('@')
        if domain == 'example.com' or local.startswith('anonymous_'):
            print(f"[email] Ignored to='{to_email}' subject='{subject}' (example/anonym)", flush=True)
            return True
    except Exception:
        # V případě neočekávaného formátu pokračuj standardní cestou
        pass

    from_email = os.getenv("EMAIL_FROM", "knowixcz@gmail.com")

    msg = MIMEMultipart('alternative')
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(text_body or '', 'plain', 'utf-8'))
    msg.attach(MIMEText(html_body or '', 'html', 'utf-8'))

    api_key = os.getenv('RESEND_API_KEY')
    if api_key:
        print(f"[email] Resend attempt to={to_email} subject='{subject}' from='{from_email}'", flush=True)
        try:
            timeout = float(os.getenv('SMTP_TIMEOUT', '20'))

            def _resend_post():
                return requests.post(
                    'https://api.resend.com/emails',
                    headers={
                        'Authorization': f'Bearer {api_key}',
                        'Content-Type': 'application/json'
                    },
                    json={
                        'from': from_email,
                        'to': [to_email],
                        'subject': subject,
                        'html': html_body or '',
                        'text': text_body or ''
                    },
                    timeout=timeout
                )

            resp = _resend_post()
            if 200 <= resp.status_code < 300:
                rid = ''
                try:
                    rid = resp.json().get('id', '')
                except Exception:
                    pass
                print(f"[email] Resend success status={resp.status_code} id={rid}", flush=True)
                return True
            elif resp.status_code == 429:
                # Respektuj Retry-After / RateLimit-Reset s exponenciálním backoffem + jitterem
                headers = resp.headers
                retry_after = headers.get('Retry-After')
                rate_reset = headers.get('X-RateLimit-Reset') or headers.get('RateLimit-Reset')
                base_delay = 0.75
                try:
                    if retry_after:
                        base_delay = max(base_delay, float(retry_after))
                    elif rate_reset:
                        # Pokud je unix timestamp, spočti delta; jinak ignoruj
                        import math
                        now = time.time()
                        ts = float(rate_reset)
                        if ts > now:
                            base_delay = max(base_delay, ts - now)
                except Exception:
                    pass
                # Exponenciální backoff s jitterem, max 3 pokusy
                max_retries = int(os.getenv('RESEND_MAX_RETRIES', '3'))
                for attempt in range(1, max_retries + 1):
                    jitter = random.uniform(0.2, 0.6)
                    delay = min(6.0, base_delay * (2 ** (attempt - 1)) + jitter)
                    print(f"[email] Resend rate limit -> sleep {delay:.2f}s, retry {attempt}/{max_retries}", flush=True)
                    time.sleep(delay)
                    resp2 = _resend_post()
                    if 200 <= resp2.status_code < 300:
                        print(f"[email] Resend retry success status={resp2.status_code}", flush=True)
                        return True
                    elif resp2.status_code != 429:
                        print(f"[email] Resend retry failure status={resp2.status_code} body={resp2.text[:200]}",
                              flush=True)
                        break
                print(f"[email] Resend final failure 429 after {max_retries} retries", flush=True)
            else:
                print(f"[email] Resend failure status={resp.status_code} body={resp.text[:200]}", flush=True)
        except Exception as e:
            print(f"[email] Resend exception: {e}", flush=True)
    else:
        print("[email] RESEND_API_KEY missing -> skipping Resend", flush=True)

    # SMTP fallback
    try:
        host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        port = int(os.getenv('SMTP_PORT', '587'))
        use_ssl = os.getenv('SMTP_SSL', '0') in ('1', 'true', 'True')
        use_tls = os.getenv('SMTP_TLS', '1') in ('1', 'true', 'True') and not use_ssl
        timeout = float(os.getenv('SMTP_TIMEOUT', '20'))
        force_ipv4 = os.getenv('SMTP_FORCE_IPV4', '0') in ('1', 'true', 'True')

        user = os.getenv('EMAIL_USER') or os.getenv('SMTP_USER') or os.getenv('EMAIL_FROM') or from_email
        password = os.getenv('EMAIL_PASSWORD') or os.getenv('SMTP_PASSWORD')

        if not password:
            print("[email] SMTP credentials missing -> abort", flush=True)
            return False

        server = None
        try:
            print(f"[email] SMTP attempt host={host} port={port} ssl={use_ssl} tls={use_tls} ipv4={force_ipv4}",
                  flush=True)
            if force_ipv4:
                import socket as _socket
                infos = _socket.getaddrinfo(host, port, _socket.AF_INET, _socket.SOCK_STREAM)
                if not infos:
                    raise OSError("No IPv4 address resolved for SMTP host")
                ipv4_addr = infos[0][4][0]
                if use_ssl:
                    server = smtplib.SMTP_SSL(ipv4_addr, port, timeout=timeout)
                    server.ehlo()
                else:
                    server = smtplib.SMTP(ipv4_addr, port, timeout=timeout)
            else:
                if use_ssl:
                    server = smtplib.SMTP_SSL(host, port, timeout=timeout)
                    server.ehlo()
                else:
                    server = smtplib.SMTP(host, port, timeout=timeout)

            if not use_ssl and use_tls:
                server.starttls()
                server.ehlo()

            server.login(user, password)
            server.sendmail(from_email, [to_email], msg.as_string())
            server.quit()
            print("[email] SMTP success", flush=True)
            return True
        finally:
            try:
                if server and getattr(server, 'sock', None):
                    server.close()
            except Exception:
                pass
    except Exception as e:
        print(
            f"Error sending HTML email (SMTP host={os.getenv('SMTP_HOST', 'smtp.gmail.com')} port={os.getenv('SMTP_PORT', '587')}): {e}",
            flush=True)
        return False

    # profile_pic=session['profile_pic'])


@auth_bp.route('/remove_student', methods=['POST'])
def remove_student():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    # Ověření, že uživatel je učitel
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT role FROM users WHERE id = %s", (session['user_id'],))
    user = cur.fetchone()
    if not user or user['role'] != 'teacher':
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    student_id = data.get('student_id')

    if not student_id:
        return jsonify({'error': 'Missing student ID'}), 400

    try:
        # Odebrání studenta ze všech skupin učitele
        cur.execute("""
            DELETE FROM teacher_groups 
            WHERE teacher_id = %s AND student_id = %s
        """, (session['user_id'], student_id))
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error removing student: {e}")
        return jsonify({'error': 'Database error'}), 500
    finally:
        cur.close()
        db.close()


@auth_bp.route('/teacher/student_stats/<int:student_id>')
def student_stats(student_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    db = get_db_connection()
    cur = db.cursor(dictionary=True)

    # Ověření, že přihlášený uživatel je učitel
    cur.execute("SELECT role FROM users WHERE id = %s", (session['user_id'],))
    teacher = cur.fetchone()
    if not teacher or teacher['role'] != 'teacher':
        return "Přístup odepřen", 403

    # Ověření, že student patří k učiteli
    cur.execute("""
        SELECT 1 FROM teacher_groups 
        WHERE teacher_id = %s AND student_id = %s
    """, (session['user_id'], student_id))
    if not cur.fetchone():
        return "Tento student není ve vaší skupině", 403

    # Načtení základních údajů o studentovi
    cur.execute("""
        SELECT first_name, last_name, email, profile_pic, xp, level, 
               english_level, streak
        FROM users WHERE id = %s
    """, (student_id,))
    student = cur.fetchone()

    # Načtení statistik z user_stats (jeden řádek jako slovník)
    cur.execute("SELECT * FROM user_stats WHERE user_id = %s", (student_id,))
    stats = cur.fetchone()

    cur.close()
    db.close()

    return render_template('stats/student_stats_chart.html', student=student, stats=stats)


@auth_bp.route('/my_stats')
def my_stats():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    user_id = session['user_id']
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT first_name, last_name, email, profile_pic, xp, level, english_level, streak FROM users WHERE id = %s",
        (user_id,))
    user = cur.fetchone()
    cur.execute("SELECT * FROM user_stats WHERE user_id = %s", (user_id,))
    stats = cur.fetchone()
    cur.close()
    db.close()
    return render_template('stats/stats.html', student=user, stats=stats)


@auth_bp.route('/settings', methods=['GET'])
def settings():
    user = session.get('user_id')
    print(
        f"[auth.settings] host={request.host} path={request.path} method={request.method} user_id={user} session_keys={list(session.keys())}")
    if not user:
        print("[auth.settings] user_id missing in session -> redirect to login")
        return redirect(url_for('auth.login'))

    db = get_db_connection()
    cur = db.cursor(dictionary=True)

    # Získání role uživatele
    cur.execute("SELECT role, english_level, theme_mode FROM users WHERE id = %s", (user,))
    user_data = cur.fetchone()
    is_teacher = user_data and user_data['role'] == 'teacher'

    # Načtení skupiny studentů pokud je učitel
    teacher_group_members = []
    active_group_name = None
    student_group_name = None
    student_groups = []
    if is_teacher:
        # Zjisti aktivní skupinu z session nebo z DB (první skupina učitele)
        active_skupina_id = session.get('active_skupina_id')
        if not active_skupina_id:
            cur.execute("SELECT id, nazev FROM teacher_skupina WHERE teacher_id = %s ORDER BY created_at LIMIT 1",
                        (user,))
            first_group = cur.fetchone()
            if first_group:
                active_skupina_id = first_group['id']
                session['active_skupina_id'] = active_skupina_id
                active_group_name = first_group['nazev']
            else:
                active_group_name = None
        else:
            cur.execute("SELECT nazev FROM teacher_skupina WHERE id = %s AND teacher_id = %s",
                        (active_skupina_id, user))
            group_row = cur.fetchone()
            if group_row:
                active_group_name = group_row['nazev']
            else:
                active_group_name = None
        # Načti studenty pouze z aktivní skupiny
        if active_skupina_id:
            cur.execute("""
                SELECT u.id, u.first_name, u.last_name, u.email, u.profile_pic, u.xp, u.level
                FROM teacher_groups tg
                JOIN users u ON tg.student_id = u.id
                WHERE tg.teacher_id = %s AND tg.skupina_id = %s
                ORDER BY u.xp DESC
            """, (user, active_skupina_id))
            teacher_group_members = cur.fetchall()
        else:
            teacher_group_members = []
    else:
        cur.execute("""
            SELECT ts.id, ts.nazev 
            FROM teacher_groups tg
            JOIN teacher_skupina ts ON tg.skupina_id = ts.id
            WHERE tg.student_id = %s
        """, (user,))
        student_groups = cur.fetchall()

    theme = user_data['theme_mode'] if user_data and user_data['theme_mode'] in ['light', 'dark'] else 'light'
    english_level = user_data['english_level'] if user_data else 'A1'
    cur.close()
    db.close()

    user_achievements = get_user_achievements(user)
    all_achievements = get_all_achievements()
    top_users = get_top_users(10)

    return render_template('settings.html',
                           theme=theme,
                           english_level=english_level,
                           profile_pic=session.get('profile_pic', 'default.webp'),
                           user_achievements=user_achievements,
                           all_achievements=all_achievements,
                           top_users=top_users,
                           teacher_group_members=teacher_group_members,
                           is_teacher=is_teacher,
                           active_group_name=active_group_name,
                           student_group_name=student_group_name,
                           student_groups=student_groups)


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
    print(
        f"[auth.upload_profile_pic] host={request.host} path={request.path} method={request.method} session_keys={list(session.keys())}")
    if 'user_name' not in session or 'user_id' not in session:
        print(f"[auth.upload_profile_pic] Missing user in session -> redirect login")
        flash("Nejdříve se musíte přihlásit.", "warning")
        return redirect(url_for('auth.login'))

    if 'file' not in request.files:
        print("[auth.upload_profile_pic] No file in request")
        flash("Žádný soubor nebyl vybrán.", "error")
        return redirect(url_for('auth.settings'))

    file = request.files['file']

    if file and allowed_file(file.filename):
        print(f"[auth.upload_profile_pic] Allowed file filename={file.filename}")
        # Vytvoř cíl a unikátní název (ignorujeme původní název uživatele)
        upload_dir = os.path.join(current_app.root_path, current_app.config['UPLOAD_FOLDER'])
        os.makedirs(upload_dir, exist_ok=True)
        unique_name = f"user_{session['user_id']}_{int(time.time())}_{secrets.token_hex(6)}.webp"
        filepath = os.path.join(upload_dir, unique_name)

        # Načti, znormalizuj a ulož jako WEBP jednotné velikosti
        try:
            img = Image.open(file.stream)
            # Konverze do RGB (kvůli webp a sjednocení)
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            else:
                img = img.convert('RGB')
            img = img.resize((128, 128))
            img.save(filepath, format='WEBP', quality=85, method=6)
        except Exception as ex:
            print(f"[auth.upload_profile_pic] Pillow error: {ex}")
            # Pokud selže Pillow, ulož soubor bezpečně bez konverze (méně preferované)
            file.seek(0)
            file.save(filepath)

        # Smaž starý soubor, pokud existuje a není to default
        old_pic = session.get('profile_pic')
        if old_pic and not old_pic.lower().startswith('default'):
            try:
                old_path = os.path.join(upload_dir, old_pic)
                if os.path.isfile(old_path):
                    os.remove(old_path)
                    print(f"[auth.upload_profile_pic] Removed old pic {old_pic}")
            except Exception as ex:
                print(f"[auth.upload_profile_pic] Remove old pic error: {ex}")

        # Aktualizuj session a DB s novým systémovým názvem
        session['profile_pic'] = unique_name
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET profile_pic = %s WHERE id = %s", (unique_name, session["user_id"]))
            conn.commit()
        print(f"[auth.upload_profile_pic] Stored as {unique_name}")

        flash("Profilová fotka byla úspěšně nahrána.", "success")
        return redirect(url_for('auth.settings'))
    else:
        print(f"[auth.upload_profile_pic] Disallowed file: {file.filename if file else None}")
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


@auth_bp.route('/request_teacher', methods=['POST'])
def request_teacher():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Musíte být přihlášeni.'}), 401

    data = request.get_json()
    school = data.get('school', '').strip()
    subject = data.get('subject', '').strip()
    title = data.get('title', '').strip()
    user_id = session['user_id']

    if not school or not subject or not title:
        return jsonify({'success': False, 'error': 'Vyplňte všechna pole.'})

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Zkontroluj, zda už žádost neexistuje
            cursor.execute("SELECT id FROM teacher_pendings WHERE user_id = %s", (user_id,))
            if cursor.fetchone():
                return jsonify({'success': False, 'error': 'Žádost už byla odeslána.'})

            cursor.execute(
                "INSERT INTO teacher_pendings (user_id, school, subject, title, status, created_at) VALUES (%s, %s, %s, %s, %s, NOW())",
                (user_id, school, subject, title, 'pending')
            )
            conn.commit()

        # Pošli adminovi email (změň na svůj email)
        admin_email = "vojta.kurinec@gmail.com"
        user_name = session.get('user_name', 'Uživatel')
        send_email(
            admin_email,
            "Nová žádost o roli učitele",
            f"Uživatel {user_name} (ID: {user_id}) požádal o roli učitele.\nŠkola: {school}\nPředmět: {subject}\nTitul: {title}\n Přihlaš se na uživatele s id 1 : https://knowix.cz/admin/teacher_requests nebo http://localhost:5000/admin/teacher_requests"
        )

        return jsonify({'success': True})
    except Exception as e:
        print("Chyba při ukládání žádosti o učitele:", e)
        return jsonify({'success': False, 'error': 'Chyba serveru.'})


@auth_bp.route('/add_school', methods=['POST'])
def add_school():
    data = request.get_json()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'Název školy je povinný.'})
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT IGNORE INTO schools (name) VALUES (%s)", (name,))
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        print("Chyba při přidávání školy:", e)
        return jsonify({'success': False, 'error': 'Chyba serveru.'})


@auth_bp.route('/teacher/create_group', methods=['POST'])
def create_group():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Nejste přihlášen.'}), 401
    user_id = session['user_id']
    data = request.get_json()
    nazev = data.get('nazev', '').strip()
    if not nazev:
        return jsonify({'success': False, 'error': 'Název skupiny je povinný.'})
    db = get_db_connection()
    cur = db.cursor()
    try:
        cur.execute("INSERT IGNORE INTO teacher_skupina (nazev, teacher_id) VALUES (%s, %s)", (nazev, user_id))
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        print('Chyba při vytváření skupiny:', e)
        return jsonify({'success': False, 'error': 'Chyba při vytváření skupiny.'})
    finally:
        cur.close()
        db.close()


@auth_bp.route('/teacher/groups')
def teacher_groups():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Nejste přihlášen.'}), 401
    user_id = session['user_id']
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM teacher_skupina WHERE teacher_id = %s ORDER BY created_at", (user_id,))
    groups = cur.fetchall()
    cur.close()
    db.close()
    return jsonify({'success': True, 'groups': groups})


@auth_bp.route('/teacher/set_group', methods=['POST'])
def set_active_group():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Nejste přihlášen.'}), 401
    group_id = request.get_json().get('group_id')
    session['active_skupina_id'] = group_id
    return jsonify({'success': True})


# Úprava přidávání studenta, aby šel do aktivní skupiny
@auth_bp.route('/add_student', methods=['POST'])
def add_student():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not logged in'}), 401
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if not user or user['role'] != 'teacher':
        return jsonify({'error': 'Access denied'}), 403
    data = request.get_json()
    student_email = data.get('student_email')
    if not student_email:
        return jsonify({'error': 'E-mail studenta je povinný'}), 400
    cur.execute("SELECT id FROM users WHERE email = %s", (student_email,))
    student = cur.fetchone()
    if not student:
        return jsonify({'error': 'Student nebyl nalezen'}), 404
    skupina_id = session.get('active_skupina_id')
    if not skupina_id:
        return jsonify({'error': 'Nejprve vytvořte a vyberte skupinu.'}), 400
    # Ověř, že skupina patří učiteli
    cur.execute("SELECT id FROM teacher_skupina WHERE id = %s AND teacher_id = %s", (skupina_id, user_id))
    group_check = cur.fetchone()
    if not group_check:
        return jsonify({'error': 'Skupina neexistuje nebo vám nepatří.'}), 400
    try:
        cur.execute("INSERT INTO teacher_groups (teacher_id, student_id, skupina_id) VALUES (%s, %s, %s)",
                    (user_id, student['id'], skupina_id))
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error adding student: {e}")
        return jsonify({'error': 'Chyba při přidávání studenta'}), 500
    finally:
        cur.close()
        db.close()


# LOGIN/REGISTRACE
# 📌 **Route pro registraci**
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        print(f"[auth.register] POST host={request.host} path={request.path} ip={request.remote_addr}")
        first_name = request.form['first_name'].strip()
        last_name = request.form['last_name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        birthdate = request.form.get('birthdate') or None
        english_level = request.form.get('english_level')
        school_name = request.form.get('school', '').strip()

        if not first_name or not last_name or not email or not password:
            flash("Vyplňte všechna povinná pole!", "error")
            return redirect(url_for('auth.register'))

        if not english_level:
            flash("Vyberte prosím úroveň angličtiny.", "error")
            return redirect(url_for('auth.register'))

        if not school_name:
            flash("Vyberte nebo zadejte školu.", "error")
            return redirect(url_for('auth.register'))

        hashed_password = generate_password_hash(password)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            # 1. Najdi školu podle jména
            cursor.execute("SELECT id FROM schools WHERE name = %s", (school_name,))
            school_row = cursor.fetchone()
            print(f"[auth.register] school exists={bool(school_row)}")
            if school_row:
                school_id = school_row[0]
            else:
                # 2. Pokud škola neexistuje, vytvoř ji
                cursor.execute("INSERT INTO schools (name) VALUES (%s)", (school_name,))
                conn.commit()
                # 3. Znovu najdi školu podle jména (pro jistotu správného ID)
                cursor.execute("SELECT id FROM schools WHERE name = %s", (school_name,))
                school_row = cursor.fetchone()
                print(f"[auth.register] school created, id_found={bool(school_row)}")
                if school_row:
                    school_id = school_row[0]
                else:
                    print("[auth.register] ERROR: school not found after insert")
                    flash("Chyba při ukládání školy.", "error")
                    return redirect(url_for('auth.register'))

            try:
                cursor.execute(
                    """
                    INSERT INTO users 
                    (first_name, last_name, email, password, birthdate, english_level, school)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (first_name, last_name, email, hashed_password, birthdate, english_level, school_id)
                )
                conn.commit()
                print(f"[auth.register] user insert ok email={email}")
                flash("Registrace úspěšná! Nyní se můžete přihlásit.", "success")
                # Nově: stránka s nabídkou instalace PWA
                session['just_registered'] = True
                return render_template('registration_success.html')
            except mysql.connector.IntegrityError:
                print(f"[auth.register] IntegrityError for email={email}")
                flash("Tento e-mail je již zaregistrován!", "error")
                return redirect(url_for('auth.register'))

    # GET: načti školy pro datalist
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT name FROM schools ORDER BY name")
        schools = cursor.fetchall()
    return render_template('registrace.html', schools=schools)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        print(f"[auth.login] POST from host={request.host} path={request.path} email={email}")
        password = request.form['password']

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, first_name, last_name, password, profile_pic FROM users WHERE email = %s",
                           (email,))
            user = cursor.fetchone()
            print(f"[auth.login] DB user found={bool(user)}")

            if user and check_password_hash(user[3], password):
                session["user_id"] = user[0]
                session["user_name"] = f"{user[1]} {user[2]}"
                session["profile_pic"] = user[4] if user[4] else 'default.jpg'  # Přidej roli uživatele do session
                print(f"[auth.login] session set user_id={session.get('user_id')} session_keys={list(session.keys())}")
                return redirect(url_for('main.index'))
            else:
                print("[auth.login] Bad credentials")
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
        # Bezpečné získání hodnoty z formuláře, aby se předešlo BadRequestKeyError -> 400
        input_data = (request.form.get('email_or_username') or '').strip().lower()

        if not input_data:
            flash("Zadejte e-mail nebo jméno.", "error")
            return redirect(url_for('auth.forgot_password'))

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, first_name, email 
                    FROM users 
                    WHERE email = %s OR LOWER(first_name) = %s
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


@auth_bp.route('/terms')
def terms():
    return render_template('terms.html')


@auth_bp.route('/cookies')
def cookies():
    return render_template('cookie.html')


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
            return redirect(url_for('auth.reset_password'))

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


@auth_bp.route('/resend_code', methods=['POST'])
def resend_code():
    if 'reset_email' not in session:
        flash("Nejprve zadejte svůj email na stránce pro obnovení hesla.", "error")
        return redirect(url_for('auth.forgot_password'))

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


@auth_bp.route('/teacher/create_assignment', methods=['POST'])
def create_assignment():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Nejste přihlášen.'}), 401
    user_id = session['user_id']
    db = get_db_connection()
    cur = db.cursor()
    # Ověř, že je učitel
    cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if not user or user[0] != 'teacher':
        return jsonify({'success': False, 'error': 'Pouze učitel může zadávat úkoly.'}), 403
    data = request.get_json()
    zadani = data.get('zadani', '').strip()
    skupina_id = session.get('active_skupina_id')
    if not zadani or not skupina_id:
        return jsonify({'success': False, 'error': 'Chybí zadání nebo skupina.'}), 400
    try:
        cur.execute("INSERT INTO assignments (skupina_id, zadani) VALUES (%s, %s)", (skupina_id, zadani))
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        print('Chyba při vytváření úkolu:', e)
        return jsonify({'success': False, 'error': 'Chyba při vytváření úkolu.'})
    finally:
        cur.close()
        db.close()


@auth_bp.route('/student/group_assignments')
def group_assignments():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Nejste přihlášen.'}), 401

    user_id = session['user_id']
    try:
        db = get_db_connection()
        cur = db.cursor(dictionary=True)

        # Získání všech skupin studenta
        cur.execute("""
            SELECT DISTINCT tg.skupina_id
            FROM teacher_groups tg
            WHERE tg.student_id = %s
        """, (user_id,))
        groups = cur.fetchall()

        if not groups:
            return jsonify({'success': True, 'assignments': []})

        # Vytvoření seznamu ID skupin
        group_ids = [str(group['skupina_id']) for group in groups]

        # Načtení úkolů ze všech skupin
        query = f"""
            SELECT a.id, a.zadani, a.created_at, ts.nazev AS group_name 
            FROM assignments a
            JOIN teacher_skupina ts ON a.skupina_id = ts.id
            WHERE a.skupina_id IN ({','.join(group_ids)})
            ORDER BY a.created_at DESC
        """
        cur.execute(query)
        assignments = cur.fetchall()

        return jsonify({'success': True, 'assignments': assignments})

    except Exception as e:
        print(f"Chyba v group_assignments: {str(e)}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500
    finally:
        if cur:
            cur.close()
        if db:
            db.close()


@auth_bp.route('/teacher/group_assignments', methods=['GET'])
def teacher_group_assignments():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Nejste přihlášen.'}), 401

    user_id = session['user_id']
    try:
        db = get_db_connection()
        cur = db.cursor(dictionary=True)

        # Získání aktivní skupiny učitele
        active_group_id = session.get('active_skupina_id')
        if not active_group_id:
            return jsonify({'success': False, 'error': 'Není vybrána žádná aktivní skupina.'}), 400

        # Načtení úkolů z aktivní skupiny
        cur.execute('''
            SELECT a.id, a.zadani, a.created_at
            FROM assignments a
            WHERE a.skupina_id = %s
            ORDER BY a.created_at DESC
        ''', (active_group_id,))
        assignments = cur.fetchall()

        return jsonify({'success': True, 'assignments': assignments})

    except Exception as e:
        print(f"Chyba v teacher_group_assignments: {str(e)}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

    finally:
        if cur:
            cur.close()
        if db:
            db.close()


@auth_bp.route('/teacher/delete_assignment/<int:assignment_id>', methods=['DELETE'])
def delete_assignment(assignment_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Nejste přihlášen.'}), 401

    user_id = session['user_id']
    try:
        db = get_db_connection()
        cur = db.cursor()

        # Ověření, že úkol patří do aktivní skupiny učitele
        active_group_id = session.get('active_skupina_id')
        cur.execute('''
            SELECT 1 FROM assignments
            WHERE id = %s AND skupina_id = %s
        ''', (assignment_id, active_group_id))
        if not cur.fetchone():
            return jsonify({'success': False, 'error': 'Úkol neexistuje nebo nepatří do vaší skupiny.'}), 403

        # Smazání úkolu
        cur.execute('DELETE FROM assignments WHERE id = %s', (assignment_id,))
        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        print(f"Chyba v delete_assignment: {str(e)}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

    finally:
        if cur:
            cur.close()
        if db:
            db.close()


@auth_bp.route('/teacher/edit_assignment/<int:assignment_id>', methods=['POST'])
def edit_assignment(assignment_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Nejste přihlášen.'}), 401

    user_id = session['user_id']
    data = request.get_json()
    new_zadani = data.get('zadani', '').strip()

    if not new_zadani:
        return jsonify({'success': False, 'error': 'Zadání nemůže být prázdné.'}), 400

    try:
        db = get_db_connection()
        cur = db.cursor()

        # Ověření, že úkol patří do aktivní skupiny učitele
        active_group_id = session.get('active_skupina_id')
        cur.execute('''
            SELECT 1 FROM assignments
            WHERE id = %s AND skupina_id = %s
        ''', (assignment_id, active_group_id))
        if not cur.fetchone():
            return jsonify({'success': False, 'error': 'Úkol neexistuje nebo nepatří do vaší skupiny.'}), 403

        # Aktualizace úkolu
        cur.execute('''
            UPDATE assignments
            SET zadani = %s
            WHERE id = %s
        ''', (new_zadani, assignment_id))
        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        print(f"Chyba v edit_assignment: {str(e)}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

    finally:
        if cur:
            cur.close()
        if db:
            db.close()


@auth_bp.route('/register_finalize', methods=['POST'])
def register_finalize():
    session.pop('just_registered', None)
    return jsonify({'success': True})


@auth_bp.route('/admin/test_email', methods=['POST'])
def admin_test_email():
    """Testovací endpoint: odešle e‑mail a vrátí JSON výsledek. Jen pro admina (user_id=1)."""
    if session.get('user_id') != 1:
        return jsonify({'success': False, 'error': 'Přístup zamítnut.'}), 403
    data = request.get_json(silent=True) or {}
    to_email = data.get('to') or session.get('reset_email') or os.getenv('TEST_EMAIL_TO', 'vojta.kurinec@gmail.com')
    subject = data.get('subject') or 'Test Knowix email'
    text = data.get('text') or 'Ahoj! Toto je testovací e‑mail z Knowixu.'
    html = data.get('html') or '<strong>Ahoj!</strong> Toto je testovací e‑mail z Knowixu.'
    if not to_email:
        return jsonify({'success': False, 'error': 'Chybí cílový e‑mail (to).'}), 400
    ok = send_email_html(to_email, subject, text, html)
    return jsonify({'success': bool(ok), 'to': to_email, 'subject': subject})


oauth = OAuth()


@auth_bp.route('/test/oauth')
def test_oauth():
    """Testovací endpoint pro ladění OAuth."""
    _init_oauth()

    # Zkontrolujte metadata
    try:
        metadata = oauth.google.load_server_metadata()
        return jsonify({
            'metadata': {
                'authorization_endpoint': metadata.get('authorization_endpoint'),
                'token_endpoint': metadata.get('token_endpoint'),
                'userinfo_endpoint': metadata.get('userinfo_endpoint'),
                'jwks_uri': metadata.get('jwks_uri'),
            },
            'client_id': os.environ.get('GOOGLE_CLIENT_ID')[:10] + '...' if os.environ.get(
                'GOOGLE_CLIENT_ID') else None,
            'redirect_uri': os.environ.get('OAUTH_REDIRECT_URI') or url_for('auth.callback_google', _external=True)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _init_oauth(app=None):
    """Inicializuje OAuth klienta pro Google podle env proměnných."""
    app = app or current_app
    oauth.init_app(app)

    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    if not client_id or not client_secret:
        raise RuntimeError('GOOGLE_CLIENT_ID nebo GOOGLE_CLIENT_SECRET není nastaveno')

    client = oauth._clients.get('google')  # type: ignore[attr-defined]
    if client is None:
        client = oauth.register(
            name='google',
            client_id=client_id,
            client_secret=client_secret,
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile', 'prompt': 'consent'},
        )
    else:
        client.client_id = client_id
        client.client_secret = client_secret

    if hasattr(client, '_server_metadata'):
        del client._server_metadata

    try:
        metadata = client.load_server_metadata()
        current_app.logger.debug(f"Metadata načtena: {metadata.get('authorization_endpoint')}")
    except Exception as e:
        current_app.logger.error(f"Chyba při načítání metadat: {str(e)}")
        client = oauth.register(
            name='google',
            client_id=client_id,
            client_secret=client_secret,
            authorize_url='https://accounts.google.com/o/oauth2/v2/auth',
            access_token_url='https://oauth2.googleapis.com/token',
            jwks_uri='https://www.googleapis.com/oauth2/v3/certs',
            userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
            client_kwargs={'scope': 'openid email profile', 'prompt': 'consent'},
        )
        if hasattr(client, '_server_metadata'):
            del client._server_metadata


def _generate_temporary_password():
    # Přesný formát KnowixGoogle + 5 číslic
    return 'KnowixGoogle' + ''.join(random.choices(string.digits, k=5))


def _hash_password(plain):
    # Použij werkzeug generate_password_hash (PBKDF2) – lze přepnout na bcrypt/argon2
    return generate_password_hash(plain)


def _send_temporary_password_email(email, temp_password):
    print(temp_password)
    subject = 'Knowix – Dočasné heslo pro první přihlášení'
    text_body = (
        'Dobrý den,\n\n'
        'Váš dočasný přístup k Knowix byl vytvořen přes Google.\n'
        f'Dočasné heslo: {temp_password}\n\n'
        'Toto heslo je dočasné. Doporučujeme okamžitou změnu hesla – v aplikaci použijte "Zapomenuté heslo"\n'
        'nebo odkaz v profilu k nastavení vlastního hesla.\n\n'
        'Bezpečnější alternativa je jednorázový odkaz pro nastavení hesla (doporučeno).\n\n'
        'Tým Knowix'
    )
    html_body = (
        '<p>Dobrý den,</p>'
        '<p>Váš dočasný přístup k Knowix byl vytvořen přes Google.</p>'
        f'<p><strong>Dočasné heslo:</strong> <code>{temp_password}</code></p>'
        '<p><em>Toto heslo je dočasné.</em> Doporučujeme okamžitou změnu hesla – v aplikaci použijte '
        '„Zapomenuté heslo“ nebo odkaz v profilu k nastavení vlastního hesla.</p>'
        '<p><strong>Bezpečnější alternativa</strong> je jednorázový odkaz pro nastavení hesla (doporučeno).</p>'
        '<p>Tým Knowix</p>'
    )
    return send_email_html(email, subject, text_body, html_body)


@auth_bp.route('/debug/db')
def debug_db():
    """Debug endpoint pro kontrolu struktury DB."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        # Zkontrolujte strukturu tabulky users
        cur.execute("DESCRIBE users")
        columns = cur.fetchall()

        # Zkontrolujte, zda existují nějací uživatelé
        cur.execute("SELECT COUNT(*) as count FROM users")
        count = cur.fetchone()['count']

        cur.close()
        conn.close()

        return jsonify({
            'table_structure': columns,
            'user_count': count,
            'env_check': {
                'GOOGLE_CLIENT_ID_exists': bool(os.environ.get('GOOGLE_CLIENT_ID')),
                'GOOGLE_CLIENT_SECRET_exists': bool(os.environ.get('GOOGLE_CLIENT_SECRET')),
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def create_user_from_google(profile):
    """Vytvoří uživatele z Google profilu, vygeneruje dočasné heslo a pošle e‑mail."""
    google_id = profile.get('sub')
    email = profile.get('email')
    first_name = profile.get('given_name') or ''
    last_name = profile.get('family_name') or ''
    avatar_url = profile.get('picture') or None

    current_app.logger.debug(f"Vytvářím uživatele: email={email}, google_id={google_id}")

    temp_password = _generate_temporary_password()
    password_hash = _hash_password(temp_password)

    now = datetime.utcnow()

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        current_app.logger.debug(f"Vkládám uživatele do DB...")
        cur.execute(
            """
            INSERT INTO users (provider, provider_id, email, first_name, last_name, avatar_url, password, created_at, last_login)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            ('google', google_id, email, first_name, last_name, avatar_url, password_hash, now, now)
        )
        conn.commit()
        user_id = cur.lastrowid
        current_app.logger.debug(f"Uživatel vytvořen s ID: {user_id}")
    except Exception as e:
        current_app.logger.error(f"Chyba při vkládání uživatele do DB: {str(e)}", exc_info=True)
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

    # Pošleme e‑mail s dočasným heslem
    try:
        _send_temporary_password_email(email, temp_password)
        current_app.logger.debug(f"Email s dočasným heslem odeslán na {email}")
    except Exception as e:
        current_app.logger.warning(f"Email send failed: {type(e).__name__}: {str(e)[:120]}")

    return user_id


@auth_bp.route('/login/google')
def login_google():
    """Zahájí OAuth2 flow s Googlem. Používá state pro CSRF."""
    try:
        _init_oauth()
        redirect_uri = os.environ.get('OAUTH_REDIRECT_URI') or url_for('auth.callback_google', _external=True)

        # Whitelist kontrola redirect URI (základní ochrana)
        allowed_base = os.environ.get('OAUTH_REDIRECT_BASE')
        if allowed_base and not redirect_uri.startswith(allowed_base):
            flash('Neplatné redirect URI (není na whitelistu).', 'error')
            return redirect(url_for('auth.login'))

        # Před zahájením OAuth pročisti session (prevence kolize state/nonce)
        session.clear()

        # Získejte metadata pro debug
        try:
            metadata = oauth.google.load_server_metadata()
            current_app.logger.debug(f"Metadata načtena: {metadata.get('authorization_endpoint')}")
        except Exception as e:
            current_app.logger.warning(f"Nepodařilo se načíst metadata: {str(e)}")

        return oauth.google.authorize_redirect(redirect_uri)

    except Exception as e:
        current_app.logger.error(f"Chyba v login_google: {str(e)}", exc_info=True)
        flash('Nastala chyba při pokusu o přihlášení přes Google.', 'error')
        return redirect(url_for('auth.login'))


@auth_bp.route('/callback/google')
def callback_google():
    """Zpracuje návrat z Google OAuth, vytvoří/načte uživatele a přihlásí ho."""
    _init_oauth()

    try:
        token = oauth.google.authorize_access_token()
        current_app.logger.debug(f"Token získán: {list(token.keys())}")
    except Exception as e:
        current_app.logger.error(f"Chyba při získávání tokenu: {str(e)}", exc_info=True)
        flash('Přihlášení přes Google selhalo.', 'error')
        return redirect(url_for('auth.login'))

    try:
        profile = oauth.google.parse_id_token(token, nonce=None)
        current_app.logger.debug(f"Profil získán z ID tokenu: {list(profile.keys())}")
    except Exception as e:
        current_app.logger.error(f"Chyba při parsování ID tokenu: {str(e)}", exc_info=True)
        flash('Chyba při zpracování dat z Googlu.', 'error')
        return redirect(url_for('auth.login'))

    if not profile or not profile.get('email') or not profile.get('sub'):
        current_app.logger.error(f"Profil neobsahuje potřebná data: {profile}")
        flash('Google profil neobsahuje potřebná data.', 'error')
        return redirect(url_for('auth.login'))

    google_id = profile.get('sub')
    email = profile.get('email')

    current_app.logger.debug(f"Zpracovávám uživatele: email={email}, google_id={google_id}")

    # Najdi existujícího uživatele
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        current_app.logger.debug(f"Hledám uživatele s provider=google, provider_id={google_id}")
        cur.execute("SELECT id, first_name, last_name FROM users WHERE provider=%s AND provider_id=%s",
                    ('google', google_id))
        user = cur.fetchone()
        current_app.logger.debug(f"Nalezený uživatel: {user}")

        if not user:
            current_app.logger.debug(f"Uživatel neexistuje, vytvářím nového...")
            # Pokud neexistuje, vytvoř nového
            user_id = create_user_from_google(profile)
            user = {'id': user_id, 'first_name': profile.get('given_name'), 'last_name': profile.get('family_name')}
            current_app.logger.debug(f"Nový uživatel vytvořen: {user}")

        # Aktualizuj last_login
        current_app.logger.debug(f"Aktualizuji last_login pro user_id={user['id']}")
        cur.execute("UPDATE users SET last_login=%s WHERE id=%s", (datetime.utcnow(), user['id']))
        conn.commit()
        current_app.logger.debug(f"Databázové operace dokončeny")

    except Exception as e:
        current_app.logger.error(f"Databázová chyba: {str(e)}", exc_info=True)
        flash('Došlo k chybě při práci s databází.', 'error')
        return redirect(url_for('auth.login'))
    finally:
        cur.close()
        conn.close()

    # Přihlas do session
    session['user_id'] = user['id']
    session['user_name'] = f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip()
    session.modified = True

    current_app.logger.debug(f"Uživatel přihlášen: user_id={user['id']}, user_name={session['user_name']}")

    # Po přihlášení přesměruj rovnou na hlavní stránku
    return redirect(url_for('main.index'))


def ensure_users_table():
    """Zajistí, že tabulka users existuje a má potřebné sloupce pro Google OAuth.
    Vytvoří tabulku, pokud chybí. Dále přidá chybějící sloupce.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INT AUTO_INCREMENT PRIMARY KEY,
              provider VARCHAR(32) NULL,
              provider_id VARCHAR(128) NULL,
              email VARCHAR(255) NOT NULL,
              first_name VARCHAR(100) NULL,
              last_name VARCHAR(100) NULL,
              avatar_url VARCHAR(512) NULL,
              password VARCHAR(255) NOT NULL,
              english_level ENUM('A1','A2','B1','B2','C1','C2') NULL,
              school INT NULL,
              created_at TIMESTAMP NULL,
              last_login TIMESTAMP NULL,
              UNIQUE KEY uniq_email (email)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )
        # Přidej unikátní kombinaci provider+provider_id
        cur.execute(
            """
            ALTER TABLE users
            ADD UNIQUE KEY IF NOT EXISTS uniq_provider (provider, provider_id);
            """
        )
    except Exception:
        # Některé MySQL verze nepodporují IF NOT EXISTS u ALTER; fallback kontrola přes INFORMATION_SCHEMA
        conn.rollback()
        try:
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'users' AND column_name = 'provider'")
            if cur.fetchone()[0] == 0:
                cur.execute("ALTER TABLE users ADD COLUMN provider VARCHAR(32) NULL")
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'users' AND column_name = 'provider_id'")
            if cur.fetchone()[0] == 0:
                cur.execute("ALTER TABLE users ADD COLUMN provider_id VARCHAR(128) NULL")
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'users' AND index_name = 'uniq_provider'")
            if cur.fetchone()[0] == 0:
                cur.execute("ALTER TABLE users ADD UNIQUE KEY uniq_provider (provider, provider_id)")
            conn.commit()
        except Exception:
            conn.rollback()
            # Log jen stručně
            print("[db] Nepodařilo se automaticky upravit schéma users.")
    finally:
        cur.close()
        conn.close()
