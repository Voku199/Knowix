"""Knowix — vstupní bod webové aplikace.

Tady se skládá celá aplikace dohromady:

1.  Konfigurace Flasku a výběr session backendu (Redis v produkci, filesystem lokálně).
2.  Import a registrace všech feature blueprintů (každý žije v routes/<oblast>/).
3.  Globální request hooky:
      - before_request: cookie pravidla podle domény, redirect na www, guest účty
      - after_request:  bezpečnostní hlavičky (CSP, HSTS, ...)
4.  Context procesory pro šablony (streak, XP, denní úkoly).
5.  Globální error handler (HTML nebo JSON podle Accept hlavičky).

Spuštění: `python main.py` (dev server na portu 9999, viz konec souboru).
"""

import _paths  # noqa: F401 — přidá core/, services/, routes/* na sys.path; musí být před lokálními importy

# --- Standardní knihovna ---
import importlib
import logging
import mimetypes
import os
import traceback
from uuid import uuid4

# --- Třetí strany ---
import redis
from dotenv import load_dotenv
from flask import (
    Flask, g, jsonify, make_response, redirect, render_template,
    request, send_from_directory, session,
)
from werkzeug.middleware.proxy_fix import ProxyFix

# --- Interní: core + services ---
from db import ensure_users_table_guest, get_db_connection, initialize_database_backend
from security_ext import init_security
from streak import get_user_streak
from worker_main import start_worker_thread

# --- Blueprinty: user ---
from auth import auth_bp, ensure_users_table
from daily_quest import daily_bp, get_daily_quests_for_user
from feedback import feedback_bp
from obchod import obchod_bp
from onboarding import onboarding_bp
from push_notifications import push_bp, test_send_push
from reminders import reminders_bp
from stats import user_stats_bp
from theme import theme_bp
from xp import get_user_xp_and_level, xp_bp

# --- Blueprinty: music ---
from A1_music import exercises_bp
from listening import listening_bp
from podcast import podcast_bp
from vlastni_music import vlastni_music_bp

# --- Blueprinty: AI ---
from ai import ai_bp
from AI_gramatika import ai_gramatika_bp
from AI_poslech import ai_poslech_bp
from chat import zpravy_bp
from roleplaying import roleplaying_bp

# --- Blueprinty: grammar ---
from at_on import at_on_bp
from nepravidelna_slovesa import verbs_bp
from present_perfect import chat_bp
from psani import psani_bp

# --- Blueprinty: games ---
from drawing import drawing_bp
from hangman import hangman_bp
from shadow_ml import shadow_ml_bp
from slovni_fotbal import slovni_bp
from wordle import wordle_bp

# --- Blueprinty: misc ---
from admin import admin_bp
from main_routes import main_bp
from news import news_bp
from prijmacky import prijmacky_bp
from proc import proc_bp
from review import review_bp
from uvidet import uvidet

# --- Blueprinty: math (hotové, ale zatím vypnuté) ---
# from math_main import math_main_bp
# from math_pocitejsam import math_pocitejsam_bp
# from math_cas import cas_bp
# from math_ulohy import math_ulohy_bp
# from math_porovnani import porovnani_bp
# from math_prevodky import prevodky_bp

# Zajisti správný MIME typ pro WebP
mimetypes.add_type('image/webp', '.webp')


# ===========================================================================
# Základní konfigurace
# ===========================================================================

app = Flask(__name__)

load_dotenv(dotenv_path=".env")
initialize_database_backend(force=True)
ensure_users_table()
ensure_users_table_guest()

