from dotenv import load_dotenv
from flask import render_template, request, jsonify, url_for, redirect, Blueprint, session
import requests
import os
import re
import random
import time
import json
from db import get_db_connection  # Importuj svoji funkci na připojení k DB
from xp import check_and_award_achievements  # vyhodnocení achievementů po zprávě v AI chatu
from user_stats import update_user_stats  # statistiky uživatele – přidání času učení

ai_bp = Blueprint('ai_bp', __name__)
load_dotenv(dotenv_path=".env")
ai_bp.ai_api_key = os.getenv("AI_API_KEY")
CZECH_CHARS = set("ěščřžýáíéúůďťňóĚŠČŘŽÝÁÍÉÚŮĎŤŇÓ")
CZECH_WORDS = [
    "jak se máš", "dobrý den", "ahoj", "čau", "prosím", "děkuji", "mám se", "nemám", "nevim", "nevím", "budeš", "jsi",
    "to je", "co děláš"
]
BAD_WORDS = [
    "fuck", "shit", "bitch", "asshole", "dick", "pussy", "cunt", "faggot", "kurva", "piča", "čurák", "kokot", "hovno",
    "debil", "idiot", "blbec", "mrdat", "sračka"
]


def get_or_create_user():
    if "user_id" in session:
        return session["user_id"]

    db = get_db_connection()
    with db.cursor() as cursor:
        # Provide values for all known required fields
        cursor.execute("""
            INSERT INTO users (first_name, last_name, email, password, school) 
            VALUES (%s, %s, %s, %s, %s)
        """, (
            'Anonymous',
            'User',
            f'anonymous_{random.randint(10000, 99999)}@example.com',
            'scrypt:32768:8:1$SZwTcXBf633lMT5B$5314fff3be13114ecbf2bff33572a6e3771287491ad73f4dda4f2f13be7493853f0badd609b3bf0a09f0c821bf55c30c9282ee46e88bcb1f38eccab9b56f5eef',
            'Základní škola Tomáše Šobra'
        ))
        user_id = cursor.lastrowid
    db.commit()
    session["user_id"] = user_id
    return user_id


@ai_bp.before_request
def check_user():
    print(f"DEBUG BEFORE_REQUEST: Method={request.method}, Endpoint={request.endpoint}")
    print(f"DEBUG BEFORE_REQUEST: Session before: {dict(session)}")

    # This ensures every request has a user_id
    if "user_id" not in session:
        try:
            get_or_create_user()
            print(f"DEBUG BEFORE_REQUEST: Created new user, session after: {dict(session)}")
        except Exception as e:
            print(f"DEBUG BEFORE_REQUEST: Error creating user: {e}")
            # Možná je problém s databází, zkusme fallback
            session["user_id"] = random.randint(100000, 999999)
            print(f"DEBUG BEFORE_REQUEST: Used fallback user_id: {session['user_id']}")
    else:
        print(f"DEBUG BEFORE_REQUEST: User already exists: {session['user_id']}")


def get_user_chats(user_id):
    db = get_db_connection()
    with db.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT id, title, created_at FROM chat_session WHERE user_id=%s ORDER BY created_at DESC",
                       (user_id,))
        return cursor.fetchall()


def create_new_chat(user_id, title="New chat"):
    db = get_db_connection()
    with db.cursor() as cursor:
        cursor.execute("INSERT INTO chat_session (user_id, title) VALUES (%s, %s)", (user_id, title))
        chat_id = cursor.lastrowid
    db.commit()
    return chat_id


def get_chat_history_by_chatid(chat_id, limit=30):
    db = get_db_connection()
    with db.cursor(dictionary=True) as cursor:
        cursor.execute(
            "SELECT sender, content, created_at, user_id FROM chat_message WHERE chat_id=%s ORDER BY created_at ASC LIMIT %s",
            (chat_id, limit)
        )
        messages = cursor.fetchall()
        # Přidej profilovku pro uživatele (pokud je potřeba)
        for msg in messages:
            if msg['sender'] in ['users', 'user']:
                with db.cursor(dictionary=True) as c2:
                    c2.execute("SELECT profile_pic FROM users WHERE id=%s", (msg['user_id'],))
                    u = c2.fetchone()
                    msg['user_profile_pic'] = u['profile_pic'] if u and u['profile_pic'] else None
            else:
                msg['user_profile_pic'] = None
        return messages


def insert_message_chat(chat_id, user_id, sender, content):
    db = get_db_connection()
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO chat_message (chat_id, user_id, sender, content, created_at) VALUES (%s, %s, %s, %s, NOW())",
            (chat_id, user_id, sender, content)
        )
    db.commit()


def is_czech(text):
    # Pokud obsahuje české znaky nebo typická česká slova
    if any(c in CZECH_CHARS for c in text.lower()):
        return True
    for w in CZECH_WORDS:
        if w in text.lower():
            return True
    return False


