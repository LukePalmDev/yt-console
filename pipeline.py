"""
Handheld Console Review Analyzer
---------------------------------
Estrae trascritti da una playlist YouTube e li analizza con Claude API.
Output: reviews.json + reviews.xlsx

Dipendenze:
    pip install -r requirements.txt

Uso:
    export ANTHROPIC_API_KEY="incolla-qui-la-chiave"
    python pipeline.py --playlist "https://www.youtube.com/playlist?list=PLxxx"
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
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
_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")

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


def load_dotenv(path: Path = Path(".env")) -> None:
    """Carica KEY=VALUE da un file .env senza sovrascrivere l'ambiente."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def _as_dict(value: object) -> dict:
    """Ritorna value se è un dict, altrimenti un dict vuoto."""
    return value if isinstance(value, dict) else {}


def _as_str_list(value: object) -> list[str]:
    """Normalizza un campo lista (o una stringa) in lista di stringhe."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and item != ""]
    return [str(value)]


def parse_playlist_lines(stdout: str) -> list[dict]:
    """Converte l'output di yt-dlp in una lista di {id, title}."""
    videos = []
    for line in stdout.splitlines():
        if "\t" not in line:
            continue
        vid_id, title = line.split("\t", 1)
        vid_id = vid_id.strip()
        title = title.strip()
        if not _VIDEO_ID_RE.fullmatch(vid_id):
            continue
        videos.append({"id": vid_id, "title": title})
    return videos


