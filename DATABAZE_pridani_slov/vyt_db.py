import sqlite3

def init_db():
    conn = sqlite3.connect('irregular_verbs.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS irregular_verbs (
        id INTEGER PRIMARY KEY,
        infinitive TEXT NOT NULL,
        past_simple TEXT NOT NULL,
        past_participle TEXT NOT NULL,
        translation TEXT NOT NULL,
        sentence TEXT NOT NULL
    )
    ''')
    conn.commit()
    conn.close()

init_db()
