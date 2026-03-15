"""
handlers/pending.py — Vaqtinchalik xotira.

Bot guruhga qo'shilganda shu yerda saqlanadi,
admin tasdiqlagunicha yoki o'tkazib yuborgancha.

{chat_id: group_title}
"""

pending_groups: dict[int, str] = {}
