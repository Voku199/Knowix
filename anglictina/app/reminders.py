import time
import threading
import secrets
from flask import Blueprint, session, jsonify, render_template, request
from db import get_db_connection
from auth import send_email_html
import os
import random
import json  # doplněn import pro push JSON payload

# PyWebPush pro push notifikace (volitelné)
try:
    from pywebpush import webpush as _webpush, WebPushException as _WebPushException
except Exception:
    _webpush = None


    class _WebPushException(Exception):
        pass

VAPID_PUBLIC_KEY = os.getenv('VAPID_PUBLIC_KEY')
VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY')
VAPID_EMAIL = os.getenv('VAPID_EMAIL', 'admin@knowix.cz')

reminders_bp = Blueprint('reminders', __name__)

CHECK_INTERVAL_SECONDS = 3600  # 1 hodina
INACTIVITY_THRESHOLD_HOURS = 24  # zachováno pro kompatibilitu (1 den)
# Nové prahové hodnoty pro více stupňů (dny)
_EMAIL_STAGE_THRESHOLDS = {1: 1, 3: 3, 7: 7}


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


def _compose_reminder_bodies(first_name: str, unsubscribe_link: str, stage: int, variant: dict):
    """Vrací (text_body, html_body) pro daný stupeň neaktivity.
    variant: {'title': ..., 'lead': ..., 'cta': ..., 'subject': ...}
    """
    subject_lead = variant.get('lead', '')
    text_body = (
        f"Ahoj {first_name},\n\n"
        f"{subject_lead}\n\n"
        "Otevři Knowix: https://www.knowix.cz/\n\n"
        "Pokud už nechceš dostávat tyto připomínkové emaily, klikni na odhlašovací odkaz:\n"
        f"{unsubscribe_link}\n\n"
        "Měj se,\nTeam Knowix"
    )
    hero_img_webp = "https://www.knowix.cz/static/pic/logo.webp"
    title = variant.get('title', 'Procvič si angličtinu')
    lead = variant.get('lead', '')
    cta_label = variant.get('cta', 'Pokračovat na Knowix')
    path = variant.get('url', '/')
    full_url = f"https://www.knowix.cz{path}" if path.startswith('/') else path
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
          <h1>{title}</h1>
          <p>{lead}</p>
          <p>
            <a class='cta' href='{full_url}'>{cta_label}</a>
          </p>
          <p class='muted'>Nechceš tyto připomínky? <a href='{unsubscribe_link}'>Odhlásit e‑maily</a> jedním kliknutím.</p>
        </div>
      </div>
      <div class='footer'>
        © {2025} Knowix · Tento e‑mail je informační. Prosím neodpovídej.
      </div>
    </body>
    </html>
    """
    return text_body, html_body


# Humorné varianty pro e‑maily podle stupně (každá má subject/title/lead/cta)
_EMAIL_STAGE_VARIANTS = {
    1: [
        {
            'subject': 'Den pauzy? Dej si mini comeback na Knowix',
            'title': 'Mini pauza skončila? 🎯',
            'lead': '24 hodin bez procvičování – stačí 3 minuty a mozek si vzpomene.',
            'cta': 'Rozjet lekci',
            'url': '/daily_quest'
        },
        {
            'subject': 'Tvůj anglický streak se ptá kde jsi',
            'title': 'Streak volá 📞',
            'lead': 'Chybíš mu už jeden den. Zachraň to rychlou lekcí!',
            'cta': 'Zachránit streak',
            'url': '/'
        }
    ],
    3: [
        {
            'subject': '3 dny ticha… pojď to rozbít',
            'title': '3 dny ticha…',
            'lead': 'Angličtina zůstala stát. Jedna krátká výzva a jsi zpět v rytmu.',
            'cta': 'Dát výzvu',
            'url': '/daily_quest'
        },
        {
            'subject': 'Comeback time! 3 dny je dost',
            'title': 'Come back kid 🏃',
            'lead': 'Pauza stačila. Jeden rychlý úkol a jedeš dál!',
            'cta': 'Vrátit se',
            'url': '/'
        }
    ],
    7: [
        {
            'subject': 'Týdenní dovča? Restartni angličtinu',
            'title': 'Týdenní dovča? 🌴',
            'lead': 'Zpět do akce! Dáme si easy lekci na rozjezd.',
            'cta': 'Restart',
            'url': '/'
        },
        {
            'subject': 'Tvůj streak tě potichu judgeuje 😅',
            'title': 'Streak tě jemně soudí 😅',
            'lead': 'Zkus mu dát šanci – 1 minuta stačí a jede dál.',
            'cta': 'Dát minutu',
            'url': '/daily_quest'
        }
    ]
}


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
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reminder_token VARCHAR(128) NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_email_stage TINYINT NULL DEFAULT 0"  # nový sloupec
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
    """Vrátí list tuple (user_id, email, first_name, token, stage) pro neaktivní uživatele podle 1/3/7 dnů.
    Uživateli se nový stage pošle jen jednou (porovnání s last_email_stage)."""
    users = []
    conn = None;
    cur = None
    try:
        conn = get_db_connection();
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.id, u.email, COALESCE(u.first_name,'') AS first_name, u.reminder_token,
                   u.last_email_stage, u.last_reminder_sent, us.last_active,
                   TIMESTAMPDIFF(DAY, us.last_active, NOW()) AS days_inactive
            FROM users u
            JOIN user_stats us ON u.id = us.user_id
            WHERE u.receive_reminder_emails = 1
            """
        )
        now_stage_candidates = []
        for row in cur.fetchall():
            (uid, email, first_name, token, last_stage, last_sent, last_active, days_inactive) = row
            if email is None:
                continue
            try:
                last_stage = last_stage or 0
                # určíme cílový stage
                target_stage = 0
                if days_inactive is None:
                    continue
                if days_inactive >= _EMAIL_STAGE_THRESHOLDS[7] and last_stage < 7:
                    target_stage = 7
                elif days_inactive >= _EMAIL_STAGE_THRESHOLDS[3] and last_stage < 3:
                    target_stage = 3
                elif days_inactive >= _EMAIL_STAGE_THRESHOLDS[1] and last_stage < 1:
                    target_stage = 1
                else:
                    continue
                # throttle – pokud poslán email před méně než 12 hodinami, přeskoč
                if last_sent is not None:
                    # DB porovnání by bylo přes TIMESTAMPDIFF, zde hrubý skip (ponechá jednoduchost)
                    pass
                now_stage_candidates.append((uid, email, first_name, token, target_stage))
            except Exception:
                continue
        users = now_stage_candidates
    except Exception as ex:
        print(f"[reminders] Eligible multi-stage error: {ex}")
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


