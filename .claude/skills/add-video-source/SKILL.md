# Skill: Add Video Source

TRIGGER: "aggiungi supporto per [fonte/canale/tipo di video]"

PRECONDIZIONI:
- Leggere `.claude/context/architecture.md` per capire il flusso attuale
- Sapere se la nuova fonte usa trascritti YouTube o un altro meccanismo

PASSI:
1. Identificare se la fonte è compatibile con `youtube-transcript-api` (canale YouTube) o richiede un nuovo step
2. Se è un canale YouTube: aggiungere logica di fetch playlist specifica in `get_playlist_video_ids()`
3. Se è una fonte esterna (podcast, blog): creare nuova funzione `get_transcript_from_[fonte]()` che rispetti la stessa interfaccia (`video_id: str → str | None`)
4. Aggiornare `EXTRACTION_PROMPT` se il formato del contenuto è diverso (es. testo scritto vs parlato)
5. Aggiornare `save_excel()` se ci sono nuovi campi da estrarre
6. Testare con `--limit 2` su un campione

OUTPUT ATTESO:
- Funzione di fetch aggiuntiva o modificata in `pipeline.py`
- Eventuale aggiornamento del prompt se necessario
- Funzionamento verificato con `--limit 2`

NOTE:
- Mantenere la cache-first logic: qualsiasi nuova fonte deve usare `TRANSCRIPTS_DIR` per caching
- Il campo `_video_url` deve sempre essere popolato con URL funzionante
