from flask import Blueprint, render_template, request, jsonify, session
from datetime import datetime
from auth import get_db_connection

news_bp = Blueprint('news', __name__, template_folder='templates')


# Třídy modelů
class User:
    @staticmethod
    def get_by_id(user_id):
        """Získání uživatele podle ID"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT first_name, last_name, email 
                FROM users 
                WHERE id = %s
            """, (user_id,))
            user = cursor.fetchone()
            cursor.close()
            conn.close()
            return user
        except Exception as e:
            print("Chyba při získávání uživatele:", str(e))
            return None


class News:
    @staticmethod
    def get_all():
        """Získání všech novinek"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT n.*, u.first_name, u.last_name 
                FROM news n
                JOIN users u ON n.author_id = u.id
                ORDER BY n.created_at DESC
            """)
            news = cursor.fetchall()
            cursor.close()
            conn.close()
            return news
        except Exception as e:
            print("Chyba při získávání novinek:", str(e))
            return []

    @staticmethod
    def create(title, content, author_id):
        """Vytvoření nové novinky"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO news (title, content, author_id, created_at)
                VALUES (%s, %s, %s, %s)
            """, (title, content, author_id, datetime.now()))
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            print("Chyba při vytváření novinky:", str(e))
            return False


# Helper funkce
def validate_owner(user_id):
    """Ověření identity majitele"""
    user = User.get_by_id(user_id)
    if user:
        return (
                user['first_name'] == "Vojtěch" and
                user['last_name'] == "Kurinec" and
                user['email'] == "vojta.kurinec@gmail.com"
        )
    return False


# Routy
@news_bp.route('/news')
def news_page():
    is_owner = False
    if 'user_id' in session:
        is_owner = validate_owner(session['user_id'])
    return render_template('news/news.html', is_owner=is_owner)


@news_bp.route('/get_news')
def get_news():
    try:
        news_items = News.get_all()
        formatted_news = [{
            'id': item['id'],
            'title': item['title'],
            'content': item['content'],
            'author': f"{item['first_name']} {item['last_name']}",
            'created_at': item['created_at'].strftime('%d.%m.%Y %H:%M'),
            'updated_at': item['updated_at'].strftime('%d.%m.%Y %H:%M') if item['updated_at'] else None
        } for item in news_items]

        return jsonify({'news': formatted_news})
    except Exception as e:
        print("Chyba v get_news route:", str(e))
        return jsonify({'error': 'Internal server error'}), 500


@news_bp.route('/news', methods=['POST'])
def add_news():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Nejste přihlášen'}), 401

    if not validate_owner(session['user_id']):
        return jsonify({'status': 'error', 'message': 'Neoprávněný přístup'}), 403

    data = request.get_json()
    if News.create(
            title=data.get('title'),
            content=data.get('content'),
            author_id=session['user_id']
    ):
        return jsonify({'status': 'success'})

    return jsonify({'status': 'error', 'message': 'Chyba při ukládání'}), 500
