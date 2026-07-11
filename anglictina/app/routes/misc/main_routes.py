"""Hlavní stránka a skill-tree (blueprint `main`).

Index vykresluje skill-tree ze static/skill_tree.json; postup uživatele se
odvozuje z tabulky user_lessons_completed (plněné přes user_stats.update_user_stats
s lesson_area_key).
"""

from flask import Blueprint, render_template, session, redirect
from db import get_db_connection

main_bp = Blueprint('main', __name__)


def ensure_user_lessons_table_exists():
    conn = get_db_connection()
    cur = None
    try:
        cur = conn.cursor()
        cur.execute(
            """
CREATE TABLE IF NOT EXISTS user_lessons_completed (
    user_id INT NOT NULL,
    area_key VARCHAR(100) NOT NULL,
    PRIMARY KEY (user_id, area_key)
)
            """
        )
        conn.commit()
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        try:
            conn.close()
        except Exception:
            pass


ensure_user_lessons_table_exists()


def _get_completed_lesson_keys_for_user(user_id: int) -> set[str]:
    if not user_id:
        return set()

    conn = None
    cur = None
    rows = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT area_key FROM user_lessons_completed WHERE user_id = %s",
            (user_id,),
        )
        rows = cur.fetchall() or []
    except Exception:
        return set()
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return {row[0] for row in rows if row and row[0]}


def _mission_has_lesson_requirement(mission: dict) -> str | None:
    """Pokud mise obsahuje speciální podmínku typu lesson_area_key, vrátí její hodnotu."""
    if not isinstance(mission, dict):
        return None
    key = mission.get('lesson_area_key') or mission.get('lesson_key')
    if isinstance(key, str) and key.strip():
        return key.strip()
    return None


def _load_skill_tree_config():
    """Načte konfiguraci skill-tree z JSON souboru."""
    import json
    import os

    from _paths import APP_DIR
    base_dir = APP_DIR
    cfg_path = os.path.join(base_dir, 'static', 'skill_tree.json')

    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"version": 1, "phases": []}
            if not isinstance(data.get('phases', []), list):
                data['phases'] = []
            return data
    except FileNotFoundError:
        return {"version": 1, "phases": []}


def _normalize_level(level: str) -> str:
    level = (level or '').strip().upper()
    valid = {'A1', 'A2', 'B1', 'B2', 'C1', 'C2'}
    return level if level in valid else 'A1'


def _get_user_english_level() -> str:
    """Získá english_level pouze z DB."""
    user_id = session.get('user_id')

    try:
        from db import get_db_connection
        db = get_db_connection()
        try:
            with db.cursor() as cur:
                if user_id:
                    cur.execute('SELECT english_level FROM users WHERE id = %s LIMIT 1', (user_id,))
                else:
                    cur.execute('SELECT english_level FROM users WHERE username = %s LIMIT 1', ('guest',))
                row = cur.fetchone()
                lvl = row[0] if row and row[0] else 'A1'
        finally:
            db.close()

        return _normalize_level(lvl)
    except Exception:
        return 'A1'


def _phase_unlock_index_for_user_level(level: str, phases_count: int | None = None) -> int:
    """Mapuje English level na odemčenou fázi."""
    level = _normalize_level(level)

    if level in ('A1', 'A2'):
        idx = 0
    elif level in ('B1'):
        idx = 1
    elif level in ('B2'):
        idx = 2
    elif level in ('C1'):
        idx = 4
    else:
        idx = 6

    if phases_count is not None and phases_count > 0:
        idx = min(idx, phases_count - 1)

    return idx


def _build_positions_for_path(n: int):
    """Vygeneruje pozice pro n uzlů (max 15) ve stylu "cik-cak"."""
    n = max(0, min(int(n or 0), 15))
    if n == 0:
        return []

    xs = [20, 55, 30, 70, 45, 25, 60, 35, 75, 50, 30, 65, 40, 80, 55]
    top = 12
    bottom = 88
    if n == 1:
        ys = [top]
    else:
        step = (bottom - top) / (n - 1)
        ys = [top + i * step for i in range(n)]

    return [(xs[i], ys[i]) for i in range(n)]


