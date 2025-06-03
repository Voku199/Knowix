from waitress import serve
from flask import Flask, current_app

from auth import auth_bp
from nepravidelna_slovesa import verbs_bp
from main_routes import main_bp
from A1_music import exercises_bp  # Add this import
from feedback import feedback_bp
from hangman import hangman_bp
from theme import theme_bp
from news import news_bp
from present_perfect import chat_bp
from at_on import at_on_bp
from listening import listening_bp
from flask import after_this_request

import os
from dotenv import load_dotenv

app = Flask(__name__)
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
app.register_blueprint(listening_bp)


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
# serve(app, host="0.0.0.0", port=8080) PRO SERVER

if __name__ == "__main__":
    app.run(port=5000)
