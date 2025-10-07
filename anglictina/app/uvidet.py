from flask import Blueprint, render_template, session

uvidet = Blueprint('uvidet', __name__)


@uvidet.route('/uvidet')
@uvidet.route('/qr')
@uvidet.route('/Knowix')
def prezentace():
    return render_template('uvidet.html',
                           user_name=session.get("user_name"),
                           profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg"))
