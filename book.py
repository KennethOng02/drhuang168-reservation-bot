#!/usr/bin/env python3
"""
Clinic reservation bot for drhuang168.com.tw
Automatically books an appointment at midnight when slots open.

Usage:
  python book.py              # waits until start_time then books
  python book.py --dry-run    # finds the slot but skips final submission
  python book.py --now        # starts immediately, ignores start_time
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.drhuang168.com.tw/dispensary"
FORM_URL = f"{BASE_URL}/form.php"
RESERVATION_URL = f"{BASE_URL}/reservation.php"
COMPLETE_URL = f"{BASE_URL}/reservation-complete.php"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": FORM_URL,
}

TIME_LABELS = {
    "am": ["08:00", "09:00"],
    "pm": ["14:30", "15:30"],
    "nt": ["18:00", "19:00"],
}


def load_config(path="config.json"):
    with open(path) as f:
        return json.load(f)


def wait_until(start_time_str: str):
    """Sleep until the given HH:MM:SS time today (or tomorrow if already past)."""
    now = datetime.now()
    h, m, s = map(int, start_time_str.split(":"))
    target = now.replace(hour=h, minute=m, second=s, microsecond=0)
    delta = (target - now).total_seconds()
    if delta <= 0:
        print(f"[*] start_time {start_time_str} already passed — starting immediately")
        return
    print(f"[*] Waiting until {start_time_str} ({int(delta)}s from now)...")
    # Print countdown every 10s for the last minute, then every second
    while True:
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0:
            break
        if remaining <= 10:
            print(f"    {remaining:.1f}s remaining...", end="\r", flush=True)
            time.sleep(0.2)
        elif remaining <= 60:
            print(f"    {int(remaining)}s remaining...", end="\r", flush=True)
            time.sleep(1)
        else:
            time.sleep(10)
    print()


def fetch_slots(session: requests.Session, target_date: str, doctors: list, time_of_day: str):
    """
    Fetch form.php and return list of matching available slots, sorted by doctor priority.
    Each slot is a dict: {date, id, csrf, token, doctor, time_label}
    """
    try:
        resp = session.get(FORM_URL, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [!] fetch_slots error: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    buttons = soup.select("a.reservetion-btn")

    if not buttons:
        return []

    slots = []
    for btn in buttons:
        date = btn.get("data-order", "")
        slot_id = btn.get("data-id", "")
        csrf = btn.get("data-csrf", "")
        token = btn.get("data-token", "")

        # Normalise date format: "2026-04-6" → "2026-04-06" for comparison
        # The site uses non-zero-padded dates; compare loosely
        if not _dates_match(date, target_date):
            continue

        # Doctor name is in the sibling h2.infoName inside the same parent div
        parent = btn.find_parent()
        doctor_tag = parent.find("h2", class_="infoName") if parent else None
        doctor = doctor_tag.get_text(strip=True) if doctor_tag else ""
        # Strip subtitle span text
        subtitle = doctor_tag.find("span") if doctor_tag else None
        if subtitle:
            doctor = doctor.replace(subtitle.get_text(strip=True), "").strip()

        if doctors and doctor not in doctors:
            continue

        # Find time label from sibling .sideWorld in the same column
        time_label = _find_time_label(soup, btn)

        if time_of_day != "any":
            prefixes = TIME_LABELS.get(time_of_day, [])
            if not any(time_label.startswith(p) for p in prefixes):
                continue

        priority = doctors.index(doctor) if doctor in doctors else 999
        slots.append({
            "date": date,
            "id": slot_id,
            "csrf": csrf,
            "token": token,
            "doctor": doctor,
            "time_label": time_label,
            "priority": priority,
        })

    slots.sort(key=lambda s: s["priority"])
    return slots


def _dates_match(site_date: str, target_date: str) -> bool:
    """
    Compare dates ignoring zero-padding differences.
    site_date may be "2026-04-6", target_date may be "2026-04-06" or "2026-4-6".
    """
    try:
        # Parse both and compare as date objects
        site_parts = site_date.split("-")
        target_parts = target_date.split("-")
        if len(site_parts) != 3 or len(target_parts) != 3:
            return False
        return (
            int(site_parts[0]) == int(target_parts[0])
            and int(site_parts[1]) == int(target_parts[1])
            and int(site_parts[2]) == int(target_parts[2])
        )
    except (ValueError, IndexError):
        return False


def _find_time_label(soup: BeautifulSoup, btn) -> str:
    """
    Try to determine the time label for the slot by looking at the column headers.
    The schedule is a flat list of .dayAreaAm/.dayAreaPm/.dayAreaNt divs inside .ibox divs.
    Time headers are .sideWorld elements in the first .ibox.
    """
    try:
        # Find all iboxes
        iboxes = soup.select("div.ibox")
        if not iboxes:
            return ""
        # First ibox contains time headers
        time_headers = [el.get_text(strip=True) for el in iboxes[0].select("p.sideWorld")]

        # Find which ibox our button is in
        btn_ibox = btn.find_parent("div", class_="ibox")
        if not btn_ibox:
            return ""

        # Find the column index of the button within its ibox
        day_areas = btn_ibox.find_all(
            "div", class_=lambda c: c and ("dayAreaAm" in c or "dayAreaPm" in c or "dayAreaNt" in c)
        )
        btn_parent = btn.find_parent(
            "div", class_=lambda c: c and ("dayAreaAm" in c or "dayAreaPm" in c or "dayAreaNt" in c)
        )
        if btn_parent in day_areas:
            col_idx = day_areas.index(btn_parent)
            if col_idx < len(time_headers):
                return time_headers[col_idx]
    except Exception:
        pass
    return ""


def select_slot(session: requests.Session, slot: dict):
    """
    POST to reservation.php to select the slot.
    Returns (success: bool, form_data: dict or None)
    """
    payload = {
        "datevalue": slot["date"],
        "value": slot["id"],
        "rostervalue": "0",
        "csrfvalue": slot["csrf"],
        "tokenvalue": slot["token"],
    }
    try:
        resp = session.post(RESERVATION_URL, data=payload, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [!] select_slot error: {e}")
        return False, None

    text = resp.text
    if "201001" in text or "錯誤" in text or "逾時" in text:
        print(f"  [!] select_slot rejected: server returned error")
        return False, None

    # Extract hidden fields from the returned patient form
    soup = BeautifulSoup(text, "html.parser")
    form = soup.find("form", id="reservationform")
    if not form:
        print(f"  [!] select_slot: no reservationform found in response")
        return False, None

    form_data = {}
    for hidden in form.find_all("input", type="hidden"):
        form_data[hidden.get("name")] = hidden.get("value", "")

    return True, form_data


def submit_reservation(session: requests.Session, form_data: dict, patient: dict, dry_run: bool):
    """
    POST to reservation-complete.php with patient details.
    Returns (success: bool, response_html: str)
    """
    payload = {
        **form_data,
        "identitynumber": patient["identity_number"],
        "username": patient["name"],
        "phonenumber": patient["phone"],
        "birthyears": str(patient["birth_year"]),
        "birthmonth": str(patient["birth_month"]),
        "birthbay": str(patient["birth_day"]),
    }

    if dry_run:
        print("  [DRY RUN] Would POST to reservation-complete.php with:")
        for k, v in payload.items():
            if k == "identitynumber":
                v = v[:3] + "***" + v[-2:]  # mask ID
            print(f"    {k} = {v}")
        return True, "<dry-run: no response>"

    try:
        resp = session.post(COMPLETE_URL, data=payload, headers={**HEADERS, "Referer": RESERVATION_URL}, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [!] submit_reservation error: {e}")
        return False, ""

    text = resp.text
    failed = any(kw in text for kw in ["201001", "錯誤", "逾時", "失敗"])
    return not failed, text


def save_confirmation(html: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(f"confirmation_{timestamp}.html")
    path.write_text(html, encoding="utf-8")
    return path


def notify_macos(message: str, title: str = "掛號機器人"):
    subprocess.run(
        ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
        check=False,
    )


def open_in_browser(path: Path):
    subprocess.run(["open", str(path)], check=False)


def main():
    parser = argparse.ArgumentParser(description="drhuang168 reservation bot")
    parser.add_argument("--dry-run", action="store_true", help="Find slot but skip final submission")
    parser.add_argument("--now", action="store_true", help="Start immediately, ignore start_time")
    parser.add_argument("--config", default="config.json", help="Path to config file")
    args = parser.parse_args()

    config = load_config(args.config)
    patient = config["patient"]
    prefs = config["preferences"]
    target_date = prefs["target_date"]
    doctors = prefs.get("doctors", [])
    time_of_day = prefs.get("time_of_day", "any")
    retry_interval = config.get("retry_interval_seconds", 8)
    start_time = config.get("start_time", "00:00:00")

    print(f"[*] Target date : {target_date}")
    print(f"[*] Doctors     : {', '.join(doctors) if doctors else 'any'}")
    print(f"[*] Time of day : {time_of_day}")
    print(f"[*] Retry every : {retry_interval}s")
    if args.dry_run:
        print("[*] DRY RUN mode — final submission will be skipped")

    if not args.now:
        wait_until(start_time)

    attempt = 0
    while True:
        attempt += 1
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Attempt {attempt} — fetching schedule...")

        session = requests.Session()
        slots = fetch_slots(session, target_date, doctors, time_of_day)

        if not slots:
            print(f"  No matching slots found. Retrying in {retry_interval}s...")
            time.sleep(retry_interval)
            continue

        slot = slots[0]
        print(f"  Found slot: {slot['doctor']} on {slot['date']} {slot['time_label']}")
        print(f"  Selecting slot (id={slot['id']})...")

        ok, form_data = select_slot(session, slot)
        if not ok:
            print(f"  Retrying in {retry_interval}s...")
            time.sleep(retry_interval)
            continue

        print(f"  Submitting patient details...")
        success, html = submit_reservation(session, form_data, patient, dry_run=args.dry_run)

        if success:
            print(f"\n[+] Reservation SUCCESS!")
            if not args.dry_run:
                path = save_confirmation(html)
                print(f"[+] Confirmation saved to {path}")
                open_in_browser(path)
                notify_macos(f"成功預約 {slot['doctor']} 醫師 {slot['date']} {slot['time_label']}")
            else:
                print("[+] Dry run complete — no actual booking was made.")
            sys.exit(0)
        else:
            print(f"  Submission failed. Retrying in {retry_interval}s...")
            time.sleep(retry_interval)


if __name__ == "__main__":
    main()
