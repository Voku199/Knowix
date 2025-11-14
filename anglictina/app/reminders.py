import time
import threading
import secrets
from flask import Blueprint, session, jsonify, render_template, request
from db import get_db_connection
from auth import send_email_html

reminders_bp = Blueprint('reminders', __name__)

CHECK_INTERVAL_SECONDS = 3600  # 1 hodina
INACTIVITY_THRESHOLD_HOURS = 24


# Filtrace e-mailů pro odesílání připomínek

def _should_skip_email(email: str) -> bool:
    if not email:
        return True
    e = email.strip().lower()
    # 1) Skip anonymní placeholdery typu anonymous*@example.com
    if e.startswith('anonymous') and e.endswith('@example.com'):
        return True
    # 2) TLD filtr (.com, .cz, .sk, .eu) – výjimka pro example.com
    if '@' not in e:
        return True
    domain = e.split('@', 1)[1]
    if domain == 'example.com':
        return False  # explicitní výjimka
    # Získat TLD
    if '.' not in domain:
        return True
    tld = domain.rsplit('.', 1)[-1]
    allowed = {'com', 'cz', 'sk', 'eu'}
    return tld not in allowed


def _compose_reminder_body(first_name: str, unsubscribe_link: str) -> str:
    return (
        f"Ahoj {first_name},\n\n"
        "Nezaznamenali jsme u tebe žádnou aktivitu za posledních 24 hodin. Přijď si udělat krátkou lekci na Knowix a udrž svou angličtinu v kondici!\n\n"
        "Otevři Knowix: https://www.knowix.cz/\n\n"
        "Pokud už nechceš dostávat tyto připomínkové emaily, klikni na odhlašovací odkaz:\n"
        f"{unsubscribe_link}\n\n"
        "Měj se,\nTeam Knowix"
    )


def _compose_reminder_bodies(first_name: str, unsubscribe_link: str):
    text_body = (
        f"Ahoj {first_name},\n\n"
        "Nezaznamenali jsme u tebe žádnou aktivitu za posledních 24 hodin. Přijď si udělat krátkou lekci na Knowix a udrž svou angličtinu v kondici!\n\n"
        "Otevři Knowix: https://www.knowix.cz/\n\n"
        "Pokud už nechceš dostávat tyto připomínkové emaily, klikni na odhlašovací odkaz:\n"
        f"{unsubscribe_link}\n\n"
        "Měj se,\nTeam Knowix"
    )

    # WebP banner (externí URL). Pozn.: některé klienty nemusí WebP zobrazit; alt text zůstává.
    hero_img_webp = "https://www.knowix.cz/static/pic/logo.webp"

    html_body = f"""
    <!doctype html>
    <html lang='cs'>
    <head>
      <meta charset='utf-8'>
      <meta name='viewport' content='width=device-width, initial-scale=1'>
      <title>Knowix připomínka</title>
      <style>
        body {{ background:#f5f7fb; margin:0; padding:20px; font-family:Arial, Helvetica, sans-serif; color:#222; }}
        .container {{ max-width:560px; margin:0 auto; background:#ffffff; border-radius:14px; overflow:hidden; box-shadow:0 6px 20px rgba(0,0,0,0.08); }}
        .hero {{ text-align:center; padding:0; background:#eaf3ff; }}
        .hero img {{ display:block; width:100%; height:auto; }}
        .content {{ padding:28px 24px; text-align:center; }}
        h1 {{ font-size:22px; margin:0 0 10px; color:#0a2540; }}
        p {{ font-size:15px; line-height:1.6; margin:0 0 16px; color:#334155; }}
        .cta {{ display:inline-block; margin-top:14px; background:#0a66c2; color:#fff !important; text-decoration:none; padding:12px 22px; border-radius:8px; font-weight:bold; }}
        .muted {{ color:#64748b; font-size:12px; margin-top:18px; }}
        .footer {{ text-align:center; color:#94a3b8; font-size:12px; padding:16px 0 0; }}
        a {{ color:#0a66c2; }}
      </style>
    </head>
    <body>
      <div class='container'>
        <div class='hero'>
          <img src='{hero_img_webp}' alt='Knowix banner' />
        </div>
        <div class='content'>
          <h1>Ahoj {first_name}, dej si dnes krátkou lekci 🎯</h1>
          <p>
            Posledních 24 hodin jsme nezaznamenali žádnou aktivitu. Jen pár minut denně udělá zázraky.
            Přijď si procvičit angličtinu a udrž si tempo.
          </p>
          <p>
            Klikni na tlačítko a pokračuj na Knowix. Máme připravené krátké úkoly přesně pro tebe.
          </p>
          <p>
            <a class='cta' href='https://www.knowix.cz/'>Pokračovat na Knowix</a>
          </p>
          <p class='muted'>
            Nechceš tyto připomínky? <a href='{unsubscribe_link}'>Odhlásit e‑maily</a> jedním kliknutím.
          </p>
        </div>
      </div>
      <div class='footer'>
        © {2025} Knowix · Tento e‑mail je informační. Prosím neodpovídej.
      </div>
    </body>
    </html>
    """
    return text_body, html_body


