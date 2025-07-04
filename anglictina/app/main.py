import os

from dotenv import load_dotenv
from flask import Flask, render_template, session, send_from_directory
from flask_socketio import SocketIO

from A1_music import exercises_bp  # Add this import
from ai import ai_bp
from at_on import at_on_bp
from auth import auth_bp
from chat import zpravy_bp
from feedback import feedback_bp
# from game import game_bp
from hangman import hangman_bp
from listening import listening_bp
from main_routes import main_bp
from nepravidelna_slovesa import verbs_bp
from news import news_bp
from obchod import obchod_bp
from present_perfect import chat_bp
from review import review_bp
from roleplaying import roleplaying_bp
from streak import get_user_streak
from theme import theme_bp
from pexeso import pexeso_bp, register_socketio_handlers
# Sekce
from xp import get_user_xp_and_level
from xp import xp_bp

socketio = SocketIO()

app = Flask(__name__)
socketio.init_app(app, cors_allowed_origins="*", async_mode="eventlet")

load_dotenv(dotenv_path=".env")
app.secret_key = os.getenv("SECRET_KEY")

# Konfigurace
app.config['UPLOAD_FOLDER'] = 'static/profile_pics'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['GENIUS_ACCESS_TOKEN'] = os.getenv('GENIUS_ACCESS_TOKEN')  # Add this
app.config['DEEPL_API_KEY'] = os.getenv('DEEPL_API_KEY')  # Add this

# Registrace blueprintů
app.register_blueprint(main_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(verbs_bp)
app.register_blueprint(exercises_bp)  # Add this line
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
# app.register_blueprint(game_bp)
app.register_blueprint(pexeso_bp)


@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('templates', 'sitemap.xml')


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
    # vrátí stránku error.html s informací o výpadku
    return render_template('error.html', error_code=e.code), e.code


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
    # ✅ Content Security Policy (CSP)
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "frame-ancestors 'none';"
    )

    # ✅ HTTP Strict Transport Security (HSTS)
    response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains; preload'

    # ✅ X-Frame-Options – ochrana proti clickjackingu
    response.headers['X-Frame-Options'] = 'DENY'

    # ✅ Cross-Origin Opener Policy
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'

    # ✅ Cross-Origin Resource Policy
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'

    # ✅ X-Content-Type-Options
    response.headers['X-Content-Type-Options'] = 'nosniff'

    # ✅ Referrer Policy
    response.headers['Referrer-Policy'] = 'no-referrer-when-downgrade'

    return response


# app.run(port=5000) PRO LOCALNÍ SERVER

# =====================================================
# -------------------!!!SERVER!!!----------------------
# =====================================================
# serve(app, host="0.0.0.0", port=8080, threads=32) PRO SERVER
# socketio.run(app, host="0.0.0.0", port=5000)

register_socketio_handlers(socketio)

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)