def _evaluate_requirement(stats: dict, req: dict) -> bool:
    """Vyhodnotí jednu podmínku mise proti statistikám uživatele."""
    if not isinstance(req, dict):
        return False

    metric = req.get('metric')
    op = req.get('op', '>=').strip()
    target = req.get('value')

    if not metric or target is None:
        return False

    current = 0
    if isinstance(stats, dict):
        current = stats.get(metric, 0) or 0

    try:
        current_val = float(current)
        target_val = float(target)
    except (TypeError, ValueError):
        return False

    if op == '>=':
        return current_val >= target_val
    if op == '>':
        return current_val > target_val
    if op == '==':
        return current_val == target_val
    if op == '<=':
        return current_val <= target_val
    if op == '<':
        return current_val < target_val

    return False


def _mark_lesson_completed(user_id: int, lesson_key: str) -> None:
    """Zaznamená dokončení lekce v databázi (idempotentně)."""
    if not user_id or not lesson_key:
        return

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT IGNORE INTO user_lessons_completed (user_id, area_key) VALUES (%s, %s)",
            (user_id, lesson_key),
        )
        conn.commit()
    except Exception as e:
        print(f"Chyba při zaznamenávání dokončení lekce: {e}")
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _is_mission_completed(stats: dict, mission: dict, completed_lesson_keys: set[str] | None = None) -> bool:
    """Vrátí True, pokud je mise splněná.

    Nová logika:
    1. Pokud má mise lesson_area_key a je v completed_lesson_keys -> splněno
    2. Pokud má requirements a všechny jsou splněny -> splněno
    3. Pokud NEMÁ requirements (prázdný seznam) -> považujeme za splněno (pro první misi)
    """
    if completed_lesson_keys is None:
        completed_lesson_keys = set()

    lesson_key = _mission_has_lesson_requirement(mission)
    reqs = mission.get('requirements') or []

    # 1) Pokud máme lesson_key a už je splněn
    if lesson_key and lesson_key in completed_lesson_keys:
        return True

    # 2) Pokud máme requirements, vyhodnotit je
    if reqs:
        reqs_ok = all(_evaluate_requirement(stats, r) for r in reqs)
        return reqs_ok

    # 3) Pokud NEMÁME requirements (prázdný seznam) -> považujeme za splněno
    # To umožní první misi být dostupná i bez lesson_key v completed_lesson_keys
    return True


def _annotate_skills_with_progress(path_items, stats: dict, completed_lesson_keys: set[str], user_id: int = None):
    """Z path položek vytvoří strukturu skills s info o progressu."""
    if not isinstance(path_items, list):
        path_items = []

    positions = _build_positions_for_path(len(path_items))
    skills = []

    # Sekvenční odemykání
    all_prev_completed = True
    for idx, item in enumerate(path_items):
        if not isinstance(item, dict):
            item = {}
        x, y = positions[idx]

        lesson_key = _mission_has_lesson_requirement(item)
        reqs = item.get('requirements') or []

        # Zkontrolovat, zda je mise splněna
        completed = _is_mission_completed(stats, item, completed_lesson_keys)

        # Pokud mise je splněna přes requirements, ale má lesson_key a ještě není zaznamenán,
        # automaticky ho zaznamenáme
        if completed and lesson_key and user_id and lesson_key not in completed_lesson_keys:
            # Zkontrolujeme zvlášť, zda jsou splněny requirements (aby jsme necyklili)
            reqs_ok = all(_evaluate_requirement(stats, r) for r in reqs) if reqs else False
            if reqs_ok:
                _mark_lesson_completed(user_id, lesson_key)
                completed_lesson_keys.add(lesson_key)

        # Nastavit stav uzlu
        if completed:
            state = 'completed'
        else:
            state = 'available' if all_prev_completed else 'locked'

        import json
        try:
            reqs_serialized = json.dumps(reqs, ensure_ascii=False)
        except TypeError:
            reqs_serialized = '[]'

        skills.append({
            'id': item.get('id') or f'node_{idx + 1}',
            'title': item.get('title') or f'Uzel {idx + 1}',
            'desc': item.get('desc') or '',
            'href': item.get('href') or '/',
            'x': x,
            'y': y,
            'locked': state == 'locked',
            'state': state,
            'requirements': reqs,
            'requirements_json': reqs_serialized,
            'lesson_area_key': lesson_key,
        })

        all_prev_completed = all_prev_completed and completed

    return skills


