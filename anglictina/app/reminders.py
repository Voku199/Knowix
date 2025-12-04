import time
import threading
import secrets
from flask import Blueprint, session, jsonify, render_template, request
from db import get_db_connection
from auth import send_email_html
import os
import random
import json

# PyWebPush pro push notifikace
try:
    from pywebpush import webpush as _webpush, WebPushException as _WebPushException
except Exception:
    _webpush = None
    _WebPushException = Exception

VAPID_PUBLIC_KEY = os.getenv('VAPID_PUBLIC_KEY')
VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY')
VAPID_EMAIL = os.getenv('VAPID_EMAIL', 'admin@knowix.cz')

reminders_bp = Blueprint('reminders', __name__)
CHECK_INTERVAL_SECONDS = 3600  # 1 hodina

# Denní limity
MAX_EMAILS_PER_DAY = 2
MAX_PUSHES_PER_DAY = 5
MIN_PUSHES_PER_DAY = 2

# Volitelné hodiny pro odeslání e‑mailů (CSV v ENV, např. "9,13,19")
_EMAIL_HOURS_ENV = os.getenv('REMINDER_EMAIL_HOURS', '')
try:
    EMAIL_SEND_HOURS = sorted({int(h) for h in _EMAIL_HOURS_ENV.split(',') if h.strip() != ''}) or [9, 13, 19]
except Exception:
    EMAIL_SEND_HOURS = [9, 13, 19]

# Personalizované šablony push zpráv
_PUSH_TEMPLATES = [
    ("Ahoj {first}! Je čas na angličtinu 🎯", "Stačí pár minut a posuneš se dál.", "/"),
    ("{first}, nezapomeň trénovat 💪", "Dnešní lekce tě čeká!", "/daily_quest"),
    ("Angličtina volá 📞", "{first}, minutka procvičení a budeš lepší!", "/"),
    ("Quick reminder 🔔", "{first}, 5 minut angličtiny = velký pokrok!", "/song-selection"),
    ("Comeback time! 🏃", "Vrať se do formy rychlým cvičením, {first}!", "/"),
    # nové hravé varianty
    ("Mini mise pro {first} 🚀", "Odehraj si krátký quest a získáš XP!", "/daily_quest"),
    ("Poslech na 2 minuty 🎧", "{first}, dej si krátkou písničku nebo dialog.", "/song-selection"),
    ("Streak čeká na boost 🔥", "Jedno cvičení dnes = delší série zítra, {first}.", "/"),
    ("Vocabulary snack 🍪", "Ochutnej pár nových slovíček – rychlé a chutné!", "/anglictina"),
    ("Grammar flash ✨", "Mrkni na mini gramatiku, {first}. Bleskovka!", "/anglictina"),
    ("Zpátky do hry 🎮", "Klik a jedeš – 3 minuty a hotovo.", "/"),
    ("Restart dne 🌀", "Krátký trénink = lepší nálada. Go {first}!", "/"),
]


def _format_push_message(first_name: str | None) -> tuple[str, str, str]:
    f = (first_name or 'kamaráde').split()[0]
    title, body, url = random.choice(_PUSH_TEMPLATES)
    return title.format(first=f), body.format(first=f), url


def _should_skip_email(email: str) -> bool:
    """Filtrace neplatných e-mailů"""
    if not email:
        return True
    e = email.strip().lower()
    if e.startswith('anonymous') and e.endswith('@example.com'):
        return True
    if '@' not in e:
        return True
    domain = e.split('@', 1)[1]
    if domain == 'example.com':
        return False
    if '.' not in domain:
        return True
    tld = domain.rsplit('.', 1)[-1]
    allowed = {'com', 'cz', 'sk', 'eu'}
    return tld not in allowed