app.secret_key = os.getenv("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("SECRET_KEY is missing. Set SECRET_KEY in environment.")

app.config.update(
    SESSION_COOKIE_NAME=os.getenv('SESSION_COOKIE_NAME', 'knowix_session'),
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=True,  # Přepíná se dynamicky v before_request podle hosta
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_USE_SIGNER=True,
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,  # 30 dní
    SESSION_REFRESH_EACH_REQUEST=True,
    UPLOAD_FOLDER='static/profile_pics',
    ALLOWED_EXTENSIONS={'png', 'jpg', 'jpeg', 'gif'},
    GENIUS_ACCESS_TOKEN=os.getenv('GENIUS_ACCESS_TOKEN'),
    DEEPL_API_KEY=os.getenv('DEEPL_API_KEY'),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)

# Proxy fix kvůli správnému HTTPS z pohledu Flasku (Railway běží za proxy)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)


# ===========================================================================
# Session backend: Redis v produkci, filesystem lokálně
# ===========================================================================

# Dynamický import Flask-Session — obchází konflikt s lokální složkou "flask_session"
try:
    FlaskSession = importlib.import_module('flask_session').Session
except Exception:
    FlaskSession = None

redis_url = os.getenv('REDIS_URL')
if redis_url and not os.getenv('FLASK_DEBUG'):  # Redis jen v produkci
    try:
        app.config['SESSION_TYPE'] = 'redis'
        app.config['SESSION_REDIS'] = redis.from_url(redis_url)
        app.config['SESSION_REDIS'].ping()
        print(f"[main] Session backend: Redis OK -> {redis_url}")
    except Exception as ex:
        print(f"[main] WARNING: Redis ping failed ({ex}). Falling back to filesystem sessions.")
        app.config['SESSION_TYPE'] = 'filesystem'
else:
    app.config['SESSION_TYPE'] = 'filesystem'
    print("[main] Session backend: filesystem (local development)")

if app.config['SESSION_TYPE'] == 'filesystem':
    # Adresář mimo OneDrive, aby sync nerozbíjel session soubory
    session_dir = os.path.join(os.path.expanduser("~"), "knowix_sessions")
    os.makedirs(session_dir, exist_ok=True)
    app.config['SESSION_FILE_DIR'] = session_dir
    print(f"[main] Using session directory: {session_dir}")

if FlaskSession:
    FlaskSession(app)


# ===========================================================================
# Registrace blueprintů
# ===========================================================================

BLUEPRINTS = [
    # misc / jádro webu
    main_bp, admin_bp, news_bp, prijmacky_bp, proc_bp, review_bp, uvidet,
    # user
    auth_bp, daily_bp, feedback_bp, obchod_bp, onboarding_bp, push_bp,
    reminders_bp, user_stats_bp, theme_bp, xp_bp,
    # music
    exercises_bp, listening_bp, podcast_bp, vlastni_music_bp,
    # AI
    ai_bp, ai_gramatika_bp, ai_poslech_bp, zpravy_bp, roleplaying_bp,
    # grammar
    at_on_bp, verbs_bp, chat_bp, psani_bp,
    # games
    drawing_bp, hangman_bp, shadow_ml_bp, slovni_bp, wordle_bp,
    # math (vypnuté): math_main_bp, math_pocitejsam_bp, cas_bp,
    #                  math_ulohy_bp, porovnani_bp, prevodky_bp
]

for bp in BLUEPRINTS:
    app.register_blueprint(bp)

init_security(app)

if os.getenv('START_WORKER_IN_WEB', '0') == '1':
    start_worker_thread()
else:
    print('[main] Background worker ve web procesu je vypnutý (nastav START_WORKER_IN_WEB=1 pro zapnutí).', flush=True)


# ===========================================================================
# Pomocné funkce
# ===========================================================================

def _is_private_ip(host: str) -> bool:
    """True pro privátní IP rozsahy (přístup z mobilu v lokální síti)."""
    return any(host.startswith(prefix) for prefix in (
        '192.168.', '10.', '172.16.', '172.17.', '172.18.', '172.19.',
        '172.20.', '172.21.', '172.22.', '172.23.', '172.24.', '172.25.',
        '172.26.', '172.27.', '172.28.', '172.29.', '172.30.', '172.31.',
    ))


# Placeholder heslo pro guest účty (scrypt hash — guest se přes něj nikdy nepřihlašuje)
_GUEST_PASSWORD_HASH = (
    'scrypt:32768:8:1$SZwTcXBf633lMT5B$5314fff3be13114ecbf2bff33572a6e3771287491ad73f4dda4f2f13be'
    '7493853f0badd609b3bf0a09f0c821bf55c30c9282ee46e88bcb1f38eccab9b56f5eef'
)


def _create_guest_account() -> None:
    """Založí guest účet a uloží jeho users.id do session.

    Vytvoří řádek v `users` (is_guest=1) + navázaný řádek v `guest`. Do session
    se ukládá users.id (ne guest.id), aby XP, streak a statistiky pracovaly
    s jedním konzistentním ID a nemusely řešit, že jde o hosta.
    """
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Sloupec email je NOT NULL -> unikátní placeholder
        guest_email = f"guest_{uuid4().hex[:12]}@example.com"

        # 1) "Shadow" uživatel v users, aby FK (user_stats, ...) ukazovaly na users.id
        cur.execute(
            """
            INSERT INTO users (first_name, last_name, email, password, school, is_guest, has_seen_onboarding)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            ('Guest', 'User', guest_email, _GUEST_PASSWORD_HASH, 'Knowix', 1, 0),
        )
        user_id = cur.lastrowid

        # 2) Záznam v tabulce guest odkazující na users.id
        cur.execute(
            """
            INSERT INTO guest (user_id, first_name, last_name, email, password, school, is_guest,
                               has_seen_onboarding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (user_id, 'Guest', 'User', guest_email, _GUEST_PASSWORD_HASH, 'Knowix', 1, 0),
        )
        conn.commit()

        # 3) Session drží users.id — zbytek aplikace nepozná rozdíl mezi guestem a userem
        session['user_id'] = user_id
        session['is_guest'] = True
        session['has_seen_onboarding'] = 0
        session['onboarding_step'] = 1
    except Exception as ex:
        print(f"[onboarding] WARNING: failed to create guest: {ex}")
    finally:
        try:
            if cur:
                cur.close()
            if conn:
                conn.close()
        except Exception:
            pass


# ===========================================================================
# before_request: doména, cookie pravidla, guest bootstrap
# ===========================================================================

@app.before_request
def handle_domain_and_session():
    host = request.host.split(':')[0]

    # Debug logy pro login/registraci/index
    if request.path in ('/login', '/register', '/'):
        cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
        print(
            f"[before_request] host={host} path={request.path} method={request.method} "
            f"session_keys={list(session.keys())} sid={request.cookies.get(cookie_name)}")

    # Cookie parametry podle hosta — musí být stabilní pro daný host
    if host.endswith('knowix.cz'):
        app.config['SESSION_COOKIE_DOMAIN'] = '.knowix.cz'
        app.config['SESSION_COOKIE_SECURE'] = True
    elif host in ('localhost', '127.0.0.1') or _is_private_ip(host):
        # HTTP přístup z mobilu v lokální síti -> nezabezpečené cookie povoleny
        app.config['SESSION_COOKIE_DOMAIN'] = None
        app.config['SESSION_COOKIE_SECURE'] = False
    else:
        # Ostatní hosty (např. veřejná IP v dev): respektuj schéma requestu.
        # Na HTTP musí být Secure=False, jinak prohlížeč cookie neuloží.
        app.config['SESSION_COOKIE_DOMAIN'] = None
        app.config['SESSION_COOKIE_SECURE'] = bool(request.is_secure)

    # Holou doménu přesměruj na www kvůli konzistentní cookie doméně
    if host in ("knowix.cz", "knowix.up.railway.app"):
        target = "https://www.knowix.cz" + request.full_path
        code = 308 if request.method not in ("GET", "HEAD", "OPTIONS") else 301
        return redirect(target, code=code)

    # Nepřihlášený návštěvník dostane transparentně guest účet
    if 'user_id' not in session:
        _create_guest_account()
    session.setdefault('has_seen_onboarding', 0)
    session.setdefault('onboarding_step', 1)

    # Nový guest bez onboardingu -> /welcome (jen root GET/HEAD).
    # Přihlášený (ne-guest) uživatel se sem nikdy vynuceně neposílá.
    if request.path == '/' and request.method in ('GET', 'HEAD'):
        if session.get('is_guest') and not session.get('has_seen_onboarding'):
            if request.args.get('skip_welcome') != '1':  # explicitní skip bez loopů
                return redirect('/welcome')

    # Permanentní session pro přihlášené
    if 'user_id' in session:
        session.permanent = True
        session.setdefault('_last_refresh', 0)

    # Informativní flag pro after_request
    g.session_keys_before = set(session.keys())


# ===========================================================================
# after_request: bezpečnostní hlavičky (CSP, HSTS, ...)
# ===========================================================================

# Uvolněná CSP jen pro vlastni_music_bp (embeduje YouTube přehrávač)
_CSP_VLASTNI_MUSIC = (
    "default-src 'self' https://www.youtube.com https://www.youtube-nocookie.com https://s.ytimg.com https://i.ytimg.com; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://www.youtube.com https://s.ytimg.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https://i.ytimg.com https://s.ytimg.com; "
    "frame-src https://www.youtube.com https://www.youtube-nocookie.com; "
    "object-src 'none';"
)

# Výchozí CSP pro zbytek aplikace (vč. Google Analytics, Quill, Spotify/YouTube embedů)
_CSP_DEFAULT = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
    "https://cdn.quilljs.com https://cdn.jsdelivr.net "
    "https://www.youtube.com https://s.ytimg.com "
    "https://www.googletagmanager.com https://www.google-analytics.com https://ssl.google-analytics.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.quilljs.com https://cdnjs.cloudflare.com; "
    "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
    "img-src 'self' data: https: blob: https://www.google-analytics.com https://ssl.google-analytics.com https://www.googletagmanager.com https://stats.g.doubleclick.net; "
    "connect-src 'self' https://cdn.quilljs.com https://www.google-analytics.com https://region1.google-analytics.com https://region1.analytics.google.com https://analytics.google.com https://stats.g.doubleclick.net https://www.googletagmanager.com https://fonts.googleapis.com https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
    "frame-src https://open.spotify.com https://*.spotify.com https://www.youtube-nocookie.com https://www.youtube.com https://*.youtube.com; "
    "media-src 'self' blob:; "
    "object-src 'none'; frame-ancestors 'none';"
)


@app.after_request
def add_security_headers(response):
    # Speciální režim pro vlastni_music_bp: uvolněná CSP kvůli YouTube embedu
    endpoint = request.endpoint or ''
    if endpoint.startswith('vlastni_music_bp.'):
        response.headers['Content-Security-Policy'] = _CSP_VLASTNI_MUSIC
        # Restriktivní hlavičky by komplikovaly přehrávání
        for h in ('Permissions-Policy', 'Cross-Origin-Opener-Policy',
                  'Cross-Origin-Resource-Policy', 'X-Frame-Options'):
            response.headers.pop(h, None)
        # HSTS jen na produkční doméně
        if not request.host.endswith('knowix.cz'):
            response.headers.pop('Strict-Transport-Security', None)
        return response

    # Debug logy pro login/registraci/index
    if request.path in ('/login', '/register', '/'):
        set_cookie_header = response.headers.get('Set-Cookie')
        print(
            f"[after_request] host={request.host} path={request.path} status={response.status_code} "
            f"set_cookie={'Set-Cookie' in response.headers} "
            f"cookie_domain={app.config.get('SESSION_COOKIE_DOMAIN')} "
            f"samesite={app.config.get('SESSION_COOKIE_SAMESITE')} "
            f"secure={app.config.get('SESSION_COOKIE_SECURE')} "
            f"set_cookie_header={set_cookie_header[:160] if set_cookie_header else None}")

    # Detekce prostředí
    host = request.host.split(':')[0]
    is_localhost = host in ('localhost', '127.0.0.1')
    is_prod = host.endswith('knowix.cz')
    is_https = bool(request.is_secure)

    csp = _CSP_DEFAULT
    if is_prod and is_https:
        csp += " upgrade-insecure-requests;"
    response.headers['Content-Security-Policy'] = csp

    response.headers['Permissions-Policy'] = (
        'geolocation=(), microphone=(self), camera=(), '
        'fullscreen=(self "https://www.youtube.com" "https://www.youtube-nocookie.com"), '
        'magnetometer=(), gyroscope=(self "https://www.youtube.com" "https://www.youtube-nocookie.com"), usb=(), payment=()'
    )

    # HSTS jen pro produkční HTTPS
    if is_prod and is_https:
        response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains; preload'
    else:
        response.headers.pop('Strict-Transport-Security', None)

    # COOP/CORP jen na důvěryhodných origínech; na privátní IP vypnout
    if is_prod and is_https or is_localhost:
        response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
        response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    else:
        response.headers.pop('Cross-Origin-Opener-Policy', None)
        response.headers.pop('Cross-Origin-Resource-Policy', None)

    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer-when-downgrade'
    return response


# ===========================================================================
# Context procesory pro šablony (streak, XP, denní úkoly)
# ===========================================================================

# Názvy levelů: (max_level, název) — první vyhovující řádek vyhrává
_LEVEL_NAMES = [
    (1, "Začátečník"),
    (2, "Učeň"),
    (4, "Student"),
    (5, "Pokročilý"),
    (6, "Expert Knowixu"),
    (8, "Mistr"),
    (10, "Legenda"),
    (12, "Volax"),
    (15, "Král Knowixu"),
]


def get_level_name(level):
    """Vrátí český název levelu podle tabulky _LEVEL_NAMES."""
    for max_level, name in _LEVEL_NAMES:
        if level <= max_level:
            return name
    return _LEVEL_NAMES[-1][1]


@app.context_processor
def inject_streak():
    user_id = session.get('user_id')
    if user_id:
        return dict(user_streak=get_user_streak(user_id))
    return dict(user_streak=0)


@app.context_processor
def inject_xp_info():
    user_id = session.get('user_id')
    if not user_id:
        return {}
    user_data = get_user_xp_and_level(user_id)
    xp = user_data.get("xp", 0)
    level = user_data.get("level", 1)
    xp_in_level = xp % 50  # level = 50 XP
    return dict(
        user_xp=xp,
        user_level=level,
        user_level_name=get_level_name(level),
        user_progress_percent=int((xp_in_level / 50) * 100),
        user_xp_in_level=xp_in_level,
    )


@app.context_processor
def inject_daily_quests_cp():
    user_id = session.get('user_id')
    if user_id:
        return dict(daily_quests=get_daily_quests_for_user(user_id))
    return dict(daily_quests=None)


# ===========================================================================
# Globální error handler (HTML nebo JSON podle Accept hlavičky)
# ===========================================================================

@app.errorhandler(502)
@app.errorhandler(503)
@app.errorhandler(504)
@app.errorhandler(500)
@app.errorhandler(404)
@app.errorhandler(Exception)
def server_error(e):
    code = getattr(e, 'code', 500)
    tb = traceback.format_exc()

    # Kontext requestu pro log (mimo request context nemusí existovat)
    try:
        user_id = session.get('user_id')
    except Exception:
        user_id = None
    try:
        path, method = request.path, request.method
    except Exception:
        path, method = '<no request>', '<no method>'

    logging.getLogger("main").error(
        "[main] server_error: type=%s code=%s msg=%s method=%s path=%s user_id=%s\n%s",
        type(e).__name__, code, str(e), method, path, user_id, tb,
    )

    wants_json = ('application/json' in request.headers.get('Accept', '')) or \
                 ('application/json' in request.headers.get('Content-Type', '')) or \
                 request.path.endswith('/check-answer')
    if wants_json:
        return jsonify({'error': str(e), 'code': code, 'traceback': tb}), code
    return render_template('error.html', error_code=code, error_message=str(e), error_traceback=tb), code


# ===========================================================================
# Drobné routy vlastněné přímo aplikací (statické soubory, PWA, aliasy)
# ===========================================================================

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('templates', 'sitemap.xml')


@app.route('/robots.txt')
def robots_txt():
    return send_from_directory('templates', 'robots.txt')


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


@app.route('/kontakty')
def kontakty():
    return render_template('kontakty.html')


@app.route('/offline')
def offline_page():
    """Offline fallback stránka pro PWA."""
    return render_template('offline.html')


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static'), 'favicon.ico',
        mimetype='image/vnd.microsoft.icon')


