# AI Homework Checker (`#vazifa`)

AI-powered homework review inside Telegram groups. When a student posts their
work with the `#vazifa` hashtag, the bot collects the material, sends it to
**Anthropic Claude**, and replies — as a reply to the student's message — with a
professional, bilingual (🇺🇿 Uzbek + 🇷🇺 Russian) review: strengths, concrete
errors, fixes, recommendations, and a score out of 10.

> UI copy is in Uzbek by project convention; this document is in English for
> contributors and operators.

---

## How it works

```
Student in group:  <photo | code | .zip | link | text>  +  #vazifa
        │
        ▼
homework_ai router  ──(group + #vazifa)──►  collect material
        │                                      (photo albums buffered)
        ▼
homework_extract.build_homework_payload()  ──►  Anthropic content blocks
        │                                         (text + base64 images)
        ▼
ai_service.analyze_homework()  ──►  Claude (vision + code review)
        │
        ▼
Reply to the student's message  (HTML-safe, chunked, UZ + RU)
```

### Supported submission formats

| Format | Handling |
|--------|----------|
| **Photo** (single or album) | Downloaded → base64 → Claude **vision** block |
| **Image document** (png/jpg/gif/webp) | Same as photo |
| **ZIP archive** | Code/text files extracted; `node_modules`, `.git`, `__pycache__`, `__MACOSX`, binaries skipped |
| **Code/text file** (html, css, js, ts, py, json, …) | Decoded as text |
| **Link** | Source fetched over HTTP(S); GitHub `blob` URLs converted to `raw`; SSRF-guarded |
| **Plain text / pasted code** | Used directly (the `#vazifa` tag is stripped) |

Multiple screenshots sent as a Telegram **album** are buffered by
`media_group_id` and analyzed together in a single request.

---

## Setup (required)

Two steps beyond setting the environment variable are mandatory:

1. **Disable group privacy in BotFather** — otherwise the bot cannot see
   files/photos in groups:
   > @BotFather → `/setprivacy` → select the bot → **Disable**

2. **Set the API key** in your environment / hosting secrets:
   > `ANTHROPIC_API_KEY=sk-ant-...` (from <https://console.anthropic.com> → API Keys)

   - **Railway:** Service → *Variables* → `ANTHROPIC_API_KEY` (auto-redeploys).
   - **Render:** Settings → *Environment* → `ANTHROPIC_API_KEY`.
   - **Local:** add it to `.env`.

Never commit the key — keep it only in environment variables.

---

## Configuration

All settings live in `config.py` (prefix `AI_`). Only `ANTHROPIC_API_KEY` is
required; everything else has sensible defaults.

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | **Required.** Anthropic API key. |
| `AI_HOMEWORK_ENABLED` | `1` | Master toggle for the feature (`0` to disable). |
| `AI_MODEL` | `claude-sonnet-4-6` | Model. Higher quality: `claude-opus-4-8` (~5× cost). |
| `AI_MAX_TOKENS` | `3500` | Max tokens in the analysis reply. |
| `AI_HOMEWORK_TRIGGERS` | `#vazifa,#uyvazifa,#дз,#homework` | Comma-separated trigger hashtags. |
| `AI_HOMEWORK_DAILY_LIMIT` | `5` | Per-student daily analysis limit (`0` = unlimited). |
| `AI_MAX_IMAGES` | `6` | Max images per submission. |
| `AI_MAX_IMAGE_MB` | `4.5` | Max size per image (MB). |
| `AI_MAX_ZIP_FILES` | `40` | Max files read from a ZIP. |
| `AI_MAX_FILE_CHARS` | `16000` | Max characters per file/snippet. |
| `AI_MAX_TOTAL_CHARS` | `60000` | Max total characters sent to the model. |
| `AI_MAX_LINK_BYTES` | `400000` | Max bytes fetched from a link. |

---

## Architecture

| File | Responsibility |
|------|----------------|
| `ai_service.py` | `AsyncAnthropic` wrapper. Teacher-persona system prompt (with prompt caching), `analyze_homework()`, vision + text. Lazy-imports `anthropic` so the bot runs even if the package/key is absent. |
| `homework_extract.py` | `build_homework_payload()` — turns Telegram messages into Anthropic content blocks. Telegram file download, ZIP extraction, link fetching (GitHub→raw, SSRF guard), size limits. |
| `handlers/homework_ai.py` | aiogram router. Group `#vazifa` filter, media-group buffering, per-student daily limit, status message, HTML-safe chunked reply. |
| `config.py` | `AI_*` settings. |

### Router ordering (important)

`homework_ai_router` is registered **before** `commands_router` in `main.py`.
`handlers/commands.py` has a catch-all `auto_save_group` handler that matches
every group message and stops propagation; if `homework_ai` were registered
after it, `#vazifa` messages would never reach this feature.

The `homework_ai` filter is narrow (group chat + `#vazifa`, or any album part),
so it does not interfere with private-chat flows or other group commands. For
non-homework albums it still records the chat (replacing the `auto_save_group`
side effect) and then exits without calling the model.

### Cost & abuse controls

- **Trigger-gated** — only runs on an explicit `#vazifa`, never on ordinary chat.
- **Per-student daily limit** (`AI_HOMEWORK_DAILY_LIMIT`, in-memory; resets on
  restart and at midnight by date key).
- **Material caps** — image count/size, ZIP file count, per-file and total
  character limits, link byte cap.
- **Prompt caching** — the static teacher persona is cached (`cache_control`).

### Security

- **SSRF guard** on link fetching: only `http`/`https`; hostnames that resolve
  to private, loopback, link-local, reserved, or multicast addresses (and
  `localhost`, `*.local`, `*.internal`) are refused.
- **HTML safety** — Claude is instructed to return plain text; the reply is
  additionally `html.escape()`-d before sending, so code containing `<`, `>`,
  `&` cannot break Telegram HTML parsing.
- The API key lives only in environment variables and is never logged.

---

## Usage

In any group where the bot is an admin with privacy disabled:

1. Post the homework — a screenshot, a code file, a `.zip`, a link, or pasted
   code — and include `#vazifa` in the caption or message text.
2. The bot replies “🔍 checking…”, then edits it into the full bilingual review.

Example reply shape:

```
📋 Baxtiyorov Sunnatilla — AI tahlil natijasi:

🇺🇿 ...
✅ Yaxshi tomonlar: ...
⚠️ Xato va kamchiliklar: ...
💡 Tavsiyalar: ...
⭐ Baho: 8/10

🇷🇺 ...
```

---

## Testing

The flow is verified offline with a mocked Anthropic client (no network, no
spend): request assembly, response parsing, ZIP filtering, URL extraction,
SSRF guard, GitHub-raw conversion, and the handler path (status reply, DB name
resolution, HTML escaping, chunking, daily-limit increment, not-configured and
limit-exceeded branches, album buffering).

A live end-to-end test additionally requires a real `ANTHROPIC_API_KEY`, a real
`BOT_TOKEN`, and a test group with privacy disabled.

---

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| Bot ignores `#vazifa` with a photo/file | Group privacy still **enabled** in BotFather. |
| Reply: “AI tekshiruvi hali sozlanmagan” | `ANTHROPIC_API_KEY` not set in the environment. |
| Reply: “Tekshirish uchun material topilmadi” | No supported material found (only the tag, or unsupported file type). |
| Reply: “Bugungi AI tekshiruv limiti tugadi” | `AI_HOMEWORK_DAILY_LIMIT` reached for that student today. |
| “Havola xavfsizlik sababli ochilmadi” | The link resolves to a private/loopback address (SSRF guard). |
