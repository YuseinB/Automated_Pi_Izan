#!/usr/bin/env python3

import RPi.GPIO as GPIO
import requests
import datetime
import time
import os
import sys

# =====================
# НАСТРОЙКИ
# =====================

LAT = 41.624
LON = 23.933
METHOD = 3  # Muslim World League
RELAY_PIN = 17
TIMES_FILE = "/home/user/azan/prayer_times.txt"
AUDIO_PATH = "/home/user/azan/"

# =====================
# GPIO НАСТРОЙКА
# =====================

GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT)
GPIO.output(RELAY_PIN, GPIO.LOW)

# =====================
# ФУНКЦИИ
# =====================

def log(msg):
    print(f"[{datetime.datetime.now()}] {msg}")
    sys.stdout.flush()

def fetch_prayer_times():
    try:
        today = datetime.date.today()
        url = f"http://api.aladhan.com/v1/timings/{today}?latitude={LAT}&longitude={LON}&method={METHOD}"
        response = requests.get(url, timeout=15)
        data = response.json()

        timings = data["data"]["timings"]

        with open(TIMES_FILE, "w") as f:
            f.write(f"Fajr={timings['Fajr'][:5]}\n")
            f.write(f"Dhuhr={timings['Dhuhr'][:5]}\n")
            f.write(f"Asr={timings['Asr'][:5]}\n")
            f.write(f"Maghrib={timings['Maghrib'][:5]}\n")
            f.write(f"Isha={timings['Isha'][:5]}\n")

        log("Prayer times updated.")

    except Exception as e:
        log(f"ERROR fetching prayer times: {e}")

def load_prayer_times():
    times = {}
    try:
        with open(TIMES_FILE, "r") as f:
            for line in f:
                name, value = line.strip().split("=")
                times[name] = value
    except:
        log("Could not read prayer times file.")
    return times

def play_azan(name):
    try:
        log(f"Starting Azan for {name}")

        GPIO.output(RELAY_PIN, GPIO.HIGH)
        time.sleep(5)

        os.system(f"mpg123 {AUDIO_PATH}{name.lower()}.mp3")

        time.sleep(5)
        GPIO.output(RELAY_PIN, GPIO.LOW)

        log(f"Finished Azan for {name}")

    except Exception as e:
        log(f"ERROR during azan: {e}")

# =====================
# СТАРТ
# =====================

if not os.path.exists(TIMES_FILE):
    fetch_prayer_times()

last_fetch_day = datetime.date.today()

while True:
    now = datetime.datetime.now()

    # Обновяване веднъж дневно
    if datetime.date.today() != last_fetch_day:
        fetch_prayer_times()
        last_fetch_day = datetime.date.today()

    prayer_times = load_prayer_times()
    current_time = now.strftime("%H:%M")

    for name, prayer_time in prayer_times.items():
        if current_time == prayer_time:
            play_azan(name)
            time.sleep(60)

    time.sleep(20)
