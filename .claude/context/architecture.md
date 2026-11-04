# Architecture — YT-Console

## Flusso dati

```
URL Playlist YouTube
       │
       ▼
[STEP 1] get_playlist_video_ids()
  yt-dlp --flat-playlist → lista [{id, title}, ...]
       │
       ▼ (per ogni video)
[STEP 2] get_transcript()
  Cache check: output/transcripts/{video_id}.txt
  Se manca → YouTubeTranscriptApi().fetch() → salva cache → return text
       │
       ▼
[STEP 3] analyze_transcript()
  Prompt = EXTRACTION_PROMPT.format(transcript=text)
  Claude API (claude-sonnet-4-6, max_tokens=2000)
  JSON parse → aggiunge _video_id, _video_title, _video_url
  Rate limit: backoff esponenziale (60s, 120s, 240s), max 3 tentativi
       │
       ▼ (ogni 5 video + fine)
[STEP 4] save_json() + save_excel()
  output/reviews.json  ← lista di oggetti JSON nested
  output/reviews.xlsx  ← DataFrame appiattito (pd.json_normalize non usato,
                          appiattimento manuale per controllo colonne)
```

## Schema JSON di output per ogni video
Campi principali (vedi `EXTRACTION_PROMPT` in pipeline.py):
- `console` → nome, produttore, anno_uscita, generazione, paese_origine
- `specifiche_tecniche` → cpu, ram, display, batteria, storage, connettivita[], audio, altro
- `design_ergonomia` → materiali, peso_grammi, dimensioni, form_factor, giudizio_recensore
- `performance` → fluidita, caricamenti, surriscaldamento, autonomia_reale, giudizio_recensore
- `software_giochi` → os, libreria, retrocompatibilita, titoli_citati[], giudizio_recensore
- `prezzo_valore` → prezzo_lancio, prezzo_attuale, rapporto_qualita_prezzo
- `verdetto` → pro[], contro[], voto, per_chi_e, sintesi_finale, citazione_notevole
- `meta` → tono_recensore, focus_principale, confronti_con[]
- `_video_id`, `_video_title`, `_video_url` ← aggiunti dopo il parse

## Responsabilità moduli
| Funzione | Responsabilità |
|---|---|
| `get_playlist_video_ids()` | Chiama yt-dlp, ritorna lista dict |
| `get_transcript()` | Gestisce cache + download trascritto |
| `analyze_transcript()` | Claude API call + JSON parse + retry |
| `save_json()` | Serializza lista results → file |
| `save_excel()` | Appiattisce nested JSON → DataFrame → .xlsx |
| `main()` | Orchestrazione, argparse, loop, salvataggio incrementale |

## Decisioni architetturali
- **Single-file**: bassa complessità, tool monouso. Se cresce oltre 500 righe, separare in `src/`.
- **Subprocess yt-dlp** invece di API YouTube: evita OAuth e funziona con playlist pubbliche.
- **Cache trascritti su file**: i trascritti non cambiano nel tempo, la cache evita rate limiting di YouTube e rende il `--resume` efficiente.
- **Appiattimento manuale Excel**: `pd.json_normalize()` produce colonne con nomi tipo `console.nome` poco leggibili. L'appiattimento manuale permette nomi italiani e controllo esplicito.
- **Trascritto troncato a 120k char**: evita di superare il context window con trascritti molto lunghi.

## Decision log
Vedi `docs/decisions/` per ADR formali (Architecture Decision Records).
