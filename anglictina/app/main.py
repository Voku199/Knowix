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

# app.run(port=5000) PRO LOCALNÍ SERVER
# serve(app, host="0.0.0.0", port=8080) PRO SERVER

if __name__ == "__main__":
    app.run(port=5000)