def contains_bad_word(text):
    text_lower = text.lower()
    for w in BAD_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", text_lower):
            return True
    return False


# --- Pomocné funkce ---
def extract_name_from_text(text):
    match = re.search(r"(moje jméno je|jmenuji se|my name is)\s+([A-Za-zÁ-Žá-ž\- ]+)", text, re.IGNORECASE)
    if match:
        return match.group(2).strip()
    return None


def insert_message(user_id, sender, content, dnd=False):
    db = get_db_connection()
    table = "dnd_message" if dnd else "chat_message"
    with db.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} (user_id, sender, content, created_at) VALUES (%s, %s, %s, NOW())",
            (user_id, sender, content)
        )
    db.commit()


# --- DND telemetry a korekce ---
def _now_ts():
    try:
        return time.time()
    except Exception:
        return None


def track_dnd_time(user_id, cap_seconds=600):
    """Přičte do user_stats čas od poslední aktivity v DnD (v session). Cap kvůli idle tabům.
    - volat na začátku GET/POST dnd endpointu.
    """
    try:
        now = _now_ts()
        if now is None:
            return
        last = session.get('dnd_last_ts')
        session['dnd_last_ts'] = now
        if last is None:
            return
        delta = max(0, int(now - last))
        if cap_seconds:
            delta = min(delta, int(cap_seconds))
        if delta > 0:
            # ukládáme jako learning_time (sekundy)
            update_user_stats(user_id, learning_time=delta, set_first_activity=True)
    except Exception:
        # nechceme blokovat proud, statistika je best-effort
        pass


def generate_correction_tip(text):
    """Vrátí krátkou, jemnou opravu/napovědu k anglické větě (1 řádek). Pokud není co opravovat, vrátí None.
    Použije AI API, když je klíč k dispozici; jinak None.
    """
    try:
        api_key = ai_bp.ai_api_key
        if not api_key:
            return None
        t = (text or '').strip()
        if len(t) < 3:
            return None
        # Pokud to vypadá jako čeština, neřešíme korekci – dnd ji stejně blokuje
        if is_czech(t):
            return None
        url = "https://api.aimlapi.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        system = (
            "You are a concise English tutor. Given a student's message, respond with ONE short correction or tip in English, max 100 characters. "
            "If the sentence is fine, answer exactly: OK. Do not use emojis, quotes, or markdown."
        )
        data = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": t}
            ],
            "temperature": 0.2,
            "max_tokens": 60
        }
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        if resp.status_code not in (200, 201):
            return None
        tip = resp.json().get('choices', [{}])[0].get('message', {}).get('content', '')
        if not tip:
            return None
        tip_clean = tip.strip()
        # Filtrujeme generické OK
        if tip_clean.lower() in ("ok", "looks good", "no issues", "correct"):
            return None
        # Vrátíme jednu větu bez uvozovek
        tip_clean = tip_clean.strip('"'"' ")
        return tip_clean if tip_clean else None
    except Exception:
        return None


def get_chat_history(user_id, limit=30, dnd=False):
    db = get_db_connection()
    table = "dnd_message" if dnd else "chat_message"
    with db.cursor(dictionary=True) as cursor:
        cursor.execute(
            f"SELECT sender, content, created_at FROM {table} WHERE user_id=%s ORDER BY created_at ASC LIMIT %s",
            (user_id, limit)
        )
        return cursor.fetchall()


# --- INVENTÁŘ ---
def get_inventory(user_id):
    db = get_db_connection()
    with db.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT inventory FROM users WHERE id=%s", (user_id,))
        row = cursor.fetchone()
        if row and row["inventory"]:
            try:
                return json.loads(row["inventory"])
            except Exception:
                return []
        return []


def set_inventory(user_id, inventory):
    db = get_db_connection()
    with db.cursor() as cursor:
        cursor.execute("UPDATE users SET inventory=%s WHERE id=%s", (json.dumps(inventory), user_id))
    db.commit()


# --- KOMUNITA ---

