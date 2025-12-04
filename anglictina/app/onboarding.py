from flask import Blueprint, session, request, jsonify, render_template_string
from db import get_db_connection
import json

onboarding_bp = Blueprint('onboarding', __name__)

# Struktura kroků
ONBOARDING_STEPS = [
    {
        'id': 1,
        'title': 'Vítej v Knowix!',
        'message': 'Ahoj! Já jsem Alex. Jsem tu, abych ti ukázal/a, jak se učit anglicky zábavně a efektivně. Společně projdeme základní funkce.',
        'target_selector': None,
        'action_required': 'click_next',
        'position': 'center',
        'show_skip': True
    },
    {
        'id': 2,
        'title': 'Angličtina – lekce a cvičení',
        'message': 'Klikni na ikonu Angličtiny vpravo nahoře (vlajka). Tam najdeš lekce, cvičení a témata k procvičování.',
        'target_selector': 'a[href="/anglictina"]',
        'action_required': 'click',
        'position': 'top-right',
        'show_skip': True
    },
    {
        'id': 3,
        'title': 'Obchod s lekcemi',
        'message': 'V obchodě najdeš nové lekce a bonusy. Získáváš je za XP body, které vyděláš učením. Klikni na "Obchod" v menu.',
        'target_selector': 'a[href="/obchod"]',
        'action_required': 'click',
        'position': 'top-right',
        'show_skip': True
    },
    {
        'id': 4,
        'title': 'Aplikace (PWA)',
        'message': 'Knowix můžeš mít jako aplikaci. Na hlavní stránce klikni na "PWA aplikace" – uvidíš návod k instalaci.',
        'target_selector': '[onclick="openPwaHelp()"]',
        'action_required': 'click_next',
        'position': 'bottom',
        'show_skip': True
    },
    {
        'id': 5,
        'title': 'Domů a Denní úkoly',
        'message': 'Kliknutím na logo vlevo nahoře se vždy vrátíš domů. Na hlavní stránce vlevo uvidíš Denní úkoly – plň je pro odměny.',
        'target_selector': '.logo a',
        'action_required': 'click',
        'position': 'bottom',
        'show_skip': True
    },
    {
        'id': 6,
        'title': 'Streak – denní série',
        'message': 'Tady vidíš svoji denní sérii (streak). Procvičuj každý den a série poroste – odměny a motivace čekají!',
        'target_selector': '.streak-badge',
        'action_required': 'click_next',
        'position': 'top-right',
        'show_skip': True
    },
    {
        'id': 7,
        'title': 'Napiš nám Feedback',
        'message': 'Máme rádi zpětnou vazbu. Klikni na ikonu chatu a napiš nám, co zlepšit nebo co se ti líbí.',
        'target_selector': 'a[href="/feedback"]',
        'action_required': 'click',
        'position': 'top-right',
        'show_skip': True
    },
    {
        'id': 8,
        'title': 'Hotovo!',
        'message': 'Paráda! Teď už víš, kde jsou lekce, obchod, jak se vrátit domů, denní úkoly, streaky i instalace aplikace. Pokračuj v procvičování – krátce každý den = rychlý pokrok!',
        'target_selector': None,
        'action_required': 'complete',
        'position': 'bottom',
        'show_skip': False
    }
]


@onboarding_bp.route('/onboarding/next', methods=['POST'])
def next_step():
    """Přejde na další krok onboadingu"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    data = request.get_json()
    step_completed = data.get('step_completed', 1)

    try:
        # Aktualizuj session
        session['onboarding_step'] = step_completed + 1

        # Pokud je to poslední krok, označ onboarding jako dokončený
        if step_completed >= len(ONBOARDING_STEPS):
            session['has_seen_onboarding'] = 1

            # Aktualizuj databázi
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET has_seen_onboarding = 1 WHERE id = %s",
                (session['user_id'],)
            )
            conn.commit()
            cur.close()
            conn.close()

            return jsonify({
                'success': True,
                'completed': True,
                'redirect': '/'
            })

        # Vrátí data pro další krok
        next_step_data = next((s for s in ONBOARDING_STEPS if s['id'] == step_completed + 1), None)

        return jsonify({
            'success': True,
            'next_step': next_step_data,
            'progress': int((step_completed / len(ONBOARDING_STEPS)) * 100)
        })

    except Exception as e:
        print(f"[onboarding] Error in next_step: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@onboarding_bp.route('/onboarding/skip', methods=['POST'])
def skip_onboarding():
    """Přeskočí celý onboarding"""
    if 'user_id' not in session:
        return jsonify({'success': False}), 401

    try:
        session['has_seen_onboarding'] = 1
        session.pop('onboarding_step', None)

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET has_seen_onboarding = 1 WHERE id = %s",
            (session['user_id'],)
        )
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({'success': True})
    except Exception as e:
        print(f"[onboarding] Error skipping: {e}")
        return jsonify({'success': False}), 500


@onboarding_bp.route('/onboarding/status', methods=['GET'])
def onboarding_status():
    """Vrátí stav onboadingu"""
    return jsonify({
        'has_seen_onboarding': session.get('has_seen_onboarding', 0),
        'current_step': session.get('onboarding_step', 1),
        'show_onboarding': session.get('user_id') and not session.get('has_seen_onboarding', 0)
    })


@onboarding_bp.route('/onboarding/data', methods=['GET'])
def onboarding_data():
    """Vrátí data pro aktuální krok"""
    current_step = session.get('onboarding_step', 1)
    step_data = next((s for s in ONBOARDING_STEPS if s['id'] == current_step), ONBOARDING_STEPS[0])

    return jsonify({
        'current_step': current_step,
        'step_data': step_data,
        'total_steps': len(ONBOARDING_STEPS),
        'progress': int(((current_step - 1) / len(ONBOARDING_STEPS)) * 100)
    })
