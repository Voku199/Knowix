# --- Flask and SocketIO imports ---
from dotenv import load_dotenv
from flask import Flask, render_template, session, send_from_directory, request, redirect, jsonify, g
# from flask_session import Session
import importlib
from streak import get_user_streak
import traceback
import redis
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import mimetypes

# Zajisti správný MIME typ pro WebP
mimetypes.add_type('image/webp', '.webp')

# Import všech blueprintů
from A1_music import exercises_bp
from ai import ai_bp
from at_on import at_on_bp
from auth import auth_bp
from chat import zpravy_bp
from feedback import feedback_bp
from hangman import hangman_bp
from listening import listening_bp
from main_routes import main_bp
from nepravidelna_slovesa import verbs_bp
from news import news_bp
from obchod import obchod_bp
from present_perfect import chat_bp
from review import review_bp
from roleplaying import roleplaying_bp
from theme import theme_bp
from xp import get_user_xp_and_level
from xp import xp_bp
from drawing import drawing_bp
from psani import psani_bp
from stats import user_stats_bp
from admin import admin_bp
from vlastni_music import vlastni_music_bp
from proc import proc_bp
from security_ext import init_security
from AI_poslech import ai_poslech_bp
from uvidet import uvidet  # QR landing page blueprint
from shadow_ml import shadow_ml_bp
from podcast import podcast_bp
from slovni_fotbal import slovni_bp
from daily_quest import daily_bp, get_daily_quests_for_user
from AI_gramatika import ai_gramatika_bp
from reminders import reminders_bp, start_reminder_scheduler  # Přidán import připomínkového systému
from push_notifications import push_bp  # PWA push notifikace blueprint

# -------- Matematiky --------------------
# from math_main import math_main_bp
# from math_pocitejsam import math_pocitejsam_bp
# from math_cas import cas_bp
# from math_ulohy import math_ulohy_bp
# from math_porovnani import porovnani_bp
# from math_prevodky import prevodky_bp

# --------- Prezentace --------------


app = Flask(__name__)

