from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for

# Import centrálni XP a streak systém
try:
    from xp import add_xp_to_user
except Exception:
    add_xp_to_user = None

try:
    from streak import update_user_streak
except Exception:
    update_user_streak = None

from user_stats import update_user_stats

podcast_bp = Blueprint('podcast_bp', __name__)

from pathlib import Path

STATIC_PODCAST_DIR = Path(__file__).resolve().parent / 'static' / 'podcast'
LRC_DIR = STATIC_PODCAST_DIR / 'lrc'
MP3_DIR = STATIC_PODCAST_DIR / 'mp3'


def _list_podcasts():
    mp3s = {p.stem: p.name for p in MP3_DIR.glob('*.mp3')}
    lrcs = {p.stem: p.name for p in LRC_DIR.glob('*.lrc')}
    items = []
    for key, mp3_name in mp3s.items():
        items.append({
            'id': key,
            'title': key,
            'has_lrc': key in lrcs,
            'mp3': f"podcast/mp3/{mp3_name}",
            'lrc': f"podcast/lrc/{lrcs.get(key, '')}" if key in lrcs else None,
        })
    return items


@podcast_bp.route('/podcast')
def podcast_main():
    podcasts = _list_podcasts()
    return render_template('podcast/podcast_main.html', podcasts=podcasts)


@podcast_bp.route('/podcast/<podcast_id>')
def podcast_detail(podcast_id):
    podcasts = {p['id']: p for p in _list_podcasts()}
    item = podcasts.get(podcast_id)
    if not item:
        return redirect(url_for('podcast_bp.podcast_main'))

    # Build question sets
    all_correct = False
    questions = []
    if podcast_id.lower() == 'apple':
        questions = [
            {
                'id': 1,
                'q': 'Based on what we just discussed, what year was the Apple I initially released?',
                'answer_type': 'free',
                'correct': ['1976', 'year 1976'],
            },
            {
                'id': 2,
                'q': 'What was that key technological principle, the one about transistors doubling, that helped make computers smaller over time?',
                'answer_type': 'free',
                'correct': ["moore's law", 'moore law', 'moore’s law'],
            },
            {
                'id': 3,
                'q': 'What common household item did he design the Apple I to connect to instead?',
                'answer_type': 'free',
                'correct': ['television', 'tv', 'a television', 'a tv'],
            },
            {
                'id': 4,
                'q': 'What was the name of that computer?',
                'answer_type': 'free',
                'correct': ['apple i', 'the apple i'],
            },
        ]
    elif podcast_id.lower() == 'c418' or podcast_id.lower() == 'c418_vs':
        # English translations of provided Czech questions
        questions = [
            {
                'id': 1,
                'q': "What was Daniel Rosenfeld's (C418) original job that strongly influenced his approach to making music?",
                'answer_type': 'free',
                'correct': ['factory work', 'manual labor', 'manual labour', 'assembly line',
                            'work on an assembly line', 'working in a factory', 'hard manual work on a production line',
                            'working on a production line'],
            },
            {
                'id': 2,
                'q': 'What was the key condition of the agreement between C418 and Notch regarding music for Minecraft?',
                'answer_type': 'free',
                'correct': ['c418 kept 100% of the rights and royalties', 'he kept all rights and royalties',
                            'full creative freedom', 'retained full rights'],
            },
            {
                'id': 3,
                'q': "Due to technical limits of the game engine the music couldn't loop smoothly. What creative solution did C418 use?",
                'answer_type': 'free',
                'correct': ['long moments of silence and random sporadic playback',
                            'used long periods of silence and played music randomly',
                            'he used long silence and random playback'],
            },
            {
                'id': 4,
                'q': 'Why did C418 stop composing new music for Minecraft after Microsoft bought the game?',
                'answer_type': 'free',
                'correct': ['microsoft wanted work for hire and full rights assignment which he refused',
                            'they required him to transfer all rights and compose on commission',
                            'microsoft demanded full rights so he refused'],
            },
        ]
    elif podcast_id.lower() == 'minecraft':
        questions = [
            {
                'id': 1,
                'q': 'Which of these versions of Minecraft do you consider the peak of its evolution?',
                'answer_type': 'mcq',
                'options': ['Golden era / Beta 1.7.3', 'Diamond era / Beta 1.8 and later',
                            'Modern era / 1.13 and later'],
            },
            {
                'id': 2,
                'q': 'Which combat system do you prefer?',
                'answer_type': 'mcq',
                'options': ['Fast and simple (pre-1.9)', 'More strategic with cooldown (1.9 and later)'],
            },
            {
                'id': 3,
                'q': 'What is more important to you in Minecraft?',
                'answer_type': 'mcq',
                'options': ['Emptiness, mystery and your own story (older versions)',
                            'Richness of structures and guaranteed content (newer versions)'],
            },
            {
                'id': 4,
                'q': 'Was Microsoft’s arrival more of a benefit or a threat to Minecraft?',
                'answer_type': 'mcq',
                'options': ['Benefit (stability, accessibility, education)',
                            'Threat (loss of spirit, microtransactions)'],
            },
        ]

    return render_template('podcast/podcast_music.html', item=item, questions=questions)


