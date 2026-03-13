# Core — YT-Console

## Stack
- Python 3.11+, single-file pipeline (`pipeline.py`)
- `yt-dlp` → estrae video IDs e titoli dalla playlist (via subprocess)
- `youtube-transcript-api` → scarica trascritti (con cache locale in `output/transcripts/`)
- `anthropic` SDK → Claude `claude-sonnet-4-6` per estrazione strutturata JSON
- `pandas` + `openpyxl` → export Excel appiattito

## Regole critiche (non violare mai)
1. **Il modello è `claude-sonnet-4-6`** — non usare alias con date (es. `-20250514`).
2. **La cache trascritti è sacra** — non cancellare `output/transcripts/`. Ogni file è `{video_id}.txt`. Se esiste, non ri-scaricare.
3. **Salvataggio incrementale** — `save_json()` viene chiamato ogni 5 video e al termine. Non spostare questa logica fuori dal loop.

## Entry point
```bash
python pipeline.py --playlist "<URL>" [--limit N] [--resume]
```

## File on-demand
- `architecture.md` — flusso completo, schema JSON di output, decisioni prese
- `conventions.md` — naming, error handling, pattern da seguire
