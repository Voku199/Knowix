import random
import json
import os
import string
from flask import Blueprint, request, send_from_directory, render_template, jsonify
from db import get_db_connection

pexeso_bp = Blueprint('pexeso', __name__)

ROOMS = {}
PLAYER_ROOM = {}


def insert_room(room_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO pexeso_rooms (room_id) VALUES (%s)",
                (room_id,)
            )
        conn.commit()
    finally:
        conn.close()


def room_exists(room_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pexeso_rooms WHERE room_id = %s",
                (room_id,)
            )
            return cursor.fetchone() is not None
    finally:
        conn.close()


def get_all_rooms():
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT room_id, created_at FROM pexeso_rooms ORDER BY created_at DESC")
            return cursor.fetchall()
    finally:
        conn.close()


def load_words():
    with open('static/pexeso/slova.json', encoding='utf-8') as f:
        return json.load(f)


def create_cards(words_list):
    """
    words_list: list ve tvaru [{ "cz": "chléb", "en": "bread" }, ...]
    Vrací zamíchané karty s informací o páru a jazyku.
    """
    pairs = words_list.copy()
    random.shuffle(pairs)
    pairs = pairs[:8]  # nebo jiný počet podle potřeby
    cards = []
    mapping = {}
    idx = 0
    for pair in pairs:
        en = pair["en"]
        cz = pair["cz"]
        cards.append({'text': en, 'flipped': False, 'matched': False, 'pair': en, 'lang': 'en'})
        mapping[idx] = (en, 'en')
        idx += 1
        cards.append({'text': cz, 'flipped': False, 'matched': False, 'pair': en, 'lang': 'cz'})
        mapping[idx] = (en, 'cz')
        idx += 1
    random.shuffle(cards)
    return cards, mapping


@pexeso_bp.after_request
def set_csp(response):
    response.headers[
        'Content-Security-Policy'] = "script-src 'self' 'unsafe-inline' https://cdn.socket.io https://www.googletagmanager.com"
    return response


@pexeso_bp.route('/pexeso/rooms')
def list_rooms():
    rooms = get_all_rooms()
    return jsonify(rooms)


@pexeso_bp.route('/pexeso')
def index():
    return render_template('pexeso/pexeso.html')


@pexeso_bp.route('/pexeso/static/<path:filename>')
def pexeso_static(filename):
    return send_from_directory('static/pexeso', filename)


@pexeso_bp.route('/words.json')
def words_json():
    return send_from_directory('static/pexeso', 'slova.json')


@pexeso_bp.route('/pexeso/create_room', methods=['POST'])
def create_room():
    while True:
        room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not room_exists(room_id):
            break
    insert_room(room_id)
    ROOMS[room_id] = {'players': [], 'scores': [0, 0], 'turn': 1, 'cards': [], 'matched': set(), 'mapping': {}}
    return jsonify({'room_id': room_id})


