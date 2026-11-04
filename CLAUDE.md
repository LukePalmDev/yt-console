# YT-Console — Handheld Console Review Analyzer

## Contesto rapido
Pipeline Python che estrae trascritti da playlist YouTube e li analizza con Claude API.
Input: URL playlist YouTube con video-recensioni di console portatili.
Output: `output/reviews.json` + `output/reviews.xlsx` con dati strutturati per ogni console recensita.

## Come usarmi
- Per iniziare una sessione: leggi `.claude/context/core.md`
- Per decisioni architetturali: chiedi di caricare `.claude/context/architecture.md`
- Per stile e pattern di codice: `.claude/context/conventions.md`

## File di contesto disponibili
- `core.md` — stack, regole critiche, entry point
- `architecture.md` — flusso dati, responsabilità moduli, decisioni prese
- `conventions.md` — naming, pattern, error handling

## Struttura
```
pipeline.py          ← unico entry point, tutto il codice
output/              ← gitignored, generato a runtime
  transcripts/       ← cache trascritti per video ID
  reviews.json       ← risultati aggregati
  reviews.xlsx       ← export Excel appiattito
```

## Esecuzione
```bash
export ANTHROPIC_API_KEY="incolla-qui-la-chiave"
pip install -r requirements.txt
python pipeline.py --playlist "https://www.youtube.com/playlist?list=PLxxx"
python pipeline.py --playlist "..." --limit 3          # test su 3 video
python pipeline.py --playlist "..." --resume           # riprende da dove era
```
