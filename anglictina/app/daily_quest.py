from flask import Blueprint, jsonify, request, session
from datetime import date, datetime, timezone
from db import get_db_connection
from user_stats import ensure_user_stats_exists
from xp import add_xp_to_user
import os
import json
import random
import hashlib

daily_bp = Blueprint('daily', __name__)


# ---- Interní utilitky ----

def _json_path():
    # static je ve stejné složce jako tento modul -> ../static/daily_quest.json
    base_dir = os.path.dirname(__file__)
    return os.path.join(base_dir, 'static', 'daily_quest.json')


def _load_daily_quests():
    """
    Načte denní úkoly ze static/daily_quest.json.
    Pokud soubor chybí nebo je prázdný, vrátí výchozí sadu.
    Struktura položky:
      {
        "id": "AT_COR_10",
        "title": "At/On/In: 10 správně",
        "desc": "Získej 10 správných odpovědí v cvičení At/On/In.",
        "stat": "at_cor",
        "target": 10,
        "mode": "delta",  # "delta" = počítá se rozdíl od dnešního základu, "total" = absolutní hodnota
        "reward_xp": 15,
        "reward_keys": 0
      }
    """
    path = _json_path()
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    return data
    except Exception:
        pass
    # fallback výchozí úkoly
    return [
        {
            "id": "LISTEN_5",
            "title": "Poslech: 5 správně",
            "desc": "Získej dnes 5 správných odpovědí v poslechu.",
            "stat": "lis_cor",
            "target": 5,
            "mode": "delta",
            "reward_xp": 10,
            "reward_keys": 1
        },
        {
            "id": "LESSON_1",
            "title": "Dokonči lekci",
            "desc": "Dokonči dnes alespoň 1 lekci.",
            "stat": "total_lessons_done",
            "target": 1,
            "mode": "delta",
            "reward_xp": 20,
            "reward_keys": 0
        },
        {
            "id": "HANGMAN_3",
            "title": "Šibenice: 3 slova",
            "desc": "Uhodni dnes 3 slova v Hangmanu.",
            "stat": "hangman_words_guessed",
            "target": 3,
            "mode": "delta",
            "reward_xp": 10,
            "reward_keys": 1
        },
        {
            "id": "WRITING_50",
            "title": "Psaní: 50 slov",
            "desc": "Napiš dnes 50 slov v Psaní.",
            "stat": "total_psani_words",
            "target": 50,
            "mode": "delta",
            "reward_xp": 20,
            "reward_keys": 2
        }
    ]


def _ensure_tables():
    """Vytvoří pomocné tabulky pro denní úkoly, pokud neexistují."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_daily_snapshots (
                user_id INT NOT NULL,
                day DATE NOT NULL,
                column_name VARCHAR(64) NOT NULL,
                base_value BIGINT NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, day, column_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_daily_quests (
                user_id INT NOT NULL,
                day DATE NOT NULL,
                quest_id VARCHAR(64) NOT NULL,
                claimed TINYINT(1) NOT NULL DEFAULT 0,
                claimed_at DATETIME NULL,
                PRIMARY KEY (user_id, day, quest_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        # Tabulka pro klíče (měna) – slouží i do budoucna
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_keys (
                user_id INT NOT NULL PRIMARY KEY,
                key_count INT NOT NULL DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        # Pokud nemáme práva, tiše ignorujeme – feature prostě nebude perzistentní
        pass


def _add_keys_to_user(user_id: int, amount: int):
    if not amount:
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Zajistit existenci řádku
        cur.execute("INSERT IGNORE INTO user_keys (user_id, key_count) VALUES (%s, 0)", (user_id,))
        # Navýšit počet klíčů
        cur.execute("UPDATE user_keys SET key_count = key_count + %s WHERE user_id = %s", (int(amount), user_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


def _get_user_stats_row(user_id):
    ensure_user_stats_exists(user_id)
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM user_stats WHERE user_id = %s", (user_id,))
    row = cur.fetchone() or {}
    cur.close()
    conn.close()
    return row


def _get_snapshot(user_id, day, column_name):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT base_value FROM user_daily_snapshots WHERE user_id = %s AND day = %s AND column_name = %s",
        (user_id, day, column_name)
    )
    r = cur.fetchone()
    cur.close()
    conn.close()
    return int(r[0]) if r and r[0] is not None else None


def _set_snapshot(user_id, day, column_name, base_value):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_daily_snapshots (user_id, day, column_name, base_value)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE base_value = VALUES(base_value)
            """,
            (user_id, day, column_name, int(base_value))
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


def _get_claim_record(user_id, day, quest_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT claimed FROM user_daily_quests WHERE user_id = %s AND day = %s AND quest_id = %s",
        (user_id, day, quest_id)
    )
    r = cur.fetchone()
    cur.close()
    conn.close()
    if not r:
        return None
    return bool(r[0])


