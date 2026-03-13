# Conventions — YT-Console

## Naming
- **File**: snake_case (`pipeline.py`)
- **Funzioni**: snake_case, verbo_oggetto (`get_transcript`, `save_excel`, `analyze_transcript`)
- **Costanti globali**: UPPER_SNAKE_CASE (`OUTPUT_DIR`, `MODEL`, `DELAY_BETWEEN_CALLS`)
- **Variabili locali**: snake_case corto e descrittivo (`vid_id`, `transcript`, `raw`)
- **Parametri privati/interni**: prefisso underscore (`_retries`)

## Struttura funzioni
Ogni funzione ha:
1. Docstring breve (una riga)
2. Parametri tipizzati (Python type hints)
3. Return type hint (incluso `| None` se può fallire)
4. Print di stato con emoji per tracciabilità a console

## Error handling
- **Errori attesi** (trascritto non disponibile, JSON malformato): cattura exception specifica, print `⚠️` o `❌`, ritorna `None`
- **Rate limit Claude**: backoff esponenziale (60s × 2^n), max 3 tentativi, poi ritorna `None` e si passa al video successivo
- **Errori fatali** (API key mancante, yt-dlp crash): `raise` con messaggio chiaro — non silenziare
- **Non usare bare `except:`** — sempre specificare l'eccezione

## Pattern da seguire
- **Cache-first**: controlla sempre se il file esiste prima di fare richieste di rete
- **Salvataggio incrementale**: non aspettare la fine per scrivere su disco
- **Fail gracefully per video**: un video fallito non blocca il resto della pipeline
- **`None` come sentinel**: le funzioni ritornano `None` in caso di fallimento non fatale; il chiamante controlla `if data:`

## Pattern da evitare
- **Ricorsione senza limite** per retry: usare `_retries` counter con max
- **f-string con slice non limitato**: usare `title[:60]` nei print per leggibilità console
- **`json.loads()` senza pulizia**: Claude può restituire markdown — pulire sempre prima del parse
- **Hardcoded percorsi stringa**: usare sempre `Path` oggetti, mai concatenazione stringa

## Logging / print
Convenzione emoji per output console:
- `📋` → fetch / enumerazione
- `✅` → successo
- `⚠️` → warning non fatale (trascritto mancante, ecc.)
- `❌` → errore (analisi fallita, JSON malformato)
- `⏳` → attesa (rate limit)
- `💾` → salvataggio file
- `📊` → output dati
- `🎮` → processing video
- `⏭️` → skip (già processato)
- `▶️` → resume
- `🏁` → completato
