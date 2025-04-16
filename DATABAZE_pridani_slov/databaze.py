from dotenv import load_dotenv
from flask import Flask
import os

# Načti proměnné z secret.env souboru
load_dotenv(dotenv_path="secret.env")

# Nastav SECRET_KEY
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
print(app.secret_key)  # Debug výpis
