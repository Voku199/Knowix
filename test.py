from dotenv import load_dotenv
import os

load_dotenv()  # Načte proměnné z .env souboru

import mysql.connector

mydb = mysql.connector.connect(
    host=os.environ["DB_HOST"],
    port=int(os.environ["DB_PORT"]),
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASS"],
    database=os.environ["DB_NAME"],
    connection_timeout=30,
)

cursor = mydb.cursor()
print("Připojeno k databázi!")
