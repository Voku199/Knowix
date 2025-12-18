import os
import json
import re
import tempfile
import errno
import time
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify, current_app
from db import get_db_connection

try:
    from xp import add_xp_to_user
except Exception as ex:
    # Zalogujs chybu importu, aby bylo vidět, proč se případně nepřidávají XP
    try:
        current_app.logger.error(f"[slovni_fotbal] Failed to import add_xp_to_user from xp: {ex}")
    except Exception:
        # current_app nemusí být k dispozici při importu modulu
        print(f"[slovni_fotbal] Failed to import add_xp_to_user from xp: {ex}")
    add_xp_to_user = None
try:
    from streak import update_user_streak
except Exception:
    update_user_streak = None

slovni_bp = Blueprint("slovni_fotbal", __name__, template_folder="templates")

# Přidáme endpoint set_timer mezi vyjmuté z CSRF (pokud security_ext existuje)
try:
    import security_ext

    try:
        # pokusíme se přidat několik možných názvů endpointu, aby to bylo odolné vůči různým názvům
        security_ext.EXEMPT_ENDPOINTS.add('slovni_fotbal.slovni_set_timer')
    except Exception:
        try:
            lst = list(security_ext.EXEMPT_ENDPOINTS)
            if 'slovni_fotbal.slovni_set_timer' not in lst:
                lst.append('slovni_fotbal.slovni_set_timer')
            # přidejme i varianty bez namespace pro případ jiného registrátoru
            if 'slovni_set_timer' not in lst:
                lst.append('slovni_set_timer')
            security_ext.EXEMPT_ENDPOINTS = set(lst)
        except Exception:
            pass
except Exception:
    pass

CACHE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "cache"))
CACHE_FILE = os.path.join(CACHE_PATH, "slovni_fotbal_cache.json")

TIMER_SECONDS = 60  # odpověď musí přijít do 60 sekund

# pokusíme se importovat ai modul, pokud existuje
try:
    from ai import ask_community_ai
except Exception:
    ask_community_ai = None


def ensure_cache():
    try:
        os.makedirs(CACHE_PATH, exist_ok=True)
    except Exception:
        # pokud se nepodaří vytvořit složku, nechceme crashovat aplikaci
        return False
    if not os.path.isfile(CACHE_FILE):
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"words": []}, f, ensure_ascii=False, indent=2)
        except Exception:
            # pokud zápis selže, smažeme případný poškozený soubor a vytvoríme nový
            try:
                if os.path.exists(CACHE_FILE):
                    os.remove(CACHE_FILE)
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump({"words": []}, f, ensure_ascii=False, indent=2)
            except Exception:
                return False
    return True


def load_cache():
    ok = ensure_cache()
    if not ok:
        return {"words": []}
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # pokud je obsah poškozený, snažíme se přepsat základní strukturou
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"words": []}, f, ensure_ascii=False, indent=2)
            return {"words": []}
        except Exception:
            return {"words": []}


def save_word_to_cache(word):
    # atomický zápis přes temp soubor (NamedTemporaryFile je bezpečnější na Windows)
    data = load_cache()
    words = set(data.get("words", []))
    if word in words:
        return
    words.add(word)
    payload = {"words": sorted(list(words))}
    try:
        ensure_cache()
        dirpath = CACHE_PATH
        # Použijeme NamedTemporaryFile s delete=False, zapíšeme textově a pak atomicky nahradíme cílový soubor
        tmpf = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, dir=dirpath, suffix=".tmp",
                                             prefix="slovni_") as tmpf:
                json.dump(payload, tmpf, ensure_ascii=False, indent=2)
                tmpf.flush()
                os.fsync(tmpf.fileno())
            tmpname = tmpf.name
            os.replace(tmpname, CACHE_FILE)
        finally:
            # pokud tmp soubor z nějakého důvodu zůstal, pokusíme se ho odstranit
            try:
                if tmpf is not None and os.path.exists(tmpf.name):
                    os.remove(tmpf.name)
            except Exception:
                pass
    except OSError as e:
        # Ignorujeme chyby zapisování cache, aplikace může normálně pokračovat
        try:
            if getattr(e, 'errno', None) == errno.EBADF:
                # Bad file descriptor - pokusíme se znovu vytvořit soubor běžným způsobem
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    except Exception:
        pass


