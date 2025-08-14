from flask import render_template, redirect, session, url_for, flash, jsonify, Blueprint
from db import get_db_connection

admin_bp = Blueprint('admin', __name__, template_folder='templates')


@admin_bp.route('/admin/teacher_requests')
def admin_teacher_requests():
    # Povolit jen adminovi (např. user_id == 1 nebo role == 'admin')
    if session.get('user_id') != 1:
        flash("Přístup zamítnut.", "error")
        return redirect(url_for('main.index'))

    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT tp.id, tp.user_id, tp.school, tp.subject, tp.title, tp.status, u.first_name, u.last_name, u.email
            FROM teacher_pendings tp
            JOIN users u ON tp.user_id = u.id
            WHERE tp.status = 'pending'
            ORDER BY tp.created_at ASC
        """)
        requests = cursor.fetchall()
    return render_template('admin/admin_teacher_requests.html', requests=requests)


@admin_bp.route('/admin/teacher_requests/approve/<int:request_id>', methods=['POST'])
def approve_teacher_request(request_id):
    if session.get('user_id') != 1:
        return jsonify({'success': False, 'error': 'Přístup zamítnut.'}), 403

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Získat user_id z žádosti
            cursor.execute("SELECT user_id FROM teacher_pendings WHERE id = %s", (request_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'Žádost nenalezena.'})
            user_id = row[0]
            # Nastavit roli uživatele na Teacher
            cursor.execute("UPDATE users SET role = 'teacher' WHERE id = %s", (user_id,))
            # Označit žádost jako schválenou
            cursor.execute(
                "UPDATE teacher_pendings SET status = 'approved', reviewed_at = NOW(), reviewed_by = %s WHERE id = %s",
                (session['user_id'], request_id))
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        print("Chyba při schvalování učitele:", e)
        return jsonify({'success': False, 'error': 'Chyba serveru.'})


@admin_bp.route('/admin/teacher_requests/reject/<int:request_id>', methods=['POST'])
def reject_teacher_request(request_id):
    if session.get('user_id') != 1:
        return jsonify({'success': False, 'error': 'Přístup zamítnut.'}), 403

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE teacher_pendings SET status = 'rejected', reviewed_at = NOW(), reviewed_by = %s WHERE id = %s",
                (session['user_id'], request_id))
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        print("Chyba při zamítání učitele:", e)
        return jsonify({'success': False, 'error': 'Chyba serveru.'})