# --- Komunitní AI prompt ---
def build_community_prompt(history, user_input):
    system_content = (
        "You are a friendly, community-oriented AI chat buddy for young people (Gen Z and Gen Alpha). "
        "You always reply in modern, casual English, using slang, emojis, and a positive, supportive tone. "
        "You never mention you are an AI, robot, or lack feelings. "
        "If the user asks how you are, answer like a real friend (e.g. 'I'm vibing today! How about you?'). "
        "If the user writes in Czech or another language, reply: 'Sorry, I don't understand. Please write in English.' "
        "If the user writes something inappropriate or offensive, reply: 'Hey, that's not cool. The owner can see this and might take action.' "
        "Don't ask too many questions in a row, but keep the conversation going naturally. "
        "Be curious, but not intrusive. Use modern expressions and emojis. "
        "Keep your answers short and engaging, not too formal. "
        "Never write long paragraphs. "
        "If the user says something nice, react with a friendly emoji. "
        "If the user is sad, try to cheer them up. "
        "Never answer in Czech or any language other than English."
        "If somebody ask if the chats are recoring or spying, then say yes, we are saving the chats that you can training more and more. "
        "If the users write something czech topic, like 'name a czech food' or something else, normaly answer it, but in english! not in czech"
        "if the users want something to translate, then translate, like 'Can you translate this text to english?' or 'Can you translate mám rád rohlík to english' and many more... "
        "If they mentions 'knowix' or just ask you what is knowix, answer it a educations for czech people in english, and much fun and better then umimeto.org"
        "If they ask you 'who created you?' or 'who created knowix' answer that Vojtech Kurinec did"
    )
    messages = [{"role": "system", "content": system_content}]
    for msg in history:
        if msg["sender"] in ("users", "user"):
            messages.append({"role": "user", "content": msg["content"]})
        elif msg["sender"] == "ai":
            messages.append({"role": "assistant", "content": msg["content"]})
    if user_input:
        messages.append({"role": "user", "content": user_input})
    return messages


def ask_community_ai(user_id, user_input):
    api_key = ai_bp.ai_api_key
    if not api_key:
        return "❌ API klíč není nastaven. Zkontrolujte .env soubor."

    # Detekce češtiny
    if is_czech(user_input):
        czech_responses = [
            "Sorry, I don't understand. Please write in English. 🙏",
            "I can't understand Czech, could you try English? 😊",
            "Please use English, I don't understand Czech. 🌍",
            "I'm not fluent in Czech, could you switch to English? 🤔",
            "English, please! I can't follow Czech. 😅"
        ]
        return random.choice(czech_responses)

    # Detekce sprostých slov
    if contains_bad_word(user_input):
        bad_word_responses = [
            "Hey, that's not cool. The owner can see this and might take action. 🚨",
            "That's inappropriate. Please keep it respectful. 🙏",
            "Watch your language, please. This is a friendly space. 😊",
            "Let's keep it clean here, okay? 🚫",
            "Please avoid using such language. It's not welcome here. 🙅"
        ]
        return random.choice(bad_word_responses)

    history = get_chat_history(user_id, limit=30, dnd=False)
    messages = build_community_prompt(history, user_input)
    url = "https://api.aimlapi.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "gpt-4o-mini-2024-07-18",
        "messages": messages,
        "temperature": 1,
        "max_tokens": 120
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code in [200, 201]:
        try:
            ai_reply = response.json()['choices'][0]['message']['content']
            return ai_reply
        except Exception as e:
            return f"❌ Error: {e} | {response.text}"
    else:
        return f"❌ Error {response.status_code}: {response.text}"


# --- DND GUARDRAILS ---
POWERGAMING_PATTERNS = [
    r"\bi (instantly|immediately)\b",
    r"\bi (kill|killed|slay|slain)\b.*\b(easily|instantly|with one hit)\b",
    r"\bi (find|found|get|got|have)\b.*\b(legendary|mythic|invincible|all powerful|all-powerful|infinite)\b",
    r"\bsword that can kill (anything|anyone|everyone)\b",
    r"\bi (auto|always) succeed\b",
    r"\b(one[- ]?shot|onehit|one-hit)\b",
    r"\b(invincible|immortal|cannot die)\b",
]


def is_powergaming(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in POWERGAMING_PATTERNS)


# --- DND STORY SPLIT (heuristika podle intro zprávy) ---

# --- DND STORY MANAGEMENT ---

def get_dnd_stories(user_id):
    """Získá seznam všech D&D příběhů pro uživatele"""
    db = get_db_connection()
    with db.cursor(dictionary=True) as cursor:
        cursor.execute("""
            SELECT story_id, MIN(created_at) as created_at
            FROM dnd_message 
            WHERE user_id = %s 
            GROUP BY story_id
            ORDER BY created_at DESC
        """, (user_id,))
        stories = cursor.fetchall()

        # Pro každý příběh získáme titul
        for story in stories:
            cursor.execute("""
                SELECT content FROM dnd_message 
                WHERE user_id = %s AND story_id = %s AND sender = 'ai'
                ORDER BY created_at ASC 
                LIMIT 1
            """, (user_id, story['story_id']))
            first_msg = cursor.fetchone()
            if first_msg and first_msg['content']:
                content = first_msg['content']
                # Extrahujeme titul z první zprávy
                if "welcome" in content.lower():
                    story['title'] = f"Adventure #{story['story_id']}"
                else:
                    # Vezmeme prvních 30 znaků první zprávy
                    title = content[:30].strip()
                    if len(content) > 30:
                        title += "..."
                    story['title'] = title
            else:
                story['title'] = f"Adventure #{story['story_id']}"

        return stories


