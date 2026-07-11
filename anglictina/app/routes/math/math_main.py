from flask import Blueprint, render_template, session, redirect, url_for

math_main_bp = Blueprint('math', __name__)


@math_main_bp.route('/math')
def math():
    return render_template('__math__/stupen.html',
                           user_name=session.get("user_name"),
                           profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg"))


@math_main_bp.route('/math/stupen1')
def stupen1():
    return render_template('__math__/1_stupen/main_stupen1.html',
                           user_name=session.get("user_name"),
                           profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg"))


@math_main_bp.route('/math/stupen2')
def stupen2():
    return render_template('__math__/2_stupen/main_stupen2.html',
                           user_name=session.get("user_name"),
                           profile_pic=session.get("profile_pic", "static/profile_pics/default.jpg"))
