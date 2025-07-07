from flask import Blueprint, render_template, request, session, jsonify, current_app, redirect, url_for
from datetime import datetime
from db import get_db_connection
import os
import uuid
from werkzeug.utils import secure_filename
import unicodedata
import re

zpravy_bp = Blueprint('zpravy', __name__, template_folder='templates')

BANNED_WORDS = {
    "nigga", "nigger", "chcípni", "vole", "kunda", "kurva", "pica", "píca", "píča", "pica", "piča",
    "hovno", "sračka", "sracka", "kokot", "jebat", "prdel", "fuck", "shit", "bitch", "debil", "zmrd", "čurák", "curak",
    "idiot", "retard", "blbec", "mrdka", "mrdat", "zmije", "čubka", "cubka", "zasran", "zasranej", "zasrana", "zasrany",
    "píčus", "picus", "píčák", "picak", "čůrák", "curak", "čurák", "curak", "čurák", "curak", "chcípni na raka",
    "sybau",
}


def normalize_text(text):
    # Odstraní diakritiku, převede na malá písmena, odstraní speciální znaky a opakování písmen
    text = unicodedata.normalize('NFD', text)
    text = text.encode('ascii', 'ignore').decode('utf-8')
    text = text.lower()
    text = re.sub(r'[^a-z0-9]', '', text)  # odstraní vše kromě písmen a číslic
    text = re.sub(r'(.)\1{2,}', r'\1', text)  # nahradí 3+ stejná písmena za jedno (kuuurva -> kurva)
    return text


def contains_banned_word(zprava):
    norm = normalize_text(zprava)
    for word in BANNED_WORDS:
        if word in norm:
            return True
    return False


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif', 'webp'}


@zpravy_bp.route('/zpravy', methods=['GET'])
def zpravy():
    if 'user_name' not in session:
        return redirect(url_for('auth.login'))
    return render_template('chat/chat.html')


@zpravy_bp.route('/zpravy/seznam', methods=['GET'])
def zpravy_seznam():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, user_name, zprava, created_at, image_path FROM zpravy ORDER BY id DESC LIMIT 30")
    zpravy = cur.fetchall()
    cur.close()
    conn.close()
    zpravy.reverse()  # nejstarší první

    # Přidej image_url pro frontend
    for z in zpravy:
        if z["image_path"]:
            z["image_url"] = url_for('static', filename=f'zpravy_img/{z["image_path"]}')
        else:
            z["image_url"] = None
    return jsonify(zpravy)


@zpravy_bp.route('/zpravy/poslat', methods=['POST'])
def zpravy_poslat():
    if 'user_name' not in session:
        return jsonify({'error': 'Nejste přihlášeni.'}), 401

    zprava = request.form.get('zprava', '').strip()

    # Kontrola sprostých slov
    if contains_banned_word(zprava):
        return jsonify({'error': 'Zpráva obsahuje nevhodný obsah.'}), 400

    # Kontrola prázdné zprávy (text i obrázek)
    if not zprava and 'image' not in request.files:
        return jsonify({'error': 'Zpráva je prázdná.'}), 400
    if len(zprava) > 500:
        return jsonify({'error': 'Zpráva je příliš dlouhá.'}), 400

    # --- ANTI-SPAM ochrana ---
    # Uživatel může poslat max 1 zprávu za 2 sekundy
    last_sent = session.get('last_msg_sent')
    now = datetime.now().timestamp()
    if last_sent and now - last_sent < 2:
        return jsonify({'error': 'Zprávy nelze posílat tak rychle za sebou.'}), 429
    session['last_msg_sent'] = now

    # Zpracování obrázku
    image_path = None
    if 'image' in request.files:
        file = request.files['image']
        if file.filename != '':
            if allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                upload_folder = os.path.join(current_app.root_path, 'static', 'zpravy_img')
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                file_path = os.path.join(upload_folder, unique_filename)
                file.save(file_path)
                image_path = unique_filename
            else:
                return jsonify({'error': 'Nepovolený typ souboru. Povolené: PNG, JPG, JPEG, GIF, WEBP.'}), 400

    # Uložení do databáze
    user_name = session['user_name']
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO zpravy (user_name, zprava, created_at, image_path) VALUES (%s, %s, %s, %s)",
        (user_name, zprava, datetime.now(), image_path)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})
