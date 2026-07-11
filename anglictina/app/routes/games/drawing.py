from flask import Blueprint, render_template

drawing_bp = Blueprint('drawing', __name__)


@drawing_bp.route('/kresleni')
def drawing_page():
    return render_template('drawing/drawing.html')
