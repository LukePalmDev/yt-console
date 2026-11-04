"""Test della pipeline senza rete e senza credenziali."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import anthropic

import pipeline
from pipeline import (
    analyze_transcript,
    get_playlist_video_ids,
    get_transcript,
    load_dotenv,
    load_previous_results,
    main,
    parse_model_json,
    parse_playlist_lines,
    save_excel,
)


ROOT = Path(__file__).resolve().parents[1]
VIDEO_ID = "abcdefghijk"


class _Messages:
    def __init__(self, text: str):
        self.text = text
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(content=[SimpleNamespace(text=self.text)])


class _Client:
    def __init__(self, text: str):
        self.messages = _Messages(text)


class _RateLimit(anthropic.RateLimitError):
    def __init__(self):
        Exception.__init__(self, "rate limit")


class _AlwaysLimited:
    def __init__(self):
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        raise _RateLimit()


class PipelineTests(unittest.TestCase):
    def test_parse_playlist_lines_keeps_valid_ids_only(self):
        stdout = "\n".join([
            f"{VIDEO_ID}\tGame Boy",
            "NA\tmissing",
            "not-an-id\tbad",
            "short\ttoo short",
            f"{VIDEO_ID}\tSecondo\ttab",
        ])
        videos = parse_playlist_lines(stdout)
        self.assertEqual(videos, [
            {"id": VIDEO_ID, "title": "Game Boy"},
            {"id": VIDEO_ID, "title": "Secondo\ttab"},
        ])

    def test_yt_dlp_uses_module_and_checks_certificates(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=f"{VIDEO_ID}\tTitolo\n", stderr=""
        )
        with patch("pipeline.subprocess.run", return_value=completed) as run:
            videos = get_playlist_video_ids("https://www.youtube.com/playlist?list=PLtest")
        self.assertEqual(videos, [{"id": VIDEO_ID, "title": "Titolo"}])
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:3], [sys.executable, "-m", "yt_dlp"])
        self.assertNotIn("--no-check-certificates", cmd)

    def test_yt_dlp_failure_is_fatal(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="errore di rete"
        )
        with patch("pipeline.subprocess.run", return_value=completed):
            with self.assertRaises(RuntimeError) as ctx:
                get_playlist_video_ids("https://www.youtube.com/playlist?list=PLtest")
        self.assertIn("errore di rete", str(ctx.exception))

    def test_invalid_video_id_is_not_used_as_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("pipeline.TRANSCRIPTS_DIR", Path(tmp)):
                self.assertIsNone(get_transcript("../etc/passwd"))
            self.assertEqual(list(Path(tmp).rglob("*")), [])

    def test_transcript_cache_skips_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / f"{VIDEO_ID}.txt"
            cache.write_text("già in cache", encoding="utf-8")
            with patch("pipeline.TRANSCRIPTS_DIR", Path(tmp)):
                with patch("pipeline.YouTubeTranscriptApi") as api:
                    text = get_transcript(VIDEO_ID)
            api.assert_not_called()
        self.assertEqual(text, "già in cache")

    def test_parse_model_json_strips_markdown_and_preamble(self):
        raw = "Ecco il risultato:\n```json\n{\"voto\": 1}\n```\nfine"
        self.assertEqual(parse_model_json(raw), {"voto": 1})

    def test_braces_in_transcript_do_not_break_prompt(self):
        client = _Client(json.dumps({"console": {"nome": "Game Boy"}, "verdetto": {"voto": "8/10"}}))
        data = analyze_transcript(client, {"id": VIDEO_ID, "title": "Titolo"}, "usa {questo} e }")
        content = client.messages.kwargs["messages"][0]["content"]
        self.assertIn("usa {questo} e }", content)
        self.assertIn('"nome": "nome completo della console"', content)
        self.assertEqual(data["_video_url"], f"https://www.youtube.com/watch?v={VIDEO_ID}")

    def test_rate_limit_stops_after_three_calls(self):
        client = _AlwaysLimited()
        with patch("pipeline.time.sleep") as sleep:
            result = analyze_transcript(client, {"id": VIDEO_ID, "title": "Titolo"}, "testo")
        self.assertIsNone(result)
        self.assertEqual(client.calls, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [60, 120])

    def test_save_excel_accepts_null_objects_and_string_lists(self):
        results = [{
            "_video_title": "Recensione",
            "_video_url": "https://www.youtube.com/watch?v=abcdefghijk",
            "console": None,
            "specifiche_tecniche": {"connettivita": "WiFi"},
            "verdetto": {"pro": "solida", "contro": None, "voto": 0},
            "software_giochi": {"titoli_citati": ["Tetris", None]},
            "meta": {"confronti_con": []},
        }]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reviews.xlsx"
            save_excel(results, path)
            from openpyxl import load_workbook
            sheet = load_workbook(path).active
            headers = [cell.value for cell in sheet[1]]
            row = {headers[i]: sheet[2][i].value for i in range(len(headers))}
        self.assertIsNone(row["Console"])
        self.assertEqual(row["Connettività"], "WiFi")
        self.assertEqual(row["Pro"], "solida")
        self.assertFalse(row["Contro"])
        self.assertEqual(row["Voto"], 0)
        self.assertEqual(row["Titoli Citati"], "Tetris")

    def test_load_previous_results_ignores_rows_without_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reviews.json"
            path.write_text(json.dumps([
                {"_video_id": VIDEO_ID, "console": None},
                {"console": {}},
                "rotto",
            ]), encoding="utf-8")
            results, ids = load_previous_results(path)
        self.assertEqual(len(results), 2)
        self.assertEqual(ids, {VIDEO_ID})

    def test_load_previous_results_rejects_non_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reviews.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_previous_results(path)

    def test_load_dotenv_does_not_override_or_print(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                '# commento\nexport KEEP_ME="gia-impostata"\nNEW_KEY=\'valore\'\n',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"KEEP_ME": "originale"}, clear=False):
                os.environ.pop("NEW_KEY", None)
                load_dotenv(env_file)
                self.assertEqual(os.environ["KEEP_ME"], "originale")
                self.assertEqual(os.environ["NEW_KEY"], "valore")
                os.environ.pop("NEW_KEY", None)

    def test_main_runs_without_network_and_saves_null_console(self):
        videos = [{"id": f"{i:011d}", "title": f"Video {i}"} for i in range(1, 6)]
        payload = json.dumps({"console": None, "verdetto": {"voto": 0, "pro": ["ok"]}})

        class FakeAnthropic:
            def __init__(self, api_key):
                self.messages = _Messages(payload)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            argv = ["pipeline.py", "--playlist", "https://www.youtube.com/playlist?list=PLtest"]
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-not-a-real-key"}, clear=False):
                with patch("sys.argv", argv):
                    with patch("pipeline.OUTPUT_DIR", out):
                        with patch("pipeline.TRANSCRIPTS_DIR", out / "transcripts"):
                            with patch("pipeline.time.sleep"):
                                with patch("pipeline.get_playlist_video_ids", return_value=videos):
                                    with patch("pipeline.get_transcript", return_value="trascritto di prova"):
                                        with patch("pipeline.anthropic.Anthropic", FakeAnthropic):
                                            main()
            saved = json.loads((out / "reviews.json").read_text(encoding="utf-8"))
            self.assertEqual(len(saved), 5)
            self.assertIsNone(saved[0]["console"])
            self.assertEqual(saved[0]["verdetto"]["voto"], 0)
            self.assertTrue((out / "reviews.xlsx").is_file())

            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-not-a-real-key"}, clear=False):
                with patch("sys.argv", argv + ["--resume"]):
                    with patch("pipeline.OUTPUT_DIR", out):
                        with patch("pipeline.TRANSCRIPTS_DIR", out / "transcripts"):
                            with patch("pipeline.time.sleep"):
                                with patch("pipeline.get_playlist_video_ids", return_value=videos):
                                    with patch("pipeline.get_transcript") as transcript:
                                        with patch("pipeline.anthropic.Anthropic", FakeAnthropic):
                                            main()
            transcript.assert_not_called()

    def test_cli_requires_api_key_without_calling_youtube(self):
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(ROOT / "pipeline.py"), "--playlist", "https://example.invalid/playlist"],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ANTHROPIC_API_KEY", result.stderr)
        self.assertNotIn("sk-", result.stderr)


if __name__ == "__main__":
    unittest.main()
