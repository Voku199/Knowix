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


def ensure_core_tables_exist():
    """Zajistí vytvoření hlavních tabulek, pokud neexistují.

    Funkce je idempotentní – může se volat opakovaně.
    Vytváří pouze tabulky/úpravy, které NEMÁŠ nikde jinde v kódu
    (pro denní questy a rozšířené user_stats už máš vlastní logiku v jiných modulech).
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Základní tabulka uživatelů – minimální schéma podle použití v kódu
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                email VARCHAR(255),
                password_hash VARCHAR(255),
                first_name VARCHAR(255),
                last_name VARCHAR(255),
                xp INT NOT NULL DEFAULT 0,
                level INT NOT NULL DEFAULT 1,
                theme_mode VARCHAR(32) DEFAULT NULL,
                streak INT NOT NULL DEFAULT 0,
                last_streak_date DATE DEFAULT NULL,
                reminder_token VARCHAR(255) DEFAULT NULL,
                receive_reminder_emails TINYINT(1) NOT NULL DEFAULT 1,
                english_level VARCHAR(32) DEFAULT NULL,
                role VARCHAR(32) DEFAULT 'user'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

        # Základní tabulka user_stats – detailní schéma dořeší user_stats.py pomocí ALTER TABLE
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_stats (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL UNIQUE,
                total_lessons_done INT NOT NULL DEFAULT 0,
                correct_answers INT NOT NULL DEFAULT 0,
                wrong_answers INT NOT NULL DEFAULT 0,
                total_learning_time INT NOT NULL DEFAULT 0,
                last_active DATETIME DEFAULT NULL,
                total_psani_words INT NOT NULL DEFAULT 0,
                first_activity DATETIME DEFAULT NULL,
                AI_poslech_minut INT NOT NULL DEFAULT 0,
                AI_poslech_seconds INT NOT NULL DEFAULT 0,
                hangman_words_guessed INT NOT NULL DEFAULT 0,
                irregular_verbs_guessed INT NOT NULL DEFAULT 0,
                irregular_verbs_wrong INT NOT NULL DEFAULT 0,
                pp_wrong INT NOT NULL DEFAULT 0,
                pp_maybe INT NOT NULL DEFAULT 0,
                pp_correct INT NOT NULL DEFAULT 0,
                roleplaying_cr INT NOT NULL DEFAULT 0,
                roleplaying_mb INT NOT NULL DEFAULT 0,
                roleplaying_wr INT NOT NULL DEFAULT 0,
                lis_cor INT NOT NULL DEFAULT 0,
                lis_wr INT NOT NULL DEFAULT 0,
                at_cor INT NOT NULL DEFAULT 0,
                at_wr INT NOT NULL DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

        # Tabulka pro zamražení streaku (freeze) – používá se v obchod.py a test_freeze.py
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_freeze (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                freeze_date DATE NOT NULL,
                used TINYINT(1) NOT NULL DEFAULT 0,
                UNIQUE KEY uniq_user_date (user_id, freeze_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

        # Tabulka pro XP boostery – používá se v obchod.py a xp.py
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_xp_booster (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                start_date DATETIME NOT NULL,
                end_date DATETIME NOT NULL,
                active TINYINT(1) NOT NULL DEFAULT 1,
                KEY idx_user_active (user_id, active)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

        # Tabulka achievements + user_achievements – používá se v xp.py
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS achievements (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                code VARCHAR(64) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                condition_type VARCHAR(64) NOT NULL,
                condition_value BIGINT NOT NULL DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_achievements (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                achievement_id INT NOT NULL,
                achieved_at DATETIME NOT NULL,
                UNIQUE KEY uniq_user_achievement (user_id, achievement_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

        # Tabulka pro push notifikace – používá se v push_notifications.py
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                endpoint TEXT NOT NULL,
                p256dh VARCHAR(255) NOT NULL,
                auth VARCHAR(255) NOT NULL,
                created_at DATETIME NOT NULL,
                installed TINYINT(1) NOT NULL DEFAULT 1,
                last_seen DATETIME DEFAULT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

        # Tabulka feedback – používá se v review.py a feedback.py
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id INT NULL,
                message TEXT NOT NULL,
                rating INT NULL,
                timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_edited TINYINT(1) NOT NULL DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

        # Tabulka news – používá se v news.py
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS news (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                author_id INT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

        # Tabulka psani – používá se v psani.py
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS psani (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                obsah TEXT NOT NULL,
                public TINYINT(1) NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        # Pokud nemáme práva (např. jen read-only DB), tiše skončíme
        pass
