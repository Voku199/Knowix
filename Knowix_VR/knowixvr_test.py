from flask import Flask, render_template
from pathlib import Path
from functools import lru_cache

try:
    from mutagen.mp3 import MP3  # type: ignore
except Exception:  # mutagen nemusí být nainstalovaný
    MP3 = None

from flask import jsonify, url_for

app = Flask(
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/static',
)

# Root složka Knowix_VR
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / 'static'
MUSIC_DIR = STATIC_DIR / 'music'
AUDIO_DIR = MUSIC_DIR / 'audio'
LRC_DIR = MUSIC_DIR / 'LRC'

SONGS = [
    {
        'id': 'my_kind_of_woman',
        'title': 'My Kind of Woman',
        'audio_filename': 'My_kind_of_woman.mp3',
        'lrc_filename': 'My_kind_of_woman.lrc',
        'logo_filename': 'music/My_kind_of_woman.jpeg',
    },
    {
        'id': 'runaway',
        'title': 'Runaway',
        'audio_filename': 'Runaway.mp3',
        'lrc_filename': 'Runaway.lrc',
        'logo_filename': 'music/Runaway.jpeg',
    },
]


@lru_cache(maxsize=64)
def _get_mp3_duration_seconds(audio_path: str) -> float | None:
    """Vrátí délku MP3 v sekundách. Když není k dispozici mutagen, vrátí None."""
    p = Path(audio_path)
    if not p.exists():
        return None

    if MP3 is None:
        return None

    try:
        mp3 = MP3(str(p))
        length = float(getattr(mp3.info, 'length', 0.0) or 0.0)
        return length if length > 0 else None
    except Exception:
        return None


@app.get('/api/vr/songs')
def api_vr_songs():
    items = []
    for s in SONGS:
        dur = _get_mp3_duration_seconds(str(AUDIO_DIR / s['audio_filename']))
        items.append(
            {
                'id': s['id'],
                'title': s['title'],
                'duration_seconds': dur,
                'logo_url': url_for('static', filename=s['logo_filename']),
                'audio_url': url_for('static', filename=f"music/audio/{s['audio_filename']}"),
                'lrc_url': url_for('static', filename=f"music/LRC/{s['lrc_filename']}"),
            }
        )

    return jsonify({'songs': items})


@app.route('/')
def index():
    return render_template('knowixvr.html')


if __name__ == '__main__':
    host = '0.0.0.0'
    port = 5050
    app.run(host=host, port=port)