def _send_single_reminder(user_id: int, email: str, first_name: str, token: str, stage: int):
    """Pošle jeden HTML email pro neaktivního uživatele pro daný stage a aktualizuje last_reminder_sent + last_email_stage."""
    unsubscribe_link = f"https://www.knowix.cz/email/unsubscribe/{token}"
    variants = _EMAIL_STAGE_VARIANTS.get(stage, _EMAIL_STAGE_VARIANTS[1])
    variant = random.choice(variants)
    text_body, html_body = _compose_reminder_bodies(first_name, unsubscribe_link, stage, variant)
    subject = variant.get('subject', 'Procvič si angličtinu na Knowix')
    ok = send_email_html(email, subject, text_body, html_body)
    conn = None;
    cur = None
    try:
        conn = get_db_connection();
        cur = conn.cursor()
        cur.execute("UPDATE users SET last_reminder_sent = NOW(), last_email_stage = %s WHERE id = %s",
                    (stage, user_id))
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
    """Hlavní funkce pro rozeslání multi‑stage připomínkových emailů neaktivním uživatelům (1/3/7 dní)."""
    _ensure_reminder_columns()
    _ensure_user_stats_rows()
    users = _eligible_inactive_users()
    sent = 0
    for uid, email, first_name, token, stage in users:
        if not email or _should_skip_email(email):
            continue
        res = _send_single_reminder(uid, email, first_name or "student", token or "", stage)
        if res:
            sent += 1
    print(f"[reminders] Multi-stage scan hotovo, odesláno {sent} emailů / {len(users)} kandidátů")
    return sent, len(users)


