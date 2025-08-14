from datetime import date, timedelta
from db import get_db_connection


class StreakSystem:
    def __init__(self, user_id):
        self.user_id = user_id
        self.today = date.today()
        self.conn = get_db_connection()
        self.current_streak = 0
        self.last_date = None
        self.status = "unchanged"
        self.new_streak = 0

    def __enter__(self):
        self.load_user_data()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.close()
        return False

    def load_user_data(self):
        """Načte aktuální streak data uživatele"""
        with self.conn.cursor(dictionary=True) as cur:
            cur.execute("SELECT streak, last_streak_date FROM users WHERE id = %s", (self.user_id,))
            row = cur.fetchone()

        if not row:
            raise ValueError(f"User {self.user_id} not found")

        self.current_streak = row['streak'] or 0
        self.last_date = self.normalize_date(row['last_streak_date'])

    @staticmethod
    def normalize_date(date_value):
        """Převede různé formáty datumu na date objekt"""
        if not date_value:
            return None
        if isinstance(date_value, date):
            return date_value
        if isinstance(date_value, str):
            return date.fromisoformat(date_value)
        if hasattr(date_value, "date"):
            return date_value.date()
        return None

    def has_completed_today(self):
        """Kontrola, zda uživatel dnes již lekci dokončil"""
        return self.last_date == self.today

    def is_consecutive_day(self):
        """Kontrola konsekutivního dne"""
        return self.last_date == self.today - timedelta(days=1)

    def use_freeze_if_available(self):
        """Pokus o použití freeze pro dnešek"""
        with self.conn.cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT id FROM user_freeze "
                "WHERE user_id = %s AND used = FALSE AND freeze_date = %s",
                (self.user_id, self.today)
            )
            if freeze := cur.fetchone():
                cur.execute("UPDATE user_freeze SET used = TRUE WHERE id = %s", (freeze["id"],))
                self.conn.commit()
                return True
        return False

    def calculate_new_streak(self):
        """Hlavní logika výpočtu nového streaku"""
        # První lekce uživatele
        if not self.last_date:
            self.status = "started"
            return 1

        # Konsekutivní den
        if self.is_consecutive_day():
            self.status = "continued"
            return self.current_streak + 1

        # Přerušení streaku - pokus o použití freeze
        if self.use_freeze_if_available():
            self.status = "freeze_used"
            return self.current_streak

        # Reset streaku
        self.status = "broken"
        return 1

    def update(self):
        """Hlavní metoda pro aktualizaci streaku"""
        if self.has_completed_today():
            self.status = "already_done"
            return self.status_report()

        self.new_streak = self.calculate_new_streak()

        # Aktualizace databáze
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET streak = %s, last_streak_date = %s WHERE id = %s",
                (self.new_streak, self.today, self.user_id)
            )
            self.conn.commit()

        return self.status_report()

    def status_report(self):
        """Vrátí kompletní report o stavu streaku"""
        streak_value = self.current_streak if self.status == "already_done" else self.new_streak
        return {
            "streak": streak_value,
            "status": self.status,
            "last_date": self.last_date,
            "today": self.today
        }


# API funkce pro použití v aplikaci
def update_user_streak(user_id):
    """Aktualizuje streak uživatele pomocí nového systému"""
    try:
        with StreakSystem(user_id) as system:
            return system.update()
    except ValueError as e:
        return {"error": str(e)}


def get_user_streak(user_id):
    """Získá aktuální streak uživatele"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT streak FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            # Always fetch the result, even if None
            return row[0] if row is not None else 0
    finally:
        conn.close()