@podcast_bp.route('/podcast/<podcast_id>/check', methods=['POST'])
def check_answers(podcast_id):
    try:
        # Check if it's JSON request (AJAX) or form data
        duration_secs = 0
        if request.is_json:
            data = request.get_json()
            answers = data.get('answers', {})
            try:
                dur_raw = data.get('duration_seconds')
                if dur_raw is not None:
                    duration_secs = int(float(dur_raw))
                    if duration_secs < 0:
                        duration_secs = 0
                    if duration_secs > 7200:
                        duration_secs = 7200
            except Exception:
                duration_secs = 0
        else:
            # Handle classic form submission
            answers = {}
            for key, value in request.form.items():
                if key.startswith('q'):
                    qid = key.replace('q', '')
                    answers[qid] = value
            # optional duration from form
            try:
                dur_raw = request.form.get('duration_seconds')
                if dur_raw:
                    duration_secs = int(float(dur_raw))
                    if duration_secs < 0:
                        duration_secs = 0
                    if duration_secs > 7200:
                        duration_secs = 7200
            except Exception:
                duration_secs = 0

        print(f"Received answers: {answers}")  # Debug print

        podcasts = {p['id']: p for p in _list_podcasts()}

        if podcast_id not in podcasts:
            if request.is_json:
                return jsonify({'ok': False, 'error': 'unknown podcast'}), 404
            else:
                # For form submission, redirect back with error
                return redirect(url_for('podcast_bp.podcast_detail', podcast_id=podcast_id))

        def norm(s):
            if not s:
                return ""
            return ' '.join(str(s).lower().strip().split())

        resp = {}
        qs = []
        all_correct = False

        # Build same set as in detail route
        if podcast_id.lower() == 'apple':
            qs = [
                ('1', ['1976', 'year 1976']),
                ('2', ["moore's law", 'moore law', 'moore’s law']),
                ('3', ['television', 'tv', 'a television', 'a tv']),
                ('4', ['apple i', 'the apple i']),
            ]
        elif podcast_id.lower() in ('c418', 'c418_vs'):
            qs = [
                ('1', ['factory work', 'manual labor', 'manual labour', 'assembly line',
                       'work on an assembly line', 'working in a factory',
                       'hard manual work on a production line', 'working on a production line']),
                ('2', ['c418 kept 100% of the rights and royalties', 'he kept all rights and royalties',
                       'full creative freedom', 'retained full rights']),
                ('3', ['long moments of silence and random sporadic playback',
                       'used long periods of silence and played music randomly',
                       'he used long silence and random playback']),
                ('4', ['microsoft wanted work for hire and full rights assignment which he refused',
                       'they required him to transfer all rights and compose on commission',
                       'microsoft demanded full rights so he refused']),
            ]
        elif podcast_id.lower() == 'minecraft':
            # MCQs – always ok
            resp = {k: True for k in answers.keys()}
            all_correct = True
        else:
            resp = {}
            all_correct = False

        if podcast_id.lower() != 'minecraft':
            # Check answers with better matching
            for qid, correct_list in qs:
                user_answer = norm(answers.get(qid, ''))
                # Check if user answer contains any of the correct answers
                resp[qid] = any(correct_answer in user_answer for correct_answer in correct_list)

            all_correct = all(resp.values()) if resp else False

        # Vypočti počty správně/špatně pro statistiky
        uid = session.get('user_id')
        if uid:
            if podcast_id.lower() == 'minecraft':
                corr = len(answers)
                wrong = 0
            else:
                corr = sum(1 for v in resp.values() if v)
                wrong = sum(1 for v in resp.values() if not v)
            # Aktualizuj statistiky pro Podcast (pds_*) a globální correct/wrong. Čas dle duration_seconds.
            try:
                update_user_stats(uid, correct=corr, wrong=wrong, pds_cor=corr, pds_wr=wrong,
                                  learning_time=(duration_secs if duration_secs > 0 else None))
            except Exception:
                pass

        # Award XP if all_correct
        if all_correct and add_xp_to_user:
            try:
                # Přidej XP uživateli (pokud je přihlášen)
                uid = session.get('user_id')
                if uid:
                    add_xp_to_user(uid, 10)
                    # Pokus o aktualizaci streaku, pokud modul dostupný
                    try:
                        if update_user_streak:
                            update_user_streak(uid)
                    except Exception:
                        pass
                else:
                    print('Podcast: uživatel není přihlášen, XP nepřidáno')
            except Exception as e:
                print(f"Error adding XP: {e}")

        # Return appropriate response based on request type
        if request.is_json:
            return jsonify({
                'ok': True,
                'results': resp,
                'all_correct': all_correct
            })
        else:
            # For form submission, redirect back with results in session
            session['quiz_results'] = {
                'results': resp,
                'all_correct': all_correct
            }
            return redirect(url_for('podcast_bp.podcast_detail', podcast_id=podcast_id))

    except Exception as e:
        print(f"Error in check_answers: {e}")
        if request.is_json:
            return jsonify({'ok': False, 'error': 'Internal server error'}), 500
        else:
            return redirect(url_for('podcast_bp.podcast_detail', podcast_id=podcast_id))