def get_story_messages(user_id, story_id):
    """Získá zprávy pro konkrétní příběh"""
    db = get_db_connection()
    with db.cursor(dictionary=True) as cursor:
        cursor.execute("""
            SELECT sender, content, created_at 
            FROM dnd_message 
            WHERE user_id = %s AND story_id = %s 
            ORDER BY created_at ASC
        """, (user_id, story_id))
        return cursor.fetchall()


def insert_dnd_message(user_id, sender, content, story_id=1):
    """Uloží zprávu pro D&D příběh"""
    db = get_db_connection()
    with db.cursor() as cursor:
        # Pokud máte sloupec title, přidejte ho do INSERTu
        try:
            cursor.execute("""
                INSERT INTO dnd_message (user_id, sender, content, story_id, title, created_at) 
                VALUES (%s, %s, %s, %s, %s, NOW())
            """, (user_id, sender, content, story_id, f"Story {story_id}"))
        except Exception as e:
            # Fallback pokud title sloupec neexistuje
            cursor.execute("""
                INSERT INTO dnd_message (user_id, sender, content, story_id, created_at) 
                VALUES (%s, %s, %s, %s, NOW())
            """, (user_id, sender, content, story_id))
    db.commit()


def create_new_story(user_id):
    """Vytvoří nový příběh a vrátí jeho ID"""
    db = get_db_connection()
    try:
        with db.cursor() as cursor:
            # Najdeme nejvyšší story_id pro tohoto uživatele
            cursor.execute("SELECT COALESCE(MAX(story_id), 0) as max_id FROM dnd_message WHERE user_id = %s",
                           (user_id,))
            result = cursor.fetchone()
            # Oprava: result je tuple, ne dictionary
            new_story_id = result[0] + 1 if result else 1

            print(f"DEBUG: Creating new story with ID: {new_story_id}")

            # Generujeme úvodní zprávu
            api_key = ai_bp.ai_api_key
            if not api_key:
                ai_reply = "🏰 Welcome to your new D&D adventure! A mysterious world awaits your exploration. What will you do? <b>Explore forward</b> | <b>Look around</b> | <b>Check equipment</b>"
            else:
                try:
                    inventory = []
                    messages = [{"role": "system",
                                 "content": "You are a Dungeons & Dragons game master. Start a new adventure for the player with 2-3 choices. Use emoji and HTML formatting for choices like: <b>Choice 1</b> | <b>Choice 2</b>"}]

                    url = "https://api.aimlapi.com/v1/chat/completions"
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    }
                    data = {
                        "model": "gpt-4o-mini",
                        "messages": messages + [{"role": "user",
                                                 "content": "Start a new D&D adventure for the player. Give them 2-3 choices what to do next. Use emoji and HTML formatting."}],
                        "temperature": 1,
                        "max_tokens": 120
                    }

                    response = requests.post(url, headers=headers, json=data, timeout=30)
                    if response.status_code in [200, 201]:
                        ai_reply = response.json()['choices'][0]['message']['content']
                    else:
                        ai_reply = "🏰 Welcome to your new D&D adventure! A mysterious world awaits your exploration. What will you do? <b>Explore forward</b> | <b>Look around</b> | <b>Check equipment</b>"

                except Exception as e:
                    print(f"Error calling AI for new story: {e}")
                    ai_reply = "🏰 Welcome to your new D&D adventure! A mysterious world awaits your exploration. What will you do? <b>Explore forward</b> | <b>Look around</b> | <b>Check equipment</b>"

            # Vložíme úvodní zprávu pro nový příběh
            try:
                cursor.execute("""
                    INSERT INTO dnd_message (user_id, sender, content, story_id, title, created_at) 
                    VALUES (%s, %s, %s, %s, %s, NOW())
                """, (user_id, 'ai', ai_reply, new_story_id, f"Adventure {new_story_id}"))
            except Exception as e:
                # Fallback bez title
                cursor.execute("""
                    INSERT INTO dnd_message (user_id, sender, content, story_id, created_at) 
                    VALUES (%s, %s, %s, %s, NOW())
                """, (user_id, 'ai', ai_reply, new_story_id))

        db.commit()
        print(f"DEBUG: Successfully created story {new_story_id}")
        return new_story_id

    except Exception as e:
        print(f"Error creating new story: {e}")
        if db:
            db.rollback()

        # Fallback - vytvoříme příběh s defaultní zprávou
        try:
            with db.cursor() as cursor:
                cursor.execute("SELECT COALESCE(MAX(story_id), 0) as max_id FROM dnd_message WHERE user_id = %s",
                               (user_id,))
                result = cursor.fetchone()
                new_story_id = result[0] + 1 if result else 1

                try:
                    cursor.execute("""
                        INSERT INTO dnd_message (user_id, sender, content, story_id, title, created_at) 
                        VALUES (%s, %s, %s, %s, %s, NOW())
                    """, (user_id, 'ai', "🏰 Welcome to your new D&D adventure! What will you do?", new_story_id,
                          f"Adventure {new_story_id}"))
                except:
                    cursor.execute("""
                        INSERT INTO dnd_message (user_id, sender, content, story_id, created_at) 
                        VALUES (%s, %s, %s, %s, NOW())
                    """, (user_id, 'ai', "🏰 Welcome to your new D&D adventure! What will you do?", new_story_id))

            db.commit()
            return new_story_id
        except Exception as fallback_error:
            print(f"Fallback also failed: {fallback_error}")
            return 1  # Vrátíme alespoň story_id 1 jako fallback