def _compose_reminder_email(first_name: str, unsubscribe_link: str) -> tuple:
    """Vrátí (text, html) obsah e-mailu"""
    # Více zábavných předmětů, aby nebyl pořád stejný
    subjects = [
        "Je čas na angličtinu! 🎯",
        "{first}, dáme dnes mini‑lekci? ✨",
        "Pět minut denně = velký skok 🚀",
        "Tvá angličtina se těší na comeback 🔄",
        "Coffee break s angličtinou ☕📚",
        # nové varianty
        "{first}, dnes stačí 3 minuty a máš splněno ✅",
        "Rychlá mise: 1 mini úkol a XP do kapsy 🎖️",
        "Chvilka slovíček? {first}, pojď na to 📚",
        "Nastartuj streak 🔥 – krátké cvičení stačí",
        "Poslech na dobrou náladu 🎧",
        "{first}, malý krok dnes, velký skok zítra 🚀",
        "Rozcvička pro mozek 🧠",
        "Lehká gramatika na večer ✍️",
    ]
    subject = random.choice(subjects).format(first=first_name.split()[0] if first_name else 'Kamaráde')

    # Malé tipy/cta varianty
    ctas = [
        ("Pokračovat na Knowix", "https://www.knowix.cz/"),
        ("Dnešní mini‑mise", "https://www.knowix.cz/anglictina"),
        ("Zkus písničku", "https://www.knowix.cz/song-selection"),
        # nové varianty CTA
        ("Nastartovat Daily Quest", "https://www.knowix.cz/daily_quest"),
        ("Krátké procvičení", "https://www.knowix.cz/"),
        ("Mini gramatika", "https://www.knowix.cz/anglictina"),
        ("Posílit streak", "https://www.knowix.cz/"),
    ]
    cta_text, cta_href = random.choice(ctas)

    fun_lines = [
        "Dneska stačí jen 5 minut – mozku to stačí, motivaci to stačí, a progres je jistý.",
        "Máš 2 volné minuty? Dej si rychlý poslech nebo pár vět, angličtina ti poděkuje.",
        "Bonus: každé cvičení zvedá tvůj streak a XP. Malé krůčky dělají velké věci.",
        "Tip: když nevíš co, klikni na Daily Quest – připravili jsme to za tebe.",
        "Lámání jazyků povoleno. Smích také. 😀",
        # nové hravé řádky
        "Malá porce angličtiny = velká spokojenost. 🍰",
        "Rychlá dávka slovíček a máš hotovo. ⚡",
        "Mozek si rád zacvičí – dej mu šanci. 🧠",
        "Streak roste s každým mini‑krokem. 🔥",
        "Zpátky na vlnu – klik a jedeš. 🌊",
        "Krátký poslech, dlouhá radost. 🎧",
        "Dnes nehoníme dokonalost, jen malý pokrok. ✅",
        "XP do kapsy během pár minut. 🎖️",
    ]
    fun_line = random.choice(fun_lines)

    text_body = (
        f"Ahoj {first_name},\n\n"
        "Dnes je ideální chvíle na krátké procvičení. "
        f"{fun_line}\n\n"
        f"Otevři Knowix: {cta_href}\n\n"
        "Pokud už nechceš dostávat tyto připomínkové emaily, klikni na odhlašovací odkaz:\n"
        f"{unsubscribe_link}\n\n"
        "Měj se,\nTeam Knowix"
    )

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
        .tips {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:12px; margin-top:8px; text-align:left; }}
        .cta {{ display:inline-block; margin-top:14px; background:#0a66c2; color:#fff !important; text-decoration:none; padding:12px 22px; border-radius:8px; font-weight:bold; }}
        .muted {{ color:#64748b; font-size:12px; margin-top:18px; }}
        .footer {{ text-align:center; color:#94a3b8; font-size:12px; padding:16px 0 0; }}
        a {{ color:#0a66c2; }}
      </style>
    </head>
    <body>
      <div class='container'>
        <div class='hero'>
          <img src='https://www.knowix.cz/static/pic/logo.webp' alt='Knowix banner' />
        </div>
        <div class='content'>
          <h1>{subject}</h1>
          <p>{fun_line}</p>
          <div class='tips'>
            <ul style='padding-left:18px;margin:8px 0;'>
              <li>Krátké cvičení dnes, dlouhodobý pokrok zítra 🚀</li>
              <li>Nejrychlejší start: Daily Quest nebo poslech</li>
              <li>Streaky a XP tě podrží – dej si minutu 😉</li>
            </ul>
          </div>
          <p>
            <a class='cta' href='{cta_href}'>{cta_text}</a>
          </p>
          <p class='muted'>Nechceš tyto připomínky? <a href='{unsubscribe_link}'>Odhlásit e‑maily</a> jedním kliknutím.</p>
        </div>
      </div>
      <div class='footer'>
        © {time.localtime().tm_year} Knowix · Tento e‑mail je informační. Prosím neodpírej.
      </div>
    </body>
    </html>
    """

    return text_body, html_body, subject


def _ensure_reminder_columns():
    """Zajistí potřebné sloupce v databázi"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Základní sloupce pro e-maily
        alter_cmds = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS receive_reminder_emails TINYINT(1) NOT NULL DEFAULT 1",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_reminder_sent DATETIME NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reminder_token VARCHAR(128) NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_sends_today INT NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_email_date DATE NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS push_sends_today INT NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_push_date DATE NULL"
        ]

        for sql in alter_cmds:
            try:
                cur.execute(sql)
            except Exception:
                try:
                    base_sql = sql.replace(" IF NOT EXISTS", "")
                    cur.execute(base_sql)
                except Exception:
                    pass

        # Implicitně zapnout e-maily pro všechny uživatele, kde je hodnota NULL
        try:
            cur.execute("UPDATE users SET receive_reminder_emails = 1 WHERE receive_reminder_emails IS NULL")
        except Exception:
            pass

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
        print(f"[reminders] Database setup error: {ex}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _ensure_user_stats_rows():
    """Vytvoří chybějící user_stats řádky"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
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
        print(f"[reminders] User stats setup error: {ex}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _get_email_candidates():
    """Získá kandidáty na e-mailové připomínky (bez omezení hodin a aktivity)"""
    candidates = []
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Vytvoř dnesní efektivní čítač bez potřeby denního resetu a zajisti min. 6h rozestup mezi e-maily
        cur.execute(
            """
            SELECT 
                u.id, 
                u.email, 
                COALESCE(u.first_name, ''), 
                u.reminder_token,
                CASE WHEN u.last_email_date = CURDATE() THEN u.email_sends_today ELSE 0 END AS sends_today
            FROM users u
            WHERE u.receive_reminder_emails = 1
              AND u.email IS NOT NULL
              AND (u.last_reminder_sent IS NULL OR TIMESTAMPDIFF(HOUR, u.last_reminder_sent, NOW()) >= 6)
              AND (u.last_email_date IS NULL OR u.last_email_date != CURDATE() OR u.email_sends_today < %s)
            """,
            (MAX_EMAILS_PER_DAY,)
        )

        candidates = cur.fetchall()
    except Exception as ex:
        print(f"[reminders] Get email candidates error: {ex}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    return candidates


def _get_push_candidates():
    """Získá kandidáty na push notifikace"""
    candidates = []
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
                SELECT DISTINCT u.id,
                       COALESCE(u.first_name, ''),
                       CASE WHEN u.last_push_date = CURDATE() THEN u.push_sends_today ELSE 0 END AS sends_today,
                       TIMESTAMPDIFF(HOUR, us.last_active, NOW()) as hours_inactive
                FROM users u
                JOIN user_stats us ON u.id = us.user_id
                WHERE EXISTS (SELECT 1 FROM push_subscriptions ps WHERE ps.user_id = u.id)
                  AND (u.last_push_date = CURDATE() OR u.push_sends_today < %s)
                  AND TIMESTAMPDIFF(HOUR, us.last_active, NOW()) >= 3
                  AND us.last_active IS NOT NULL
            """, (MAX_PUSHES_PER_DAY,))

        candidates = cur.fetchall()
    except Exception as ex:
        print(f"[reminders] Get push candidates error: {ex}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    return candidates


def _send_email_reminder(user_id: int, email: str, first_name: str, token: str) -> bool:
    """Pošle jeden e-mail"""
    unsubscribe_link = f"https://www.knowix.cz/email/unsubscribe/{token}"
    text_body, html_body, subject = _compose_reminder_email(first_name, unsubscribe_link)

    success = send_email_html(email, subject, text_body, html_body)

    if success:
        conn = None
        cur = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            today = time.strftime('%Y-%m-%d')
            # Pokud je nový den, nastavíme čítač na 1; jinak inkrementujeme
            cur.execute(
                """
                UPDATE users 
                SET last_reminder_sent = NOW(),
                    email_sends_today = CASE WHEN last_email_date = %s THEN email_sends_today + 1 ELSE 1 END,
                    last_email_date = %s
                WHERE id = %s
                """,
                (today, today, user_id)
            )
            conn.commit()
        except Exception as ex:
            print(f"[reminders] Update email counter error: {ex}")
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    return success


def _send_push_reminder(user_id: int, first_name: str) -> bool:
    """Pošle push notifikaci"""
    if not (_webpush and VAPID_PRIVATE_KEY and VAPID_EMAIL):
        return False

    title, body, url = _format_push_message(first_name)

    conn = None
    cur = None
    sent = False

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = %s",
            (user_id,)
        )
        subscriptions = cur.fetchall()

        for sub in subscriptions:
            try:
                subscription_info = {
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}
                }

                _webpush(
                    subscription_info=subscription_info,
                    data=json.dumps({"title": title, "body": body, "url": url}),
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": f"mailto:{VAPID_EMAIL}"}
                )
                sent = True

            except _WebPushException as ex:
                print(f"[reminders] Push send error user={user_id}: {ex}")

        if sent:
            today = time.strftime('%Y-%m-%d')
            # Reset/inkrement denního čítače podle data
            cur.execute(
                """
                UPDATE users 
                SET push_sends_today = CASE WHEN last_push_date = %s THEN push_sends_today + 1 ELSE 1 END,
                    last_push_date = %s
                WHERE id = %s
                """,
                (today, today, user_id)
            )
            conn.commit()

    except Exception as ex:
        print(f"[reminders] Push processing error: {ex}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    return sent


def _ensure_settings_table():
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                `key` VARCHAR(64) PRIMARY KEY,
                `value` VARCHAR(256) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        # Default: reminders_enabled = 1 pokud záznam neexistuje
        cur.execute("SELECT value FROM app_settings WHERE `key`='reminders_enabled'")
        row = cur.fetchone()
        if not row:
            cur.execute("INSERT INTO app_settings (`key`, `value`) VALUES ('reminders_enabled','1')")
        conn.commit()
    except Exception as ex:
        print(f"[reminders] Settings table ensure error: {ex}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# Globální cache příznaku povolení připomínek
_REMINDERS_FLAG_CACHE: dict[str, tuple[bool, float]] = {}
_FLAG_CACHE_TTL = 60  # sekundy


def _get_global_reminders_enabled() -> bool:
    # Env override (např. REMINDERS_FORCE_DISABLE=1)
    if os.getenv('REMINDERS_FORCE_DISABLE') in ('1', 'true', 'True'):  # tvrdé vypnutí
        return False
    now = time.time()
    cached = _REMINDERS_FLAG_CACHE.get('reminders_enabled')
    if cached and (now - cached[1] < _FLAG_CACHE_TTL):
        return cached[0]
    conn = None
    cur = None
    enabled = True
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT value FROM app_settings WHERE `key`='reminders_enabled'")
        row = cur.fetchone()
        if row:
            enabled = (row[0] == '1')
        _REMINDERS_FLAG_CACHE['reminders_enabled'] = (enabled, now)
    except Exception as ex:
        print(f"[reminders] Get global flag error: {ex}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return enabled


def _set_global_reminders_enabled(flag: bool) -> bool:
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE app_settings SET value=%s WHERE `key`='reminders_enabled'", ('1' if flag else '0',))
        if cur.rowcount == 0:
            cur.execute("INSERT INTO app_settings (`key`,`value`) VALUES ('reminders_enabled', %s)",
                        ('1' if flag else '0',))
        conn.commit()
        _REMINDERS_FLAG_CACHE['reminders_enabled'] = (flag, time.time())
        return True
    except Exception as ex:
        print(f"[reminders] Set global flag error: {ex}")
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def send_daily_reminders():
    """Hlavní funkce pro rozesílání denních připomínek"""
    _ensure_settings_table()  # jistota že tabulka existuje
    if not _get_global_reminders_enabled():
        print("[reminders] Skipped (globálně vypnuto)", flush=True)
        return 0, 0
    _ensure_reminder_columns()
    _ensure_user_stats_rows()
    # Zrušeno explicitní resetování čítačů – řídíme podle last_email_date/last_push_date

    emails_sent = 0
    pushes_sent = 0

    current_hour = time.localtime().tm_hour

    # E-maily: pouze ve vybraných hodinách, jinak úplně přeskočit
    email_enabled = bool(os.getenv("RESEND_API_KEY") or os.getenv("EMAIL_PASSWORD") or os.getenv("SMTP_PASSWORD"))
    if email_enabled and current_hour in EMAIL_SEND_HOURS:
        email_candidates = _get_email_candidates()
        for user_id, email, first_name, token, sends_today in email_candidates:
            if _should_skip_email(email):
                continue
            if sends_today >= MAX_EMAILS_PER_DAY:
                continue
            if _send_email_reminder(user_id, email, first_name or 'student', token):
                emails_sent += 1
    else:
        # Volitelný debug: mimo povolené hodiny
        pass

    # Push notifikace: ponecháme původní logiku s časováním a pravděpodobností
    push_hours = [9, 12, 15, 18, 21]
    if current_hour in push_hours and _webpush and VAPID_PRIVATE_KEY:
        push_candidates = _get_push_candidates()

        for user_id, first_name, sends_today, hours_inactive in push_candidates:
            probability = 0.8 if sends_today < MIN_PUSHES_PER_DAY else 0.4
            if random.random() < probability:
                if _send_push_reminder(user_id, first_name):
                    pushes_sent += 1

    print(f"[reminders] Daily reminders: {emails_sent} emails, {pushes_sent} pushes", flush=True)
    return emails_sent, pushes_sent


def _scheduler_loop(app):
    """Hlavní smyčka plánovače"""
    print("[reminders] Scheduler thread started")
    while True:
        try:
            send_daily_reminders()
        except Exception as ex:
            print(f"[reminders] Scheduler error: {ex}")
        time.sleep(CHECK_INTERVAL_SECONDS)


def start_reminder_scheduler(app):
    """Spustí plánovač připomínek"""
    if app.config.get('_reminder_scheduler_started'):
        return
    app.config['_reminder_scheduler_started'] = True
    t = threading.Thread(target=_scheduler_loop, args=(app,), daemon=True)
    t.start()


# REST API endpoints
@reminders_bp.route('/admin/run_reminder_scan', methods=['POST'])
def admin_run_reminder_scan():
    if session.get('user_id') != 1:
        return jsonify({'success': False, 'error': 'Přístup zamítnut.'}), 403
    emails_sent, pushes_sent = send_daily_reminders()
    return jsonify({
        'success': True,
        'emails_sent': emails_sent,
        'pushes_sent': pushes_sent
    })


@reminders_bp.route('/admin/email_report')
def admin_email_report():
    """Admin přehled dnešních odeslání e‑mailů/push notifikací (GET, jen user_id==1).
    Parametr all=1 zobrazí všechny uživatele, jinak jen ty s dnešním odesláním.
    """
    if session.get('user_id') != 1:
        return jsonify({'success': False, 'error': 'Přístup zamítnut.'}), 403

    show_all = request.args.get('all') == '1'

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        base_sql = (
            """
            SELECT u.id,
                   COALESCE(u.first_name, ''),
                   u.email,
                   u.last_reminder_sent,
                   CASE WHEN u.last_email_date = CURDATE() THEN u.email_sends_today ELSE 0 END AS emails_sent_today,
                   u.last_email_date,
                   CASE WHEN u.last_push_date = CURDATE() THEN u.push_sends_today ELSE 0 END AS pushes_sent_today,
                   u.last_push_date,
                   us.last_active
            FROM users u
            LEFT JOIN user_stats us ON us.user_id = u.id
            WHERE u.receive_reminder_emails = 1
            """
        )
        if not show_all:
            base_sql += " AND ((u.last_email_date = CURDATE() AND u.email_sends_today > 0) OR (u.last_push_date = CURDATE() AND u.push_sends_today > 0))"
        base_sql += " ORDER BY emails_sent_today DESC, u.last_reminder_sent DESC"
        cur.execute(base_sql)
        rows = cur.fetchall() or []

        # HTML přehled
        html = [
            "<h2>Reminders – přehled dnešních odeslání</h2>",
            f"<p>Filtr: {'všichni uživatelé' if show_all else 'pouze s dnešním odesláním'} | <a href='?all=1'>zobrazit všechny</a></p>",
            "<table border='1' cellpadding='6' cellspacing='0'>",
            "<tr><th>ID</th><th>Jméno</th><th>Email</th><th>Last email sent</th><th>Emails dnes</th><th>Last email date</th><th>Push dnes</th><th>Last push date</th><th>Last active</th></tr>"
        ]
        for r in rows:
            uid, first_name, email, last_email_dt, emails_today, last_email_date, pushes_today, last_push_date, last_active = r
            html.append(
                f"<tr><td>{uid}</td><td>{first_name}</td><td>{email}</td>"
                f"<td>{last_email_dt or ''}</td><td>{emails_today}</td><td>{last_email_date or ''}</td>"
                f"<td>{pushes_today}</td><td>{last_push_date or ''}</td><td>{last_active or ''}</td></tr>"
            )
        html.append("</table>")
        return "\n".join(html)

    except Exception as ex:
        print(f"[reminders] Admin email report error: {ex}")
        return jsonify({'success': False, 'error': 'Chyba serveru.'}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@reminders_bp.route('/admin/reminders/status')
def reminders_status():
    if session.get('user_id') != 1:
        return jsonify({'success': False, 'error': 'Přístup zamítnut.'}), 403
    return jsonify({'success': True, 'enabled': _get_global_reminders_enabled()})


@reminders_bp.route('/admin/reminders/enable', methods=['POST'])
def reminders_set_enabled():
    if session.get('user_id') != 1:
        return jsonify({'success': False, 'error': 'Přístup zamítnut.'}), 403
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get('enabled'))
    ok = _set_global_reminders_enabled(enabled)
    return jsonify({'success': ok, 'enabled': enabled})


@reminders_bp.route('/email/unsubscribe/<token>')
def unsubscribe(token):
    """Odhlášení z e-mailových připomínek"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
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
            cur.close()
        if conn:
            conn.close()


@reminders_bp.route('/email/test_reminder', methods=['POST'])
def test_reminder():
    """Testovací endpoint pro odeslání připomínky"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Nepřihlášen.'}), 401

    uid = session['user_id']
    conn = None
    cur = None
    try:
        conn = get_db_connection()
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
            cur.execute("UPDATE users SET reminder_token = %s WHERE id = %s", (token, uid))
            conn.commit()

        unsubscribe_link = f"https://www.knowix.cz/email/unsubscribe/{token}"
        text_body, html_body, subject = _compose_reminder_email(first_name or 'student', unsubscribe_link)

        if not send_email_html(email, subject, text_body, html_body):
            return jsonify({'success': False, 'error': 'Odeslání selhalo.'}), 500

        return jsonify({'success': True, 'email': email, 'subject': subject})

    except Exception as ex:
        print(f"[reminders] Test reminder error: {ex}")
        return jsonify({'success': False, 'error': 'Chyba serveru.'}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
