from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, render_template, request

prijmacky_bp = Blueprint('prijmacky', __name__)

LEVELS: dict[str, dict[str, str]] = {
    # key -> {label, json}
    'a2': {'label': 'A2 (základní)', 'json': 'a2_test.json'},
    'b1b2': {'label': 'B1–B2 (střední)', 'json': 'b1_b2_test.json'},
    'c1c2': {'label': 'C1–C2 (pokročilá)', 'json': 'c1_c2_test.json'},
}


@dataclass
class MarkResult:
    is_correct: bool
    normalized_user: str


def _static_prijmacky_dir() -> str:
    # JSONy držíme u aplikace ve static/prijmacky
    return os.path.join(os.path.dirname(__file__), 'static', 'prijmacky')


def _load_test(level_key: str) -> dict[str, Any]:
    level_key = (level_key or '').strip().lower()
    if level_key not in LEVELS:
        level_key = 'a2'

    path = os.path.join(_static_prijmacky_dir(), LEVELS[level_key]['json'])
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Minimal sanity-check pro šablonu
    if not isinstance(data, dict) or not isinstance(data.get('sections'), list):
        raise ValueError('Invalid test JSON structure')

    return data


_ws_re = re.compile(r'\s+')


def _normalize_answer(val: str) -> str:
    """Normalizace pro tolerantní porovnání: trim, lower, sjednocení mezer.

    Pozn.: Neřešíme lemmatizaci ani punctuation heavy logiku; cílem je férové vyhodnocení bez JS/frameworků.
    """
    if val is None:
        return ''
    val = str(val).strip().lower()
    val = _ws_re.sub(' ', val)
    return val


def _mark_question(question: dict[str, Any], user_val: str) -> MarkResult:
    normalized_user = _normalize_answer(user_val)

    correct_list = question.get('correct') or []
    alt_list = question.get('alternatives') or []

    # U open-ended psaní může být correct prázdné => nepočítá se do skóre.
    if not correct_list:
        return MarkResult(is_correct=True, normalized_user=normalized_user)

    accepted = [
        _normalize_answer(x)
        for x in (list(correct_list) + list(alt_list))
        if isinstance(x, str) and x.strip()
    ]

    is_correct = normalized_user in accepted
    return MarkResult(is_correct=is_correct, normalized_user=normalized_user)


def _rating_label(percent: float) -> str:
    if percent < 50:
        return '❌ Nedostačující'
    if percent < 65:
        return '⚠️ Na hraně'
    if percent < 85:
        return '✅ Přijatelné'
    return '🔥 Výborné'


@prijmacky_bp.route('/prijmacky', methods=['GET', 'POST'])
def prijimacky():
    """Simulace přijímacích zkoušek z AJ.

    - GET: výběr úrovně + (volitelně) zobrazení testu
    - POST: vyhodnocení odpovědí z HTML formuláře

    Bez JS frameworků: render + submit klasickým <form>.
    """

    level_key = (request.values.get('level') or 'a2').strip().lower()
    if level_key not in LEVELS:
        level_key = 'a2'

    # Na GET bez action=run nechceme hned ukazovat test, jen výběr.
    show_test = request.method == 'POST' or (request.args.get('run') == '1')

    test_data = _load_test(level_key) if show_test else None

    result = None
    if request.method == 'POST':
        # Vyhodnocení po sekcích
        per_section: list[dict[str, Any]] = []
        total_count = 0
        total_correct = 0

        improvements: dict[str, int] = {}

        for section in (test_data.get('sections') or []) if test_data else []:
            sec_type = section.get('type') or 'other'
            sec_title = section.get('title') or sec_type

            questions = section.get('questions') or []
            sec_count = 0
            sec_correct = 0
            marked_questions: list[dict[str, Any]] = []

            for q in questions:
                qid = q.get('id')
                if not qid:
                    continue

                user_val = request.form.get(f"q_{qid}", '')
                mark = _mark_question(q, user_val)

                # Otázky bez correct nepočítáme (writing short_answer)
                is_scored = bool(q.get('correct'))
                if is_scored:
                    sec_count += 1
                    total_count += 1
                    if mark.is_correct:
                        sec_correct += 1
                        total_correct += 1
                    else:
                        improvements[sec_title] = improvements.get(sec_title, 0) + 1

                marked_questions.append(
                    {
                        'id': qid,
                        'prompt': q.get('prompt') or q.get('question') or '',
                        'format': q.get('format') or 'text',
                        'user': user_val,
                        'is_correct': mark.is_correct,
                        'correct': q.get('correct') or [],
                        'alternatives': q.get('alternatives') or [],
                        'explanation': q.get('explanation') or '',
                        'is_scored': is_scored,
                    }
                )

            sec_percent = (sec_correct / sec_count * 100.0) if sec_count else None
            per_section.append(
                {
                    'type': sec_type,
                    'title': sec_title,
                    'count': sec_count,
                    'correct': sec_correct,
                    'percent': sec_percent,
                    'questions': marked_questions,
                }
            )

        percent = (total_correct / total_count * 100.0) if total_count else 0.0

        # Oblasti ke zlepšení: seřadit podle počtu chyb
        improve_list = [k for k, _v in sorted(improvements.items(), key=lambda kv: kv[1], reverse=True)]

        result = {
            'total': {
                'count': total_count,
                'correct': total_correct,
                'percent': round(percent, 1),
                'rating': _rating_label(percent),
            },
            'sections': per_section,
            'improvements': improve_list,
        }

    return render_template(
        'prijmacky/prijimacky.html',
        levels=LEVELS,
        selected_level=level_key,
        show_test=show_test,
        test=test_data,
        result=result,
    )