def parse_model_json(raw: str) -> dict:
    """Estrae l'oggetto JSON dalla risposta del modello, anche con markdown."""
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```", 2)
        text = parts[1] if len(parts) > 1 else text
        stripped = text.lstrip()
        if stripped.lower().startswith("json"):
            text = stripped[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end < start:
        raise json.JSONDecodeError("Nessun oggetto JSON nella risposta", text, 0)
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise json.JSONDecodeError("La risposta JSON non è un oggetto", text, start)
    return data


def load_previous_results(path: Path) -> tuple[list[dict], set[str]]:
    """Carica i risultati già salvati per --resume."""
    if not path.exists():
        return [], set()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path} non è JSON valido") from exc
    if not isinstance(loaded, list):
        raise RuntimeError(f"{path} non è una lista JSON")
    results = [item for item in loaded if isinstance(item, dict)]
    processed_ids = {
        item["_video_id"]
        for item in results
        if isinstance(item.get("_video_id"), str)
    }
    return results, processed_ids


# ─────────────────────────────────────────────
# STEP 1 — Fetch video IDs dalla playlist
# ─────────────────────────────────────────────
def get_playlist_video_ids(playlist_url: str) -> list[dict]:
    """Usa yt-dlp per estrarre tutti i video ID e titoli dalla playlist."""
    print(f"📋 Fetching playlist: {playlist_url}")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "yt_dlp",
            "--flat-playlist",
            "--print",
            "%(id)s\t%(title)s",
            "--no-warnings",
            playlist_url,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp error: {result.stderr.strip()}")

    videos = parse_playlist_lines(result.stdout)
    print(f"✅ Trovati {len(videos)} video")
    return videos


# ─────────────────────────────────────────────
# STEP 2 — Scarica trascritto
# ─────────────────────────────────────────────
def get_transcript(video_id: str, languages: list[str] | None = None) -> str | None:
    """Scarica il trascritto di un video. Prova prima IT, poi EN."""
    if languages is None:
        languages = ["it", "en", "en-US", "en-GB"]

    if not _VIDEO_ID_RE.fullmatch(video_id):
        print("  ⚠️  ID video non valido, salto")
        return None

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = TRANSCRIPTS_DIR / f"{video_id}.txt"
    if cache_path.exists():
        cached = cache_path.read_text(encoding="utf-8").strip()
        if cached:
            return cached
        cache_path.unlink()

    api = YouTubeTranscriptApi()
    try:
        transcript = api.fetch(video_id, languages=languages)
        text = " ".join(entry.text for entry in transcript).strip()
        if not text:
            print(f"  ⚠️  Trascritto vuoto per {video_id}")
            return None
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

    # format() systema le graffe dello schema. Il trascritto si concatena dopo,
    # altrimenti una parentesi nel parlato rompe il prompt o viene raddoppiata.
    prompt = EXTRACTION_PROMPT.format(transcript="{transcript}").replace("{transcript}", transcript)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        data = parse_model_json(response.content[0].text)
        data["_video_id"] = video["id"]
        data["_video_title"] = video["title"]
        data["_video_url"] = f"https://www.youtube.com/watch?v={video['id']}"
        return data

    except json.JSONDecodeError as e:
        print(f"  ❌ JSON parse error per {video['id']}: {e}")
        return None
    except anthropic.RateLimitError:
        if _retries >= 2:
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
def save_json(results: list[dict], path: Path) -> None:
    """Serializza la lista dei risultati su disco."""
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 JSON salvato: {path}")


def save_excel(results: list[dict], path: Path) -> None:
    """Appiattisce i dati nested per un Excel leggibile."""
    rows = []
    for r in results:
        if not isinstance(r, dict):
            continue
        c = _as_dict(r.get("console"))
        s = _as_dict(r.get("specifiche_tecniche"))
        d = _as_dict(r.get("design_ergonomia"))
        p = _as_dict(r.get("performance"))
        sw = _as_dict(r.get("software_giochi"))
        pv = _as_dict(r.get("prezzo_valore"))
        v = _as_dict(r.get("verdetto"))
        m = _as_dict(r.get("meta"))

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
            "Connettività": ", ".join(_as_str_list(s.get("connettivita"))),
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
            "Titoli Citati": ", ".join(_as_str_list(sw.get("titoli_citati"))),
            # Prezzo
            "Prezzo Lancio": pv.get("prezzo_lancio"),
            "Rapporto Q/P": pv.get("rapporto_qualita_prezzo"),
            # Verdetto
            "Pro": " | ".join(_as_str_list(v.get("pro"))),
            "Contro": " | ".join(_as_str_list(v.get("contro"))),
            "Voto": v.get("voto"),
            "Per Chi È": v.get("per_chi_e"),
            "Sintesi Finale": v.get("sintesi_finale"),
            # Meta
            "Tono Recensore": m.get("tono_recensore"),
            "Confronti Con": ", ".join(_as_str_list(m.get("confronti_con"))),
        })

    df = pd.DataFrame(rows)
    df.to_excel(path, index=False, engine="openpyxl")
    print(f"📊 Excel salvato: {path}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Analizza playlist di recensioni handheld")
    parser.add_argument("--playlist", required=True, help="URL della playlist YouTube")
    parser.add_argument("--limit", type=int, default=None, help="Analizza solo i primi N video (test)")
    parser.add_argument("--resume", action="store_true", help="Riprendi da dove si era interrotto")
    args = parser.parse_args()

    load_dotenv()

    # Setup directories
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    # Carica risultati precedenti se si riprende
    results_path = OUTPUT_DIR / "reviews.json"
    results: list[dict] = []
    processed_ids: set[str] = set()
    if args.resume and results_path.exists():
        results, processed_ids = load_previous_results(results_path)
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
        else:
            print(f"\n[{i}/{total}] 🎮 {video['title'][:70]}")

            # Trascritto
            transcript = get_transcript(vid_id)
            if not transcript:
                print("  ⚠️  Trascritto non disponibile, salto")
            else:
                print(f"  📝 Trascritto: {len(transcript):,} caratteri")

                # Analisi Claude
                print("  🤖 Analisi Claude...")
                data = analyze_transcript(client, video, transcript)
                if data:
                    console_name = _as_dict(data.get("console")).get("nome") or "N/D"
                    voto = _as_dict(data.get("verdetto")).get("voto")
                    if voto is None or voto == "":
                        voto = "N/D"
                    print(f"  ✅ {console_name} | Voto: {voto}")
                    results.append(data)
                    processed_ids.add(vid_id)
                else:
                    print("  ❌ Analisi fallita")

                time.sleep(DELAY_BETWEEN_CALLS)

        # Salvataggio incrementale ogni 5 video e all'ultimo
        if results and (i % 5 == 0 or i == total):
            save_json(results, results_path)

    # Output finale
    if results:
        save_json(results, results_path)
        save_excel(results, OUTPUT_DIR / "reviews.xlsx")
        print(f"\n🏁 Completato! {len(results)}/{total} video analizzati con successo")
        print("   → output/reviews.json")
        print("   → output/reviews.xlsx")
    else:
        print("\n⚠️  Nessun risultato prodotto")


if __name__ == "__main__":
    main()
