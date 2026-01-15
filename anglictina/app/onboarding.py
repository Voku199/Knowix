from flask import Blueprint, render_template, request, redirect, url_for, session
from db import get_db_connection

onboarding_bp = Blueprint('onboarding_bp', __name__)

STEPS = [
    ('welcome', 'Vítej v Knowixu'),
    ('source', 'Jak ses o nás dozvěděl?'),
    ('use_cases', 'Jak chceš Knowix využít?'),
    ('level', 'Jaká je tvoje úroveň?'),
    ('value', 'Co Knowix dokáže'),
    ('minutes', 'Kolik minut chceš cvičit?'),
    ('notifications', 'Notifikace'),
    ('sample', 'Ukázkové cvičení'),
    ('final', 'Hotovo'),
]
STEP_INDEX = {k: i + 1 for i, (k, _) in enumerate(STEPS)}


def _answers() -> dict:
    a = session.get('onboarding_answers')
    if not isinstance(a, dict):
        a = {}
        session['onboarding_answers'] = a
    return a


def _current_step_name() -> str:
    # default step 1
    idx = int(session.get('onboarding_step') or 1)
    idx = max(1, min(idx, len(STEPS)))
    return STEPS[idx - 1][0]


def _set_step(name: str) -> None:
    session['onboarding_step'] = STEP_INDEX.get(name, 1)


def _persist_has_seen_onboarding(uid: int, value: int = 1) -> None:
    conn = get_db_connection()
    cur = None
    try:
        cur = conn.cursor()
        cur.execute('UPDATE users SET has_seen_onboarding = %s WHERE id = %s', (int(value), int(uid)))
        conn.commit()
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        conn.close()


@onboarding_bp.route('/onboarding', methods=['GET'])
def onboarding_root():
    # Onboarding je primárně pro guest flow.
    # Přihlášený (ne-guest) uživatel se sem nemá vynuceně posílat a nemá být blokovaný onboarding guardem.
    if session.get('user_id') and not session.get('is_guest'):
        return redirect('/')

    # pokud už onboarding viděl (typicky guest), pošli domů
    if session.get('has_seen_onboarding'):
        return redirect('/')
    return redirect(url_for('onboarding_bp.step', step=_current_step_name()))


@onboarding_bp.route('/onboarding/step/<step>', methods=['GET'])
def step(step: str):
    # Přihlášený (ne-guest) uživatel onboarding nepotřebuje.
    if session.get('user_id') and not session.get('is_guest'):
        return redirect('/')

    if session.get('has_seen_onboarding'):
        return redirect('/')

    # vynucení pořadí
    cur = _current_step_name()
    if STEP_INDEX.get(step, 1) != STEP_INDEX.get(cur, 1):
        return redirect(url_for('onboarding_bp.step', step=cur))

    step_title = dict(STEPS).get(step, 'Onboarding')

    embed_html = None
    if step == 'sample':
        # render embed preview z vlastni_music (standalone partial)
        try:
            from flask import render_template as _rt
            embed_html = _rt('vlastni_music/embed_preview.html', video_id=None, youtube_url=None)
        except Exception:
            embed_html = '<div style="opacity:.8;">Ukázka cvičení se nepodařila načíst.</div>'

    return render_template(
        'onboarding_new.html',
        step=step,
        step_title=step_title,
        step_index=STEP_INDEX.get(step, 1),
        step_total=len(STEPS),
        answers=_answers(),
        embed_html=embed_html,
    )


@onboarding_bp.route('/onboarding/next', methods=['POST'])
def next_step():
    step = (request.form.get('step') or '').strip()
    if not step or step not in STEP_INDEX:
        step = _current_step_name()

    # guard: nesmí přeskočit
    if step != _current_step_name():
        return redirect(url_for('onboarding_bp.step', step=_current_step_name()))

    a = _answers()

    if step == 'welcome':
        choice = request.form.get('choice')
        a['welcome_choice'] = choice

    elif step == 'source':
        a['source'] = request.form.get('source')

    elif step == 'use_cases':
        # multi-select
        a['use_cases'] = request.form.getlist('use_cases')

    elif step == 'level':
        a['level'] = request.form.get('level')

    elif step == 'value':
        a['value_seen'] = True

    elif step == 'minutes':
        try:
            a['target_minutes'] = int(request.form.get('minutes') or 0)
        except Exception:
            a['target_minutes'] = 0

    elif step == 'notifications':
        a['notif_result'] = request.form.get('notif_result') or 'skipped'

    elif step == 'sample':
        a['sample_done'] = bool(int(request.form.get('sample_done') or '0'))

        # Po ukázce chceme onboarding považovat za dokončený.
        session['has_seen_onboarding'] = 1
        session['onboarding_completed'] = True
        uid = session.get('user_id')
        if uid:
            try:
                _persist_has_seen_onboarding(int(uid), 1)
            except Exception:
                pass

        return redirect('/')

    # posun
    idx = STEP_INDEX.get(step, 1)
    next_idx = min(idx + 1, len(STEPS))
    session['onboarding_step'] = next_idx
    return redirect(url_for('onboarding_bp.step', step=STEPS[next_idx - 1][0]))


@onboarding_bp.route('/onboarding/prev', methods=['POST'])
def prev_step():
    idx = int(session.get('onboarding_step') or 1)
    idx = max(1, idx - 1)
    session['onboarding_step'] = idx
    return redirect(url_for('onboarding_bp.step', step=STEPS[idx - 1][0]))


@onboarding_bp.route('/onboarding/finish', methods=['POST'])
def finish():
    # Ulož do session i DB, že onboarding byl dokončen
    session['has_seen_onboarding'] = 1
    uid = session.get('user_id')
    if uid:
        try:
            _persist_has_seen_onboarding(int(uid), 1)
        except Exception:
            pass

    # (volitelně) uložit answers do DB: zatím jen do session; rozšíření lze později
    session['onboarding_completed'] = True

    return redirect('/')