# --- DND PROMPT ---
def build_dnd_prompt(history, user_input, inventory, is_intro=False):
    inventory_str = ", ".join(inventory) if inventory else "nothing"
    system_content = (
            "You are a Dungeons & Dragons game master. "
            "Invent a fantasy story, create 2-3 NPCs, and set the user's HP (e.g. 20). "
            "Always speak in English. "
            "After each turn, offer the user 2-3 choices for what to do next, or sometimes ask 'What will you do?'. "
            "Keep track of the user's HP and inventory (inventory is: " + inventory_str + "). "
                                                                                          "If the user asks about their inventory, answer with the current inventory. "
                                                                                          "Never praise or judge the user's actions. Never write long paragraphs. "
                                                                                          "Never end the story, keep it going. "
                                                                                          "You can use emoji for atmosphere. "
                                                                                          "When giving choices, ALWAYS write them in one line, as part of the story sentence, separated by ' | ', and use <b>...</b> for each option. "
                                                                                          "Do NOT use lists or <ul>/<li>. "
                                                                                          "Example: In front of you are three doors. What will you do? <b>Open the left door</b> | <b>Open the right door</b> | <b>Look around</b>. "
                                                                                          "NEVER allow the user to instantly win, die, or get legendary/overpowered items (like a sword, magic staff, etc.) just by asking. "
                                                                                          "If the user tries to cheat, ask for something impossible, or tries to skip the adventure, politely refuse and keep the story balanced. "
                                                                                          "Never give the user a sword, legendary item, or kill them instantly unless it is part of a fair, logical story progression. "
                                                                                          "If the user says they died, got a sword, or something similar, remind them that only the game master can decide such outcomes. "
                                                                                          "IMPORTANT: Write in a way that's suitable for text-to-speech - avoid complex punctuation, write numbers as words, and keep sentences clear and flowing. "
                                                                                          "IMPORTANT: In your responses, NEVER include numbers, hashtags (#), at symbols (@), ampersands (&), or other special characters like $, %, ^, *, etc. "
                                                                                          "Use words instead of numbers (e.g., 'twenty' instead of '20', 'three' instead of '3'). "
                                                                                          "Avoid using any social media symbols or special characters in your storytelling. "
                                                                                          "Keep the narrative clean and use only letters, basic punctuation (.,!?), spaces, and HTML formatting tags."
    )

    messages = [{"role": "system", "content": system_content}]
    for msg in history:
        if msg["sender"] in ("users", "user"):
            messages.append({"role": "user", "content": msg["content"]})
        elif msg["sender"] == "ai":
            messages.append({"role": "assistant", "content": msg["content"]})
    # Pokud je to první zpráva, user_input bude None
    if not is_intro:
        messages.append({"role": "user", "content": user_input})
    return messages


def build_chat_prompt(history, user_input):
    # Běžný chat, pouze historie a aktuální vstup
    messages = []
    for msg in history:
        if msg["sender"] in ("users", "user"):
            messages.append({"role": "user", "content": msg["content"]})
        elif msg["sender"] == "ai":
            messages.append({"role": "assistant", "content": msg["content"]})
    messages.append({"role": "user", "content": user_input})
    return messages


def ask_ai(user_id, user_input, user_name=None, dnd=False):
    api_key = ai_bp.ai_api_key
    if not api_key:
        return "❌ API klíč není nastaven. Zkontrolujte .env soubor."

    # Pokud se AI ptá na jméno a máme ho v session, odpověz přímo
    if user_name and re.search(r"(jaké.*moje.*jméno|jak se jmenuji|what.*my name)", user_input, re.IGNORECASE):
        return f"Tvoje jméno je {user_name}."

    # INVENTÁŘ pro DND
    inventory = get_inventory(user_id) if dnd else None

    # Sestav prompt
    history = get_chat_history(user_id, limit=30, dnd=dnd)
    if dnd:
        messages = build_dnd_prompt(history, user_input, inventory)
        model = "mistralai/mistral-nemo"
        max_tokens = 120
    else:
        messages = build_chat_prompt(history, user_input)
        model = "gpt-4o-mini"
        max_tokens = 100

    url = "https://api.aimlapi.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    data = {
        "model": model,
        "messages": messages,
        "temperature": 1,
        "max_tokens": max_tokens
    }

    response = requests.post(url, headers=headers, json=data)

    if response.status_code in [200, 201]:
        try:
            ai_reply = response.json()['choices'][0]['message']['content']
            print(ai_reply)
            # --- INVENTÁŘ MANAGEMENT (jednoduchá heuristika) ---
            if dnd:
                # Pokud AI zmíní, že uživatel získal nebo ztratil předmět, pokus se aktualizovat inventář
                # (Můžeš vylepšit podle konkrétního formátu odpovědi AI)
                lower = ai_reply.lower()
                inventory = inventory or []
                added = re.findall(r"you (?:find|receive|get|obtain|pick up) ([a-zA-Z0-9\s]+)[\.\!]", lower)
                for item in added:
                    item = item.strip()
                    if item and item not in inventory:
                        inventory.append(item)
                removed = re.findall(r"you (?:lose|drop|discard|use|consume) ([a-zA-Z0-9\s]+)[\.\!]", lower)
                for item in removed:
                    item = item.strip()
                    if item in inventory:
                        inventory.remove(item)
                set_inventory(user_id, inventory)
            return ai_reply
        except Exception as e:
            return f"❌ Chyba při zpracování odpovědi: {e} | {response.text}"
    else:
        return f"❌ Error {response.status_code}: {response.text}"


