import os, secrets
from flask import session, request, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


# Inteligentní volba storage pro limiter (Redis -> fallback memory)


def _determine_storage_uri():
    # Vynucení paměťového backendu pro lokální vývoj nebo proměnnou
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

# Central Limiter instance (fallback už vyřešen výše)
limiter = Limiter(
    get_remote_address,
    storage_uri=_storage_uri,
    default_limits=["300 per hour", "100 per 15 minutes"],
    headers_enabled=True
)

CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
EXEMPT_ENDPOINTS = set()
EXEMPT_PREFIXES = ('vlastni_music_bp.',)  # prefixy endpointu, na ktere se CSRF ani limiter nemaji aplikovat


def _ensure_csrf_token():
    token = session.get('_csrf_token')
    print(token)
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


def init_security(app):
    # Pokud se mezitím změnilo prostředí (např. import proběhl s REDIS_URL, ale lokálně ho nechceme),
    # můžeme případně re‑inicializovat limiter (volitelně – zde stačí stávající konfigurace).
    limiter.init_app(app)

    @app.before_request
    def _csrf_protect():
        # Vyjimka podle prefixu endpointu
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

            # Debug logování
            print(f"[CSRF DEBUG] Endpoint: {request.endpoint}")
            print(f"[CSRF DEBUG] Session token: {session_token}")
            print(f"[CSRF DEBUG] Sent token: {sent_token}")
            print(f"[CSRF DEBUG] Form data: {dict(request.form)}")

            if not session_token or not sent_token or session_token != sent_token:
                print(f"[CSRF DEBUG] CSRF check failed!")
                abort(400)

    # Exempt limiter pro prefixy
    for rule in list(app.url_map.iter_rules()):
        if any(rule.endpoint.startswith(p) for p in EXEMPT_PREFIXES):
            try:
                limiter.exempt(rule.endpoint)
            except Exception:
                pass

    app.jinja_env.globals['csrf_token'] = _ensure_csrf_token