def _ensure_reminder_columns():
    """Idempotentně zajistí nové sloupce v tabulce users pro emailové připomínky."""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        alter_cmds = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS receive_reminder_emails TINYINT(1) NOT NULL DEFAULT 1",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_reminder_sent DATETIME NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reminder_token VARCHAR(128) NULL"
        ]
        for sql in alter_cmds:
            try:
                cur.execute(sql)
            except Exception:
                # Fallback pro starší verzi bez IF NOT EXISTS
                try:
                    base_sql = sql.replace(" IF NOT EXISTS", "")
                    cur.execute(base_sql)
                except Exception:
                    pass
        conn.commit()
        # Doplň tokeny uživatelům kde chybí
        cur.execute("SELECT id FROM users WHERE reminder_token IS NULL")
        for (uid,) in cur.fetchall():
            token = secrets.token_urlsafe(32)
            try:
                cur.execute("UPDATE users SET reminder_token = %s WHERE id = %s", (token, uid))
            except Exception:
                pass
        conn.commit()
    except Exception as ex:
        print(f"[reminders] Column ensure error: {ex}")
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _ensure_user_stats_rows():
    """Vytvoří chybějící user_stats řádky pro uživatele (minimalisticky)."""
    conn = None;
    cur = None
    try:
        conn = get_db_connection();
        cur = conn.cursor()
        cur.execute("SELECT id FROM users")
        all_users = {row[0] for row in cur.fetchall()}
        cur.execute("SELECT user_id FROM user_stats")
        existing = {row[0] for row in cur.fetchall()}
        missing = all_users - existing
        for uid in missing:
            try:
                cur.execute(
                    "INSERT INTO user_stats (user_id, total_lessons_done, correct_answers, wrong_answers, total_learning_time, last_active, total_psani_words, first_activity, AI_poslech_minut) VALUES (%s,0,0,0,0,NOW(),0,NULL,0)",
                    (uid,))
            except Exception:
                pass
        if missing:
            conn.commit()
    except Exception as ex:
        print(f"[reminders] ensure user_stats rows error: {ex}")
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _eligible_inactive_users():
    """Vrátí list tuple (user_id, email, first_name, token) pro neaktivní uživatele nad prahovou hodnotu."""
    users = []
    conn = None;
    cur = None
    try:
        conn = get_db_connection();
        cur = conn.cursor()
        query = (
            "SELECT u.id, u.email, u.first_name, u.reminder_token "
            "FROM users u JOIN user_stats us ON u.id = us.user_id "
            "WHERE u.receive_reminder_emails = 1 "
            "AND us.last_active < (NOW() - INTERVAL %s HOUR) "
            "AND (u.last_reminder_sent IS NULL OR u.last_reminder_sent < (NOW() - INTERVAL %s HOUR))"
        )
        cur.execute(query, (INACTIVITY_THRESHOLD_HOURS, INACTIVITY_THRESHOLD_HOURS))
        users = cur.fetchall()
    except Exception as ex:
        print(f"[reminders] Eligible query error: {ex}")
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return users


def _send_single_reminder(user_id: int, email: str, first_name: str, token: str):
    """Pošle jeden HTML email pro neaktivního uživatele a aktualizuje last_reminder_sent."""
    unsubscribe_link = f"https://www.knowix.cz/email/unsubscribe/{token}"
    text_body, html_body = _compose_reminder_bodies(first_name, unsubscribe_link)
    ok = send_email_html(email, "Připomínka: procvič si dnes angličtinu na Knowix", text_body, html_body)
    conn = None;
    cur = None
    try:
        conn = get_db_connection();
        cur = conn.cursor()
        cur.execute("UPDATE users SET last_reminder_sent = NOW() WHERE id = %s", (user_id,))
        conn.commit()
    except Exception as ex:
        print(f"[reminders] Update last_reminder_sent error user={user_id}: {ex}")
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return ok


def send_inactivity_reminders():
    """Hlavní funkce pro rozeslání připomínkových emailů neaktivním uživatelům."""
    _ensure_reminder_columns()
    _ensure_user_stats_rows()
    users = _eligible_inactive_users()
    sent = 0
    for uid, email, first_name, token in users:
        if not email or _should_skip_email(email):
            continue
        res = _send_single_reminder(uid, email, first_name or "student", token or "")
        if res:
            sent += 1
    print(f"[reminders] Scan hotovo, odesláno {sent} emailů / {len(users)} kandidátů")
    return sent, len(users)


def send_reminders_to_all():
    """Pošle připomínku všem uživatelům s povolenými e‑maily a nastaví last_reminder_sent=NOW()."""
    _ensure_reminder_columns()
    sent = 0
    total = 0
    conn = None;
    cur = None
    try:
        conn = get_db_connection();
        cur = conn.cursor()
        cur.execute("SELECT id, email, first_name, reminder_token FROM users WHERE receive_reminder_emails = 1")
        users = cur.fetchall()
        total = len(users)
        for uid, email, first_name, token in users:
            if not email or _should_skip_email(email):
                continue
            if not token:
                # vygeneruj token pokud chybí
                import secrets as _s
                token = _s.token_urlsafe(32)
                try:
                    cur.execute("UPDATE users SET reminder_token = %s WHERE id = %s", (token, uid))
                    conn.commit()
                except Exception:
                    pass
            if _send_single_reminder(uid, email, first_name or "student", token or ""):
                sent += 1
    except Exception as ex:
        print(f"[reminders] send_reminders_to_all error: {ex}")
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    print(f"[reminders] send_all hotovo: odesláno {sent}/{total}")
    return sent, total