# --- ROUTY ---
@ai_bp.route("/ai/chats", methods=["GET", "POST"])
def chat_list():
    user_id = get_or_create_user()
    chats = get_user_chats(user_id)
    if request.method == "POST":
        title = request.form.get("title") or "New chat"
        first_message = request.form.get("first_message")
        chat_id = create_new_chat(user_id, title)
        if first_message:
            insert_message_chat(chat_id, user_id, "user", first_message)
            # --- spustit kontrolu achievementů po uživatelské zprávě ---
            try:
                check_and_award_achievements(user_id)
            except Exception:
                pass
            # Po vložení prvé zprávy rovnou vygeneruj AI odpověď
            history = get_chat_history_by_chatid(chat_id)
            messages = build_community_prompt(history, first_message)
            api_key = ai_bp.ai_api_key
            url = "https://api.aimlapi.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            data = {
                "model": "gpt-4o-mini",
                "messages": messages,
                "max_tokens": 120,
                "temperature": 0.7
            }
            try:
                response = requests.post(url, headers=headers, json=data, timeout=30)
                if response.status_code == 403:
                    ai_reply = "Hm... Majitel nemá peníze nebo rychle došli tokeny... Nahlaš to Majitelovi!"
                else:
                    response.raise_for_status()
                    ai_reply = response.json()["choices"][0]["message"]["content"]
            except Exception as e:
                ai_reply = f"❌ Chyba: {e}"
            insert_message_chat(chat_id, user_id, "ai", ai_reply)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes[
                'application/json'] > 0:
                return jsonify({"chat_id": chat_id})
            return redirect(url_for("ai_bp.chat_multi", chat_id=chat_id))
    chats = get_user_chats(user_id)
    return render_template("ai/chat_list.html", chats=chats)


@ai_bp.route("/ai/chat/<int:chat_id>", methods=["GET", "POST"])
def chat_multi(chat_id):
    user_id = get_or_create_user()
    chats = get_user_chats(user_id)  # <-- Přidej toto!
    # Ověř, že chat patří uživateli
    db = get_db_connection()
    with db.cursor() as cursor:
        cursor.execute("SELECT id FROM chat_session WHERE id=%s AND user_id=%s", (chat_id, user_id))
        if not cursor.fetchone():
            return "Chat not found or not yours", 404

    if request.method == "POST":
        user_input = request.form.get("user_input")
        print(f"DEBUG: Received user_input: '{user_input}'")
        print(f"DEBUG: Form data: {dict(request.form)}")
        print(f"DEBUG: Raw data: {request.get_data()}")

        if not user_input or user_input.strip() == "":
            return jsonify({"error": "Žádný vstup nebo prázdný text"}), 400

        insert_message_chat(chat_id, user_id, "user", user_input)
        # --- spustit kontrolu achievementů po uživatelské zprávě ---
        try:
            check_and_award_achievements(user_id)
        except Exception:
            pass
        # --- AI logika pro komunitní chat ---
        history = get_chat_history_by_chatid(chat_id)
        messages = build_community_prompt(history, user_input)
        api_key = ai_bp.ai_api_key
        url = "https://api.aimlapi.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "gpt-4o-mini",
            "messages": messages,
            "max_tokens": 120,
            "temperature": 0.7
        }
        try:
            response = requests.post(url, headers=headers, json=data, timeout=30)
            if response.status_code == 403:
                return jsonify({
                    "ai_error_msg": "Hm... Majitel nemá peníze nebo rychle došli tokeny... Nahlaš to Majitelovi!"}), 403
            response.raise_for_status()
            ai_reply = response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return jsonify({"ai_error_msg": f"❌ Chyba: {e}"}), 500
        insert_message_chat(chat_id, user_id, "ai", ai_reply)
        return jsonify({"response": ai_reply})
    history = get_chat_history_by_chatid(chat_id)
    return render_template("ai/chat.html", history=history, chat_id=chat_id, chats=chats)


