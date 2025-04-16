from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import json
import random
import os
from dotenv import load_dotenv
import mysql.connector
from werkzeug.utils import secure_filename
from PIL import Image
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from random import choices
import string
import time



app = Flask(__name__)

load_dotenv(dotenv_path=".env")
app.secret_key = os.getenv("SECRET_KEY")

UPLOAD_FOLDER = 'static/profile_pics'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

users = {}  # Dočasné ukládání uživatelů (v budoucnu použij databázi)

# Načteme JSON soubor se slovesy a větami
with open('verbs.json', 'r') as f:
    verbs_data = json.load(f)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Funkce pro odeslání e-mailu (zůstává stejná)
def send_email(to_email, subject, body):
    from_email = "skolnichat.zib@gmail.com"
    from_password = os.getenv("EMAIL_PASSWORD")

    # Create email
    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        # Connect to SMTP server and send email
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(from_email, from_password)
        text = msg.as_string()
        server.sendmail(from_email, to_email, text)
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False
# Generování náhodného 8místného ověřovacího kódu
def generate_verification_code():
    return ''.join(choices(string.digits, k=8))
def get_db_connection():
    return mysql.connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASS"],
        database=os.environ["DB_NAME"],
        connection_timeout=30
    )

# Vytvoření tabulky pro uživatele
# In the init_db() function, add these tables:
def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                          id INT AUTO_INCREMENT PRIMARY KEY,
                          first_name VARCHAR(100) NOT NULL,
                          last_name VARCHAR(100) NOT NULL,
                          email VARCHAR(100) UNIQUE NOT NULL,
                          password VARCHAR(255) NOT NULL,
                          birthdate DATE,
                          profile_pic VARCHAR(255) DEFAULT 'default.jpg')''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS user_lessons (
                          id INT AUTO_INCREMENT PRIMARY KEY,
                          user_id INT NOT NULL,
                          lesson_id INT NOT NULL,
                          completed BOOLEAN DEFAULT FALSE,
                          completion_date TIMESTAMP NULL,
                          FOREIGN KEY (user_id) REFERENCES users(id))''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS lesson_progress (
                          id INT AUTO_INCREMENT PRIMARY KEY,
                          user_id INT NOT NULL,
                          lesson_id INT NOT NULL,
                          verb VARCHAR(100) NOT NULL,
                          completed BOOLEAN DEFAULT FALSE,
                          timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                          FOREIGN KEY (user_id) REFERENCES users(id))''')
        conn.commit()

init_db()  #


def get_possible_answers(verb, correct_tense):
    """Get 3 random wrong answers + the correct one"""
    verb_entry = next((item for item in verbs_data if verb in [item["verb1"], item["verb2"], item["verb3"]]), None)
    if not verb_entry:
        return []

    correct_answer = verb_entry[correct_tense]
    all_answers = []

    # Get all possible verb forms from the data
    for item in verbs_data:
        if "verb1" in item: all_answers.append(item["verb1"])
        if "verb2" in item: all_answers.append(item["verb2"])
        if "verb3" in item: all_answers.append(item["verb3"])

    # Remove duplicates and the correct answer
    all_answers = list(set(all_answers))
    if correct_answer in all_answers:
        all_answers.remove(correct_answer)

    # Select 3 random wrong answers (or less if not enough available)
    wrong_answers = random.sample(all_answers, min(3, len(all_answers)))
    answers = wrong_answers + [correct_answer]
    random.shuffle(answers)
    return answers


def generate_test(verb):
    # Find matching verb in all forms
    verb_entry = next((item for item in verbs_data
                       if verb in [item["verb1"], item["verb2"], item["verb3"]]), None)
    if not verb_entry:
        return None, None, None

    # Get used sentences from session
    used_sentences = session.get('used_sentences', [])

    # Filter examples
    available_examples = [ex for ex in verb_entry["examples"] if ex not in used_sentences]
    if not available_examples:
        return None, None, None  # No more unused examples

    # Select a random example sentence
    chosen_sentence = random.choice(available_examples)

    # Find which tense placeholder exists in the sentence
    for tense in ["verb1", "verb2", "verb3"]:
        placeholder = f"{{{tense}}}"
        if placeholder in chosen_sentence:
            correct_answer = verb_entry[tense]
            sentence = chosen_sentence.replace(placeholder, "_____", 1)

            # Save the used sentence
            used_sentences.append(chosen_sentence)
            session['used_sentences'] = used_sentences

            return sentence, correct_answer, tense

    return None, None, None


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    user_name = session.get("user_name")
    profile_pic = session.get("profile_pic", "default.jpg")
    return render_template('index.html', user_name=user_name)
# **Inicializace databáze**

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        input_data = request.form['email_or_username']

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, first_name, email 
                    FROM users 
                    WHERE email = %s OR first_name = %s
                """, (input_data, input_data))
                user = cursor.fetchone()

            if user:
                verification_code = generate_verification_code()

                # Uložení informací do session
                session['reset_user_id'] = user[0]  # ID uživatele
                session['reset_email'] = user[2]  # Email uživatele
                session['reset_code'] = verification_code
                session['code_timestamp'] = time.time()

                # Odeslání emailu
                subject = "Obnovení hesla - ověřovací kód"
                body = f"""
                Váš ověřovací kód je: {verification_code}

                Kód je platný 15 minut. Pokud jste tento kód nevyžádali, ignorujte tento email.
                """

                if send_email(user[2], subject, body):
                    flash("Ověřovací kód byl odeslán na váš e-mail.", "success")
                    return redirect(url_for('verify_code'))
                else:
                    flash("Nepodařilo se odeslat ověřovací email.", "error")
            else:
                flash("Uživatel s tímto emailem nebo jménem nebyl nalezen.", "error")

        except Exception as e:
            print(f"Chyba při obnově hesla: {str(e)}")
            flash("Došlo k neočekávané chybě. Zkuste to prosím později.", "error")

    return render_template('forgot_password.html')
# 2. Route pro zadání ověřovacího kódu
@app.route('/verify_code', methods=['GET', 'POST'])
def verify_code():
    if request.method == 'POST':
        input_code = request.form.get('verification_code')
        stored_code = session.get('reset_code')
        code_time = session.get('code_timestamp')

        # Kontrola platnosti kódu (15 minut)
        if code_time and (time.time() - code_time) > 900:  # 900 sekund = 15 minut
            flash("Ověřovací kód expiroval. Žádejte nový.", "error")
            return redirect(url_for('forgot_password'))

        if input_code and stored_code == input_code:
            session['verified'] = True
            flash("Ověření proběhlo úspěšně! Nyní můžete změnit heslo.", "success")
            return redirect(url_for('reset_password'))
        else:
            flash("Zadaný kód není správný. Zkuste to prosím znovu.", "error")
            return redirect(url_for('verify_code'))

    return render_template('verify_code.html')


@app.route('/resend_code', methods=['POST'])
def resend_code():
    if 'reset_email' not in session:
        flash("Nejprve zadejte svůj email na stránce pro obnovení hesla.", "error")
        return redirect(url_for('forgot_password'))

    try:
        verification_code = generate_verification_code()

        # Aktualizace session
        session['reset_code'] = verification_code
        session['code_timestamp'] = time.time()

        subject = "Nový ověřovací kód pro obnovení hesla"
        body = f"""
        Váš nový ověřovací kód je: {verification_code}

        Kód je platný 15 minut. Pokud jste tento kód nevyžádali, ignorujte tento email.
        """

        if send_email(session['reset_email'], subject, body):
            flash("Nový ověřovací kód byl odeslán na váš email.", "success")
        else:
            flash("Nepodařilo se odeslat nový ověřovací kód.", "error")

    except Exception as e:
        print(f"Chyba při opětovném odeslání kódu: {str(e)}")
        flash("Došlo k chybě při generování nového kódu.", "error")

    return redirect(url_for('verify_code'))


# 3. Route pro nastavení nového hesla
@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    # Ujisti se, že byl uživatel ověřen
    if not session.get('verified'):
        flash("Nejprve musíte ověřit svou totožnost.", "error")
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not new_password or not confirm_password:
            flash("Vyplňte obě pole.", "error")
            return redirect(url_for('reset_password'))

        if new_password != confirm_password:
            flash("Hesla se neshodují.", "error")
            return redirect(url_for('reset_password'))

        hashed_password = generate_password_hash(new_password)

        user_id = session.get('reset_user_id')  # Oprava: správné získání ID uživatele
        if not user_id:
            flash("Došlo k chybě, zkuste to znovu.", "error")
            return redirect(url_for('forgot_password'))

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET password = %s WHERE id = %s", (hashed_password, user_id))
            conn.commit()

        # Vyčistíme session pro reset hesla
        session.pop('reset_code', None)
        session.pop('reset_user', None)
        session.pop('verified', None)

        flash("Vaše heslo bylo úspěšně změněno, nyní se přihlaste.", "success")
        return redirect(url_for('login'))

    return render_template('reset_password.html')





@app.route('/upload_profile_pic', methods=['POST'])
def upload_profile_pic():
    if 'user_name' not in session or 'user_id' not in session:
        flash("Nejdříve se musíte přihlásit.", "warning")
        return redirect(url_for('login'))

    if 'file' not in request.files:
        flash("Žádný soubor nebyl vybrán.", "error")
        return redirect(url_for('settings'))

    file = request.files['file']

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        img = Image.open(filepath)
        img = img.resize((128, 128))
        img.save(filepath)

        session['profile_pic'] = filename

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET profile_pic = %s WHERE id = %s", (filename, session["user_id"]))
            conn.commit()

        flash("Profilová fotka byla úspěšně nahrána.", "success")
        return redirect(url_for('settings'))
    else:
        flash("Podporované formáty jsou pouze PNG, JPG, JPEG nebo GIF.", "error")
        return redirect(url_for('settings'))


@app.route('/test', methods=['GET', 'POST'])
def test():
    if 'user_id' not in session:
        flash("Pro testování se musíte přihlásit.", "warning")
        return redirect(url_for('login'))

    LESSON_ID = 1
    VERBS_PER_LESSON = 10

    if request.method == 'POST':
        # 1) VÝBĚR SLOVESA
        if 'verb' in request.form or 'continue' in request.form:
            verb = request.form.get('verb')
            if not verb:
                flash("Neplatné sloveso", "error")
                return redirect(url_for('test'))

            # Resetovat progress pro nové kolo
            session['current_verb'] = verb
            session['used_sentences'] = []
            session['lesson_complete'] = False  # Resetovat stav lekce

            verb_entry = next((item for item in verbs_data
                               if verb in [item["verb1"], item["verb2"], item["verb3"]]), None)
            if not verb_entry:
                flash("Sloveso nenalezeno", "error")
                return redirect(url_for('test'))

            sentence, correct_answer, tense = generate_test(verb)
            if not sentence:
                flash("Žádné příklady pro toto sloveso.", "error")
                return redirect(url_for('test'))

            session['current_sentence'] = sentence
            session['current_tense'] = tense

            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(DISTINCT verb) 
                    FROM lesson_progress 
                    WHERE user_id = %s AND lesson_id = %s AND completed = TRUE
                """, (session['user_id'], LESSON_ID))
                verbs_done = cursor.fetchone()[0] or 0

            session['verbs_done'] = verbs_done

            return render_template('form_odp.html',
                                   sentence=sentence,
                                   verb=verb,
                                   possible_answers=get_possible_answers(verb, tense),
                                   feedback=None,
                                   verbs_done=verbs_done,
                                   total_verbs=VERBS_PER_LESSON)

        # 2) ZPRACOVÁNÍ ODPOVĚDI
        verb = session.get('current_verb')
        user_answer = request.form.get('user_answer')

        if not verb:
            flash("Nejprve vyber sloveso.", "error")
            return redirect(url_for('test'))

        if not user_answer:
            flash("Zadej odpověď před odesláním.", "warning")
            return redirect(url_for('test'))

        verb_entry = next((item for item in verbs_data
                           if verb in [item["verb1"], item["verb2"], item["verb3"]]), None)
        if not verb_entry:
            flash("Sloveso nebylo nalezeno", "error")
            return redirect(url_for('test'))

        current_tense = session.get('current_tense')
        if not current_tense:
            flash("Chyba s časem slovesa.", "error")
            return redirect(url_for('test'))

        correct_answer = verb_entry[current_tense]
        is_correct = user_answer.strip().lower() == correct_answer.lower()
        feedback = "✅ Správně!" if is_correct else f"❌ Špatně! Správná odpověď byla: {correct_answer}"

        if is_correct:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id FROM lesson_progress 
                    WHERE user_id = %s AND lesson_id = %s AND verb = %s AND completed = TRUE
                """, (session['user_id'], LESSON_ID, verb))
                already_completed = cursor.fetchone()

                if not already_completed:
                    cursor.execute("""
                        INSERT INTO lesson_progress (user_id, lesson_id, verb, completed)
                        VALUES (%s, %s, %s, TRUE)
                        ON DUPLICATE KEY UPDATE completed = TRUE
                    """, (session['user_id'], LESSON_ID, verb))
                    conn.commit()

            # Aktualizuj počet
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(DISTINCT verb) 
                    FROM lesson_progress 
                    WHERE user_id = %s AND lesson_id = %s AND completed = TRUE
                """, (session['user_id'], LESSON_ID))
                verbs_done = cursor.fetchone()[0] or 0

            session['verbs_done'] = verbs_done

            # V části 2) ZPRACOVÁNÍ ODPOVĚDI upravte:
            if verbs_done >= VERBS_PER_LESSON:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO user_lessons (user_id, lesson_id, completed, completion_date)
                        VALUES (%s, %s, TRUE, NOW())
                        ON DUPLICATE KEY UPDATE completed = TRUE, completion_date = NOW()
                    """, (session['user_id'], LESSON_ID))
                    conn.commit()
                session['lesson_complete'] = True
            else:
                session['lesson_complete'] = False  # Umožnit pokračování

        # Další věta
        sentence, correct_answer, tense = generate_test(verb)
        if not sentence:
            session['lesson_complete'] = True  # <- TADY TO CHYBĚLO
            return render_template('form_odp.html',
                                   sentence=None,
                                   verb=verb,
                                   possible_answers=[],
                                   feedback=feedback,
                                   is_correct=is_correct,
                                   verbs_done=session.get('verbs_done', 0),
                                   total_verbs=VERBS_PER_LESSON,
                                   lesson_complete=True,
                                   no_more_sentences=True)

        session['current_sentence'] = sentence
        session['current_tense'] = tense

        return render_template('form_odp.html',
                               sentence=sentence,
                               verb=verb,
                               possible_answers=get_possible_answers(verb, tense),
                               feedback=feedback,
                               is_correct=is_correct,
                               verbs_done=session.get('verbs_done', 0),
                               total_verbs=VERBS_PER_LESSON,
                               lesson_complete=session.get('lesson_complete', False))

    # GET – výběr slovesa
    if 'lesson_complete' in session:
        flash("Lekce dokončena! 🎉", "success")
        session.pop('lesson_complete')

    verbs = sorted(set(item['verb1'] for item in verbs_data))
    verbs_done = 0
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(DISTINCT verb) 
            FROM lesson_progress 
            WHERE user_id = %s AND lesson_id = %s AND completed = TRUE
        """, (session['user_id'], LESSON_ID))
        result = cursor.fetchone()
        verbs_done = result[0] if result else 0

    return render_template('select_verb.html',
                           verbs=verbs,
                           verbs_done=verbs_done,
                           total_verbs=VERBS_PER_LESSON)


@app.route('/continue')
def continue_lesson():
    if 'user_id' not in session:
        flash("Pro pokračování se musíte přihlásit.", "warning")
        return redirect(url_for('login'))

    # Reset session variables for a new lesson
    session.pop('lesson_complete', None)
    session.pop('verbs_done', None)
    session.pop('used_sentences', None)
    session.pop('current_verb', None)
    session.pop('current_sentence', None)
    session.pop('current_tense', None)
    session.pop('verbs_done', None)  # Reset progress counter

    return redirect(url_for('test'))
# LOGIN/REGISTRACE
# 📌 **Route pro registraci**
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first_name = request.form['first_name'].strip()
        last_name = request.form['last_name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        birthdate = request.form.get('birthdate') or None

        if not first_name or not last_name or not email or not password:
            flash("Vyplňte všechna povinná pole!", "error")
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO users (first_name, last_name, email, password, birthdate) VALUES (%s, %s, %s, %s, %s)",
                    (first_name, last_name, email, hashed_password, birthdate)
                )
                conn.commit()
                flash("Registrace úspěšná! Nyní se můžete přihlásit.", "success")
                return redirect(url_for('login'))
            except mysql.connector.IntegrityError:
                flash("Tento e-mail je již zaregistrován!", "error")
                return redirect(url_for('register'))

    return render_template('registrace.html')



@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, first_name, last_name, password, profile_pic FROM users WHERE email = %s",
                           (email,))
            user = cursor.fetchone()

            if user and check_password_hash(user[3], password):
                session["user_id"] = user[0]
                session["user_name"] = f"{user[1]} {user[2]}"
                session["profile_pic"] = user[4] if user[4] else 'default.jpg'
                return redirect(url_for('index'))
            else:
                flash("Nesprávný e-mail nebo heslo!", "error")

    return render_template('login.html')

# 📌 **Route pro odhlášení**
@app.route('/logout')
def logout():
    session.clear()
    flash("Byli jste úspěšně odhlášeni.", "info")
    return redirect(url_for('index'))


@app.route('/settings')
def settings():
    if 'user_id' not in session:
        flash("Nejdřív se musíš přihlásit.", "warning")
        return redirect(url_for('login'))

    if 'profile_pic' not in session:
        session['profile_pic'] = 'default.jpg'

    return render_template('settings.html', profile_pic=session['profile_pic'])


if __name__ == '__main__':
    app.run(debug=True)