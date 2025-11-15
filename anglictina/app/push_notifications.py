import os
import json
from flask import Blueprint, request, jsonify, session
from db import get_db_connection

try:
    from pywebpush import webpush, WebPushException
except ImportError:
    webpush = None


    class WebPushException(Exception):
        pass

push_bp = Blueprint('push_bp', __name__, url_prefix='/push')

VAPID_PUBLIC_KEY = os.getenv('VAPID_PUBLIC_KEY')
VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY')
VAPID_EMAIL = os.getenv('VAPID_EMAIL', 'admin@knowix.cz')

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NULL,
    endpoint VARCHAR(500) NOT NULL UNIQUE,
    p256dh VARCHAR(150) NOT NULL,
    auth VARCHAR(150) NOT NULL,
    installed TINYINT(1) NOT NULL DEFAULT 0,
    last_seen TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

ALTERS = (
    "ALTER TABLE push_subscriptions ADD COLUMN installed TINYINT(1) NOT NULL DEFAULT 0",
    "ALTER TABLE push_subscriptions ADD COLUMN last_seen TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
)


def ensure_table():
    try:
        conn = get_db_connection();
        cur = conn.cursor();
        cur.execute(TABLE_SQL);
        conn.commit()
        # pokusné altery (ignoruj, pokud již existují)
        for sql in ALTERS:
            try:
                cur.execute(sql)
                conn.commit()
            except Exception:
                pass
        cur.close();
        conn.close()
    except Exception as ex:
        print(f'[push] TABLE ensure error: {ex}')


ensure_table()


@push_bp.get('/vapid-public-key')
def vapid_public_key():
    return jsonify({'publicKey': VAPID_PUBLIC_KEY or ''})


@push_bp.post('/subscribe')
def subscribe():
    # Uživatelské subscription chceme ukládat i bez VAPID/pywebpush (pro pozdější aktivaci)
    try:
        data = request.get_json(force=True) or {}
        subscription = data.get('subscription') or data
        endpoint = subscription.get('endpoint')
        keys = subscription.get('keys', {})
        p256dh = keys.get('p256dh')
        auth = keys.get('auth')
        if not (endpoint and p256dh and auth):
            return jsonify({'ok': False, 'error': 'Invalid subscription object'}), 400
        user_id = session.get('user_id')
        conn = get_db_connection();
        cur = conn.cursor()
        sql = 'INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE user_id=VALUES(user_id), p256dh=VALUES(p256dh), auth=VALUES(auth)'
        cur.execute(sql, (user_id, endpoint, p256dh, auth))
        conn.commit();
        cur.close();
        conn.close()
        # Info zda je připraveno na odeslání
        ready = bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY and webpush)
        return jsonify({'ok': True, 'ready_for_push': ready})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500


@push_bp.get('/count')
def count_subscriptions():
    try:
        conn = get_db_connection();
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM push_subscriptions')
        total = cur.fetchone()[0]
        cur.close();
        conn.close()
        return jsonify({'ok': True, 'count': total})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500


def _send_webpush(sub, payload: dict):
    if not (VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY and webpush):
        raise WebPushException('Push sending not configured (missing VAPID or pywebpush)')
    return webpush(
        subscription=sub,
        data=json.dumps(payload),
        vapid_private_key=VAPID_PRIVATE_KEY,
        vapid_public_key=VAPID_PUBLIC_KEY,
        vapid_claims={"sub": f"mailto:{VAPID_EMAIL}"}
    )


@push_bp.get('/broadcast')
def broadcast_get_info():
    return jsonify({'ok': False, 'error': 'Use POST',
                    'hint': 'POST JSON {"title":"...","body":"...","url":"/..."} to /push/broadcast'}), 405


@push_bp.post('/broadcast')
def broadcast():
    if 'user_id' not in session:
        return jsonify({'ok': False, 'error': 'Auth required'}), 401
    title = request.json.get('title', 'Knowix')
    body = request.json.get('body', 'Nová lekce je dostupná!')
    url = request.json.get('url', '/')
    sent = 0;
    failed = 0
    try:
        conn = get_db_connection();
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT endpoint, p256dh, auth FROM push_subscriptions')
        rows = cur.fetchall();
        cur.close();
        conn.close()
        ready = bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY and webpush)
        if not ready:
            return jsonify(
                {'ok': False, 'error': 'Push not configured', 'sent': 0, 'failed': 0, 'subscriptions': len(rows)})
        for row in rows:
            sub = {'endpoint': row['endpoint'], 'keys': {'p256dh': row['p256dh'], 'auth': row['auth']}}
            try:
                _send_webpush(sub, {'title': title, 'body': body, 'url': url})
                sent += 1
            except WebPushException as wex:
                print(f'[push] send error: {wex}');
                failed += 1
        return jsonify({'ok': True, 'sent': sent, 'failed': failed, 'subscriptions': len(rows)})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500


