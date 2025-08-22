# --- Flask and SocketIO imports ---
from dotenv import load_dotenv
from flask import Flask, render_template, session, send_from_directory, request, redirect, jsonify
from flask_session import Session
from streak import get_user_streak, update_user_streak
import traceback
import redis
from werkzeug.middleware.proxy_fix import ProxyFix

import os
import sys

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
from pexeso import pexeso_bp, register_socketio_handlers
from xp import get_user_xp_and_level
from xp import xp_bp
from drawing import drawing_bp
from psani import psani_bp
from stats import user_stats_bp
from admin import admin_bp
from vlastni_music import vlastni_music_bp
from proc import proc_bp

app = Flask(__name__)

# NEJDŘÍVE načti proměnné prostředí a nastav SECRET_KEY
load_dotenv(dotenv_path=".env")
app.secret_key = os.getenv("SECRET_KEY")
if not app.secret_key:
    print("[main] ERROR: SECRET_KEY is not set in environment! Session will not persist correctly.")
    raise RuntimeError("SECRET_KEY is missing. Set SECRET_KEY in environment for stable sessions.")

# Session/cookie konfigurace (bezpečná a stabilní)
app.config['SESSION_TYPE'] = 'redis'
if os.getenv('REDIS_URL'):
    app.config['SESSION_REDIS'] = redis.from_url(os.getenv('REDIS_URL'))

# Cookie základní nastavení – upraví se v before_request podle hostu
app.config['SESSION_COOKIE_NAME'] = os.getenv('SESSION_COOKIE_NAME', 'knowix_session')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_USE_SIGNER'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 60 * 60 * 24 * 30  # 30 dní
app.config['SESSION_REFRESH_EACH_REQUEST'] = True  # DŮLEŽITÉ: vynuť refresh cookies

# Respektuj proxy hlavičky (https, host, port) – důležité pro secure cookies
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# Fallback: pokud Redis není dostupný, přepnout na filesystem sessions
use_redis = False
force_fs = os.getenv('SESSION_FORCE_FILESYSTEM', '').strip() == '1'
redis_url = os.getenv('REDIS_URL')
if not force_fs and redis_url and app.config.get('SESSION_REDIS') is not None:
    try:
        app.config['SESSION_REDIS'].ping()
        use_redis = True
        print(f"[main] Session backend: Redis OK -> {redis_url}")
    except Exception as ex:
        print(f"[main] WARNING: Redis ping failed ({ex}). Falling back to filesystem sessions.")

if not use_redis:
    app.config['SESSION_TYPE'] = 'filesystem'
    if 'SESSION_REDIS' in app.config:
        app.config.pop('SESSION_REDIS', None)
    print("[main] Session backend: filesystem")

# TEPRVE NYNÍ inicializuj Flask-Session (s už nastaveným SECRET_KEY)
Session(app)
from security_ext import init_security

# Konfigurace
app.config['UPLOAD_FOLDER'] = 'static/profile_pics'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['GENIUS_ACCESS_TOKEN'] = os.getenv('GENIUS_ACCESS_TOKEN')
app.config['DEEPL_API_KEY'] = os.getenv('DEEPL_API_KEY')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # Max 2 MB upload (profilovky atd.)

