# import re
# import flask
#
#
# def auto_linkify(text):
#     """
#     Najde URL adresy v textu (např. www.example.com, example.com, http://...) a převede je na klikací odkazy.
#     Zachovává již existující HTML tagy.
#     """
#     # Regulární výraz pro URL (včetně www. a domén bez http)
#     url_pattern = re.compile(
#         r'(?<!href="|">|">www\.)(?P<url>(https?://|www\.)[^\s<]+|(?<!@)\b[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b(?!@))',
#         re.IGNORECASE
#     )
#
#     def repl(match):
#         url = match.group('url')
#         # Pokud URL začíná na http/https, použij přímo
#         if url.startswith('http://') or url.startswith('https://'):
#             href = url
#         elif url.startswith('www.'):
#             href = 'http://' + url
#         else:
#             href = 'http://' + url
#         return f'<a href="{href}" target="_blank" rel="noopener noreferrer">{url}</a>'
#
#     # Nejprve nahradíme všechny URL v textu
#     return url_pattern.sub(repl, text)