@app.route('/apple-touch-icon.png')
def apple_touch_icon():
    return send_from_directory(
        os.path.join(app.root_path, 'static'), 'apple-touch-icon.png',
        mimetype='image/png')


@app.route('/apple-touch-icon-precomposed.png')
def apple_touch_icon_precomposed():
    return send_from_directory(
        os.path.join(app.root_path, 'static'), 'apple-touch-icon.png',
        mimetype='image/png')


@app.route('/static/profile_pics/<path:filename>')
def serve_profile_pic(filename):
    """Profilovky s fallbackem na default obrázek."""
    try:
        return send_from_directory('static/profile_pics', filename)
    except Exception:
        try:
            return send_from_directory('static/profile_pics', 'default.webp')
        except Exception:
            return send_from_directory('static', 'favicon.ico')  # poslední záchrana


@app.route('/service-worker.js')
def service_worker_file():
    """Service worker na root cestě kvůli PWA scope."""
    resp = send_from_directory('static', 'service-worker.js')
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.route('/.well-known/appspecific/com.chrome.devtools.json')
def chrome_devtools_assoc():
    # Prázdný 204 místo 404 (Chrome DevTools si o soubor říká automaticky)
    return make_response('', 204)


@app.route('/send_notification', methods=['POST'])
def send_notification_alias_root():
    """Alias na testovací push notifikaci z push_notifications."""
    return test_send_push()


