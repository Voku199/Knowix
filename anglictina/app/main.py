# --- Flask and SocketIO imports ---
from dotenv import load_dotenv
from flask import Flask, render_template, session, send_from_directory, request, redirect

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
from streak import get_user_streak, update_user_streak
from theme import theme_bp
from pexeso import pexeso_bp, register_socketio_handlers
from xp import get_user_xp_and_level
from xp import xp_bp

app = Flask(__name__)

# --- SocketIO initialization with threading async_mode ---

load_dotenv(dotenv_path=".env")
app.secret_key = os.getenv("SECRET_KEY")

# Konfigurace
app.config['UPLOAD_FOLDER'] = 'static/profile_pics'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['GENIUS_ACCESS_TOKEN'] = os.getenv('GENIUS_ACCESS_TOKEN')
app.config['DEEPL_API_KEY'] = os.getenv('DEEPL_API_KEY')

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


@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('templates', 'sitemap.xml')


@app.route('/robots.txt')
def robots_txt():
    return send_from_directory('templates', 'robots.txt')


@app.before_request
def redirect_to_main_domain():
    host = request.host
    if host == "knowix.cz":
        return redirect("https://www.knowix.cz" + request.full_path, code=301)
    if host == "knowix.up.railway.app":
        return redirect("https://www.knowix.cz" + request.full_path, code=301)
    if host == "http://knowix.cz/":
        return redirect("https://www.knowix.cz" + request.full_path, code=301)


@app.context_processor
def inject_streak():
    user_id = session.get('user_id')
    if user_id:
        update_user_streak(user_id)
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
    return render_template('error.html', error_code=getattr(e, 'code', 500)), getattr(e, 'code', 500)


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
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "frame-ancestors 'none';"
    )
    response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains; preload'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer-when-downgrade'
    return response


# =====================================================
# -------------------!!!LOCAL!!!-----------------------
# =====================================================
# app.run(host="localhost", port=8080)


# =====================================================
# -------------------!!!SERVER!!!----------------------
# =====================================================
#     from waitress import serve
#     serve(app, host="0.0.0.0", port=8080)

# Registrace SocketIO handlerů pro pexeso


if __name__ == "__main__":
    from waitress import serve

    serve(app, host="0.0.0.0", port=8080)