@push_bp.get('/csrf-token')
def get_csrf_token():
    token = session.get('_csrf_token')
    return jsonify({'csrf_token': token or ''})


@push_bp.get('/test')
def push_test_page():
    return (
        """<!doctype html><meta charset='utf-8'><title>Push test</title><body style='font-family:system-ui;padding:24px'><h1>Push broadcast test</h1><p>Musíte být přihlášeni. Odešle POST na /push/broadcast.</p><div id='info'></div><form id='f'><label>Title <input name='title' value='Knowix'></label><br><label>Body <input name='body' value='Nová lekce je dostupná!'></label><br><label>URL <input name='url' value='/'></label><br><button>Odeslat</button></form><pre id='out'></pre><script>let CSRF=null;fetch('/push/csrf-token').then(r=>r.json()).then(j=>{CSRF=j.csrf_token||null;});fetch('/push/count').then(r=>r.json()).then(j=>{document.getElementById('info').textContent='Subscriptions: '+(j.count||0);});document.getElementById('f').addEventListener('submit', async (e)=>{e.preventDefault();const fd=new FormData(e.target);const payload=Object.fromEntries(fd.entries());const headers={'Content-Type':'application/json'};if(CSRF) headers['X-CSRFToken']=CSRF;const res=await fetch('/push/broadcast',{method:'POST',headers,body:JSON.stringify(payload)});document.getElementById('out').textContent=await res.text();});</script></body>""")


@push_bp.post('/installed')
def mark_installed():
    try:
        data = request.get_json(force=True) or {}
        endpoint = data.get('endpoint')
        installed = 1 if data.get('installed') else 0
        if not endpoint:
            return jsonify({'ok': False, 'error': 'Missing endpoint'}), 400
        conn = get_db_connection();
        cur = conn.cursor()
        cur.execute('UPDATE push_subscriptions SET installed=%s, last_seen=NOW() WHERE endpoint=%s',
                    (installed, endpoint))
        conn.commit();
        cur.close();
        conn.close()
        return jsonify({'ok': True})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500


@push_bp.post('/ping')
def ping_subscription():
    try:
        data = request.get_json(force=True) or {}
        endpoint = data.get('endpoint')
        if not endpoint:
            return jsonify({'ok': False, 'error': 'Missing endpoint'}), 400
        conn = get_db_connection();
        cur = conn.cursor()
        cur.execute('UPDATE push_subscriptions SET last_seen=NOW() WHERE endpoint=%s', (endpoint,))
        conn.commit();
        cur.close();
        conn.close()
        return jsonify({'ok': True})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500


@push_bp.post('/to-user/<int:user_id>')
def push_to_user(user_id: int):
    title = request.json.get('title', 'Knowix')
    body = request.json.get('body', 'Máte novou výzvu!')
    url = request.json.get('url', '/')
    if not (VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY and webpush):
        return jsonify({'ok': False, 'error': 'Push not configured'}), 503
    sent = 0;
    failed = 0
    try:
        conn = get_db_connection();
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE user_id=%s AND installed=1',
                    (user_id,))
        rows = cur.fetchall();
        cur.close();
        conn.close()
        for row in rows:
            sub = {'endpoint': row['endpoint'], 'keys': {'p256dh': row['p256dh'], 'auth': row['auth']}}
            try:
                _send_webpush(sub, {'title': title, 'body': body, 'url': url})
                sent += 1
            except WebPushException as wex:
                print(f'[push] send error: {wex}');
                failed += 1
        return jsonify({'ok': True, 'sent': sent, 'failed': failed})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500


@push_bp.post('/broadcast-installed')
def broadcast_installed():
    title = request.json.get('title', 'Knowix')
    body = request.json.get('body', 'Zpět do lekce?')
    url = request.json.get('url', '/')
    if not (VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY and webpush):
        return jsonify({'ok': False, 'error': 'Push not configured'}), 503
    sent = 0;
    failed = 0
    try:
        conn = get_db_connection();
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE installed=1')
        rows = cur.fetchall();
        cur.close();
        conn.close()
        for row in rows:
            sub = {'endpoint': row['endpoint'], 'keys': {'p256dh': row['p256dh'], 'auth': row['auth']}}
            try:
                _send_webpush(sub, {'title': title, 'body': body, 'url': url})
                sent += 1
            except WebPushException as wex:
                print(f'[push] send error: {wex}');
                failed += 1
        return jsonify({'ok': True, 'sent': sent, 'failed': failed})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500
