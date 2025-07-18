from dotenv import load_dotenv
from flask import render_template, request, jsonify, url_for, redirect, Blueprint, session, g
import requests
import os
import re
import random
import time
import json
from db import get_db_connection  # Importuj svoji funkci na připojení k DB

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
        cursor.execute("INSERT INTO users () VALUES ()")
        user_id = cursor.lastrowid
    db.commit()
    session["user_id"] = user_id
    return user_id


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


def get_chat_history(user_id, limit=30, dnd=False):
    db = get_db_connection()
    table = "dnd_message" if dnd else "chat_message"
    with db.cursor(dictionary=True) as cursor:
        cursor.execute(
            f"SELECT sender, content, created_at FROM {table} WHERE user_id=%s ORDER BY created_at ASC LIMIT %s",
            (user_id, limit)
        )
        return cursor.fetchall()


# def get_or_create_user():
#     # Vrací user_id z tabulky users, pokud není v session, vytvoří nového
#     if "user_id" in session:
#         return session["user_id"]
#     db = get_db_connection()
#     with db.cursor() as cursor:
#         cursor.execute("INSERT INTO users () VALUES ()")
#         user_id = cursor.lastrowid
#     db.commit()
#     session["user_id"] = user_id
#     return user_id


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
        return "Sorry, I don't understand. Please write in English. 🙏"
    # Detekce sprostých slov
    if contains_bad_word(user_input):
        return "Hey, that's not cool. The owner can see this and might take action. 🚨"

    history = get_chat_history(user_id, limit=30, dnd=False)
    messages = build_community_prompt(history, user_input)
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
        try:
            ai_reply = response.json()['choices'][0]['message']['content']
            return ai_reply
        except Exception as e:
            return f"❌ Error: {e} | {response.text}"
    else:
        return f"❌ Error {response.status_code}: {response.text}"


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
        max_tokens = 300
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
                "max_tokens": 700,
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
        if not user_input:
            return jsonify({"error": "No input"}), 400
        insert_message_chat(chat_id, user_id, "user", user_input)
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
            "max_tokens": 700,
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


@ai_bp.route("/dnd", methods=["GET", "POST"])
def dnd():
    # Získání nebo vytvoření user_id v session
    if "user_id" not in session:
        import random
        session["user_id"] = random.randint(100000, 999999)
    user_id = session["user_id"]

    # --- RESTART CHATU ---
    if request.method == "POST" and request.form.get("restart") == "1":
        db = get_db_connection()
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM dnd_message WHERE user_id=%s", (user_id,))
            db.commit()
        set_inventory(user_id, [])
        return ('', 204)

    if request.method == "POST":
        user_input = request.form.get("user_input")
        if not user_input:
            return jsonify({"error": "Žádný vstup"}), 400

        insert_message(user_id, "users", user_input, dnd=True)

        inventory = get_inventory(user_id)
        history = get_chat_history(user_id, dnd=True)
        messages = build_dnd_prompt(history, user_input, inventory)
        api_key = ai_bp.ai_api_key

        url = "https://api.aimlapi.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "mistralai/mistral-nemo",
            "messages": messages,
            "temperature": 1,
            "max_tokens": 300
        }
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 403:
            return jsonify({
                "ai_error_msg": "Hm... Majitel nema penize nebo rychle dosli tokeny... Nahlas to Majitelovi!.. prosim! A pikaču! tohle je schválně!",
                "img_url": "/static/pic/pikachu_sad.png"
            }), 403
        if response.status_code in [200, 201]:
            ai_reply = response.json()['choices'][0]['message']['content']
            # --- INVENTÁŘ MANAGEMENT (jednoduchá heuristika) ---
            lower = ai_reply.lower()
            inventory = inventory or []
            added = re.findall(r"you (?:find|receive|get|obtain|pick up) ([a-zA-Z0-9\s]+)[\.\!]", lower)
            removed = re.findall(r"you (?:lose|drop|discard|use|consume) ([a-zA-Z0-9\s]+)[\.\!]", lower)
            for item in added:
                item = item.strip()
                if item and item not in inventory:
                    inventory.append(item)
            for item in removed:
                item = item.strip()
                if item in inventory:
                    inventory.remove(item)
            set_inventory(user_id, inventory)
            insert_message(user_id, "ai", ai_reply, dnd=True)
            return jsonify({"response": ai_reply, "inventory": inventory})
        else:
            return jsonify({"response": f"❌ Error {response.status_code}: {response.text}", "inventory": inventory})

    # GET: zobraz historii chatu
    history = get_chat_history(user_id, dnd=True)
    inventory = get_inventory(user_id)
    # Pokud je historie prázdná, vygeneruj úvodní příběh od AI
    if not history:
        api_key = ai_bp.ai_api_key
        messages = build_dnd_prompt([], None, inventory, is_intro=True)
        url = "https://api.aimlapi.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "mistralai/mistral-nemo",
            "messages": messages + [{"role": "user",
                                     "content": "Start the adventure for the player. Give them 2-3 choices what to do next. Use emoji and HTML formatting."}],
            "temperature": 1,
            "max_tokens": 400
        }
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 403:
            return jsonify({
                "ai_error_msg": "Hm... Majitel nemá peníze nebo rychle došli tokeny... Nahlaš to Majitelovi!",
                "img_url": "/static/img/pikachu_sad.png"
            }), 403
        if response.status_code in [200, 201]:
            ai_reply = response.json()['choices'][0]['message']['content']
            insert_message(user_id, "ai", ai_reply, dnd=True)
            history = [{"sender": "ai", "content": ai_reply}]
        else:
            history = []
    return render_template("ai/dnd.html", history=history, inventory=inventory)
