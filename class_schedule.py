"""
class_schedule.py — Guruhlar dars jadvali (hardcoded).

ODD  = Dushanba, Chorshanba, Juma   (weekday: 0, 2, 4)
EVEN = Seshanba, Payshanba, Shanba  (weekday: 1, 3, 5)
Yakshanba (6) — dars yo'q.
"""

CLASS_SCHEDULE: dict[str, dict[str, str]] = {
    "ODD": {   # Dushanba, Chorshanba, Juma
        "nF-2803":  "14:00",
        "nF-2749":  "15:10",
        "2997-Pro": "16:20",
        "nF-2941":  "17:30",
        "nF-2694":  "18:40",
    },
    "EVEN": {  # Seshanba, Payshanba, Shanba
        "nF-2957":   "09:00",
        "nFPro-120": "10:10",
        "nF-2506":   "14:00",
        "2996-Pro":  "15:10",
    },
}
