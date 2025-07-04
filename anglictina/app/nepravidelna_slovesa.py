from flask import Blueprint, session, request, render_template, redirect, url_for, flash
from db import get_db_connection
import json
import random
from xp import get_user_xp_and_level, add_xp_to_user  # Přidán import add_xp_to_user
from streak import update_user_streak, get_user_streak  # <-- Přidán import streak systému

verbs_bp = Blueprint('verbs', __name__)

# Načtení dat se slovesy
with open('verbs.json', 'r') as f:
    verbs_data = json.load(f)

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


@verbs_bp.context_processor
def inject_streak():
    user_id = session.get('user_id')
    if user_id:
        streak = get_user_streak(user_id)
        return dict(user_streak=streak)
    return dict(user_streak=0)


@verbs_bp.context_processor
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


@verbs_bp.errorhandler(502)
@verbs_bp.errorhandler(503)
@verbs_bp.errorhandler(504)
@verbs_bp.errorhandler(500)
@verbs_bp.errorhandler(404)
@verbs_bp.errorhandler(Exception)
def server_error(e):
    # vrátí stránku error.html s informací o výpadku
    return render_template('error.html', error_code=e.code), e.code


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
    # Získání jiných forem aktuálního slovesa kromě správné
    other_forms = [verb_entry[form] for form in ["verb1", "verb2", "verb3"]
                   if form != correct_tense and verb_entry[form] != correct_answer]

    # Vyber jednu náhodnou jinou formu ze stejného slovesa (pokud existuje)
    same_verb_extra = random.choice(other_forms) if other_forms else None

    # Odeber správnou a přidruženou odpověď ze seznamu všech
    for val in [correct_answer, same_verb_extra]:
        if val in all_answers:
            all_answers.remove(val)

    # Zbytek doplň náhodnými špatnými odpověďmi
    needed_wrong = 3 - (1 if same_verb_extra else 0)
    wrong_answers = random.sample(all_answers, min(needed_wrong, len(all_answers)))

    # Finální seznam odpovědí
    answers = [correct_answer] + wrong_answers
    if same_verb_extra:
        answers.append(same_verb_extra)

    random.shuffle(answers)
    return answers


# Routy pro výuku
@verbs_bp.route('/anglictina/test', methods=['GET', 'POST'])
def test():
    LESSON_ID = 1
    VERBS_PER_LESSON = 6

    is_guest = 'user_id' not in session

    if request.method == 'POST':
        # 1) VÝBĚR SLOVESA
        if 'verb' in request.form or 'continue' in request.form:
            verb = request.form.get('verb')
            if not verb:
                flash("Neplatné sloveso", "error")
                return redirect(url_for('verbs.test'))

            session['current_verb'] = verb
            session['used_sentences'] = []
            session['lesson_complete'] = False
            session['correct_answers_for_verb'] = 0

            verb_entry = next((item for item in verbs_data
                               if verb in [item["verb1"], item["verb2"], item["verb3"]]), None)
            if not verb_entry:
                flash("Sloveso nenalezeno", "error")
                return redirect(url_for('verbs.test'))

            sentence, correct_answer, tense = generate_test(verb)
            if not sentence:
                flash("Žádné příklady pro toto sloveso.", "error")
                return redirect(url_for('verbs.test'))

            session['current_sentence'] = sentence
            session['current_tense'] = tense

            verbs_done = 0
            if not is_guest:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT COUNT(DISTINCT verb) 
                        FROM lesson_progress 
                        WHERE user_id = %s AND lesson_id = %s AND completed = TRUE
                    """, (session['user_id'], LESSON_ID))
                    verbs_done = cursor.fetchone()[0] or 0

            session['verbs_done'] = verbs_done

            return render_template('anglictina/form_odp.html',
                                   sentence=sentence,
                                   verb=verb,
                                   possible_answers=get_possible_answers(verb, tense),
                                   feedback=None,
                                   verbs_done=verbs_done,
                                   total_verbs=VERBS_PER_LESSON,
                                   progress_for_verb=0)

        # 2) ZPRACOVÁNÍ ODPOVĚDI
        verb = session.get('current_verb')
        user_answer = request.form.get('user_answer')

        if not verb:
            flash("Nejprve vyber sloveso.", "error")
            return redirect(url_for('verbs.test'))

        if not user_answer:
            flash("Zadej odpověď před odesláním.", "warning")
            return redirect(url_for('verbs.test'))

        verb_entry = next((item for item in verbs_data
                           if verb in [item["verb1"], item["verb2"], item["verb3"]]), None)
        if not verb_entry:
            flash("Sloveso nebylo nalezeno", "error")
            return redirect(url_for('verbs.test'))

        current_tense = session.get('current_tense')
        if not current_tense:
            flash("Chyba s časem slovesa.", "error")
            return redirect(url_for('verbs.test'))

        correct_answer = verb_entry[current_tense]
        is_correct = user_answer.strip().lower() == correct_answer.lower()
        feedback = "✅ Správně!" if is_correct else f"❌ Špatně! Správná odpověď byla: {correct_answer}"

        if is_correct:
            session['correct_answers_for_verb'] = session.get('correct_answers_for_verb', 0) + 1

            # --- XP ZA KAŽDOU SPRÁVNOU ODPOVĚĎ ---
            if not is_guest:
                result = add_xp_to_user(session['user_id'], 2)
                if "error" in result:
                    flash(f"XP se nepodařilo přidat: {result['error']}", "error")
                else:
                    flash(f"Získáváš 2 XP za správnou odpověď!", "success")
                    # --- STREAK LOGIKA ---
                    streak_info = update_user_streak(session['user_id'])
                    if streak_info and streak_info.get("status") in ("started", "continued"):
                        flash(f"🔥 Máš streak {streak_info['streak']} dní v řadě!", "streak")

            if session['correct_answers_for_verb'] >= 6 and not is_guest:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO lesson_progress (user_id, lesson_id, verb, completed)
                        VALUES (%s, %s, %s, TRUE)
                        ON DUPLICATE KEY UPDATE completed = TRUE
                    """, (session['user_id'], LESSON_ID, verb))
                    conn.commit()

                session['correct_answers_for_verb'] = 0
                session['used_sentences'] = []
                flash(f"Sloveso '{verb}' bylo úspěšně dokončeno! ✅", "success")
                return redirect(url_for('verbs.test'))

        # Update verbs_done count
        verbs_done = 0
        if not is_guest:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(DISTINCT verb) 
                    FROM lesson_progress 
                    WHERE user_id = %s AND lesson_id = %s AND completed = TRUE
                """, (session['user_id'], LESSON_ID))
                verbs_done = cursor.fetchone()[0] or 0
        session['verbs_done'] = verbs_done

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
                                   progress_for_verb=session.get('correct_answers_for_verb', 0))

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
                               progress_for_verb=session.get('correct_answers_for_verb', 0))

    # GET – výběr slovesa
    if 'lesson_complete' in session:
        flash("Lekce dokončena! 🎉", "success")
        session.pop('lesson_complete')

    verbs = sorted(set(item['verb1'] for item in verbs_data))
    verbs_done = 0

    if not is_guest:
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