def _scheduler_loop(app):
    print("[reminders] Scheduler thread start")
    while True:
        try:
            import os
            if os.getenv("EMAIL_PASSWORD"):
                send_inactivity_reminders()
            else:
                print("[reminders] EMAIL_PASSWORD není nastaven – skip rozesílku")
        except Exception as ex:
            print(f"[reminders] Scheduler iteration error: {ex}")
        time.sleep(CHECK_INTERVAL_SECONDS)


def start_reminder_scheduler(app):
    if app.config.get('_reminder_scheduler_started'):
        return
    app.config['_reminder_scheduler_started'] = True
    _ensure_reminder_columns()
    t = threading.Thread(target=_scheduler_loop, args=(app,), daemon=True)
    t.start()


@reminders_bp.route('/admin/run_reminder_scan', methods=['POST'])
def admin_run_reminder_scan():
    if session.get('user_id') != 1:
        return jsonify({'success': False, 'error': 'Přístup zamítnut.'}), 403
    sent, total = send_inactivity_reminders()
    return jsonify({'success': True, 'sent': sent, 'candidates': total})


@reminders_bp.route('/admin/reminders/send_all', methods=['POST'])
def admin_send_all():
    if session.get('user_id') != 1:
        return jsonify({'success': False, 'error': 'Přístup zamítnut.'}), 403
    sent, total = send_reminders_to_all()
    return jsonify({'success': True, 'sent': sent, 'total': total})


@reminders_bp.route('/email/unsubscribe/<token>')
def unsubscribe(token):
    conn = None;
    cur = None
    try:
        conn = get_db_connection();
        cur = conn.cursor()
        cur.execute("SELECT id, receive_reminder_emails FROM users WHERE reminder_token = %s", (token,))
        row = cur.fetchone()
        if not row:
            return render_template('unsubscribe.html', status='invalid')
        uid, current_flag = row
        if current_flag == 0:
            return render_template('unsubscribe.html', status='already')
        cur.execute("UPDATE users SET receive_reminder_emails = 0 WHERE id = %s", (uid,))
        conn.commit()
        return render_template('unsubscribe.html', status='done')
    except Exception as ex:
        print(f"[reminders] Unsubscribe error: {ex}")
        return render_template('unsubscribe.html', status='error')
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@reminders_bp.route('/email/enable', methods=['POST'])
def enable_emails():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Nepřihlášen.'}), 401
    uid = session['user_id']
    conn = None;
    cur = None
    try:
        conn = get_db_connection();
        cur = conn.cursor()
        cur.execute("UPDATE users SET receive_reminder_emails = 1 WHERE id = %s", (uid,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as ex:
        print(f"[reminders] enable error: {ex}")
        return jsonify({'success': False, 'error': 'Chyba serveru.'}), 500
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@reminders_bp.route('/email/test_reminder', methods=['GET', 'POST'])
def test_reminder():
    """Odešle zkušební připomínkový email aktuálně přihlášenému uživateli bez změny last_reminder_sent.
    - GET: volitelné ?subject=...
    - POST: JSON {"subject": "..."}
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Nepřihlášen.'}), 401
    uid = session['user_id']
    conn = None;
    cur = None
    try:
        conn = get_db_connection();
        cur = conn.cursor()
        cur.execute("SELECT email, first_name, reminder_token FROM users WHERE id = %s", (uid,))
        row = cur.fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'Uživatel nenalezen.'}), 404
        email, first_name, token = row
        if not email or _should_skip_email(email):
            return jsonify({'success': False, 'error': 'Email je filtrován.'}), 400
        if not token:
            token = secrets.token_urlsafe(32)
            try:
                cur.execute("UPDATE users SET reminder_token = %s WHERE id = %s", (token, uid))
                conn.commit()
            except Exception:
                pass
        unsubscribe_link = f"https://www.knowix.cz/email/unsubscribe/{token}"
        if request.method == 'POST':
            subject = (request.json or {}).get('subject') if request.is_json else None
        else:
            subject = request.args.get('subject')
        if not subject:
            subject = "Test: Připomínka procvičení na Knowix"
        text_body, html_body = _compose_reminder_bodies(first_name or 'student', unsubscribe_link)
        if not send_email_html(email, subject, text_body, html_body):
            return jsonify({'success': False, 'error': 'Odeslání selhalo.'}), 500
        return jsonify({'success': True, 'email': email, 'subject': subject})
    except Exception as ex:
        print(f"[reminders] test_reminder error: {ex}")
        return jsonify({'success': False, 'error': 'Chyba serveru.'}), 500
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass
