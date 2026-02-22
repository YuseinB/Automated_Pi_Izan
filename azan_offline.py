import smbus2
import datetime
import math
import json
import os
import time
from zoneinfo import ZoneInfo
import RPi.GPIO as GPIO
import subprocess

# =============================
# НАСТРОЙКИ
# =============================
LATITUDE = 41.659138
LONGITUDE = 23.797539
TIMEZONE = "Europe/Sofia"
TZ_SOFIA = ZoneInfo(TIMEZONE)

GPIO.setwarnings(False)
RELAY_PIN = 17
GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT)
AUDIO_DIR = "/home/user/azan/"
PRAYER_FILE = "/home/user/azan/prayer_times.json"

CHECK_INTERVAL = 20  # секунди между проверки
IMSAK_OFFSET_MINUTES = 25  # Fajr = Imsak + 20 минути
DHUHR_OFFSET_MINUTES = 6
ASR_OFFSET_MINUTES = 2
MAGHRIB_OFFSET_MINUTES = 6
ISHA_OFFSET_MINUTES = 1

# MWL ъгли
FAJR_ANGLE = 18
ISHA_ANGLE = 17


# =============================
# RTC DS3231
# =============================
def bcd2dec(bcd):
    return (bcd // 16 * 10) + (bcd % 16)


def read_ds3231():
    bus = None
    try:
        bus = smbus2.SMBus(1)
        addr = 0x68
        data = bus.read_i2c_block_data(addr, 0x00, 7)

        second = bcd2dec(data[0])
        minute = bcd2dec(data[1])
        hour = bcd2dec(data[2])
        day = bcd2dec(data[4])
        month = bcd2dec(data[5])
        year = 2000 + bcd2dec(data[6])

        return datetime.datetime(year, month, day, hour, minute, second)
    except:
        return datetime.datetime.now()
    finally:
        if bus:
            bus.close() # Винаги затваряйте шината


# =============================
# АСТРОНОМИЯ
# =============================
def calculate_time(date, angle, is_sunrise):
    day = date.timetuple().tm_yday
    lngHour = LONGITUDE / 15

    t = day + ((6 - lngHour) / 24) if is_sunrise else day + ((18 - lngHour) / 24)

    M = (0.9856 * t) - 3.289
    L = M + (1.916 * math.sin(math.radians(M))) + \
        (0.020 * math.sin(math.radians(2 * M))) + 282.634
    L %= 360

    RA = math.degrees(math.atan(0.91764 * math.tan(math.radians(L))))
    RA %= 360

    Lquadrant = (math.floor(L / 90)) * 90
    RAquadrant = (math.floor(RA / 90)) * 90
    RA += (Lquadrant - RAquadrant)
    RA /= 15

    sinDec = 0.39782 * math.sin(math.radians(L))
    cosDec = math.cos(math.asin(sinDec))

    cosH = (math.cos(math.radians(angle)) -
            (sinDec * math.sin(math.radians(LATITUDE)))) / \
           (cosDec * math.cos(math.radians(LATITUDE)))

    if cosH > 1 or cosH < -1:
        return None

    if is_sunrise:
        H = 360 - math.degrees(math.acos(cosH))
    else:
        H = math.degrees(math.acos(cosH))

    H /= 15
    T = H + RA - (0.06571 * t) - 6.622
    UT = (T - lngHour) % 24

    return UT


def utc_to_local(date, decimal_hour):
    # tz = ZoneInfo(TIMEZONE)

    h = int(decimal_hour)
    m = int((decimal_hour - h) * 60)

    dt_utc = datetime.datetime(
        date.year, date.month, date.day, h, m,
        tzinfo=datetime.timezone.utc
    )

    dt_local = dt_utc.astimezone(TZ_SOFIA)
    return dt_local.hour, dt_local.minute


def get_prayer_times(today):
    # 1. Базови изчисления (UTC)
    imsak_utc = calculate_time(today, 90 + FAJR_ANGLE, True)
    sunrise_utc = calculate_time(today, 90.833, True)
    sunset_utc = calculate_time(today, 90.833, False)
    isha_utc = calculate_time(today, 90 + ISHA_ANGLE, False)

    dhuhr_decimal = (sunrise_utc + sunset_utc) / 2
    asr_decimal = dhuhr_decimal + 3 # Приблизително за Asr

    # 2. Преобразуване към локално време (преди офсетите)
    imsak_h, imsak_m = utc_to_local(today, imsak_utc)
    dhuhr_h, dhuhr_m = utc_to_local(today, dhuhr_decimal)
    asr_h, asr_m = utc_to_local(today, asr_decimal)
    maghrib_h, maghrib_m = utc_to_local(today, sunset_utc)
    isha_h, isha_m = utc_to_local(today, isha_utc)

    # Функция помощник за добавяне на минути
    def add_minutes(h, m, offset):
        dt = datetime.datetime(today.year, today.month, today.day, h, m)
        dt += datetime.timedelta(minutes=offset)
        return dt.hour, dt.minute

    # 3. Прилагане на офсетите
    fajr_h, fajr_m = add_minutes(imsak_h, imsak_m, IMSAK_OFFSET_MINUTES)
    dhuhr_h, dhuhr_m = add_minutes(dhuhr_h, dhuhr_m, DHUHR_OFFSET_MINUTES)
    asr_h, asr_m = add_minutes(asr_h, asr_m, ASR_OFFSET_MINUTES)
    maghrib_h, maghrib_m = add_minutes(maghrib_h, maghrib_m, MAGHRIB_OFFSET_MINUTES)
    isha_h, isha_m = add_minutes(isha_h, isha_m, ISHA_OFFSET_MINUTES)

    return {
        "date": today.strftime("%Y-%m-%d"),
        "times": {
            "Imsak": {"hour": imsak_h, "minute": imsak_m},
            "Fajr": {"hour": fajr_h, "minute": fajr_m},
            "Dhuhr": {"hour": dhuhr_h, "minute": dhuhr_m},
            "Asr": {"hour": asr_h, "minute": asr_m},
            "Maghrib": {"hour": maghrib_h, "minute": maghrib_m},
            "Isha": {"hour": isha_h, "minute": isha_m},
        }
    }



# =============================
# AZAN
# =============================
def play_azan(name):
    GPIO.output(RELAY_PIN, GPIO.HIGH) # Подава 3.3V
    time.sleep(5)
    audio_file = os.path.join(AUDIO_DIR, f"{name.lower()}.mp3")
    if os.path.exists(audio_file):
        subprocess.run(["mpg123", "-q", audio_file])

    time.sleep(5)
    GPIO.output(RELAY_PIN, GPIO.LOW)  # Подава 0V
    print(f"Krai na ezana .{name}", flush=True)


# =============================
# MAIN LOOP
# =============================
def main():
    now = read_ds3231()
    current_date = now.strftime("%Y-%m-%d")
    print(f"start {current_date}", flush=True)
    
    # Първоначално зареждане на данните
    if os.path.exists(PRAYER_FILE):
        with open(PRAYER_FILE, "r") as f:
            data = json.load(f)
        if data.get("date") != current_date:
            data = get_prayer_times(now.date())
            with open(PRAYER_FILE, "w") as f:
                json.dump(data, f, indent=4)
    else:
        data = get_prayer_times(now.date())
        with open(PRAYER_FILE, "w") as f:
            json.dump(data, f, indent=4)

    # ВАЖНО: Маркираме молитвите, които вече са минали за днес, 
    # за да не ги пускаме при рестарт на скрипта
    played_today = set()
    for name, t in data["times"].items():
        prayer_dt = now.replace(hour=t["hour"], minute=t["minute"], second=0, microsecond=0)
        if now > prayer_dt:
            played_today.add(name)

    while True:
        now = read_ds3231()
        today_str = now.strftime("%Y-%m-%d")

        # Смяна на деня
        if today_str != current_date:
            data = get_prayer_times(now.date())
            with open(PRAYER_FILE, "w") as f:
                json.dump(data, f, indent=4)
            played_today.clear()
            current_date = today_str

        for name, t in data["times"].items():
            if name == "Imsak": continue

            prayer_dt = now.replace(hour=t["hour"], minute=t["minute"], second=0, microsecond=0)

            # Проверка за съвпадение (точна минута)
            if name not in played_today:
                if now.hour == t["hour"] and now.minute == t["minute"]:
                    print(f"Startirane na azan za {name} v {now.strftime('%H:%M:%S')}", flush=True)
                    play_azan(name)
                    played_today.add(name)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
