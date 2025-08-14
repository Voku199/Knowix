from flask import Blueprint, render_template, session, redirect, url_for

proc_bp = Blueprint('proc_bp', __name__)


@proc_bp.route('/proc_jit_s_nama')
def index():
    return render_template('proc_jit_s_nama.html', )