# === ZÁKLADNÍ KONFIG A SESSION BACKEND ===
load_dotenv(dotenv_path=".env")
app.secret_key = os.getenv("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("SECRET_KEY is missing. Set SECRET_KEY in environment.")

# Pokus o dynamický import Flask-Session, který obejde případný konflikt s lokální složkou "flask_session"
try:
    FlaskSession = importlib.import_module('flask_session').Session
except Exception:
    FlaskSession = None

app.config.update(
    SESSION_COOKIE_NAME=os.getenv('SESSION_COOKIE_NAME', 'knowix_session'),
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=True,  # Přepneme v before_request pro localhost
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_USE_SIGNER=True,
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,  # 30 dní
    SESSION_REFRESH_EACH_REQUEST=True,
    UPLOAD_FOLDER='static/profile_pics',
    ALLOWED_EXTENSIONS={'png', 'jpg', 'jpeg', 'gif'},
    GENIUS_ACCESS_TOKEN=os.getenv('GENIUS_ACCESS_TOKEN'),
    DEEPL_API_KEY=os.getenv('DEEPL_API_KEY'),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024
)

# Determine session backend based on environment
redis_url = os.getenv('REDIS_URL')
if redis_url and not os.getenv('FLASK_DEBUG'):  # Use Redis only in production
    try:
        app.config['SESSION_TYPE'] = 'redis'
        app.config['SESSION_REDIS'] = redis.from_url(redis_url)
        app.config['SESSION_REDIS'].ping()
        print(f"[main] Session backend: Redis OK -> {redis_url}")
    except Exception as ex:
        print(f"[main] WARNING: Redis ping failed ({ex}). Falling back to filesystem sessions.")
        app.config['SESSION_TYPE'] = 'filesystem'
else:
    # Use filesystem sessions for local development
    app.config['SESSION_TYPE'] = 'filesystem'
    print("[main] Session backend: filesystem (local development)")

# Ensure session directory exists for filesystem sessions
if app.config['SESSION_TYPE'] == 'filesystem':
    # Use a directory outside of OneDrive to avoid sync issues
    session_dir = os.path.join(os.path.expanduser("~"), "knowix_sessions")
    if not os.path.exists(session_dir):
        os.makedirs(session_dir, exist_ok=True)
    app.config['SESSION_FILE_DIR'] = session_dir
    print(f"[main] Using session directory: {session_dir}")

# Proxy fix kvůli správnému HTTPS z pohledu Flasku
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# Initialize session after all config is set
if FlaskSession:
    FlaskSession(app)

# === Registrace blueprintů ===
app.register_blueprint(main_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(verbs_bp)
app.register_blueprint(exercises_bp)
app.register_blueprint(feedback_bp)
app.register_blueprint(theme_bp)
app.register_blueprint(hangman_bp)
app.register_blueprint(news_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(at_on_bp)
app.register_blueprint(xp_bp)
app.register_blueprint(listening_bp)
app.register_blueprint(review_bp)
app.register_blueprint(obchod_bp)
app.register_blueprint(zpravy_bp)
app.register_blueprint(roleplaying_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(drawing_bp)
app.register_blueprint(psani_bp)
app.register_blueprint(user_stats_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(vlastni_music_bp)
app.register_blueprint(proc_bp)
app.register_blueprint(ai_poslech_bp)
app.register_blueprint(uvidet)  # /uvidet a /qr
app.register_blueprint(shadow_ml_bp)
app.register_blueprint(podcast_bp)
app.register_blueprint(slovni_bp)
app.register_blueprint(daily_bp)
app.register_blueprint(ai_gramatika_bp)
app.register_blueprint(reminders_bp)  # Registrace blueprintu pro unsubscribe a ruční scan
app.register_blueprint(push_bp)

# -------- Matematiky --------------------
# app.register_blueprint(math_main_bp)
# app.register_blueprint(math_pocitejsam_bp)
# app.register_blueprint(cas_bp)
# app.register_blueprint(math_ulohy_bp)
# app.register_blueprint(porovnani_bp)
# app.register_blueprint(prevodky_bp)

init_security(app)
start_reminder_scheduler(app)  # Spuštění vlákenného scheduleru (idempotentní)


# === Sitemap & robots ===
@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('templates', 'sitemap.xml')


@app.route('/kontakty')
def kontakty():
    return render_template('kontakty.html')


@app.route('/robots.txt')
def robots_txt():
    return send_from_directory('templates', 'robots.txt')


# === Offline fallback pro PWA ===
@app.route('/offline')
def offline_page():
    return render_template('offline.html')


# === BEFORE_REQUEST: doména, secure, redirect, refresh ===
@app.before_request
def handle_domain_and_session():
    host = request.host.split(':')[0]

    # Logy pro debug login/registrace/index
    if request.path in ('/login', '/register', '/'):
        cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
        print(
            f"[before_request] host={host} path={request.path} method={request.method} session_keys={list(session.keys())} sid={request.cookies.get(cookie_name)}")

    # Privátní IP rozsahy pro lokální síť (mobil -> PC)
    def _is_private_ip(h):
        return any(h.startswith(prefix) for prefix in (
            '192.168.', '10.', '172.16.', '172.17.', '172.18.', '172.19.', '172.20.', '172.21.', '172.22.', '172.23.',
            '172.24.', '172.25.', '172.26.', '172.27.', '172.28.', '172.29.', '172.30.', '172.31.'))

    # Dynamicky přenastav cookie parametry – musí být stabilní pro daný host (www i root přesměrujeme na www)
    if host.endswith('knowix.cz'):
        app.config['SESSION_COOKIE_DOMAIN'] = '.knowix.cz'
        app.config['SESSION_COOKIE_SECURE'] = True
    elif host in ('localhost', '127.0.0.1') or _is_private_ip(host):
        # Povolit nezabezpečené cookie pro lokální IP (HTTP přístup z mobilu)
        app.config['SESSION_COOKIE_DOMAIN'] = None
        app.config['SESSION_COOKIE_SECURE'] = False
    else:
        # Default pro jiné hosty (např. preview)
        app.config['SESSION_COOKIE_DOMAIN'] = None

    # Přesměruj holou doménu na www pro konzistentní cookie doménu
    if host in ("knowix.cz", "knowix.up.railway.app"):
        target = "https://www.knowix.cz" + request.full_path
        code = 308 if request.method not in ("GET", "HEAD", "OPTIONS") else 301
        return redirect(target, code=code)

    # Permanentní session pro přihlášené
    if 'user_id' in session:
        session.permanent = True
        # Lehké dotknutí se session jednou za X minut kvůli refresh cookie
        # (Flask ji po změně nebo díky SESSION_REFRESH_EACH_REQUEST obnoví)
        session.setdefault('_last_refresh', 0)
        # nepoužijeme čas – stačí existence klíče, případně by se dalo aktualizovat timestamp

    # Flag pro after_request zda byla session změněna explicitně (informativní)
    g.session_keys_before = set(session.keys())


# === Servírování profilovek s fallbackem ===
@app.route('/static/profile_pics/<path:filename>')
def serve_profile_pic(filename):
    try:
        return send_from_directory('static/profile_pics', filename)
    except Exception:
        # Bezpečný fallback
        try:
            return send_from_directory('static/profile_pics', 'default.webp')
        except Exception:
            return send_from_directory('static', 'favicon.ico')  # poslední fallback


# === Context procesory ===
@app.context_processor
def inject_streak():
    user_id = session.get('user_id')
    if user_id:
        return dict(user_streak=get_user_streak(user_id))
    return dict(user_streak=0)


LEVEL_NAMES = [
    "Začátečník", "Učeň", "Student", "Pokročilý", "Expert Knowixu", "Mistr", "Legenda", "Volax", "Král Knowixu"
]


def get_level_name(level):
    if level <= 1:
        return LEVEL_NAMES[0]
    elif level <= 2:
        return LEVEL_NAMES[1]
    elif level <= 4:
        return LEVEL_NAMES[2]
    elif level <= 5:
        return LEVEL_NAMES[3]
    elif level <= 6:
        return LEVEL_NAMES[4]
    elif level <= 8:
        return LEVEL_NAMES[5]
    elif level <= 10:
        return LEVEL_NAMES[6]
    elif level <= 12:
        return LEVEL_NAMES[7]
    elif level <= 15:
        return LEVEL_NAMES[8]
    else:
        return LEVEL_NAMES[-1]


@app.context_processor
def inject_xp_info():
    user_id = session.get('user_id')
    if user_id:
        user_data = get_user_xp_and_level(user_id)
        xp = user_data.get("xp", 0)
        level = user_data.get("level", 1)
        xp_in_level = xp % 50
        percent = int((xp_in_level / 50) * 100)
        return dict(
            user_xp=xp,
            user_level=level,
            user_level_name=get_level_name(level),
            user_progress_percent=percent,
            user_xp_in_level=xp_in_level
        )
    return {}


@app.context_processor
def inject_daily_quests_cp():
    user_id = session.get('user_id')
    if user_id:
        return dict(daily_quests=get_daily_quests_for_user(user_id))
    return dict(daily_quests=None)


# === Error handler (HTML nebo JSON) ===
@app.errorhandler(502)
@app.errorhandler(503)
@app.errorhandler(504)
@app.errorhandler(500)
@app.errorhandler(404)
@app.errorhandler(Exception)
def server_error(e):
    code = getattr(e, 'code', 500)
    tb = traceback.format_exc()
    wants_json = ('application/json' in request.headers.get('Accept', '')) or \
                 ('application/json' in request.headers.get('Content-Type', '')) or \
                 request.path.endswith('/check-answer')
    if wants_json:
        return jsonify({'error': str(e), 'code': code, 'traceback': tb}), code
    return render_template('error.html', error_code=code, error_message=str(e), error_traceback=tb), code


# === AFTER_REQUEST: bezpečnostní hlavičky + debug ===
@app.after_request
def add_security_headers(response):
    # Speciální režim: u vlastni_music_bp endpointů výrazně povolíme zdroje (embedding YouTube)
    endpoint = request.endpoint or ''
    if endpoint.startswith('vlastni_music_bp.'):
        # Minimalistická, uvolněná CSP pro tento blueprint
        response.headers['Content-Security-Policy'] = (
            "default-src 'self' https://www.youtube.com https://www.youtube-nocookie.com https://s.ytimg.com https://i.ytimg.com; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://www.youtube.com https://s.ytimg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://i.ytimg.com https://s.ytimg.com; "
            "frame-src https://www.youtube.com https://www.youtube-nocookie.com; "
            "object-src 'none';"
        )
        # Odstraníme restriktivní hlavičky které mohou komplikovat přehrávání
        for h in (
                'Permissions-Policy', 'Cross-Origin-Opener-Policy', 'Cross-Origin-Resource-Policy',
                'X-Frame-Options'
        ):
            response.headers.pop(h, None)
        # HSTS necháme jen pokud je produkce na doméně
        if not request.host.endswith('knowix.cz'):
            response.headers.pop('Strict-Transport-Security', None)
        return response

    if request.path in ('/login', '/register', '/'):
        cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
        set_cookie_header = response.headers.get('Set-Cookie')
        print(
            f"[after_request] host={request.host} path={request.path} status={response.status_code} set_cookie={'Set-Cookie' in response.headers} cookie_domain={app.config.get('SESSION_COOKIE_DOMAIN')} samesite={app.config.get('SESSION_COOKIE_SAMESITE')} secure={app.config.get('SESSION_COOKIE_SECURE')} set_cookie_header={set_cookie_header[:160] if set_cookie_header else None}")

    # CSP (rozšířená o GA domény) – pokud něco chybí, doplnit zde
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
        "https://cdn.quilljs.com https://cdn.jsdelivr.net "
        "https://www.youtube.com https://s.ytimg.com "
        "https://www.googletagmanager.com https://www.google-analytics.com https://ssl.google-analytics.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.quilljs.com https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: https: blob: https://www.google-analytics.com https://ssl.google-analytics.com https://www.googletagmanager.com https://stats.g.doubleclick.net; "
        "connect-src 'self' https://www.google-analytics.com https://region1.google-analytics.com https://region1.analytics.google.com https://analytics.google.com https://stats.g.doubleclick.net https://www.googletagmanager.com https://fonts.googleapis.com https://fonts.gstatic.com; "
        "frame-src https://open.spotify.com https://*.spotify.com https://www.youtube-nocookie.com https://www.youtube.com https://*.youtube.com; "
        "media-src 'self' blob:; "
        "object-src 'none'; frame-ancestors 'none'; upgrade-insecure-requests;"
    )
    response.headers['Permissions-Policy'] = (
        'geolocation=(), microphone=(self), camera=(), '
        'fullscreen=(self "https://www.youtube.com" "https://www.youtube-nocookie.com"), '
        'magnetometer=(), gyroscope=(self "https://www.youtube.com" "https://www.youtube-nocookie.com"), usb=(), payment=()'
    )
    response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains; preload'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer-when-downgrade'
    return response


# === Static SW na root cestě kvůli scope ===
@app.route('/service-worker.js')
def service_worker_file():
    resp = send_from_directory('static', 'service-worker.js')
    # Zajistí root scope bez chyb
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


# app.run(port=5000, debug=True)

# from waitress import serve

# serve(app, host="0.0.0.0", port=8080, threads=24, backlog=100)


# === Spuštění aplikace ===+%12
from waitress import serve

serve(app, host="0.0.0.0", port=8080, threads=24, backlog=100)
