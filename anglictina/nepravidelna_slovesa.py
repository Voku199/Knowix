from flask import Blueprint, session, request, render_template, redirect, url_for, flash
from auth import get_db_connection
import json
import random
import os
import mysql.connector

verbs_bp = Blueprint('verbs', __name__)

# def init_db():
#     with get_db_connection() as conn:
#         cursor = conn.cursor()
#         cursor.execute('''CREATE TABLE IF NOT EXISTS users (
#                           id INT AUTO_INCREMENT PRIMARY KEY,
#                           first_name VARCHAR(100) NOT NULL,
#                           last_name VARCHAR(100) NOT NULL,
#                           email VARCHAR(100) UNIQUE NOT NULL,
#                           password VARCHAR(255) NOT NULL,
#                           birthdate DATE,
#                           profile_pic VARCHAR(255) DEFAULT 'default.jpg')''')
#
#         cursor.execute('''CREATE TABLE IF NOT EXISTS user_lessons (
#                           id INT AUTO_INCREMENT PRIMARY KEY,
#                           user_id INT NOT NULL,
#                           lesson_id INT NOT NULL,
#                           completed BOOLEAN DEFAULT FALSE,
#                           completion_date TIMESTAMP NULL,
#                           FOREIGN KEY (user_id) REFERENCES users(id))''')
#
#         cursor.execute('''CREATE TABLE IF NOT EXISTS lesson_progress (
#                           id INT AUTO_INCREMENT PRIMARY KEY,
#                           user_id INT NOT NULL,
#                           lesson_id INT NOT NULL,
#                           verb VARCHAR(100) NOT NULL,
#                           completed BOOLEAN DEFAULT FALSE,
#                           timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
#                           FOREIGN KEY (user_id) REFERENCES users(id))''')
#         conn.commit()
#
# init_db()  #

# Načtení dat se slovesy
with open('verbs.json', 'r') as f:
    verbs_data = json.load(f)

# Pomocné funkce
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
# Routy pro výuku
@verbs_bp.route('/anglictina/test', methods=['GET', 'POST'])
def test():
    if 'user_id' not in session:
        flash("Pro testování se musíte přihlásit.", "warning")
        return redirect(url_for('auth.login'))

    LESSON_ID = 1
    VERBS_PER_LESSON = 6

    if request.method == 'POST':
        # 1) VÝBĚR SLOVESA
        if 'verb' in request.form or 'continue' in request.form:
            verb = request.form.get('verb')
            if not verb:
                flash("Neplatné sloveso", "error")
                return redirect(url_for('test'))

            session['current_verb'] = verb
            session['used_sentences'] = []
            session['lesson_complete'] = False
            session['correct_answers_for_verb'] = 0  # >>>

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

            return render_template('anglictina//form_odp.html',
                                   sentence=sentence,
                                   verb=verb,
                                   possible_answers=get_possible_answers(verb, tense),
                                   feedback=None,
                                   verbs_done=verbs_done,
                                   total_verbs=VERBS_PER_LESSON,
                                   progress_for_verb=0)  # >>>

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
            session['correct_answers_for_verb'] = session.get('correct_answers_for_verb', 0) + 1  # >>>

            # KONTROLA 6 SPRÁVNÝCH ODPOVĚDÍ
            if session['correct_answers_for_verb'] >= 6:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO lesson_progress (user_id, lesson_id, verb, completed)
                        VALUES (%s, %s, %s, TRUE)
                        ON DUPLICATE KEY UPDATE completed = TRUE
                    """, (session['user_id'], LESSON_ID, verb))
                    conn.commit()

                # Reset všeho pro další sloveso
                session['correct_answers_for_verb'] = 0
                session['used_sentences'] = []
                flash(f"Sloveso '{verb}' bylo úspěšně dokončeno! ✅", "success")
                return redirect(url_for('test'))  # zpět na výběr nového slovesa

        # Aktualizace počtu dokončených sloves
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(DISTINCT verb) 
                FROM lesson_progress 
                WHERE user_id = %s AND lesson_id = %s AND completed = TRUE
            """, (session['user_id'], LESSON_ID))
            verbs_done = cursor.fetchone()[0] or 0

        session['verbs_done'] = verbs_done

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
            session['lesson_complete'] = False

        sentence, correct_answer, tense = generate_test(verb)
        if not sentence:
            session['lesson_complete'] = True
            return render_template('anglictina/form_odp.html',
                                   sentence=None,
                                   verb=verb,
                                   possible_answers=[],
                                   feedback=feedback,
                                   is_correct=is_correct,
                                   verbs_done=session.get('verbs_done', 0),
                                   total_verbs=VERBS_PER_LESSON,
                                   lesson_complete=True,
                                   no_more_sentences=True,
                                   progress_for_verb=session.get('correct_answers_for_verb', 0))  # >>>

        session['current_sentence'] = sentence
        session['current_tense'] = tense

        return render_template('anglictina/form_odp.html',
                               sentence=sentence,
                               verb=verb,
                               possible_answers=get_possible_answers(verb, tense),
                               feedback=feedback,
                               is_correct=is_correct,
                               verbs_done=session.get('verbs_done', 0),
                               total_verbs=VERBS_PER_LESSON,
                               lesson_complete=session.get('lesson_complete', False),
                               progress_for_verb=session.get('correct_answers_for_verb', 0))  # >>>

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

    return render_template('anglictina/select_verb.html',
                           verbs=verbs,
                           verbs_done=verbs_done,
                           total_verbs=VERBS_PER_LESSON)


@verbs_bp.route('/continue')
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
