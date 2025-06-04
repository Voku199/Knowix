from locust import HttpUser, task, between
import random


class WebsiteUser(HttpUser):
    wait_time = between(1, 10)  # mezi každým requestem 1–3 sekundy

    @task
    def browse_site(self):
        endpoints = [
            "/",  # hlavní stránka
            "/feedback",  # zpětná vazba
            "/anglictina",  # nepravidelná slovesa
            "/listening",  # cvičení s hudbou
            "/song-selection",
            "/listening/A1/a1_lesson_morning_routine",  # novinky
            "/listening/A1/a1_lesson_park",  # chat lekce
            "/listening/A1/a1_lesson_shopping",  # šibenice
            "/listening/A2/a2_lesson_trip_to_city",  # změna tématu
            "/listening/A2/a2_lesson_weekend_with_friends",  # poslechová cvičení
            "/listening/A2/a2_lesson_balancing_hobbies",  # předložky at/on
            "/listening/A2/a2_lesson_trip_to_city",
            "/listening/B1/b1_lesson_study_abroad",
            "/listening/B1/b1_lesson_digital_detox",
            "/listening/B1/b1_lesson_first_job",
            "/listening/B2/b2_lesson2",
            "/listening/B2/b2_lesson_tech_insider_report",
            "/listening/B2/b2_lesson_tech_insider_report",
            "/listening/B2/b2_lesson_indian_scammer",
            "/exercise/0",
            "/exercise/1",
            "/exercise/2",
            "/exercise/3",
            "/exercise/4",
            "/exercise/5",
            "/exercise/6",
            "/exercise/7",
            "/exercise/8",
            "/exercise/9",
            "/exercise/10",
            "/exercise/11",
            "/hangman",
            "/gramatika",
            "/sl_chat",
            "/chat?lesson_id=mental_health",
            "/chat?lesson_id=social_media",
            "/chat?lesson_id=relationship_path",
            "/chat?lesson_id=vr_gaming",
            "/chat?lesson_id=school_future",
            "/at-on/fill-word",
            "/anglictina/test",
            "/feedback",
            "/news",
            "/login",
            "/register",

        ]
        chosen = random.choice(endpoints)
        self.client.get(chosen)

# Spusť Locust pomocí příkazu: locust -f zatez.py
