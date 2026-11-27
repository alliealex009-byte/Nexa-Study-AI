# NEXA STUDY AI

Open-source, self-hosted Telegram educational AI platform for **NEET UG** and **JEE (Main & Advanced)** students, powered by local **Ollama (`qwen2.5:3b`)** with zero paid AI APIs.

Built for **Oracle Cloud Free Tier ARM64 (`aarch64`, 2 OCPUs, 12 GB RAM, Ubuntu 24.04 LTS)** using **aiogram 3.34+** with **Telegram Bot API 9.4+ colored & premium-emoji inline sub-menus**, **Telegram Bot API 10.4+ interactive HTML Widgets (`sendWidget`)**, **10-year (2016–2025) NEET & JEE PYQ banks** working in **both Bot DM and Group Chats**, ARM64 Tesseract OCR, pure-Python BM25 NCERT RAG, SymPy math verification, and 500 MB-friendly MongoDB analytics.

---

## Features

- **10-Year (2016–2025) NEET & JEE PYQ Bank (DM + Group Chats)**:
  - Preloaded with verified 10-year (2016–2025) **NEET UG** (`data/pyq/neet_10yr_pyqs.json`) and **JEE Main / JEE Advanced** (`data/pyq/jee_10yr_pyqs.json`) questions across every year from 2016 to 2025.
  - Instant random prep commands in **both private DM and Telegram Group Chats**: `/random` (or `/prep`), `/neet`, `/jee`, and `/poll` (native Telegram Quiz Poll).
  - Includes `scripts/import_opensource_pyqs.py` to bulk-import thousands of additional PYQs from open-source HuggingFace datasets ([catchshubham/neet-dataset](https://huggingface.co/datasets/catchshubham/neet-dataset), [Reja1/jee-neet-benchmark](https://huggingface.co/datasets/Reja1/jee-neet-benchmark)) or local JSON files.
- **Telegram Bot API 9.4+ Premium Emoji & Colored Inline Sub-Menus**:
  - Uses native `InlineKeyboardButton.style` (`"primary"` blue, `"success"` green, `"danger"` red) and `InlineKeyboardButton.icon_custom_emoji_id` across the main menu and every subject/PYQ/quiz/widget sub-menu, plus `<tg-emoji>` HTML tags in messages.
  - Works out of the box with crisp Unicode fallbacks; when the bot owner has Telegram Premium (or a Fragment username), paste custom emoji IDs into `.env` (`PREMIUM_EMOJI_*`).
- **Telegram Bot API 10.4+ Interactive HTML Widgets (`sendWidget`)**:
  - Interactive **Progress Dashboard Widget**, **10-Year PYQ Flashcard Widget**, and **Pomodoro & Formula Quick-Flip Widget** via `/widget` or the main menu.
  - Every widget is validated against Telegram's `<= 32768 B` raw and `<= 4096 B` zlib level-9 limits and falls back gracefully to styled HTML cards when unavailable (e.g., in group chats or before rollout).
- **Subject-Specific AI Doubt Solver**: Biology (NCERT terminology & NEET traps), Chemistry (equations, mechanisms, physical chemistry), and Physics (given values, formulas, steps, SI units), with Simpler & Exam-Oriented modes. Use `/ask <question>` in group chats or type directly in DM.
- **Image Question Solver (ARM64 OCR)**: Upload cropped photos of printed or neat handwritten questions, equations, or labeled diagrams (`Pillow` + `tesseract-ocr`). Honestly asks for a clearer photo if OCR confidence is below threshold.
- **SymPy Mathematical Verification & Lightweight BM25 NCERT RAG**: Deterministic equation/arithmetic checking plus `<10 MB` RAM NCERT passage retrieval (`data/ncert/`).
- **Practice Quizzes, Timed Tests & Progress Analytics**: Subject-wise, chapter-wise, mixed 10-year mocks, 5-minute timed tests, weak-topic detection (`<60%` accuracy), and 500 MB MongoDB TTL indexing.

---

## Commands (DM & Group Chats)

| Command | Works In | Description |
| :--- | :--- | :--- |
| `/start`, `/menu` | DM & Group | Open colored premium-emoji main menu & subject sub-menus |
| `/random`, `/prep` | DM & Group | Random 10-year (2016–2025) NEET or JEE prep question |
| `/neet` | DM & Group | Random 10-year (2016–2025) NEET UG question |
| `/jee` | DM & Group | Random 10-year (2016–2025) JEE Main / Advanced question |
| `/poll [neet\|jee]` | DM & Group | Send a native Telegram Quiz Poll (best for study groups!) |
| `/widget` | DM (fallback in Group) | Launch Bot API 10.4 interactive HTML Widgets |
| `/ask <question>` | DM & Group | Ask AI a Biology, Chemistry, or Physics doubt |
| `/progress` | DM & Group | View accuracy, subject breakdown, weak topics & Progress Widget |
| `/help` | DM & Group | Show usage instructions |

---

## Quick Start on Ubuntu 24.04 ARM64 VPS (Termius / Android)

### 1. Verify Existing Ollama Container

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
docker network ls | grep nexa-net
curl -s http://127.0.0.1:11434/api/tags
```

### 2. Configure `.env`

```bash
cd ~/Nexa-Study-AI
cp .env.example .env
nano .env
```

Set `TELEGRAM_BOT_TOKEN`, `OLLAMA_BASE_URL=http://ollama:11434` (Docker) or `http://127.0.0.1:11434` (venv/systemd), optional `MONGODB_URI`, and optional `PREMIUM_EMOJI_*` IDs if your bot owner account has Telegram Premium.

### 3. Deploy with Docker Compose

```bash
docker compose up -d --build
docker compose logs -f nexa-bot
```

### 4. Expand 10-Year PYQs from Open-Source Datasets (Optional)

```bash
python3 scripts/import_opensource_pyqs.py --source huggingface --dataset catchshubham/neet-dataset --exam "NEET UG" --limit 250
```

### 5. Run Unit Tests

```bash
python3 -m unittest discover -s tests -v
```

### 6. Push to GitHub (`Nexa-pay/Nexa-Study-AI`)

```bash
git init
git branch -M main
git add .
git status   # Ensure .env is NOT listed
git commit -m "NEXA STUDY AI: 10-yr NEET/JEE PYQs, DM & group prep, OCR, Bot API 9.4 colored/premium menus & Bot API 10.4 widgets"
git remote add origin https://github.com/Nexa-pay/Nexa-Study-AI.git
git push -u origin main
```
