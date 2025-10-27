# security_ext.py
import os, secrets
from flask import session, request, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def _determine_storage_uri():
    if os.getenv('FLASK_ENV') == 'development' or os.getenv('USE_MEMORY_LIMITER') == '1':
        return 'memory://'
    redis_url = os.getenv('REDIS_URL')
    if not redis_url:
        return 'memory://'
    try:
        import redis
        r = redis.from_url(redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
        r.ping()
        return redis_url
    except Exception as ex:
        print(f"[security_ext] Redis limiter nedostupný ({ex}), přepínám na in-memory limiter.")
        return 'memory://'


_storage_uri = _determine_storage_uri()


def _key_func():
    # Preferuj uživatele, jinak IP (sníží riziko, že více uživatelů na jedné IP si blokuje limit)
    uid = session.get('user_id')
    if uid:
        return f"user:{uid}"
    return get_remote_address()


def _default_limits():
    # Měkčí limity v development; možnost override přes env
    if os.getenv('DISABLE_RATE_LIMIT') == '1':
        return []  # žádné limity
    if os.getenv('FLASK_ENV') == 'development':
        return ["5000 per hour"]
    custom = os.getenv('RATE_LIMIT_DEFAULTS')
    if custom:
        # např. RATE_LIMIT_DEFAULTS="1000 per hour;200 per 15 minutes"
        return [part.strip() for part in custom.split(';') if part.strip()]
    return ["300 per hour", "100 per 15 minutes"]


limiter = Limiter(
    key_func=_key_func,
    storage_uri=_storage_uri,
    default_limits=_default_limits(),
    headers_enabled=True,
    enabled=(os.getenv('DISABLE_RATE_LIMIT') != '1')
)

CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
EXEMPT_ENDPOINTS = {
    # přidej konkrétní endpointy které chceš vyjmout
    # 'main_bp.sitemap', 'main_bp.robots_txt'
}
EXEMPT_PREFIXES = (
    'vlastni_music_bp.',
    'health_bp.',  # příklad
)


def _ensure_csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


def init_security(app):
    limiter.init_app(app)

    @app.before_request
    def _csrf_protect():
        if request.endpoint and any(request.endpoint.startswith(p) for p in EXEMPT_PREFIXES):
            return
        if request.method in CSRF_METHODS:
            if request.endpoint in EXEMPT_ENDPOINTS:
                return
            if request.endpoint and request.endpoint.startswith('static'):
                return
            session_token = session.get('_csrf_token')
            sent_token = None
            if request.is_json:
                data = request.get_json(silent=True) or {}
                sent_token = data.get('csrf_token')
            if sent_token is None:
                sent_token = request.form.get('csrf_token') or request.headers.get('X-CSRFToken')
            if not session_token or not sent_token or session_token != sent_token:
                # Debug info for failed CSRF checks (neukládáme tokeny)
                try:
                    info = {
                        'endpoint': request.endpoint,
                        'method': request.method,
                        'has_session_token': bool(session_token),
                        'has_sent_token': bool(sent_token),
                        'form_keys': list(request.form.keys()),
                        'headers_contain_csrf': bool(request.headers.get('X-CSRFToken'))
                    }
                    # tisk pouze na konzoli serveru
                    print('[CSRF DEBUG] CSRF validation failed:', info)
                except Exception:
                    pass
                abort(400)

    # Exempt limiter pro prefixy + explicitní endpointy
    for rule in list(app.url_map.iter_rules()):
        if (any(rule.endpoint.startswith(p) for p in EXEMPT_PREFIXES)
                or rule.endpoint in EXEMPT_ENDPOINTS):
            try:
                limiter.exempt(rule.endpoint)
            except Exception:
                pass

    app.jinja_env.globals['csrf_token'] = _ensure_csrf_token

# Příklad per-route:
# @limiter.limit("1000 per minute")
# def heavy_api(): ...
