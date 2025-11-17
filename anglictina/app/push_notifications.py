# -*- coding: utf-8 -*-
"""
PWA Web Push – Flask blueprint

Poskytuje REST endpointy pro:
- /push/vapid-public-key (GET) – vrací veřejný VAPID klíč
- /push/subscribe (POST) – uloží/aktualizuje subscription do DB (tabulka push_subscriptions)
- /push/unsubscribe (POST) – odhlásí subscription podle endpointu
- /push/csrf-token (GET) – vrací CSRF token pro SW (pushsubscriptionchange)
- /push/test-send (POST) – odeslání testovací notifikace uživateli (admin může všem)
- /push/admin/subscriptions (GET) – jednoduchý přehled uložených subscriptions (jen admin)
- /send_notification (POST) – alias pro testovací odeslání, aby vyhověl požadavku

Pozn.: DB tabulka push_subscriptions musí existovat se sloupci:
  id (PK, AUTO_INCREMENT), user_id (INT NULL), endpoint (TEXT/ VARCHAR UNIQUE), p256dh (TEXT), auth (TEXT),
  created_at (DATETIME), installed (TINYINT(1)), last_seen (DATETIME)

Závislosti: pywebpush, cryptography, mysql-connector-python
"""
from __future__ import annotations

import json
import os
import datetime as dt
from typing import Optional, Dict, Any, List

from flask import Blueprint, request, jsonify, session, abort
from pywebpush import webpush, WebPushException

from db import get_db_connection
from security_ext import _ensure_csrf_token

# Blueprint s prefixem /push
push_bp = Blueprint('push_bp', __name__, url_prefix='/push')

# VAPID klíče – načti z env, jinak použij zadané defaulty (pro dev)
VAPID_PUBLIC_KEY = os.getenv(
    'VAPID_PUBLIC_KEY'
)
VAPID_PRIVATE_KEY = os.getenv(
    'VAPID_PRIVATE_KEY'
)
VAPID_EMAIL = os.getenv('VAPID_EMAIL')


# --- Pomocné funkce ---

def _now_utc() -> dt.datetime:
    return dt.datetime.utcnow()


def _json_ok(**extra):
    d = {'ok': True}
    d.update(extra)
    return jsonify(d)


def _json_err(msg: str, code: int = 400, **extra):
    d = {'ok': False, 'error': msg}
    d.update(extra)
    return jsonify(d), code


def _current_user_id() -> Optional[int]:
    try:
        uid = session.get('user_id')
        if uid is None:
            return None
        return int(uid)
    except Exception:
        return None


