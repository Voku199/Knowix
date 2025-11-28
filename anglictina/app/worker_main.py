# -*- coding: utf-8 -*-
"""
Knowix background worker – 24/7 mimo Flask

- Každých X minut spustí rozesílání připomínek (e-mail + push)
- Nepoužívá HTTP volání do Flasku, pracuje přímo s DB a SMTP/pywebpush
- Interval lze nastavit proměnnou prostředí REMINDER_INTERVAL_SECS (default 900 = 15 min)

Spuštění lokálně:
    python worker_main.py

Integrace do main.py:
    from worker_main import start_worker_thread
    start_worker_thread()
"""
from __future__ import annotations

import os
import time
import traceback
from datetime import datetime, UTC
import threading

# Volitelně načíst .env
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    pass

# Import modulů aplikace (DB, e-maily, push logika)
from reminders import send_daily_reminders


def _loop(interval: int) -> None:
    print(f"[worker] Thread started interval={interval}s PID={os.getpid()}", flush=True)
    while True:
        started = datetime.now(UTC).isoformat()
        try:
            emails_sent, pushes_sent = send_daily_reminders()
            print(f"[worker] {started} – done: emails={emails_sent}, pushes={pushes_sent}", flush=True)
        except Exception as ex:
            print(f"[worker] ERROR: {ex}\n{traceback.format_exc()}", flush=True)
        time.sleep(interval)


def start_worker_thread(interval: int | None = None) -> threading.Thread:
    """Spustí worker ve vlákně (idempotentní)."""
    global _worker_started
    if hasattr(start_worker_thread, 'thread') and start_worker_thread.thread.is_alive():
        return start_worker_thread.thread
    if interval is None:
        interval = int(os.getenv('REMINDER_INTERVAL_SECS', '900'))
    t = threading.Thread(target=_loop, args=(interval,), daemon=True)
    t.start()
    start_worker_thread.thread = t  # type: ignore[attr-defined]
    return t


def main() -> None:
    interval = int(os.getenv('REMINDER_INTERVAL_SECS', '900'))
    _loop(interval)


if __name__ == '__main__':
    main()