def _set_claim(user_id, day, quest_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_daily_quests (user_id, day, quest_id, claimed, claimed_at)
            VALUES (%s, %s, %s, 1, %s)
            ON DUPLICATE KEY UPDATE claimed=1, claimed_at=VALUES(claimed_at)
            """,
            (user_id, day, quest_id, datetime.now(timezone.utc))
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


def _select_today_quests(all_quests, count=4, today=None):
    """Deterministicky vybere podmnožinu dnešních úkolů (rotace každý den o půlnoci)."""
    if not all_quests:
        return []
    today = today or date.today()
    seed_str = today.isoformat()
    seed = int(hashlib.sha256(seed_str.encode('utf-8')).hexdigest(), 16) % (2 ** 32)
    rng = random.Random(seed)
    q_copy = list(all_quests)
    rng.shuffle(q_copy)
    return q_copy[:min(max(1, int(count)), len(q_copy))]


def _compute_today_quests(user_id):
    """Vrátí dnešní úkoly včetně postupu/claim stavu pro uživatele."""
    _ensure_tables()
    qlist_all = _load_daily_quests()
    # Vyber dnešní sadu (rotace o půlnoci), default 4
    qlist = _select_today_quests(qlist_all, count=4)
    today = date.today()

    # Načti aktuální statistiky
    stats_row = _get_user_stats_row(user_id)

    # Zajisti snapshoty pro delta módy
    needed_columns = {q['stat'] for q in qlist if q.get('mode') == 'delta'}
    for col in needed_columns:
        snap = _get_snapshot(user_id, today, col)
        if snap is None:
            base_val = int(stats_row.get(col, 0) or 0)
            _set_snapshot(user_id, today, col, base_val)

    # Přepočti progres
    result = []
    for q in qlist:
        stat_col = q.get('stat')
        target = int(q.get('target', 0) or 0)
        cur_val = int(stats_row.get(stat_col, 0) or 0)
        mode = q.get('mode', 'delta')
        if mode == 'delta':
            base = _get_snapshot(user_id, today, stat_col) or 0
            value = max(0, cur_val - base)
        else:
            value = cur_val
        progress = max(0, min(target, value))
        complete = value >= target
        claimed = bool(_get_claim_record(user_id, today, q['id'])) if complete else False
        result.append({
            'id': q['id'],
            'title': q.get('title', q['id']),
            'desc': q.get('desc', ''),
            'target': target,
            'progress': progress,
            'complete': complete,
            'claimed': claimed,
            'reward_xp': int(q.get('reward_xp', 0) or 0),
            'reward_keys': int(q.get('reward_keys', 0) or 0)
        })
    return result


@daily_bp.route('/daily/claim', methods=['POST'])
def claim_daily():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'not_authenticated'}), 401
    data = request.get_json(silent=True) or {}
    quest_id = data.get('quest_id')
    if not quest_id:
        return jsonify({'ok': False, 'error': 'missing_quest_id'}), 400

    # Najdi quest definici
    quests = _load_daily_quests()
    qmap = {q['id']: q for q in quests}
    if quest_id not in qmap:
        return jsonify({'ok': False, 'error': 'quest_not_found'}), 404

    today = date.today()
    # Zkontroluj stav (splněno?)
    today_list = _compute_today_quests(user_id)
    qstate = next((x for x in today_list if x['id'] == quest_id), None)
    if not qstate:
        return jsonify({'ok': False, 'error': 'state_not_found'}), 404
    if not qstate['complete']:
        return jsonify({'ok': False, 'error': 'not_complete'}), 400

    # Atomický claim: nejdřív zajistit řádek, pak přepnout claimed z 0 -> 1 a vyplatit odměnu jen jednou
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # zajistit záznam s claimed=0, pokud ještě neexistuje (idempotentně)
        cur.execute(
            """
            INSERT IGNORE INTO user_daily_quests (user_id, day, quest_id, claimed, claimed_at)
            VALUES (%s, %s, %s, 0, NULL)
            """,
            (user_id, today, quest_id)
        )
        # pokus o přepnutí na claimed=1 – jen pokud dosud nebyl claimnutý
        nowdt = datetime.now(timezone.utc)
        cur.execute(
            """
            UPDATE user_daily_quests
            SET claimed = 1, claimed_at = %s
            WHERE user_id = %s AND day = %s AND quest_id = %s AND claimed = 0
            """,
            (nowdt, user_id, today, quest_id)
        )
        changed = (cur.rowcount or 0) > 0
        if not changed:
            # už bylo claimnuto dříve -> nevyplácej odměnu znovu
            conn.commit()
            return jsonify({'ok': False, 'error': 'already_claimed'}), 400

        # Teprve teď vyplať XP a klíče (jednou)
        reward_xp = int(qmap[quest_id].get('reward_xp', 0) or 0)
        reward_keys = int(qmap[quest_id].get('reward_keys', 0) or 0)
        if reward_xp > 0:
            try:
                add_xp_to_user(user_id, reward_xp, reason=f"daily:{quest_id}")
            except Exception:
                pass
        if reward_keys > 0:
            try:
                _add_keys_to_user(user_id, reward_keys)
            except Exception:
                pass
        conn.commit()
        return jsonify({'ok': True, 'reward_xp': reward_xp, 'reward_keys': reward_keys})
    except Exception:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try:
            if cur:
                cur.close()
            if conn:
                conn.close()
        except Exception:
            pass


def get_daily_quests_for_user(user_id: int):
    """Veřejná utilita pro načtení dnešních denních úkolů pro daného uživatele."""
    if not user_id:
        return None
    try:
        return _compute_today_quests(user_id)
    except Exception:
        return None


@daily_bp.context_processor
def inject_daily_quests():
    user_id = session.get('user_id')
    if not user_id:
        return dict(daily_quests=None)
    try:
        quests = _compute_today_quests(user_id)
        return dict(daily_quests=quests)
    except Exception:
        return dict(daily_quests=None)
