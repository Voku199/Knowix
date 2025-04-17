from flask import Flask
from auth import auth_bp
from nepravidelna_slovesa import verbs_bp
from main_routes import main_bp

import os
from dotenv import load_dotenv

app = Flask(__name__)
load_dotenv(dotenv_path=".env")
app.secret_key = os.getenv("SECRET_KEY")

# Konfigurace
app.config['UPLOAD_FOLDER'] = 'static/profile_pics'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}

# Registrace blueprintů
app.register_blueprint(main_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(verbs_bp)

if __name__ == '__main__':
    app.run(debug=True)