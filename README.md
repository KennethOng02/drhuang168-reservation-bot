# drhuang168 Reservation Bot

Automatically books a clinic appointment at [黃禎憲皮膚科診所](https://www.drhuang168.com.tw) the moment slots open at midnight.

## How It Works

The clinic opens online reservations every night at 00:00 for the corresponding day one week later. Slots fill up instantly due to high demand, often crashing the server. This script:

1. Waits until `start_time` (default `00:00:00`)
2. Polls the schedule page every few seconds until your preferred doctor's slot appears
3. Immediately selects the slot and submits your patient details
4. Sends a macOS notification and opens the confirmation page on success

## Setup

```bash
cd drhuang168
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp config.example.json config.json
```

Edit `config.json` with your details (see [Configuration](#configuration) below). This file is gitignored — your personal info never gets committed.

## Usage

```bash
# Run normally — waits until start_time, then books
venv/bin/python book.py

# Start immediately, ignore start_time
venv/bin/python book.py --now

# Dry run — finds the slot but skips final submission
venv/bin/python book.py --dry-run --now

# Use a different config file
venv/bin/python book.py --config my_config.json
```

## Configuration

```json
{
  "patient": {
    "identity_number": "A123456789",
    "name": "王小明",
    "phone": "0912345678",
    "birth_year": 1990,
    "birth_month": 1,
    "birth_day": 1
  },
  "preferences": {
    "target_date": "2026-04-17",
    "doctors": ["黃禎憲"],
    "time_of_day": "any"
  },
  "retry_interval_seconds": 8,
  "start_time": "00:00:00"
}
```

| Field | Description |
|---|---|
| `target_date` | The appointment date you want, e.g. `"2026-04-17"` |
| `doctors` | Priority-ordered list of doctors. First available match wins. |
| `time_of_day` | `"am"` (08:00–12:00), `"pm"` (14:30–17:50), `"nt"` (18:00–22:00), or `"any"` |
| `retry_interval_seconds` | How often to retry when slots aren't available yet (default: `8`) |
| `start_time` | When to begin polling, in `HH:MM:SS` format (default: `"00:00:00"`) |

**Available doctors:** 黃禎憲、許宛騏、呂岳聰、何昱琳、蔡昌霖、鄭嵐心、吳鎮宇、黃千耀

## Typical Night-Before Workflow

1. Set `target_date` to the date one week from tomorrow
2. Run `venv/bin/python book.py` and leave the terminal open overnight
3. The script wakes at midnight, polls until 黃禎憲's slot appears, and books automatically
4. You'll receive a macOS notification and the confirmation page opens in your browser

## On Success

- macOS notification fires: `"成功預約 黃禎憲 醫師 ..."`
- Confirmation HTML saved as `confirmation_YYYYMMDD_HHMMSS.html` and opened in browser
