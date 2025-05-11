import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

# Získání hodnot z prostředí
db_host = os.getenv('MYSQL_HOST')  # Hostitel (např. Railway nebo localhost)
db_user = os.getenv('MYSQL_USER')  # Uživatelské jméno
db_password = os.getenv('MYSQL_PASSWORD')  # Heslo
db_name = os.getenv('MYSQL_DATABASE')  # Název databáze

# Připojení k databázi
connection = mysql.connector.connect(
    host=db_host,
    user=db_user,
    password=db_password,
    database=db_name,
    port=3306  # Ujisti se, že používáš správný port
)

cursor = connection.cursor()

# Provádění dotazů na databázi
cursor.execute("SELECT * FROM some_table")

cursor.close()
connection.close()
