# Architecture — YT-Console

> Documento di riferimento esterno. Per il contesto ottimizzato per Claude, vedi `.claude/context/architecture.md`.

## Overview

Pipeline Python monolitica che:
1. Estrae la lista di video da una playlist YouTube (via yt-dlp)
2. Scarica il trascritto di ogni video (youtube-transcript-api + cache locale)
3. Invia ogni trascritto a Claude API per estrarre dati strutturati in JSON
4. Aggrega i risultati in `output/reviews.json` e `output/reviews.xlsx`

## Diagramma flusso

```
Playlist URL → yt-dlp → [video_id, title] × N
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
             cache hit?          YouTubeTranscriptApi
             (*.txt esiste)      .fetch(video_id)
                    └─────────┬──────────┘
                              ▼
                        transcript (str)
                              │
                              ▼
                    Claude API (claude-sonnet-4-6)
                    EXTRACTION_PROMPT → JSON
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
              reviews.json         reviews.xlsx
              (incremental)        (fine pipeline)
```

## Componenti

### `pipeline.py`
Unico file sorgente. Contiene:
- Configurazione globale (costanti in cima)
- 4 step di processing come funzioni indipendenti
- `main()` come orchestratore

### `output/` (gitignored)
Generato a runtime:
- `transcripts/{video_id}.txt` — cache trascritti
- `reviews.json` — output principale, lista JSON
- `reviews.xlsx` — export Excel per analisi umana

## Decisioni chiave

| Decisione | Motivazione |
|---|---|
| Single file | Tool monouso, bassa complessità attuale |
| subprocess yt-dlp | Nessun OAuth, supporta playlist pubbliche |
| Cache trascritti su file | Evita re-download, abilita `--resume` |
| Appiattimento manuale Excel | Nomi colonne italiani e leggibili |
| Backoff esponenziale rate limit | Gestione robusta senza ricorsione infinita |

## ADR (Architecture Decision Records)
Vedi `docs/decisions/` per decisioni future da documentare formalmente.
