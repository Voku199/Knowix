from flask import Blueprint, render_template, session, redirect, url_for, send_from_directory

prezentace_bp = Blueprint('prezentace', __name__)


@prezentace_bp.route('/prezentacer_main.html')
def prezentace():
    return render_template('prezentace/prezentacer_main.html',
                           user_name=session.get("user_name"),
                           profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg"))


@prezentace_bp.route('/nazor.html')
def nazor():
    return render_template('prezentace/nazor.html',
                           user_name=session.get("user_name"),
                           profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg"))


@prezentace_bp.route('/autor.html')
def autor():
    return render_template('prezentace/autor.html',
                           user_name=session.get("user_name"),
                           profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg"))


@prezentace_bp.route('/strucny.html')
def strucny():
    return render_template('prezentace/strucny.html',
                           user_name=session.get("user_name"),
                           profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg"))


@prezentace_bp.route('/vydani.html')
def vydani():
    return render_template('prezentace/vydani.html',
                           user_name=session.get("user_name"),
                           profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg"))


# Servírování specifického CSS (aby relativní href="style.css" fungoval bez 404 a MIME chyby)
@prezentace_bp.route('/prezentace/style.css')
def prezentace_style():
    return send_from_directory('templates/prezentace', 'style.css', mimetype='text/css')


# Servírování audio souborů (relativní cesta audio/ambient.mp3)
@prezentace_bp.route('/prezentace/audio/<path:filename>')
def prezentace_audio(filename):
    return send_from_directory('static/prezentace/audio', filename)
