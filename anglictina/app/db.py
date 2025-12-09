import os
import mysql.connector


def get_db_connection():
    return mysql.connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASS"],
        database=os.environ["DB_NAME"],
        connection_timeout=30
    )


def ensure_users_table_guest():
    """Zajistí, že tabulka users existuje a má potřebné sloupce pro Google OAuth.
    Vytvoří tabulku, pokud chybí. Dále přidá chybějící sloupce.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
CREATE TABLE IF NOT EXISTS guest (
  id INT AUTO_INCREMENT PRIMARY KEY,
  first_name VARCHAR(50) NULL,
  last_name VARCHAR(50) NULL,
  email VARCHAR(100) NOT NULL,
  password VARCHAR(255) NULL,
  birthdate DATE NULL,
  profile_pk VARCHAR(255) NULL DEFAULT 'default.jpg',
  theme_mode VARCHAR(45) NULL DEFAULT 'light',
  english_level VARCHAR(3) NULL DEFAULT 'A1',
  xp INT NULL DEFAULT 0,
  level INT NULL DEFAULT 1,
  streak INT NULL DEFAULT 0,
  last_streak_date DATE NULL,
  inventory TEXT NULL,
  school VARCHAR(100) NULL,
  subject VARCHAR(100) NULL,
  role VARCHAR(45) NULL DEFAULT 'student',
  verified TINYINT(1) NULL,
  receive_reminder_emails TINYINT(1) NULL,
  last_reminder_sent DATETIME NULL,
  reminder_token VARCHAR(128) NULL,
  last_email_stage TINYINT NULL,
  last_push_reminder_sent DATETIME NULL,
  last_push_stage TINYINT NULL,
  last_email_day DATE NULL,
  email_sends_today INT NULL,
  last_push_day DATE NULL,
  push_sends_today INT NULL,
  last_email_date DATE NULL,
  last_push_date DATE NULL,
  is_guest TINYINT(1) NULL,
  has_seen_onboarding TINYINT(1) NULL,
  created_at TIMESTAMP NULL,
  provider VARCHAR(32) NULL,
  provider_id VARCHAR(128) NULL,
  avatar_url VARCHAR(5512) NULL,
  last_login TIMESTAMP NULL,
  UNIQUE KEY uniq_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )
    except Exception:

        print("[DB] Chyba při zajišťování tabulky guest:", exc_info=True)
    finally:
        cur.close()
        conn.close()
