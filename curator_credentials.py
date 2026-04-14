"""
curator_credentials.py - Kurator loginlarini tashqi secret fayldan yuklaydi.
"""

from secrets_loader import load_json_mapping

CURATORS: dict[str, dict] = load_json_mapping(
    env_json_key="CURATORS_JSON",
    env_file_key="CURATORS_FILE",
    default_filename="curators.json",
)
