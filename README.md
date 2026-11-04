# YT-Console

Pipeline Python che legge una playlist YouTube di recensioni di console portatili, scarica i trascritti e li trasforma in dati strutturati con l'API Claude.

Per ogni video produce un oggetto con console, specifiche, design, performance, software, prezzo e verdetto. I campi non citati nel video restano vuoti.

## Output

- `output/reviews.json` — elenco dei JSON estratti
- `output/reviews.xlsx` — gli stessi dati in un foglio Excel
- `output/transcripts/{video_id}.txt` — cache dei trascritti. Se il file esiste non viene riscaricato

`output/` è gitignored.

## Requisiti

- Python 3.11 o successivo
- Chiave API Anthropic

## Installazione

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Variabili d'ambiente

| Variabile | Obbligatoria | Descrizione |
|---|---|---|
| `ANTHROPIC_API_KEY` | sì | Chiave API Anthropic usata per l'estrazione JSON |

Copia `.env.example` in `.env` e inserisci la chiave. All'avvio la pipeline legge `.env` solo se la variabile non è già nell'ambiente. In alternativa:

```bash
export ANTHROPIC_API_KEY="incolla-qui-la-chiave"
```

## Esecuzione

```bash
python pipeline.py --playlist "https://www.youtube.com/playlist?list=PLxxx"
python pipeline.py --playlist "https://www.youtube.com/playlist?list=PLxxx" --limit 3
python pipeline.py --playlist "https://www.youtube.com/playlist?list=PLxxx" --resume
```

- `--limit N` analizza solo i primi N video
- `--resume` salta i video già presenti in `output/reviews.json`
- Il JSON viene riscritto ogni 5 video e alla fine. L'Excel viene scritto alla fine

YouTube può rifiutare le richieste da alcuni indirizzi IP (per esempio i datacenter). In quel caso yt-dlp si ferma con un errore, oppure il singolo trascritto viene saltato e la pipeline prosegue con il video successivo.

## Test

Non serve una chiave API:

```bash
python -m unittest discover -s tests -v
```
