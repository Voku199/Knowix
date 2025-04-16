from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import random


app = Flask(__name__)


# Funkce pro připojení k databázi a získání všech nepravidelných sloves
def get_irregular_verbs():
    conn = sqlite3.connect('irregular_verbs.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM irregular_verbs')
    verbs = cursor.fetchall()
    conn.close()
    return verbs

# Funkce pro generování vět na základě nepravidelných sloves
def generate_sentence(verb):
    # Šablony vět pro různé časy
    templates = [
        f"I {verb['past_simple']} to the store yesterday.",  # Minulý čas
        f"She {verb['infinitive']} every day to school.",  # Infinitiv, přítomný čas
        f"He will {verb['infinitive']} tomorrow at 5 PM.",  # Infinitiv, budoucí čas
        f"I have {verb['past_participle']} this book already."  # Minulé příčestí
    ]

    # Náhodně vybereme jednu šablonu
    return random.choice(templates)


# Funkce pro přidání nového slovesa do databáze
def add_irregular_verb(infinitive, past_simple, past_participle, translation, sentence):
    conn = sqlite3.connect('irregular_verbs.db')
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO irregular_verbs (infinitive, past_simple, past_participle, translation, sentence)
    VALUES (?, ?, ?, ?, ?)
    ''', (infinitive, past_simple, past_participle, translation, sentence))
    conn.commit()
    conn.close()


@app.route('/')
def index():
    verbs = get_irregular_verbs()  # Načteme všechna slovesa
    return render_template('index.html', verbs=verbs)


@app.route('/test', methods=['GET', 'POST'])
def test():
    if request.method == 'POST':
        # Zpracování odpovědi
        if 'user_answer' in request.form:  # To znamená, že uživatel odeslal odpověď
            verb_id = request.form.get('verb_id')
            user_answer = request.form.get('user_answer', '').strip()

            if not user_answer:
                verbs = get_irregular_verbs()
                return render_template('test_form.html',
                                       error="Please enter an answer!",
                                       verb_id=verb_id)

            # Získání slovesa z databáze
            conn = sqlite3.connect('irregular_verbs.db')
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM irregular_verbs WHERE id = ?', (verb_id,))
            verb = cursor.fetchone()
            conn.close()

            verb_dict = {
                'id': verb[0],
                'infinitive': verb[1],
                'past_simple': verb[2],
                'past_participle': verb[3],
                'translation': verb[4],
                'sentence': verb[5]
            }

            sentence, correct_answer, tense = generate_test(verb_dict)

            if user_answer.lower() == correct_answer.lower():
                feedback = "✅ Correct!"
                is_correct = True
            else:
                feedback = f"❌ Incorrect! The correct answer was: {correct_answer}"
                is_correct = False

            return render_template('test_form.html',
                                   feedback=feedback,
                                   is_correct=is_correct,
                                   sentence=sentence,
                                   verb_id=verb_id,
                                   user_answer=user_answer,
                                   tense=tense)

        # Pokud přišel POST požadavek, ale bez odpovědi (tj. první zobrazení testu)
        verb_id = request.form.get('verb_id')
        conn = sqlite3.connect('irregular_verbs.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM irregular_verbs WHERE id = ?', (verb_id,))
        verb = cursor.fetchone()
        conn.close()

        verb_dict = {
            'id': verb[0],
            'infinitive': verb[1],
            'past_simple': verb[2],
            'past_participle': verb[3],
            'translation': verb[4],
            'sentence': verb[5]
        }

        sentence, correct_answer, tense = generate_test(verb_dict)
        return render_template('test_form.html',
                               sentence=sentence,
                               verb_id=verb_id,
                               tense=tense)

    # GET request - zobrazení výběru sloves
    verbs = get_irregular_verbs()
    return render_template('select_verb_test.html', verbs=verbs)


# Funkce pro generování testu
def generate_test(verb):
    # List of templates with their tenses and correct forms
    templates = [
        {
            'template': "I ___ to the store yesterday.",
            'tense': "past simple",
            'correct': verb['past_simple']
        },
        {
            'template': "She ___ every day to school.",
            'tense': "present simple",
            'correct': verb['infinitive']
        },
        {
            'template': "He will ___ tomorrow at 5 PM.",
            'tense': "future simple",
            'correct': verb['infinitive']
        },
        {
            'template': "I have ___ this book already.",
            'tense': "present perfect",
            'correct': verb['past_participle']
        }
    ]

    # Choose a random template
    chosen = random.choice(templates)
    return chosen['template'], chosen['correct'], chosen['tense']


@app.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        infinitive = request.form['infinitive']
        past_simple = request.form['past_simple']
        past_participle = request.form['past_participle']
        translation = request.form['translation']
        sentence = request.form['sentence']

        add_irregular_verb(infinitive, past_simple, past_participle, translation, sentence)
        return redirect(url_for('index'))

    return render_template('add.html')


if __name__ == '__main__':
    app.run(debug=True)