@main_bp.route('/')
def index():
    """Hlavní stránka s anglickým skill-tree."""
    from flask import request
    from stats import get_simple_stats

    cfg = _load_skill_tree_config()
    phases = cfg.get('phases', [])

    user_level = _get_user_english_level()
    unlocked_phase_idx = _phase_unlock_index_for_user_level(user_level, len(phases))

    requested_phase_id = (request.args.get('phase') or '').strip()

    # Označení fází jako uzamčené podle levelu
    for i, p in enumerate(phases):
        if isinstance(p, dict):
            p['locked'] = i > unlocked_phase_idx
        else:
            phases[i] = {
                'id': f'phase_{i + 1}',
                'title': f'Fáze {i + 1}',
                'path': [],
                'locked': i > unlocked_phase_idx,
            }

    selected_phase = None
    if requested_phase_id:
        selected_phase = next((p for p in phases if p.get('id') == requested_phase_id), None)
        if selected_phase and selected_phase.get('locked'):
            selected_phase = None

    if not selected_phase:
        selected_phase = phases[unlocked_phase_idx] if phases and unlocked_phase_idx < len(phases) else (
            phases[0] if phases else None)

    path_items = (selected_phase or {}).get('path', [])
    if not isinstance(path_items, list):
        path_items = []
    path_items = path_items[:15]

    # Načtení user_stats (pokud není přihlášený user, použijeme guest)
    user_id = session.get('user_id')
    if not user_id:
        # zjistíme id uživatele 'guest'
        db = get_db_connection()
        try:
            with db.cursor() as cur:
                cur.execute('SELECT id FROM users WHERE username = %s LIMIT 1', ('guest',))
                row = cur.fetchone()
                user_id = row[0] if row else None
        finally:
            db.close()

    if user_id:
        stats = get_simple_stats(user_id) or {}
        completed_lesson_keys = _get_completed_lesson_keys_for_user(user_id)
    else:
        stats = {}
        completed_lesson_keys = set()

    # Předání user_id pro automatické zaznamenávání splněných misí
    skills = _annotate_skills_with_progress(path_items, stats, completed_lesson_keys, user_id)

    return render_template(
        'index.html',
        user_name=session.get('user_name'),
        profile_pic=session.get('profile_pic', 'static/profile_pics/default.jpg'),
        phases=phases,
        selected_phase_id=(selected_phase or {}).get('id'),
        selected_phase_title=(selected_phase or {}).get('title'),
        user_english_level=user_level,
        skills=skills,
    )


