import deepl
import os

# Zadej svůj API klíč získaný z DeepL Pro
API_KEY = "5d16815c-c88a-48f7-8092-d8008bd7ab66:fx"

# Inicializace DeepL API
translator = deepl.Translator(API_KEY)


# Funkce pro získání aktuálního stavu využití (zbylé znaky)
def check_usage():
    try:
        usage = translator.get_usage()
        remaining_chars = usage["character_limit"] - usage["character_count"]
        print(f"Zbývající znaky k překladu: {remaining_chars}")
        return remaining_chars
    except Exception as e:
        print(f"Chyba při získávání informací o limitech: {e}")
        return None


# Funkce pro překlad textu
def translate_text(text, target_lang="CS"):
    remaining_chars = check_usage()  # Získáme počet zbývajících znaků

    if remaining_chars is None:
        return "Chyba při zjišťování limitu pro překlad."

    if len(text) > remaining_chars:
        return f"Chyba: Text je příliš dlouhý pro překlad. Zbývající znaky: {remaining_chars}"

    try:
        # Použití DeepL API pro překlad
        translated = translator.translate_text(text, target_lang=target_lang)
        return translated.text
    except Exception as e:
        return f"Chyba při překladu: {e}"


# Testování překladu
text_to_translate = "We were listenin' to Lover's Rock"  # Text, který překladáš
translated_text = translate_text(text_to_translate)

# Výpis přeloženého textu
print(f"Původní text: {text_to_translate}")
print(f"Přeložený text: {translated_text}")
