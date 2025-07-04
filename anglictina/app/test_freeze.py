import sys
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv('.env')
from db import get_db_connection
from streak import update_user_streak, get_user_streak, use_freeze_if_available


def setup_test_user(user_id):
    """Reset test user streak and freeze state."""
    conn = get_db_connection()
    cur = conn.cursor()
    # Set streak to 5 and last_streak_date to two days ago
    cur.execute("UPDATE users SET streak = 5, last_streak_date = %s WHERE id = %s",
                (date.today() - timedelta(days=2), user_id))
    # Remove all freezes for this user
    cur.execute("DELETE FROM user_freeze WHERE user_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()


def give_user_freeze(user_id):
    """Insert a freeze for today for the user (simulate buying freeze)."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO user_freeze (user_id, freeze_date, used) VALUES (%s, %s, FALSE)",
        (user_id, date.today())
    )
    conn.commit()
    cur.close()
    conn.close()


def print_user_state(user_id):
    streak = get_user_streak(user_id)
    print(f"User {user_id} streak: {streak}")
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM user_freeze WHERE user_id = %s", (user_id,))
    freezes = cur.fetchall()
    print(f"User {user_id} freezes: {freezes}")
    cur.close()
    conn.close()


def test_freeze_usage(user_id):
    print("=== Setting up test user ===")
    setup_test_user(user_id)
    print_user_state(user_id)

    print("\n=== Giving user a freeze ===")
    give_user_freeze(user_id)
    print_user_state(user_id)

    print("\n=== Simulating lesson completion (should use freeze) ===")
    result = update_user_streak(user_id)
    print(f"update_user_streak result: {result}")
    print_user_state(user_id)

    assert result["status"] == "freeze_used", "Freeze should have been used"
    assert get_user_streak(user_id) == 5, "Streak should not reset if freeze is used"

    print("\n=== Simulating another lesson completion (should continue as normal) ===")
    result2 = update_user_streak(user_id)
    print(f"update_user_streak result: {result2}")
    print_user_state(user_id)
    assert result2["status"] == "already_done", "Should be already_done if called twice in a day"

    print("\n=== Simulating streak reset after 2 days without freeze ===")
    # Reset user again, but do not give freeze
    setup_test_user(user_id)
    print_user_state(user_id)
    # Simulate user waits 2 days (last_streak_date is 2 days ago, no freeze)
    result3 = update_user_streak(user_id)
    print(f"update_user_streak result: {result3}")
    print_user_state(user_id)
    assert result3["status"] == "reset", "Streak should reset if no freeze is available"
    assert get_user_streak(user_id) == 1, "Streak should be reset to 1"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_streak_freeze.py <user_id>")
        sys.exit(1)
    user_id = int(sys.argv[1])
    test_freeze_usage(user_id)