@main_bp.route('/kontakty')
def kontakty():
    return render_template('kontakty.html',
                           user_name=session.get("user_name"),
                           profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg"))


@main_bp.route('/anglictina')
def anglictina():
    return render_template('anglictina/main_anglictina.html',
                           user_name=session.get("user_name"),
                           profile_pic=session.get("profile_pic", "default.jpg"))


@main_bp.route('/skill-test/phase-1', methods=['GET', 'POST'])
def skill_test_phase_1():
    """Závěrečný mini-test pro Fázi 1.

    Pravidla vyhodnocení:
    - 0–1 chyba: "skvělá práce" (pass)
    - 2 chyby: "nevadí... kdykoliv se můžeš vrátit" (pass)
    - 3+ chyb: "zkus to někdy jindy" (fail)

    Pass (0–2 chyby) -> zapíšeme completion `F1_M10_PHASE1_COMPLETE`.
    """
    from flask import request
    from user_stats import update_user_stats

    user_id = session.get('user_id')

    if request.method == 'POST':
        # 5 otázek cca A1-A2 (blíž k A2)
        answers = {
            # vocab
            'q1': 'b',  # yesterday
            # grammar (there is/are)
            'q2': 'a',  # There are
            # grammar (past simple)
            'q3': 'c',  # went
            # grammar (comparatives)
            'q4': 'b',  # than
            # meaning / modal
            'q5': 'a',  # must
        }

        total = len(answers)
        score = 0
        wrong = 0
        wrong_questions = []

        for k, correct in answers.items():
            given = (request.form.get(k) or '').strip()
            if given == correct:
                score += 1
            else:
                wrong += 1
                wrong_questions.append(k)

        # pass threshold: max 2 chyby
        passed = wrong <= 2

        # status pro template
        if wrong <= 1:
            status = 'great'
        elif wrong == 2:
            status = 'ok'
        else:
            status = 'fail'

        if passed and user_id:
            try:
                update_user_stats(user_id, lesson_area_key='F1_M10_PHASE1_COMPLETE')
            except Exception:
                pass

        return render_template('skill_tests/phase_1_test.html', result={
            'score': score,
            'total': total,
            'wrong': wrong,
            'passed': passed,
            'status': status,
            'wrong_questions': wrong_questions,
        })

    return render_template('skill_tests/phase_1_test.html')


@main_bp.route('/skill-test/phase-2', methods=['GET', 'POST'])
def skill_test_phase_2():
    """Závěrečný test pro Fázi 2 (porozumění/poslech/čtení)."""
    from flask import request
    from user_stats import update_user_stats

    user_id = session.get('user_id')

    if request.method == 'POST':
        answers = {
            'q1': 'b',  # He was
            'q2': 'c',  # any
            'q3': 'a',  # should
            'q4': 'b',  # because
            'q5': 'c',  # went
            'q6': 'a',  # How much
        }
        total = len(answers)
        score = 0
        wrong = 0
        wrong_questions = []
        for k, correct in answers.items():
            given = (request.form.get(k) or '').strip()
            if given == correct:
                score += 1
            else:
                wrong += 1
                wrong_questions.append(k)

        passed = wrong <= 2  # 6 otázek -> max 2 chyby
        status = 'great' if wrong <= 1 else ('ok' if wrong == 2 else 'fail')

        if passed and user_id:
            try:
                update_user_stats(user_id, lesson_area_key='F2_M10_PHASE2_COMPLETE')
            except Exception:
                pass

        return render_template('skill_tests/phase_2_test.html', result={
            'score': score,
            'total': total,
            'wrong': wrong,
            'passed': passed,
            'status': status,
            'wrong_questions': wrong_questions,
        })

    return render_template('skill_tests/phase_2_test.html')


@main_bp.route('/skill-test/phase-3', methods=['GET', 'POST'])
def skill_test_phase_3():
    """Závěrečný test pro Fázi 3 (aktivní angličtina: irregulars, věty, roleplay-ready)."""
    from flask import request
    from user_stats import update_user_stats

    user_id = session.get('user_id')

    if request.method == 'POST':
        answers = {
            'q1': 'a',  # bought
            'q2': 'c',  # Have you ever been...
            'q3': 'b',  # If I were you, I would...
            'q4': 'a',  # at
            'q5': 'b',  # could
            'q6': 'c',  # since
            'q7': 'a',  # gave
        }
        total = len(answers)
        score = 0
        wrong = 0
        wrong_questions = []
        for k, correct in answers.items():
            given = (request.form.get(k) or '').strip()
            if given == correct:
                score += 1
            else:
                wrong += 1
                wrong_questions.append(k)

        passed = wrong <= 2  # 7 otázek
        status = 'great' if wrong <= 1 else ('ok' if wrong == 2 else 'fail')

        if passed and user_id:
            try:
                update_user_stats(user_id, lesson_area_key='F3_M10_PHASE3_COMPLETE')
            except Exception:
                pass

        return render_template('skill_tests/phase_3_test.html', result={
            'score': score,
            'total': total,
            'wrong': wrong,
            'passed': passed,
            'status': status,
            'wrong_questions': wrong_questions,
        })

    return render_template('skill_tests/phase_3_test.html')


@main_bp.route('/skill-test/phase-4', methods=['GET', 'POST'])
def skill_test_phase_4():
    """Závěrečný test pro Fázi 4 (gramatika: present perfect, předložky, větná stavba)."""
    from flask import request
    from user_stats import update_user_stats

    user_id = session.get('user_id')

    if request.method == 'POST':
        answers = {
            'q1': 'b',  # Have you finished...
            'q2': 'a',  # since
            'q3': 'c',  # on Monday
            'q4': 'b',  # at
            'q5': 'a',  # have been
            'q6': 'c',  # for
            'q7': 'b',  # has lived
            'q8': 'a',  # have never
        }
        total = len(answers)
        score = 0
        wrong = 0
        wrong_questions = []
        for k, correct in answers.items():
            given = (request.form.get(k) or '').strip()
            if given == correct:
                score += 1
            else:
                wrong += 1
                wrong_questions.append(k)

        passed = wrong <= 2  # 8 otázek
        status = 'great' if wrong <= 1 else ('ok' if wrong == 2 else 'fail')

        if passed and user_id:
            try:
                update_user_stats(user_id, lesson_area_key='F4_M10_PHASE4_COMPLETE')
            except Exception:
                pass

        return render_template('skill_tests/phase_4_test.html', result={
            'score': score,
            'total': total,
            'wrong': wrong,
            'passed': passed,
            'status': status,
            'wrong_questions': wrong_questions,
        })

    return render_template('skill_tests/phase_4_test.html')


@main_bp.route('/skill-test/phase-5', methods=['GET', 'POST'])
def skill_test_phase_5():
    """Závěrečný test pro Fázi 5 (zábavná angličtina + širší slovní zásoba + AI grammar)."""
    from flask import request
    from user_stats import update_user_stats

    user_id = session.get('user_id')

    if request.method == 'POST':
        answers = {
            'q1': 'c',  # excited
            'q2': 'a',  # quickly
            'q3': 'b',  # I'd rather...
            'q4': 'a',  # have been
            'q5': 'c',  # although
            'q6': 'b',  # might
            'q7': 'a',  # take
            'q8': 'c',  # were
            'q9': 'b',  # make
        }
        total = len(answers)
        score = 0
        wrong = 0
        wrong_questions = []
        for k, correct in answers.items():
            given = (request.form.get(k) or '').strip()
            if given == correct:
                score += 1
            else:
                wrong += 1
                wrong_questions.append(k)

        passed = wrong <= 2  # 9 otázek
        status = 'great' if wrong <= 1 else ('ok' if wrong == 2 else 'fail')

        if passed and user_id:
            try:
                update_user_stats(user_id, lesson_area_key='F5_M10_PHASE5_COMPLETE')
            except Exception:
                pass

        return render_template('skill_tests/phase_5_test.html', result={
            'score': score,
            'total': total,
            'wrong': wrong,
            'passed': passed,
            'status': status,
            'wrong_questions': wrong_questions,
        })

    return render_template('skill_tests/phase_5_test.html')


@main_bp.route('/skill-test/phase-6', methods=['GET', 'POST'])
def skill_test_phase_6():
    """Závěrečný test pro Fázi 6 (praxe: mix všeho, vyšší úroveň)."""
    from flask import request
    from user_stats import update_user_stats

    user_id = session.get('user_id')

    if request.method == 'POST':
        answers = {
            'q1': 'b',  # had been
            'q2': 'c',  # despite
            'q3': 'a',  # would have
            'q4': 'b',  # been living
            'q5': 'c',  # who
            'q6': 'a',  # unless
            'q7': 'b',  # take
            'q8': 'a',  # have been
            'q9': 'c',  # in case
            'q10': 'b',  # haven't I
        }
        total = len(answers)
        score = 0
        wrong = 0
        wrong_questions = []
        for k, correct in answers.items():
            given = (request.form.get(k) or '').strip()
            if given == correct:
                score += 1
            else:
                wrong += 1
                wrong_questions.append(k)

        passed = wrong <= 2  # 10 otázek
        status = 'great' if wrong <= 1 else ('ok' if wrong == 2 else 'fail')

        if passed and user_id:
            try:
                update_user_stats(user_id, lesson_area_key='F6_M10_PHASE6_COMPLETE')
            except Exception:
                pass

        return render_template('skill_tests/phase_6_test.html', result={
            'score': score,
            'total': total,
            'wrong': wrong,
            'passed': passed,
            'status': status,
            'wrong_questions': wrong_questions,
        })

    return render_template('skill_tests/phase_6_test.html')


@main_bp.route('/welcome')
def welcome():
    # /welcome je jen pro onboarding guest flow.
    # Přihlášený (ne-guest) uživatel sem nemá být posílán nikdy.
    if session.get('user_id') and not session.get('is_guest'):
        return redirect('/')

    # Pokud už onboarding byl dokončen (typicky guest), taky nemá smysl tu zůstávat.
    if session.get('has_seen_onboarding'):
        return redirect('/')

    return render_template('welcome.html')
