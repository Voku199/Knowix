from flask import Blueprint, render_template, session, redirect, url_for

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    return render_template('index.html',
                         user_name=session.get("user_name"),
                         profile_pic=session.get("profile_pic", "default.jpg"))

@main_bp.route('/anglictina')
def anglictina():
    return render_template('anglictina/main_anglictina.html',
                           user_name=session.get("user_name"),
                           profile_pic=session.get("profile_pic", "default.jpg"))