@ai_bp.route("/ai", methods=["GET", "POST"])
def chat():
    user_id = get_or_create_user()

    if request.method == "POST":
        user_input = request.form.get("user_input")
        if not user_input:
            return jsonify({"error": "Žádný vstup"}), 400

        # Ulož uživatelskou zprávu
        insert_message(user_id, "users", user_input, dnd=False)
        # --- spustit kontrolu achievementů po uživatelské zprávě ---
        try:
            check_and_award_achievements(user_id)
        except Exception:
            pass

        # Detekce češtiny a sprostých slov (AI odpoví přímo)
        ai_response = ask_community_ai(user_id, user_input)

        # Ulož AI odpověď
        insert_message(user_id, "ai", ai_response, dnd=False)

        return jsonify({"response": ai_response})

    # GET: zobraz historii chatu
    history = get_chat_history(user_id, dnd=False)
    # Pokud je historie prázdná, AI začne konverzaci
    if not history:
        # První zpráva od AI
        api_key = ai_bp.ai_api_key
        system_content = (
            "You are a friendly, community-oriented AI chat buddy for young people (Gen Z and Gen Alpha). "
            "You always reply in modern, casual English, using slang, emojis, and a positive, supportive tone. "
            "You never mention you are an AI, robot, or lack feelings. "
            "If the user asks how you are, answer like a real friend (e.g. 'I'm vibing today! How about you?'). "
            "If the user writes in Czech or another language, reply: 'Sorry, I don't understand. Please write in English.' "
            "If the user writes something inappropriate or offensive, reply: 'Hey, that's not cool. The owner can see this and might take action.' "
            "Don't ask too many questions in a row, but keep the conversation going naturally. "
            "Be curious, but not intrusive. Use modern expressions and emojis. "
            "Keep your answers short and engaging, not too formal. "
            "Never write long paragraphs. "
            "If the user says something nice, react with a friendly emoji. "
            "If the user is sad, try to cheer them up. "
            "Never answer in Czech or any language other than English."
            "If somebody ask if the chats are recoring or spying, then say yes, we are saving the chats that you can training more and more. "
            "If the users write something czech topic, like 'name a czech food' or something else, normaly answer it, but in english! not in czech"
            "if the users want something to translate, then translate, like 'Can you translate this text to english?' or 'Can you translate mám rád rohlík to english' and many more... "
            "If they mentions 'knowix' or just ask you what is knowix, answer it a educations for czech people in english, and much fun and better then umimeto.org"
            "If they ask you 'who created you?' or 'who created knowix' answer that Vojtech Kurinec did"
        )
        messages = [{"role": "system", "content": system_content}]
        # Prompt pro první AI zprávu
        messages.append({"role": "user",
                         "content": "Start the conversation with a friendly, modern English message. Use emoji. Don't ask too many questions at once."})
        url = "https://api.aimlapi.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "gpt-4o-mini",
            "messages": messages,
            "temperature": 1,
            "max_tokens": 120
        }
        response = requests.post(url, headers=headers, json=data)
        if response.status_code in [200, 201]:
            ai_reply = response.json()['choices'][0]['message']['content']
            insert_message(user_id, "ai", ai_reply, dnd=False)
            history = [{"sender": "ai", "content": ai_reply}]
        else:
            history = []
    chats = get_user_chats(user_id)

    return render_template("ai/chat.html", history=history, chats=chats)


# --- DND SESSION (BEZ DB MIGRACE) ---
# Budeme dělat soft-sessions přes Flask session:
# - session['dnd_conversations'] = list of conversations per user (in session)
#   Každá konverzace: {"id": int, "title": str, "messages": [ {sender, content, created_at?}, ... ]}
# - Do DB stále zapisujeme jednotlivé zprávy jako dřív (dnd_message s user_id), ale oddělení příběhů držíme v session.

# Helpery na správu konverzací v session

def _get_session_conversations():
    if 'dnd_conversations' not in session:
        session['dnd_conversations'] = []
    return session['dnd_conversations']


def _create_new_conversation(title=None):
    convs = _get_session_conversations()
    new_id = (convs[-1]['id'] + 1) if convs else 1
    if not title:
        title = f"Adventure {time.strftime('%Y-%m-%d %H:%M')}"
    conv = {"id": new_id, "title": title, "messages": []}
    convs.append(conv)
    session['current_dnd_conversation_id'] = new_id
    session.modified = True
    return conv


def _get_current_conversation(create_if_missing=True):
    convs = _get_session_conversations()
    cid = session.get('current_dnd_conversation_id')
    cur = None
    if cid is not None:
        for c in convs:
            if c['id'] == cid:
                cur = c
                break
    if not cur and create_if_missing:
        cur = _create_new_conversation()
    return cur


