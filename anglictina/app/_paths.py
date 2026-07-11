# _paths.py — bootstrap pro ploché importy po rozdělení modulů do podsložek.
# Přidá core/, services/ a všechny routes/* na sys.path, aby importy typu
# `from db import ...` fungovaly beze změny. Nutno importovat PŘED lokálními importy.
import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))

_dirs = [os.path.join(APP_DIR, 'core'), os.path.join(APP_DIR, 'services')]
_routes_dir = os.path.join(APP_DIR, 'routes')
if os.path.isdir(_routes_dir):
    _dirs += [
        os.path.join(_routes_dir, _d)
        for _d in sorted(os.listdir(_routes_dir))
        if os.path.isdir(os.path.join(_routes_dir, _d))
    ]

for _d in _dirs:
    if _d not in sys.path:
        sys.path.insert(0, _d)