def send_reminders_to_all():
    """Pošle připomínku všem uživatelům s povolenými e‑maily a nastaví last_reminder_sent=NOW().
    Pro hromadné rozeslání používáme stage=1 (neutrální varianty)."""
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
                import secrets as _s
                token = _s.token_urlsafe(32)
                try:
                    cur.execute("UPDATE users SET reminder_token = %s WHERE id = %s", (token, uid))
                    conn.commit()
                except Exception:
                    pass
            if _send_single_reminder(uid, email, first_name or "student", token or "", 1):
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


def _ensure_push_columns():
    """Zajistí sloupce pro push připomínky v tabulce users."""
    conn = None;
    cur = None
    try:
        conn = get_db_connection();
        cur = conn.cursor()
        alters = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_push_reminder_sent DATETIME NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_push_stage TINYINT NULL DEFAULT 0"
        ]
        for sql in alters:
            try:
                cur.execute(sql)
            except Exception:
                try:
                    base = sql.replace(" IF NOT EXISTS", "")
                    cur.execute(base)
                except Exception:
                    pass
        conn.commit()
    except Exception as ex:
        print(f"[reminders] push columns ensure error: {ex}")
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


def _load_inactive_pwa_users():
    """Načte kandidáty pro push: (user_id, first_name, days_since_last_active, last_push_stage, last_push_sent)."""
    rows = []
    conn = None;
    cur = None
    try:
        conn = get_db_connection();
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.id, COALESCE(u.first_name, ''),
                   TIMESTAMPDIFF(DAY, us.last_active, NOW()) AS days_inactive,
                   COALESCE(u.last_push_stage, 0) AS last_stage,
                   u.last_push_reminder_sent
            FROM users u
            JOIN user_stats us ON us.user_id = u.id
            JOIN push_subscriptions ps ON ps.user_id = u.id AND ps.installed = 1
            GROUP BY u.id
            """
        )
        rows = cur.fetchall()
    except Exception as ex:
        print(f"[reminders] load inactive pwa users error: {ex}")
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
    return rows


_HUMOR_MSGS = {
    1: [
        ("Mini pauza skončila?", "Dej si 3 minuty angličtiny a streak bude happy.", "/daily_quest"),
        ("Streak volá 📞", "Chybíš mu už jeden den. Zachraň to rychlou lekcí!", "/"),
        ("Angličtina na tebe mrká 😉", "Jenom pár slovíček a jsi zpět v rytmu.", "/anglictina")
    ],
    3: [
        ("3 dny ticha…", "Pojď to rozbít – dej si písničku nebo chat a vrať se do hry.", "/music"),
        ("Je čas oprášit slovíčka", "Krátká výzva a pocit vítězství zaručen.", "/daily_quest"),
        ("Come back kid 🏃", "3 dny pauza stačily. Jeden rychlý úkol a jedeš dál!", "/")
    ],
    7: [
        ("Týdenní dovča? 🌴", "Zpět do akce! Dáme si easy lekci na rozjezd.", "/"),
        ("Tvůj streak tě potichu judgeuje 😅", "Zkus mu dát šanci – 1 minuta stačí.", "/daily_quest"),
        ("Chat buddy se nudí 💬", "Napiš mu pár vět a rozmluv se.", "/chat/intro")
    ]
}


def _choose_msg(stage: int):
    arr = _HUMOR_MSGS.get(stage, _HUMOR_MSGS[1])
    return random.choice(arr)


def _send_push_to_user(user_id: int, title: str, body: str, url: str) -> tuple[int, int]:
    if not (_webpush and VAPID_PRIVATE_KEY and VAPID_EMAIL):
        return 0, 0
    conn = None;
    cur = None
    sent = 0;
    failed = 0
    try:
        conn = get_db_connection();
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE user_id=%s AND installed=1",
                    (user_id,))
        subs = cur.fetchall()
        for s in subs:
            sub = {
                "endpoint": s["endpoint"],
                "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}
            }
            try:
                _webpush(
                    subscription_info=sub,
                    data=json.dumps({"title": title, "body": body, "url": url}),
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": f"mailto:{VAPID_EMAIL}"}
                )
                sent += 1
            except _WebPushException as ex:
                print(f"[reminders] webpush error uid={user_id}: {ex}")
                failed += 1
    except Exception as ex:
        print(f"[reminders] fetch subs error uid={user_id}: {ex}")
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
    return sent, failed


def send_push_inactivity_reminders():
    """Pošle pushy podle 1/3/7 dnů neaktivity jen uživatelům s PWA."""
    _ensure_push_columns()
    if not (_webpush and VAPID_PRIVATE_KEY and VAPID_EMAIL):
        print("[reminders] Push not configured – skip push scan")
        return 0, 0

    rows = _load_inactive_pwa_users()
    total = 0
    sent_total = 0

    for uid, first_name, days_inactive, last_stage, last_sent in rows:
        target_stage = 0
        if days_inactive >= 7 and (last_stage or 0) < 7:
            target_stage = 7
        elif days_inactive >= 3 and (last_stage or 0) < 3:
            target_stage = 3
        elif days_inactive >= 1 and (last_stage or 0) < 1:
            target_stage = 1
        else:
            continue
        # throttling: pokud jsme poslali v posledních 20 hodinách, přeskoč
        try:
            if last_sent is not None:
                # Python-side delta kontrola necháme databázi – pro zjednodušení jen posíláme
                pass
        except Exception:
            pass

        title, body, url = _choose_msg(target_stage)
        s, f = _send_push_to_user(uid, title, body, url)
        total += 1
        if s > 0:
            sent_total += s
            # update user stage
            conn = None;
            cur = None
            try:
                conn = get_db_connection();
                cur = conn.cursor()
                cur.execute("UPDATE users SET last_push_stage=%s, last_push_reminder_sent=NOW() WHERE id=%s",
                            (target_stage, uid))
                conn.commit()
            except Exception as ex:
                print(f"[reminders] update push stage error uid={uid}: {ex}")
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

    print(f"[reminders] Push scan hotovo: zasláno {sent_total} pushů / {total} uživatelů (kandidáti s PWA)")
    return sent_total, total


def _scheduler_loop(app):
    print("[reminders] Scheduler thread start")
    while True:
        try:
            import os
            # E-maily dle konfigurace
            if os.getenv("EMAIL_PASSWORD"):
                send_inactivity_reminders()
            else:
                print("[reminders] EMAIL_PASSWORD není nastaven – skip rozesílku")
            # Push připomínky vždy zkusíme (pokud je konfigurace VAPID)
            try:
                send_push_inactivity_reminders()
            except Exception as ex:
                print(f"[reminders] Push scheduler error: {ex}")
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
    """Odešle zkušební multi‑stage email (default stage=1) aktuálně přihlášenému uživateli bez změny last_email_stage.
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
        stage = 1
        variant = random.choice(_EMAIL_STAGE_VARIANTS.get(stage, _EMAIL_STAGE_VARIANTS[1]))
        text_body, html_body = _compose_reminder_bodies(first_name or 'student', unsubscribe_link, stage, variant)
        if not subject:
            subject = variant.get('subject', 'Test: Procvičení na Knowix')
        if not send_email_html(email, subject, text_body, html_body):
            return jsonify({'success': False, 'error': 'Odeslání selhalo.'}), 500
        return jsonify({'success': True, 'email': email, 'subject': subject, 'stage': stage})
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
