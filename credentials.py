"""
credentials.py - O'quvchi credentiallarini tashqi secret fayldan yuklaydi.
"""

from secrets_loader import load_json_mapping

MARS_CREDENTIALS: dict[str, dict] = load_json_mapping(
    env_json_key="STUDENT_CREDENTIALS_JSON",
    env_file_key="STUDENT_CREDENTIALS_FILE",
    default_filename="student_credentials.json",
)

MARS_GROUPS: list[str] = sorted(
    {str(cred.get("group", "")).strip() for cred in MARS_CREDENTIALS.values() if cred.get("group")}
)