WORD_RE = re.compile(r"^[a-zA-Z'-]+$")


def local_validate(prev, word, used):
    w = word.strip().lower()
    if not w:
        return False, "Slovo je prázdné."
    if not WORD_RE.match(w):
        return False, "Slovo obsahuje nepovolené znaky."
    if len(w) < 2:
        return False, "Slovo je příliš krátké."
    if w in used:
        return False, "Toto slovo už bylo použité."
    if prev:
        # poslední písmeno předchozího slova
        last = prev.strip().lower()[-1]
        if w[0] != last:
            return False, f"Slovo musí začínat písmenem '{last}'."
    return True, "OK"


def ensure_slovni_columns():
    """Přidá do user_stats potřebné sloupce, pokud neexistují."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # ověříme podle INFORMATION_SCHEMA
        cur.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='user_stats' AND COLUMN_NAME='slovni_best_time'",
            (os.environ.get('DB_NAME'),))
        has_best = cur.fetchone()[0] > 0
        cur.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='user_stats' AND COLUMN_NAME='slovni_quick_points'",
            (os.environ.get('DB_NAME'),))
        has_points = cur.fetchone()[0] > 0
        cur.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='user_stats' AND COLUMN_NAME='slovni_timer_pref'",
            (os.environ.get('DB_NAME'),))
        has_timer_pref = cur.fetchone()[0] > 0
        # nové per-timer sloupce
        cur.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='user_stats' AND COLUMN_NAME='slovni_points_60'",
            (os.environ.get('DB_NAME'),))
        has_p60 = cur.fetchone()[0] > 0
        cur.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='user_stats' AND COLUMN_NAME='slovni_points_90'",
            (os.environ.get('DB_NAME'),))
        has_p90 = cur.fetchone()[0] > 0
        cur.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='user_stats' AND COLUMN_NAME='slovni_points_120'",
            (os.environ.get('DB_NAME'),))
        has_p120 = cur.fetchone()[0] > 0
        if not (has_best and has_points and has_timer_pref and has_p60 and has_p90 and has_p120):
            alters = []
            if not has_best:
                alters.append("ADD COLUMN slovni_best_time DOUBLE NULL")
            if not has_points:
                alters.append("ADD COLUMN slovni_quick_points INT NOT NULL DEFAULT 0")
            if not has_timer_pref:
                alters.append("ADD COLUMN slovni_timer_pref INT NULL")
            if not has_p60:
                alters.append("ADD COLUMN slovni_points_60 INT NOT NULL DEFAULT 0")
            if not has_p90:
                alters.append("ADD COLUMN slovni_points_90 INT NOT NULL DEFAULT 0")
            if not has_p120:
                alters.append("ADD COLUMN slovni_points_120 INT NOT NULL DEFAULT 0")
            if alters:
                sql = "ALTER TABLE user_stats " + ", ".join(alters)
                cur.execute(sql)
                conn.commit()
    except Exception:
        # pokud selže, nechceme zlomit hru
        pass
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


def update_user_slovni_stats(user_id, elapsed_seconds, was_accepted):
    """Aktualizuje uživatelská statistická pole pro slovní fotbal.
    - slovni_best_time: nejlepší (nejmenší) čas
    - slovni_quick_points: počet rychlých správných odpovědí (podle zvoleného timeru)
    Navíc udržuje per-timer body (slovni_points_60/90/120).
    Pokud je uživatel v režimu bez časování (session['slovni_timer'] == 0), aktualizace statistik se přeskočí.
    """
    if not user_id:
        return
    # pokud je režim bez časování, neaktualizujeme DB - hráč nechce soutěžit
    try:
        current_timer = int(session.get('slovni_timer', TIMER_SECONDS))
        if current_timer == 0:
            return
    except Exception:
        current_timer = TIMER_SECONDS
    try:
        ensure_slovni_columns()
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT slovni_best_time, slovni_quick_points FROM user_stats WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        # pokud záznam neexistuje, vytvoříme jej pomocí ensure_user_stats_exists z jiného modulu
        if row is None:
            try:
                from stats import ensure_user_stats_exists
                ensure_user_stats_exists(user_id)
                cur.execute("SELECT slovni_best_time, slovni_quick_points FROM user_stats WHERE user_id = %s",
                            (user_id,))
                row = cur.fetchone()
            except Exception:
                row = None
        # připrav aktualizace
        if row is not None and was_accepted and elapsed_seconds is not None:
            best = row.get('slovni_best_time')
            points = row.get('slovni_quick_points') or 0
            updates = []
            params = []
            # aktualizovat nejlepší čas pokud je menší
            if best is None or elapsed_seconds < best:
                updates.append('slovni_best_time = %s')
                params.append(elapsed_seconds)
            # pokud byl response rychlý (<= aktuálního timeru), přidáme bod
            try:
                timer_for_user = int(session.get('slovni_timer', TIMER_SECONDS))
            except Exception:
                timer_for_user = TIMER_SECONDS
            if timer_for_user > 0 and elapsed_seconds <= timer_for_user:
                # historický agregát (zachován kvůli kompatibilitě)
                updates.append('slovni_quick_points = %s')
                params.append(points + 1)
                # per-timer inkrement
                try:
                    cur2 = conn.cursor()
                    if timer_for_user == 60:
                        cur2.execute(
                            "UPDATE user_stats SET slovni_points_60 = COALESCE(slovni_points_60,0)+1 WHERE user_id=%s",
                            (user_id,))
                    elif timer_for_user == 90:
                        cur2.execute(
                            "UPDATE user_stats SET slovni_points_90 = COALESCE(slovni_points_90,0)+1 WHERE user_id=%s",
                            (user_id,))
                    elif timer_for_user == 120:
                        cur2.execute(
                            "UPDATE user_stats SET slovni_points_120 = COALESCE(slovni_points_120,0)+1 WHERE user_id=%s",
                            (user_id,))
                    conn.commit()
                    try:
                        cur2.close()
                    except Exception:
                        pass
                except Exception:
                    pass
            if updates:
                params.append(user_id)
                sql = 'UPDATE user_stats SET ' + ', '.join(updates) + ' WHERE user_id = %s'
                cur.execute(sql, tuple(params))
                conn.commit()
    except Exception:
        pass
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


def get_slovni_leaderboard_for_timer(timer_seconds, limit=10):
    """Leaderboard pro konkrétní časovač (60/90/120). Vrací pole dictů s klíči display, slovni_quick_points, slovni_best_time."""
    if timer_seconds not in (60, 90, 120):
        return []
    col = {60: 'slovni_points_60', 90: 'slovni_points_90', 120: 'slovni_points_120'}[timer_seconds]
    try:
        ensure_slovni_columns()
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            sql = (
                f"SELECT us.user_id, "
                f"COALESCE(NULLIF(TRIM(u.first_name), ''), CONCAT('User ', us.user_id)) AS display, "
                f"us.{col} AS slovni_quick_points, us.slovni_best_time "
                f"FROM user_stats us LEFT JOIN users u ON u.id = us.user_id "
                f"ORDER BY us.{col} DESC, us.slovni_best_time ASC LIMIT %s"
            )
            cur.execute(sql, (limit,))
        except Exception:
            # fallback bez joinu
            sql = (
                f"SELECT CONCAT('User ', user_id) AS display, {col} AS slovni_quick_points, slovni_best_time FROM user_stats "
                f"ORDER BY {col} DESC, slovni_best_time ASC LIMIT %s")
            cur.execute(sql, (limit,))
        rows = cur.fetchall() or []
        return rows
    except Exception:
        return []
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


def get_slovni_leaderboards_by_timer(limit=10):
    """Vrátí mapu leaderboards pro 60/90/120 sekund."""
    result = {}
    for t in (60, 90, 120):
        try:
            rows = get_slovni_leaderboard_for_timer(t, limit)
            # serializace do jednoduchých dictů (pro JSON i šablonu)
            lb = []
            for r in rows:
                if isinstance(r, dict):
                    lb.append({
                        'display': r.get('display'),
                        'slovni_quick_points': r.get('slovni_quick_points') or 0,
                        'slovni_best_time': float(r.get('slovni_best_time')) if r.get(
                            'slovni_best_time') is not None else None
                    })
                else:
                    # tuple fallback
                    lb.append({
                        'display': str(r[0]),
                        'slovni_quick_points': r[1] if len(r) > 1 else 0,
                        'slovni_best_time': float(r[2]) if len(r) > 2 and r[2] is not None else None
                    })
            result[str(t)] = lb
        except Exception:
            result[str(t)] = []
    return result


# Ponecháme i původní pomocnou funkci pro kompatibilitu (vrátí leaderboard pro 60s jako výchozí)
def get_slovni_leaderboard(limit=10):
    try:
        # Výchozí sekce: 60s (aby se nezlomily staré části kódu, které očekávají jediné pole)
        return get_slovni_leaderboard_for_timer(60, limit)
    except Exception:
        return []


def get_remaining_seconds():
    """Vypočte a vrátí zbývající sekundy podle session startu a session timeru.
    Pokud je timer == 0 (bez časování), vrací -1 jako speciální hodnotu.
    """
    timer = session.get('slovni_timer', TIMER_SECONDS)
    # pokud je režim bez časování, vraťme -1
    try:
        if int(timer) == 0:
            return -1
    except Exception:
        pass
    start = session.get('slovni_start_time')
    if start is None:
        return int(timer)
    try:
        rem = int(max(0, timer - (time.time() - float(start))))
    except Exception:
        rem = int(timer)
    return rem


@slovni_bp.route('/slovni-fotbal/state')
def slovni_state():
    """Vrátí JSON stav hry (chain, cache_count, leaderboards, remaining_seconds, timer_seconds).
    This endpoint by design NEZMĚNÍ session['slovni_start_time'] (pro silent refresh).
    """
    chain = session.get('slovni_chain', [])
    cache = load_cache()
    # kompletní mapu leaderboardů
    leaderboards = get_slovni_leaderboards_by_timer(10)
    remaining = get_remaining_seconds()
    timer = session.get('slovni_timer', TIMER_SECONDS)
    # pro kompatibilitu vybereme jednu sekci jako 'leaderboard'
    try:
        tsel = int(timer)
        if tsel not in (0, 60, 90, 120):
            tsel = 60
    except Exception:
        tsel = 60
    lb_single = leaderboards.get(str(tsel if tsel != 0 else 60), [])
    return jsonify({
        'chain': chain,
        'cache_count': len(cache.get('words', [])),
        'leaderboards': leaderboards,
        'leaderboard': lb_single,
        'remaining_seconds': remaining,
        'timer_seconds': timer
    })


@slovni_bp.route('/slovni-fotbal/set_timer', methods=['POST'])
def slovni_set_timer():
    """Nastaví session timer podle požadavku uživatele.
    Povolené hodnoty: 0 (bez časování), 60, 90, 120 sekund. Nepřepisuje start_time pokud už existuje (kromě případu, kdy jde o untimed).
    Vrátí JSON odpověď (pro AJAX).
    """
    # podporujeme form-data i JSON
    seconds = None
    start_ts = None
    try:
        if request.is_json:
            seconds = request.json.get('seconds')
            start_ts = request.json.get('start_ts')
        else:
            seconds = request.form.get('seconds') or request.values.get('seconds')
            start_ts = request.form.get('start_ts') or request.values.get('start_ts')
    except Exception:
        seconds = None
        start_ts = None
    try:
        seconds = int(seconds)
    except Exception:
        seconds = None
    # parse optional start_ts (epoch seconds)
    try:
        if start_ts is not None:
            start_ts = float(start_ts)
        else:
            start_ts = None
    except Exception:
        start_ts = None
    if seconds is None:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'ok': False, 'error': 'Invalid seconds'}), 400
        return jsonify({'ok': False, 'error': 'Invalid seconds'}), 400
    # povolené volby: 0 (bez časování), 60, 90, 120
    allowed = {0, 60, 90, 120}
    if seconds not in allowed:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'ok': False, 'error': 'Invalid timer option'}), 400
        return jsonify({'ok': False, 'error': 'Invalid timer option'}), 400
    session['slovni_timer'] = seconds
    if seconds == 0:
        # untimed: odstraň start_time pokud existuje
        session.pop('slovni_start_time', None)
    else:
        # pokud byl zaslán start_ts, nastavíme ho (to zajistí persistenci přes reload)
        if start_ts is not None:
            try:
                session['slovni_start_time'] = float(start_ts)
            except Exception:
                session['slovni_start_time'] = time.time()
        else:
            # pokud start_time neexistuje, nastavíme ho nyní (první start)
            if 'slovni_start_time' not in session:
                session['slovni_start_time'] = time.time()
    session.modified = True

    # Uložíme preferenci do databáze pokud je uživatel přihlášený
    user_id = session.get('user_id')
    if user_id:
        try:
            ensure_slovni_columns()
            conn = get_db_connection()
            cur = conn.cursor()
            # zajistíme, že existuje záznam
            try:
                from stats import ensure_user_stats_exists
                ensure_user_stats_exists(user_id)
            except Exception:
                pass
            try:
                cur.execute("UPDATE user_stats SET slovni_timer_pref = %s WHERE user_id = %s", (seconds, user_id))
                conn.commit()
            except Exception:
                # fallback: ignore
                pass
        except Exception:
            pass
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    return jsonify({'ok': True, 'timer_seconds': seconds})


@slovni_bp.route("/slovni-fotbal", methods=["GET"])
def slovni_index():
    # inicializace session
    if 'slovni_chain' not in session:
        session['slovni_chain'] = []
        session['slovni_used'] = []
        session.modified = True
    cache = load_cache()

    # pokud je uživatel přihlášen a má uloženou preferenci v DB -> načteme ji do session
    user_id = session.get('user_id')
    if user_id and 'slovni_timer' not in session:
        try:
            ensure_slovni_columns()
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT slovni_timer_pref FROM user_stats WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if row and row.get('slovni_timer_pref'):
                session['slovni_timer'] = int(row.get('slovni_timer_pref'))
                session.modified = True
        except Exception:
            pass
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    # načteme leaderboardy pro počáteční vykreslení stránky
    try:
        leaderboards = get_slovni_leaderboards_by_timer(10)
    except Exception:
        leaderboards = {"60": [], "90": [], "120": []}

    return render_template("SL_fotball/sl_fotball.html", chain=session['slovni_chain'],
                           cache_count=len(cache.get('words', [])), leaderboards=leaderboards)


@slovni_bp.route("/slovni-fotbal/play", methods=["GET", "POST"])
def slovni_play():
    if 'slovni_chain' not in session:
        session['slovni_chain'] = []
        session['slovni_used'] = []

    chain = session['slovni_chain']
    used = set(session.get('slovni_used', []))
    prev = chain[-1] if chain else None

    if request.method == 'POST':
        word = request.form.get('word', '').strip()
        word_lower = word.lower()

        # změř čas od posledního startu (server-side enforcement) - NEdestruktivně
        start = session.get('slovni_start_time')
        elapsed = None
        try:
            if start is not None:
                elapsed = time.time() - float(start)
        except Exception:
            elapsed = None

        # pokud uživatel odpověděl po limitu, zamítneme server-side
        try:
            timer_val = int(session.get('slovni_timer', TIMER_SECONDS))
        except Exception:
            timer_val = TIMER_SECONDS
        if timer_val > 0 and elapsed is not None and elapsed > timer_val:
            try:
                current_app.logger.info(
                    f"slovni_play: time expired user={session.get('user_id')} word={word_lower} elapsed={elapsed}")
            except Exception:
                pass
            # připravíme stav pro JSON odpověď
            cache = load_cache()
            leaderboard = get_slovni_leaderboard(10)
            state = {
                'chain': session.get('slovni_chain', []),
                'cache_count': len(cache.get('words', [])),
                'leaderboard': leaderboard,
                'remaining_seconds': get_remaining_seconds(),
                'timer_seconds': session.get('slovni_timer', TIMER_SECONDS)
            }
            # pokud AJAX požadavek, vrať JSON chybu s aktuálním stavem
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                user_id = session.get('user_id')
                try:
                    update_user_slovni_stats(user_id, elapsed, False)
                except Exception:
                    pass
                # NOTE: do NOT award XP/streak here; client will call reset (/slovni-fotbal/reset) when user chooses "Hrát další"
                session.modified = True
                resp = {'ok': False, 'error': 'Čas vypršel — odpověď přišla příliš pozdě.'}
                # instruct client to show end-of-round modal
                resp['show_modal'] = True
                # přidej aktuální leaderboards
                try:
                    resp['leaderboards'] = get_slovni_leaderboards_by_timer(10)
                except Exception:
                    resp['leaderboards'] = {"60": [], "90": [], "120": []}
                cache = load_cache()
                resp.update({
                    'chain': session.get('slovni_chain', []),
                    'cache_count': len(cache.get('words', [])),
                    'remaining_seconds': get_remaining_seconds(),
                    'timer_seconds': session.get('slovni_timer', TIMER_SECONDS)
                })
                return jsonify(resp), 400
            flash('Čas vypršel — odpověď přišla příliš pozdě.', 'error')
            user_id = session.get('user_id')
            try:
                update_user_slovni_stats(user_id, elapsed, False)
            except Exception:
                pass
            # NOTE: do NOT award XP/streak here; reset endpoint will handle awarding when user confirms
            session.modified = True
            return redirect(url_for('slovni_fotbal.slovni_play'))

        valid, reason = local_validate(prev, word_lower, used)
        # ai_confirmed: True = AI explicitly confirmed, False = AI explicitly rejected, None = no AI / undecided
        ai_confirmed = None
        ai_checked = False
        ai_note = None

        if not valid:
            try:
                current_app.logger.info(
                    f"slovni_play: invalid word user={session.get('user_id')} word={word_lower} reason={reason}")
            except Exception:
                pass
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                cache = load_cache()
                leaderboard = get_slovni_leaderboard(10)
                resp = {'ok': False, 'error': reason, 'chain': session.get('slovni_chain', []),
                        'cache_count': len(cache.get('words', [])), 'leaderboard': leaderboard,
                        'remaining_seconds': get_remaining_seconds(),
                        'timer_seconds': session.get('slovni_timer', TIMER_SECONDS)}
                return jsonify(resp), 400
            flash(reason, "error")
            return redirect(url_for('slovni_fotbal.slovni_play'))

        # pokud je dostupné AI, zkusíme požádat o potvrzení
        if ask_community_ai:
            try:
                ai_checked = True
                user_id = session.get('user_id')
                prompt = f"Answer only YES or NO. Is the word '{word_lower}' a valid English word and a valid continuation of '{prev}' in a word-chain?"
                ai_resp = ask_community_ai(user_id, prompt)
                ai_note = ai_resp
                if isinstance(ai_resp, str):
                    lr = ai_resp.lower()
                    if any(x in lr for x in ['yes', 'yep', 'correct', 'valid']):
                        ai_confirmed = True
                    elif any(x in lr for x in ['no', "don't", 'not valid', 'invalid', 'nope', "nah"]):
                        ai_confirmed = False
                    else:
                        # nerozhodné
                        ai_confirmed = None
                else:
                    ai_confirmed = None
            except Exception as e:
                ai_note = f"AI error: {e}"
                ai_confirmed = None

        # pokud AI potvrdila, uložíme do cache
        if ai_checked:
            if ai_confirmed is True:
                save_word_to_cache(word_lower)
                accepted_for_stats = True
                flash_msg = (True, f"✅ '{word_lower}' přijato (ověřeno AI).")
            elif ai_confirmed is False:
                accepted_for_stats = False
                # AI explicitně zamítla -> NEukládat do cache a NEpřidávat do řetězu
                flash_msg = (False, f"❌ AI říká, že '{word_lower}' není validní — slovo odmítnuto.")
                try:
                    current_app.logger.info(
                        f"slovni_play: AI rejected user={session.get('user_id')} word={word_lower} ai_note={ai_note}")
                except Exception:
                    pass
                user_id = session.get('user_id')
                try:
                    update_user_slovni_stats(user_id, elapsed, False)
                except Exception:
                    pass
                # NOTE: do NOT reset session['slovni_start_time'] here — keep the current timer running
                # if request is AJAX, return structured response without modifying start_time
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                    cache = load_cache()
                    # přidej leaderboards dle času
                    try:
                        lbmap = get_slovni_leaderboards_by_timer(10)
                    except Exception:
                        lbmap = {"60": [], "90": [], "120": []}
                    resp = {'ok': False, 'ai_result': 'NO', 'error': 'AI rejected word', 'ai_note': ai_note,
                            'chain': session.get('slovni_chain', []), 'cache_count': len(cache.get('words', [])),
                            'leaderboards': lbmap, 'remaining_seconds': get_remaining_seconds(),
                            'timer_seconds': session.get('slovni_timer', TIMER_SECONDS)}
                    return jsonify(resp), 200
                flash(flash_msg[1], "error")
                return redirect(url_for('slovni_fotbal.slovni_play'))
            else:
                accepted_for_stats = True
                flash_msg = (True, f"✅ '{word_lower}' přijato (AI nerozhodla).")
        else:
            accepted_for_stats = True
            flash_msg = (True, f"✅ '{word_lower}' přijato (bez AI ověření).")

        # aktualizujeme session (přidání do chainu pouze pokud AI neodmítla)
        chain.append(word_lower)
        used.add(word_lower)
        session['slovni_chain'] = chain
        session['slovni_used'] = list(used)
        # POZOR: nepřepisujeme session['slovni_start_time'] zde, aby se čas neresetoval po odeslání slova
        # Start time se nastavuje pouze při explicitním nastavení timeru (/set_timer) nebo při vypršení času.
        session.modified = True
        try:
            current_app.logger.info(
                f"slovni_play: accepted user={session.get('user_id')} word={word_lower} elapsed={elapsed} chain_len={len(chain)}")
        except Exception:
            pass

        # aktualizace statistik pokud bylo přijato
        user_id = session.get('user_id')
        if accepted_for_stats:
            try:
                update_user_slovni_stats(user_id, elapsed, True)
            except Exception:
                pass

        # připravíme JSON odpověď pokud AJAX
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            # načteme cache a leaderboard aktuálně pro UI
            cache = load_cache()
            try:
                lbmap = get_slovni_leaderboards_by_timer(10)
            except Exception:
                lbmap = {"60": [], "90": [], "120": []}
            resp = {'ok': True, 'chain': session['slovni_chain'], 'cache_count': len(cache.get('words', [])),
                    'leaderboards': lbmap,
                    'ai_result': ('YES' if ai_confirmed is True else ('NO' if ai_confirmed is False else 'MAYBE')),
                    'ai_note': ai_note}
            return jsonify(resp)

    # GET
    # při GET NEpřepisujeme session['slovni_start_time'] – necháme ho běžet, aby silent refresh neměnil čas
    cache = load_cache()
    # zajistíme, že session má nastavený timer (výchozí)
    if 'slovni_timer' not in session:
        session['slovni_timer'] = TIMER_SECONDS
        # pokud dosud nemáme start_time, nastavíme ho
        if 'slovni_start_time' not in session:
            session['slovni_start_time'] = time.time()
    session.modified = True
    try:
        leaderboards = get_slovni_leaderboards_by_timer(10)
    except Exception:
        leaderboards = {"60": [], "90": [], "120": []}
    return render_template("SL_fotball/sl_fotball.html", chain=chain, cache_count=len(cache.get('words', [])),
                           timer_seconds=session.get('slovni_timer', TIMER_SECONDS), leaderboards=leaderboards)


@slovni_bp.route("/slovni-fotbal/reset")
def slovni_reset():
    # před resetem udělíme XP a aktualizujeme streak pokud je hráč přihlášený a řetěz není prázdný
    try:
        user_id = session.get('user_id')
        prev_chain = list(session.get('slovni_chain', []))
        chain_len = len(prev_chain) if prev_chain else 0
        xp_awarded = 0
        new_quick_points = None
        if user_id and chain_len > 0:
            # XP = délka řetězu
            xp_awarded = int(chain_len)
            try:
                # pokud je XP backend dostupný, přidej XP; pokud ne, jen statistiky, ale bez pádu
                if add_xp_to_user is not None:
                    add_xp_to_user(user_id, xp_awarded, reason="slovni_reset")
            except Exception as ex:
                try:
                    current_app.logger.error(
                        f"[slovni_fotbal] add_xp_to_user failed user={user_id} xp={xp_awarded}: {ex}")
                except Exception:
                    pass
            try:
                if update_user_streak:
                    update_user_streak(user_id)
            except Exception:
                pass
            # aktualizuj sloupce v user_stats: přičteme slovni_quick_points o chain_len
            # Uživatel může hrát bez časování -> v tom případě NEpočítáme body do soutěže
            try:
                timer_pref = int(session.get('slovni_timer', TIMER_SECONDS))
            except Exception:
                timer_pref = TIMER_SECONDS
            if timer_pref > 0:
                try:
                    ensure_slovni_columns()
                    conn = get_db_connection()
                    cur = conn.cursor(dictionary=True)
                    # zajistíme existenci záznamu
                    from stats import ensure_user_stats_exists
                    ensure_user_stats_exists(user_id)
                    try:
                        # historický agregát (zachován)
                        cur.execute("SELECT slovni_quick_points FROM user_stats WHERE user_id = %s", (user_id,))
                        row = cur.fetchone()
                        cur_points = (
                            row.get('slovni_quick_points') if row and row.get('slovni_quick_points') is not None else 0)
                        new_quick_points = int(cur_points) + chain_len
                        cur.execute("UPDATE user_stats SET slovni_quick_points = %s WHERE user_id = %s",
                                    (new_quick_points, user_id))
                        # per-timer inkrement o délku řetězu
                        col = 'slovni_points_60' if timer_pref == 60 else ('slovni_points_90' if timer_pref == 90 else (
                            'slovni_points_120' if timer_pref == 120 else None))
                        if col:
                            cur2 = conn.cursor()
                            cur2.execute(f"UPDATE user_stats SET {col} = COALESCE({col},0) + %s WHERE user_id=%s",
                                         (chain_len, user_id))
                            conn.commit()
                            try:
                                cur2.close()
                            except Exception:
                                pass
                        conn.commit()
                    except Exception:
                        pass
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
                    try:
                        conn.close()
                    except Exception:
                        pass
    except Exception:
        prev_chain = []
        xp_awarded = 0
        new_quick_points = None
        pass

    # remove session data
    session.pop('slovni_chain', None)
    session.pop('slovni_used', None)
    session.modified = True

    # pokud jde o AJAX, vrať JSON stav pro modal/klienta včetně awarded XP a aktualizovaného leaderboardu
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        cache = load_cache()
        try:
            lbmap = get_slovni_leaderboards_by_timer(10)
        except Exception:
            lbmap = {"60": [], "90": [], "120": []}
        return jsonify({'ok': True, 'chain': prev_chain, 'cache_count': len(cache.get('words', [])),
                        'leaderboards': lbmap,
                        'remaining_seconds': get_remaining_seconds(),
                        'timer_seconds': session.get('slovni_timer', TIMER_SECONDS),
                        'xp_awarded': xp_awarded, 'new_quick_points': new_quick_points})

    flash("♻️ Pokrok resetován.", "info")
    return redirect(url_for('slovni_fotbal.slovni_index'))
