from db import get_db_connection
from datetime import datetime
from flask import Blueprint, render_template, session, redirect, url_for

user_stats_bp = Blueprint('user_stats', __name__, template_folder='templates')


def ensure_user_stats_exists(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM user_stats WHERE user_id = %s", (user_id,))
    exists = cur.fetchone()
    if not exists:
        now = datetime.now()
        cur.execute(
            """
            INSERT INTO user_stats (
                user_id,
                total_lessons_done,
                correct_answers,
                wrong_answers,
                total_learning_time,
                last_active,
                total_psani_words,
                first_activity,
                hangman_words_guessed,
                irregular_verbs_guessed,
                irregular_verbs_wrong,
                pp_wrong,
                pp_maybe,
                pp_correct,
                roleplaying_cr,
                roleplaying_mb,
                roleplaying_wr,
                lis_cor,
                lis_wr,
                at_cor,
                at_wr
            ) VALUES (
                %s, 0, 0, 0, 0, %s, 0, %s,
                0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
            )
            """,
            (user_id, now, now)
        )
        conn.commit()
    cur.close()
    conn.close()


def get_simple_stats(user_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT
            correct_answers,
            wrong_answers,
            first_activity,
            last_active,
            total_lessons_done,
            total_learning_time,
            total_psani_words,
            hangman_words_guessed,
            irregular_verbs_guessed,
            irregular_verbs_wrong,
            pp_wrong,
            pp_maybe,
            pp_correct,
            roleplaying_cr,
            roleplaying_mb,
            roleplaying_wr,
            lis_cor,
            lis_wr,
            at_cor,
            at_wr
        FROM user_stats WHERE user_id = %s
        """,
        (user_id,)
    )
    stats = cur.fetchone()
    cur.close()
    conn.close()
    return stats


@user_stats_bp.route('/my_stats')
def my_stats():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    stats = get_simple_stats(user_id)
    if not stats:
        stats = {
            'correct_answers': 0,
            'wrong_answers': 0,
            'first_activity': None,
            'last_active': None,
            'total_lessons_done': 0,
            'total_learning_time': 0,
            'total_psani_words': 0,
            'hangman_words_guessed': 0,
            'irregular_verbs_guessed': 0,
            'irregular_verbs_wrong': 0,
            'pp_wrong': 0,
            'pp_maybe': 0,
            'pp_correct': 0,
            'roleplaying_cr': 0,
            'roleplaying_mb': 0,
            'roleplaying_wr': 0,
            'lis_cor': 0,
            'lis_wr': 0,
            'at_cor': 0,
            'at_wr': 0
        }
    return render_template('stats/stats.html', stats=stats)
