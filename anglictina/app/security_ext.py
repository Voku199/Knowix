import os, secrets
from flask import session, request, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Central Limiter instance
limiter = Limiter(
    get_remote_address,
    storage_uri=os.getenv('REDIS_URL', 'memory://'),
    default_limits=["300 per hour", "100 per 15 minutes"],
    headers_enabled=True
)

CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

EXEMPT_ENDPOINTS = set()  # you can add endpoint names here dynamically


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
        if request.method in CSRF_METHODS:
            # Skip explicit endpoint exemptions
            if request.endpoint in EXEMPT_ENDPOINTS:
                return
            # Skip static files
            if request.endpoint and request.endpoint.startswith('static'):
                return
            session_token = session.get('_csrf_token')
            sent_token = None
            if request.is_json:
                try:
                    data = request.get_json(silent=True) or {}
                    sent_token = data.get('csrf_token')
                except Exception:
                    sent_token = None
            if sent_token is None:
                sent_token = request.form.get('csrf_token') or request.headers.get('X-CSRFToken')
            if not session_token or not sent_token or session_token != sent_token:
                abort(400)

    # Make token generator available to Jinja
    app.jinja_env.globals['csrf_token'] = _ensure_csrf_token
