"""
Handheld Console Review Analyzer
---------------------------------
Estrae trascritti da una playlist YouTube e li analizza con Claude API.
Output: reviews.json + reviews.xlsx

Dipendenze:
    pip install yt-dlp youtube-transcript-api anthropic pandas openpyxl

Uso:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python pipeline.py --playlist "https://www.youtube.com/playlist?list=PLxxx"
"""

import os
import json
import time
import argparse
import subprocess
from pathlib import Path

import anthropic
import pandas as pd
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
OUTPUT_DIR = Path("output")
TRANSCRIPTS_DIR = OUTPUT_DIR / "transcripts"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2000
DELAY_BETWEEN_CALLS = 2  # secondi, per evitare rate limiting

SYSTEM_PROMPT = """Sei un assistente esperto di console portatili e videogiochi.
Analizzi trascritti di video-recensioni e restituisci SOLO un oggetto JSON valido, senza testo aggiuntivo, senza markdown, senza backtick.
Sii preciso nelle informazioni tecniche e fedele al tono del recensore."""

EXTRACTION_PROMPT = """Analizza questo trascritto di una recensione di console portatile ed estrai tutte le informazioni nel seguente schema JSON.
Se un campo non è menzionato nel video, usa null.
Per i campi di testo, usa la lingua italiana.

Schema JSON richiesto:
{{
  "console": {{
    "nome": "nome completo della console",
    "produttore": "es. Nintendo, Sony, Sega, Atari...",
    "anno_uscita": numero o null,
    "generazione": "es. 8-bit, 16-bit, 32-bit, moderna...",
    "paese_origine": "es. Giappone, USA..."
  }},
  "specifiche_tecniche": {{
    "cpu": "descrizione CPU/SoC",
    "ram": "quantità RAM",
    "display": "tipo, risoluzione, dimensione pollici",
    "batteria": "capacità mAh o durata ore",
    "storage": "interno + slot espansione",
    "connettivita": ["lista: WiFi, Bluetooth, USB-C, ecc."],
    "audio": "altoparlanti, jack cuffie, ecc.",
    "altro": "sensori, giroscopio, NFC, ecc."
  }},
  "design_ergonomia": {{
    "materiali": "descrizione materiali scocca",
    "peso_grammi": numero o null,
    "dimensioni": "LxHxP mm se menzionate",
    "form_factor": "es. clamshell, slate, landscape, verticale...",
    "giudizio_recensore": "sintesi del giudizio del recensore sul design (2-3 frasi)"
  }},
  "performance": {{
    "fluidita": "descrizione fluidità/frame rate",
    "caricamenti": "velocità di caricamento giochi",
    "surriscaldamento": "problemi termici se menzionati",
    "autonomia_reale": "autonomia reale in ore",
    "giudizio_recensore": "sintesi del giudizio sulle performance (2-3 frasi)"
  }},
  "software_giochi": {{
    "os": "sistema operativo / interfaccia",
    "libreria": "descrizione della libreria disponibile",
    "retrocompatibilita": "compatibilità con generazioni precedenti",
    "titoli_citati": ["lista dei titoli di giochi menzionati"],
    "giudizio_recensore": "giudizio sulla libreria e software (2-3 frasi)"
  }},
  "prezzo_valore": {{
    "prezzo_lancio": "prezzo al lancio con valuta",
    "prezzo_attuale": "prezzo attuale se menzionato",
    "rapporto_qualita_prezzo": "giudizio del recensore (1-2 frasi)"
  }},
  "verdetto": {{
    "pro": ["lista dei punti di forza evidenziati"],
    "contro": ["lista dei punti deboli evidenziati"],
    "voto": "voto numerico o testuale se assegnato (es. 8/10, A-, Consigliato...)",
    "per_chi_e": "a chi si rivolge questa console secondo il recensore",
    "sintesi_finale": "riassunto del verdetto finale del recensore (3-5 frasi)",
    "citazione_notevole": "frase più significativa del recensore tra virgolette"
  }},
  "meta": {{
    "tono_recensore": "es. entusiasta, critico, neutro, nostalgico...",
    "focus_principale": "aspetto su cui il video si concentra maggiormente",
    "confronti_con": ["altre console con cui viene confrontata"]
  }}
}}

TRASCRITTO:
{transcript}"""