# Registrace blueprintů
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
app.register_blueprint(pexeso_bp)
app.register_blueprint(drawing_bp)
app.register_blueprint(psani_bp)
app.register_blueprint(user_stats_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(vlastni_music_bp)
app.register_blueprint(proc_bp)


@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('templates', 'sitemap.xml')


@app.route('/robots.txt')
def robots_txt():
    return send_from_directory('templates', 'robots.txt')


@app.before_request
def redirect_to_main_domain():
    host = request.host.split(':')[0]

    # Debug vstupních requestů kolem loginu/registrace/indexu
    if request.path in ('/login', '/register', '/'):
        try:
            cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
            sid = request.cookies.get(cookie_name)
            print(
                f"[before_request] host={host} path={request.path} method={request.method} session_keys={list(session.keys())} sid={sid}")
        except Exception:
            pass

    # Nastav cookie doménu a secure podle hostu
    if host.endswith('knowix.cz'):
        app.config['SESSION_COOKIE_DOMAIN'] = '.knowix.cz'
        app.config['SESSION_COOKIE_SECURE'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    elif host in ('localhost', '127.0.0.1'):
        # Lokální vývoj: nepoužívej Secure, žádná doména
        app.config['SESSION_COOKIE_DOMAIN'] = None
        app.config['SESSION_COOKIE_SECURE'] = False
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # Preferovaný host – přesměrování na www
    redirect_hosts = ("knowix.cz", "knowix.up.railway.app")
    if host in redirect_hosts:
        target = "https://www.knowix.cz" + request.full_path
        code = 308 if request.method not in ("GET", "HEAD", "OPTIONS") else 301
        return redirect(target, code=code)

    # Vynucení permanentních session pro přihlášené
    if 'user_id' in session:
        session.permanent = True
        # Force session refresh to ensure cookies are sent
# Inicializace bezpečnostních rozšíření (CSRF + rate limiting)
init_security(app)

        session.modified = True


@app.route('/static/profile_pics/<path:filename>')
def serve_profile_pic(filename):
    """Slouží profile obrázky s fallbackem na default obrázek"""
    try:
        return send_from_directory('static/profile_pics', filename)
    except:
        # Fallback na default avatar pokud obrázek neexistuje
        return send_from_directory('static/pic', 'default_avatar.png')


@app.context_processor
def inject_streak():
    user_id = session.get('user_id')
    if user_id:
        streak = get_user_streak(user_id)
        return dict(user_streak=streak)
    return dict(user_streak=0)


@app.errorhandler(502)
@app.errorhandler(503)
@app.errorhandler(504)
@app.errorhandler(500)
@app.errorhandler(404)
@app.errorhandler(Exception)
def server_error(e):
    code = getattr(e, 'code', 500)
    tb = traceback.format_exc()

    # Pokud klient očekává JSON (AJAX fetch na JSON endpoint), vrať JSON místo HTML
    wants_json = ('application/json' in request.headers.get('Accept', '')) or \
                 ('application/json' in request.headers.get('Content-Type', '')) or \
                 request.path.endswith('/check-answer')
    if wants_json:
        return jsonify({
            'error': str(e),
            'code': code,
            'traceback': tb
        }), code

    return render_template(
        'error.html',
        error_code=code,
        error_message=str(e),
        error_traceback=tb
    ), code


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
        level_name = get_level_name(level)
        return dict(
            user_xp=xp,
            user_level=level,
            user_level_name=level_name,
            user_progress_percent=percent,
            user_xp_in_level=xp_in_level
        )
    return {}


@app.after_request
def add_security_headers(response):
    # Debug odchozí odpovědi pro login/registraci/index
    if request.path in ('/login', '/register', '/'):
        try:
            cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
            has_set_cookie = any(h.lower() == 'set-cookie' for h in response.headers.keys())
            set_cookie_header = response.headers.get('Set-Cookie')
            sid_req = request.cookies.get(cookie_name)
            print(
                f"[after_request] host={request.host} path={request.path} status={response.status_code} set_cookie={has_set_cookie} sid_req={sid_req} cookie_domain={app.config.get('SESSION_COOKIE_DOMAIN')} samesite={app.config.get('SESSION_COOKIE_SAMESITE')} secure={app.config.get('SESSION_COOKIE_SECURE')} set_cookie_header={set_cookie_header[:160] if set_cookie_header else None}")
        except Exception:
            pass

    # Vylepšená CSP politika s podporou pro Google Analytics a další služby
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
        "https://cdn.quilljs.com https://cdn.jsdelivr.net "
        "https://www.youtube.com https://s.ytimg.com "
        "https://www.googletagmanager.com https://www.google-analytics.com "
        "https://ssl.google-analytics.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.quilljs.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https: blob: https://www.google-analytics.com https://ssl.google-analytics.com https://www.googletagmanager.com https://stats.g.doubleclick.net; "
        "connect-src 'self' https://www.google-analytics.com https://region1.google-analytics.com https://region1.analytics.google.com https://analytics.google.com https://stats.g.doubleclick.net https://www.googletagmanager.com; "
        "frame-src https://open.spotify.com https://*.spotify.com https://www.youtube-nocookie.com https://www.youtube.com https://*.youtube.com; "
        "object-src 'none'; frame-ancestors 'none'; upgrade-insecure-requests;"
    )
    # Přidána Permissions-Policy
    response.headers['Permissions-Policy'] = (
        "geolocation=(), microphone=(), camera=(), fullscreen=(self), magnetometer=(), gyroscope=(), usb=(), payment=()"
    )

    # Ensure cookies are properly set for authenticated users
    if 'user_id' in session and request.path in ('/login', '/register'):
        response.set_cookie(
            app.config.get('SESSION_COOKIE_NAME', 'knowix_session'),
            value=session.get('_id', ''),
            domain=app.config.get('SESSION_COOKIE_DOMAIN'),
            secure=app.config.get('SESSION_COOKIE_SECURE', True),
            httponly=app.config.get('SESSION_COOKIE_HTTPONLY', True),
            samesite=app.config.get('SESSION_COOKIE_SAMESITE', 'Lax'),
            max_age=app.config.get('PERMANENT_SESSION_LIFETIME', 60 * 60 * 24 * 30)
        )

    response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains; preload'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer-when-downgrade'
    return response


# app.run(debug=True, port=5000 debug=True)
#     from waitress import serve
#
#     serve(app, host="0.0.0.0", port=8080)

if __name__ == "__main__":
    from waitress import serve

    serve(app, host="0.0.0.0", port=8080)