# ===========================================================================
# Migrace schématu users (jen MySQL — SQLite schéma je kompletní z db.py)
# ===========================================================================

def _ensure_user_columns():
    """Doplní chybějící sloupce do users; duplicitní sloupce (chyba 1060) ignoruje."""
    from db import is_sqlite_mode
    if is_sqlite_mode():
        return  # SQLite schéma je kompletní z db._ensure_sqlite_schema()
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        alters = [
            "ALTER TABLE users ADD COLUMN is_guest TINYINT(1) DEFAULT 0",
            "ALTER TABLE users ADD COLUMN has_seen_onboarding TINYINT(1) DEFAULT 0",
            "ALTER TABLE users ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        ]
        for sql in alters:
            try:
                cur.execute(sql)
                conn.commit()
            except Exception as e:
                msg = str(getattr(e, 'msg', e))
                if 'Duplicate column' in msg or '1060' in msg:
                    continue  # sloupec už existuje
                raise
        print("[main] users table columns ensured")
    except Exception as ex:
        print(f"[main] WARNING: unable to ensure users columns: {ex}")
    finally:
        try:
            if cur:
                cur.close()
            if conn:
                conn.close()
        except Exception:
            pass


_ensure_user_columns()


# ===========================================================================
# Spuštění dev serveru
# ===========================================================================

if __name__ == '__main__':
    app.run(port=9999, debug=True, host='0.0.0.0')