def register_socketio_handlers(socketio):
    @socketio.on('join_room')
    def on_join_room(room_id):
        sid = request.sid
        if room_id not in ROOMS:
            # First player joining - create room
            ROOMS[room_id] = {
                'players': [],
                'scores': [0, 0],
                'turn': None,  # Will be set when game starts
                'cards': [],
                'matched': set(),
                'mapping': {},
                'game_started': False  # Initialize game_started flag
            }
            print(f"Created new room {room_id}")
        room = ROOMS[room_id]
        
        if len(room['players']) >= 2:
            socketio.emit('room_error', "Místnost je plná.", room=sid)
            return
            
        if sid in PLAYER_ROOM:
            from flask_socketio import leave_room
            leave_room(PLAYER_ROOM[sid])
            
        from flask_socketio import join_room
        join_room(room_id)
        
        player_num = len(room['players']) + 1
        room['players'].append(sid)
        PLAYER_ROOM[sid] = room_id
        
        # Notify the player they've joined
        socketio.emit('room_joined', {
            'player': player_num,
            'room': room_id,
            'is_host': player_num == 1  # First player is host
        }, room=sid)
        
        # If both players have joined, prepare the game
        if len(room['players']) == 2 and not room.get('game_started', False):
            print(f"Starting game in room {room_id} with players: {room['players']}")
            room['game_started'] = True
            try:
                words_json = load_words()
                level = "A1"  # TODO: Získat od uživatele, nebo podle nastavení místnosti
                words_list = words_json[level]
                cards, mapping = create_cards(words_list)
                room['cards'] = cards
                room['mapping'] = mapping
                room['scores'] = [0, 0]
                room['matched'] = set()
                
                # Randomly select who starts first (1 or 2)
                room['turn'] = random.randint(1, 2)
                print(f"Player {room['turn']} will start the game in room {room_id}")
                
                # Notify both players the game is starting
                for idx, player_sid in enumerate(room['players']):
                    player_num = idx + 1
                    your_turn = (player_num == room['turn'])
                    print(f"Sending start_game to player {player_num} (SID: {player_sid}), their turn: {your_turn}")
                    socketio.emit('start_game', {
                        'cards': cards,
                        'player_num': player_num,
                        'player_turn': room['turn'],
                        'your_turn': your_turn
                    }, room=player_sid)
                    
                # Notify who's turn it is
                print(f"Sending turn_update for room {room_id}, player {room['turn']}'s turn")
                socketio.emit('turn_update', {
                    'player_turn': room['turn']
                }, room=room_id)
                
            except Exception as e:
                print(f"Error starting game in room {room_id}: {str(e)}")
                import traceback
                traceback.print_exc()
                # Reset game state to allow retry
                room['game_started'] = False

    @socketio.on('flip_card')
    def on_flip_card(data):
        room_id = data['room']
        idx = data['idx']
        sid = request.sid
        room = ROOMS.get(room_id)
        if not room or sid not in room['players']:
            return
        socketio.emit('flip_card', idx, room=room_id, include_self=False)

    @socketio.on('check_pair')
    def on_check_pair(data):
        room_id = data['room']
        idxs = data['idxs']
        sid = request.sid
        room = ROOMS.get(room_id)
        if not room or sid not in room['players']:
            return
            
        if len(idxs) != 2:
            return
            
        i1, i2 = idxs
        if i1 == i2 or i1 >= len(room['cards']) or i2 >= len(room['cards']):
            return
            
        # Get the card data
        card1 = room['cards'][i1]
        card2 = room['cards'][i2]
        
        # Check if cards form a valid pair (same pair ID but different languages)
        is_valid_pair = (card1['pair'] == card2['pair'] and 
                        card1['lang'] != card2['lang'] and
                        'en' in [card1['lang'], card2['lang']] and
                        'cz' in [card1['lang'], card2['lang']])
        
        pidx = room['players'].index(sid)
        
        if is_valid_pair:
            # Mark both cards as matched
            room['cards'][i1]['matched'] = True
            room['cards'][i2]['matched'] = True
            room['matched'].add(i1)
            room['matched'].add(i2)
            
            # Update score for the current player
            room['scores'][pidx] += 1
            
            # Notify all clients about the match
            socketio.emit('set_matched', idxs, room=room_id)
            socketio.emit('update_scores', {'scores': room['scores']}, room=room_id)
            
            # Check if game is over
            if len(room['matched']) == len(room['cards']):
                if room['scores'][0] > room['scores'][1]:
                    winner = 1
                elif room['scores'][1] > room['scores'][0]:
                    winner = 2
                else:
                    winner = 0
                socketio.emit('game_over', {'winner': winner}, room=room_id)
            else:
                # Let the same player take another turn after a match
                socketio.emit('turn', {'turn': pidx + 1}, room=room_id)
        else:
            # No match - flip cards back and switch turns
            socketio.emit('unflip_cards', idxs, room=room_id)
            next_turn = 2 if room['turn'] == 1 else 1
            room['turn'] = next_turn
            socketio.emit('turn', {'turn': next_turn}, room=room_id)

    @socketio.on('new_game')
    def on_new_game(room_id):
        room = ROOMS.get(room_id)
        if not room:
            return
        words_json = load_words()
        level = "A1"  # TODO: Získat od uživatele, nebo podle nastavení místnosti
        words_list = words_json[level]
        cards, mapping = create_cards(words_list)
        room['cards'] = cards
        room['mapping'] = mapping
        room['scores'] = [0, 0]
        room['turn'] = 1
        room['matched'] = set()
        socketio.emit('start_game',
                      {'cards': [{'text': '', 'flipped': False, 'matched': False} for _ in cards], 'turn': 1},
                      room=room_id)
        for idx, sid in enumerate(room['players']):
            socketio.emit('start_game', {'cards': cards, 'turn': idx + 1}, room=sid)

    @socketio.on('disconnect')
    def on_disconnect():
        sid = request.sid
        room_id = PLAYER_ROOM.get(sid)
        if room_id and room_id in ROOMS:
            room = ROOMS[room_id]
            if sid in room['players']:
                room['players'].remove(sid)
            if len(room['players']) == 0:
                del ROOMS[room_id]
            else:
                socketio.emit('opponent_left', room=room_id)
        if sid in PLAYER_ROOM:
            del PLAYER_ROOM[sid]