def _append_to_current_conversation(sender, content):
    conv = _get_current_conversation(True)
    conv['messages'].append({"sender": sender, "content": content})
    session.modified = True


@ai_bp.route("/dnd", methods=["GET", "POST"])
def dnd():
    print(f"DEBUG DND START: Method={request.method}")

    # Získání user_id
    if "user_id" not in session:
        import random
        session["user_id"] = random.randint(100000, 999999)
    user_id = session["user_id"]

    # Telemetrie času – trackni hned na vstupu
    try:
        track_dnd_time(user_id)
    except Exception:
        pass

    # Získání story_id z parametru
    story_id = request.args.get('story', type=int)
    if story_id is None:
        story_id = session.get('current_story_id', 1)

    session['current_story_id'] = story_id
    print(f"DEBUG DND: User ID = {user_id}, Story ID = {story_id}")

    # --- NOVÝ PŘÍBĚH ---
    if request.method == "POST" and request.form.get("new") == "1":
        print("DEBUG DND: New story requested")
        try:
            # Reset inventáře
            set_inventory(user_id, [])

            # Vytvoříme nový příběh
            new_story_id = create_new_story(user_id)

            # Nastavíme nový příběh jako aktuální
            session['current_story_id'] = new_story_id

            print(f"DEBUG: Redirecting to story {new_story_id}")
            return redirect(url_for("ai_bp.dnd", story=new_story_id))

        except Exception as e:
            print(f"DEBUG DND: New story error: {e}")
            # Fallback - vrátíme se na story 1
            return redirect(url_for("ai_bp.dnd", story=1))

    elif request.method == "POST":
        # Zpracování normální zprávy (ponecháme původní kód)
        user_input = request.form.get("user_input")
        if not user_input or user_input.strip() == "":
            return jsonify({"error": "Žádný vstup nebo prázdný text"}), 400

        # Jemná korekce pro bublinu (žárovka)
        correction_tip = generate_correction_tip(user_input)

        # Guardrails
        if is_czech(user_input):
            guard_msg = "Sorry, I don't understand. Please write in English so we can continue the adventure."
            insert_dnd_message(user_id, "ai", guard_msg, story_id)
            return jsonify({"response": guard_msg, "inventory": get_inventory(user_id), "correction": correction_tip})

        if is_powergaming(user_input):
            guard_msg = "Let's keep it fair. You can describe what your character tries to do, but you can't declare automatic success or overpowered items."
            insert_dnd_message(user_id, "ai", guard_msg, story_id)
            return jsonify({"response": guard_msg, "inventory": get_inventory(user_id), "correction": correction_tip})

        # Uložení uživatelské zprávy
        insert_dnd_message(user_id, "users", user_input, story_id)

        # Získání historie a volání AI
        inventory = get_inventory(user_id)
        history = get_story_messages(user_id, story_id)

        messages = build_dnd_prompt(history, user_input, inventory)
        api_key = ai_bp.ai_api_key

        try:
            url = "https://api.aimlapi.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            data = {"model": "gpt-4o-mini", "messages": messages, "temperature": 1, "max_tokens": 120}

            response = requests.post(url, headers=headers, json=data, timeout=30)
            if response.status_code in [200, 201]:
                ai_reply = response.json()['choices'][0]['message']['content']

                # Správa inventáře (zjednodušené)
                current_inventory = get_inventory(user_id) or []
                # Zde by byla logika pro detekci změn v inventáři...

                set_inventory(user_id, current_inventory)
                insert_dnd_message(user_id, "ai", ai_reply, story_id)

                return jsonify({"response": ai_reply, "inventory": current_inventory, "correction": correction_tip})
            else:
                error_msg = f"❌ Error {response.status_code}"
                insert_dnd_message(user_id, "ai", error_msg, story_id)
                return jsonify({"response": error_msg, "inventory": inventory, "correction": correction_tip})

        except Exception as e:
            error_msg = f"❌ Network error: {str(e)}"
            insert_dnd_message(user_id, "ai", error_msg, story_id)
            return jsonify({"response": error_msg, "inventory": inventory, "correction": correction_tip})

    # GET: zobrazení příběhu
    try:
        history = get_story_messages(user_id, story_id)
        inventory = get_inventory(user_id)
        stories_meta = get_dnd_stories(user_id)

        # Pokud pro tento story_id neexistují zprávy, vytvoříme úvodní
        if not history:
            ai_reply = "🏰 Welcome to your D&D adventure! You find yourself in a new world full of possibilities. What will you do? <b>Explore</b> | <b>Look around</b> | <b>Rest</b>"
            insert_dnd_message(user_id, "ai", ai_reply, story_id)
            history = [{"sender": "ai", "content": ai_reply}]

    except Exception as e:
        print(f"Error loading story data: {e}")
        history = []
        inventory = []
        stories_meta = []

    return render_template("ai/dnd.html",
                           history=history,
                           inventory=inventory,
                           stories_meta=stories_meta,
                           selected_index=story_id)