# ─────────────────────────────────────────────
# STEP 1 — Fetch video IDs dalla playlist
# ─────────────────────────────────────────────
def get_playlist_video_ids(playlist_url: str) -> list[dict]:
    """Usa yt-dlp per estrarre tutti i video ID e titoli dalla playlist."""
    print(f"📋 Fetching playlist: {playlist_url}")
    result = subprocess.run(
        [
            "yt-dlp",
            "--flat-playlist",
            "--print", "%(id)s\t%(title)s",
            "--no-warnings",
            "--no-check-certificates",
            playlist_url,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp error: {result.stderr}")

    videos = []
    for line in result.stdout.strip().split("\n"):
        if "\t" in line:
            vid_id, title = line.split("\t", 1)
            videos.append({"id": vid_id.strip(), "title": title.strip()})

    print(f"✅ Trovati {len(videos)} video")
    return videos


# ─────────────────────────────────────────────
# STEP 2 — Scarica trascritto
# ─────────────────────────────────────────────
def get_transcript(video_id: str, languages: list[str] = None) -> str | None:
    """Scarica il trascritto di un video. Prova prima IT, poi EN."""
    if languages is None:
        languages = ["it", "en", "en-US", "en-GB"]

    cache_path = TRANSCRIPTS_DIR / f"{video_id}.txt"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    api = YouTubeTranscriptApi()
    try:
        transcript = api.fetch(video_id, languages=languages)
        text = " ".join([entry.text for entry in transcript])
        cache_path.write_text(text, encoding="utf-8")
        return text
    except (TranscriptsDisabled, NoTranscriptFound):
        print(f"  ⚠️  Nessun trascritto disponibile per {video_id}")
        return None
    except Exception as e:
        print(f"  ⚠️  Errore trascritto {video_id}: {e}")
        return None


# ─────────────────────────────────────────────
# STEP 3 — Analisi con Claude
# ─────────────────────────────────────────────
def analyze_transcript(client: anthropic.Anthropic, video: dict, transcript: str, _retries: int = 0) -> dict | None:
    """Manda il trascritto a Claude e ottieni JSON strutturato."""
    # Tronca il trascritto se troppo lungo (lascia ~100k token di spazio)
    max_chars = 120_000
    if len(transcript) > max_chars:
        transcript = transcript[:max_chars] + "\n[TRASCRITTO TRONCATO]"

    prompt = EXTRACTION_PROMPT.format(transcript=transcript)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Pulizia in caso di markdown residuo
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip().rstrip("```").strip()

        data = json.loads(raw)
        data["_video_id"] = video["id"]
        data["_video_title"] = video["title"]
        data["_video_url"] = f"https://www.youtube.com/watch?v={video['id']}"
        return data

    except json.JSONDecodeError as e:
        print(f"  ❌ JSON parse error per {video['id']}: {e}")
        return None
    except anthropic.RateLimitError:
        if _retries >= 3:
            print(f"  ❌ Rate limit persistente dopo 3 tentativi per {video['id']}, salto")
            return None
        wait = 60 * (2 ** _retries)
        print(f"  ⏳ Rate limit raggiunto, attendo {wait}s... (tentativo {_retries + 1}/3)")
        time.sleep(wait)
        return analyze_transcript(client, video, transcript, _retries + 1)
    except Exception as e:
        print(f"  ❌ Errore Claude per {video['id']}: {e}")
        return None


# ─────────────────────────────────────────────
# STEP 4 — Salva JSON + Excel
# ─────────────────────────────────────────────
def save_json(results: list[dict], path: Path):
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 JSON salvato: {path}")


def save_excel(results: list[dict], path: Path):
    """Appiattisce i dati nested per un Excel leggibile."""
    rows = []
    for r in results:
        c = r.get("console", {})
        s = r.get("specifiche_tecniche", {})
        d = r.get("design_ergonomia", {})
        p = r.get("performance", {})
        sw = r.get("software_giochi", {})
        pv = r.get("prezzo_valore", {})
        v = r.get("verdetto", {})
        m = r.get("meta", {})

        rows.append({
            # Meta video
            "Titolo Video": r.get("_video_title"),
            "URL": r.get("_video_url"),
            # Console
            "Console": c.get("nome"),
            "Produttore": c.get("produttore"),
            "Anno Uscita": c.get("anno_uscita"),
            "Generazione": c.get("generazione"),
            # Specs
            "CPU": s.get("cpu"),
            "RAM": s.get("ram"),
            "Display": s.get("display"),
            "Batteria": s.get("batteria"),
            "Storage": s.get("storage"),
            "Connettività": ", ".join(s.get("connettivita") or []),
            # Design
            "Peso (g)": d.get("peso_grammi"),
            "Form Factor": d.get("form_factor"),
            "Giudizio Design": d.get("giudizio_recensore"),
            # Performance
            "Giudizio Performance": p.get("giudizio_recensore"),
            "Autonomia Reale": p.get("autonomia_reale"),
            # Software
            "OS": sw.get("os"),
            "Giudizio Software": sw.get("giudizio_recensore"),
            "Titoli Citati": ", ".join(sw.get("titoli_citati") or []),
            # Prezzo
            "Prezzo Lancio": pv.get("prezzo_lancio"),
            "Rapporto Q/P": pv.get("rapporto_qualita_prezzo"),
            # Verdetto
            "Pro": " | ".join(v.get("pro") or []),
            "Contro": " | ".join(v.get("contro") or []),
            "Voto": v.get("voto"),
            "Per Chi È": v.get("per_chi_e"),
            "Sintesi Finale": v.get("sintesi_finale"),
            # Meta
            "Tono Recensore": m.get("tono_recensore"),
            "Confronti Con": ", ".join(m.get("confronti_con") or []),
        })

    df = pd.DataFrame(rows)
    df.to_excel(path, index=False, engine="openpyxl")
    print(f"📊 Excel salvato: {path}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Analizza playlist di recensioni handheld")
    parser.add_argument("--playlist", required=True, help="URL della playlist YouTube")
    parser.add_argument("--limit", type=int, default=None, help="Analizza solo i primi N video (test)")
    parser.add_argument("--resume", action="store_true", help="Riprendi da dove si era interrotto")
    args = parser.parse_args()

    # Setup directories
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    # Carica risultati precedenti se si riprende
    results_path = OUTPUT_DIR / "reviews.json"
    results = []
    processed_ids = set()
    if args.resume and results_path.exists():
        results = json.loads(results_path.read_text(encoding="utf-8"))
        processed_ids = {r["_video_id"] for r in results}
        print(f"▶️  Resume: già processati {len(processed_ids)} video")

    # Init Claude client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("Variabile ANTHROPIC_API_KEY non impostata")
    client = anthropic.Anthropic(api_key=api_key)

    # Fetch playlist
    videos = get_playlist_video_ids(args.playlist)
    if args.limit:
        videos = videos[:args.limit]

    # Processa ogni video
    total = len(videos)
    for i, video in enumerate(videos, 1):
        vid_id = video["id"]
        if vid_id in processed_ids:
            print(f"[{i}/{total}] ⏭️  Saltato (già processato): {video['title'][:60]}")
            continue

        print(f"\n[{i}/{total}] 🎮 {video['title'][:70]}")

        # Trascritto
        transcript = get_transcript(vid_id)
        if not transcript:
            print("  ⚠️  Trascritto non disponibile, salto")
            continue

        print(f"  📝 Trascritto: {len(transcript):,} caratteri")

        # Analisi Claude
        print("  🤖 Analisi Claude...")
        data = analyze_transcript(client, video, transcript)
        if data:
            console_name = data.get("console", {}).get("nome", "N/D")
            voto = data.get("verdetto", {}).get("voto", "N/D")
            print(f"  ✅ {console_name} | Voto: {voto}")
            results.append(data)
        else:
            print("  ❌ Analisi fallita")

        # Salvataggio incrementale ogni 5 video
        if i % 5 == 0 or i == total:
            save_json(results, results_path)

        time.sleep(DELAY_BETWEEN_CALLS)

    # Output finale
    if results:
        save_json(results, results_path)
        save_excel(results, OUTPUT_DIR / "reviews.xlsx")
        print(f"\n🏁 Completato! {len(results)}/{total} video analizzati con successo")
        print(f"   → output/reviews.json")
        print(f"   → output/reviews.xlsx")
    else:
        print("\n⚠️  Nessun risultato prodotto")


if __name__ == "__main__":
    main()