def _upsert_subscription(user_id: Optional[int], sub: Dict[str, Any], installed: bool) -> None:
    endpoint = sub.get('endpoint')
    keys = (sub.get('keys') or {})
    p256dh = keys.get('p256dh')
    auth = keys.get('auth')
    if not endpoint or not p256dh or not auth:
        raise ValueError('Invalid subscription payload')

    conn = get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        # Najdi existující subscription podle endpointu
        cur.execute("SELECT id FROM push_subscriptions WHERE endpoint = %s", (endpoint,))
        row = cur.fetchone()
        if row:
            cur.execute(
                """
                UPDATE push_subscriptions
                SET user_id = %s, p256dh = %s, auth = %s, installed = %s, last_seen = %s
                WHERE id = %s
                """,
                (user_id, p256dh, auth, 1 if installed else 0, _now_utc(), row['id'])
            )
        else:
            cur.execute(
                """
                INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at, installed, last_seen)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (user_id, endpoint, p256dh, auth, _now_utc(), 1 if installed else 0, _now_utc())
            )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def _delete_subscription(endpoint: str, user_id: Optional[int]) -> int:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if user_id is not None:
            cur.execute("DELETE FROM push_subscriptions WHERE endpoint = %s AND (user_id = %s OR user_id IS NULL)",
                        (endpoint, user_id))
        else:
            cur.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (endpoint,))
        deleted = cur.rowcount
        conn.commit()
        return deleted
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def _list_subscriptions(user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        if user_id is None:
            cur.execute("SELECT * FROM push_subscriptions ORDER BY id DESC LIMIT 500")
        else:
            cur.execute("SELECT * FROM push_subscriptions WHERE user_id = %s ORDER BY id DESC LIMIT 200", (user_id,))
        rows = cur.fetchall() or []
        return rows
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def _send_webpush(subscription: Dict[str, Any], payload: Dict[str, Any]):
    """Odešle jednu notifikaci na daný subscription."""
    return webpush(
        subscription_info=subscription,
        data=json.dumps(payload, ensure_ascii=False),
        vapid_private_key=VAPID_PRIVATE_KEY,
        vapid_claims={"sub": f"mailto:{VAPID_EMAIL}"},
        ttl=60
    )


# --- Endpointy ---

@push_bp.get('/vapid-public-key')
def get_vapid_public_key():
    return jsonify({'publicKey': VAPID_PUBLIC_KEY})


@push_bp.get('/csrf-token')
def get_csrf_token():
    # Vrací CSRF token pro použití v SW při pushsubscriptionchange
    token = _ensure_csrf_token()
    return jsonify({'csrf_token': token})


@push_bp.post('/subscribe')
def subscribe_push():
    if not request.is_json:
        return _json_err('Expected application/json')
    data = request.get_json(silent=True) or {}
    subscription = data.get('subscription')
    installed = bool(data.get('installed'))
    if not isinstance(subscription, dict):
        return _json_err('Missing subscription')

    try:
        _upsert_subscription(_current_user_id(), subscription, installed)
    except ValueError as ve:
        return _json_err(str(ve))
    except Exception as ex:
        return _json_err('DB error', 500, detail=str(ex))

    return _json_ok()


@push_bp.post('/unsubscribe')
def unsubscribe_push():
    if not request.is_json:
        return _json_err('Expected application/json')
    data = request.get_json(silent=True) or {}
    endpoint = data.get('endpoint')
    if not endpoint:
        return _json_err('Missing endpoint')
    try:
        deleted = _delete_subscription(endpoint, _current_user_id())
    except Exception as ex:
        return _json_err('DB error', 500, detail=str(ex))
    return _json_ok(deleted=deleted)


@push_bp.post('/test-send')
def test_send_push():
    """
    Pošle testovací push notifikaci.
    - Pokud je přihlášen admin (user_id == 1), pošle všem.
    - Jinak pošle jen aktuálnímu uživateli (pokud má subscription).
    """
    if not request.is_json:
        return _json_err('Expected application/json')
    payload = request.get_json(silent=True) or {}

    title = payload.get('title') or 'Knowix'
    body = payload.get('body') or 'Test notifikace z Knowix'
    url = payload.get('url') or '/'

    user_id = _current_user_id()
    is_admin = (user_id == 1)

    subs = _list_subscriptions(None if is_admin else user_id)
    if not subs:
        return _json_err('No subscriptions', 404)

    sent, removed, failed = 0, 0, 0
    for row in subs:
        sub_obj = {
            'endpoint': row['endpoint'],
            'keys': {'p256dh': row['p256dh'], 'auth': row['auth']}
        }
        try:
            _send_webpush(sub_obj, {
                'title': title,
                'body': body,
                'url': url,
                'tag': 'knowix-general'
            })
            sent += 1
        except WebPushException as wpe:
            status = getattr(wpe.response, 'status_code', None)
            # 404/410 znamená, že endpoint expiroval – odebereme
            if status in (404, 410):
                try:
                    _delete_subscription(row['endpoint'], None)
                    removed += 1
                except Exception:
                    pass
            else:
                failed += 1
        except Exception:
            failed += 1

    return _json_ok(sent=sent, removed=removed, failed=failed, total=len(subs))


# Admin přehled – jednoduchý HTML/JSON
@push_bp.get('/admin/subscriptions')
def admin_list_subs():
    user_id = _current_user_id()
    if user_id != 1:
        abort(403)
    rows = _list_subscriptions(None)
    # Vrátíme jednoduché HTML pro rychlou kontrolu v prohlížeči
    html = [
        '<h2>Push subscriptions</h2>',
        f'<p>Celkem: {len(rows)}</p>',
        '<table border="1" cellpadding="6" cellspacing="0">',
        '<tr><th>ID</th><th>User</th><th>Endpoint</th><th>Installed</th><th>Last seen</th><th>Created</th></tr>'
    ]
    for r in rows:
        html.append(
            f"<tr><td>{r['id']}</td><td>{r.get('user_id')}</td><td style='max-width:520px;word-break:break-all'>{r.get('endpoint')}</td>"
            f"<td>{'✓' if r.get('installed') else ''}</td><td>{r.get('last_seen')}</td><td>{r.get('created_at')}</td></tr>"
        )
    html.append('</table>')
    return "\n".join(html)


# Alias bez prefixu (splní požadavek na /send_notification)
@push_bp.post('/send_notification')
def send_notification_alias():
    return test_send_push()
