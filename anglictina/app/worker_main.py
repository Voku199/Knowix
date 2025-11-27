# -*- coding: utf-8 -*-
"""
Knowix background worker – 24/7 mimo Flask

- Každých X minut spustí rozesílání připomínek (e-mail + push)
- Nepoužívá HTTP volání do Flasku, pracuje přímo s DB a SMTP/pywebpush
- Interval lze nastavit proměnnou prostředí REMINDER_INTERVAL_SECS (default 900 = 15 min)

Spuštění lokálně:
    python worker_main.py

V produkci (Procfile):
    worker: python worker_main.py
"""
from __future__ import annotations

import os
import time
import traceback
from datetime import datetime, UTC

# Volitelně načíst .env
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    pass

# Import modulů aplikace (DB, e-maily, push logika)
from reminders import send_daily_reminders


def main() -> None:
    interval = int(os.getenv('REMINDER_INTERVAL_SECS', '900'))  # 15 min default
    print(f"[worker] Starting Knowix worker loop, interval={interval}s – PID={os.getpid()}")
    while True:
        started = datetime.now(UTC).isoformat()
        try:
            emails_sent, pushes_sent = send_daily_reminders()
            print(f"[worker] {started} – done: emails={emails_sent}, pushes={pushes_sent}")
        except Exception as ex:
            print(f"[worker] ERROR: {ex}\n{traceback.format_exc()}")
        time.sleep(interval)


if __name__ == '__main__':
    main()
