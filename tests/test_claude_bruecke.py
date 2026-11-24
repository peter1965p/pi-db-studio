"""KI-Brücke: nur erlaubte Adresse + richtiges Token, Weitergabe an Claude Code (hier Attrappe)."""
import threading
from http.server import ThreadingHTTPServer

import httpx
import pytest

from dbstudio import ki
from dbstudio.claude_bruecke import baue_handler

TOKEN = "t" * 32


@pytest.fixture
def bruecke():
    aufrufe = []

    def frage(modell, prompt):
        aufrufe.append((modell, prompt))
        if "kaputt" in prompt:
            raise ki.KIFehler("Claude meldet: kaputt")
        return "```sql\nSELECT 1\n```"

    def starte(erlaubt=("127.0.0.1",)):
        s = ThreadingHTTPServer(("127.0.0.1", 0), baue_handler(TOKEN, set(erlaubt), frage))
        threading.Thread(target=s.serve_forever, daemon=True).start()
        server.append(s)
        return f"http://127.0.0.1:{s.server_address[1]}"
    server = []
    yield starte, aufrufe
    for s in server:
        s.shutdown()


def test_weitergabe_und_ki_anbieter(bruecke, monkeypatch):
    starte, aufrufe = bruecke
    monkeypatch.setenv("DBSTUDIO_CLAUDE_BRUECKE_URL", starte())
    monkeypatch.setenv("DBSTUDIO_CLAUDE_BRUECKE_TOKEN", TOKEN)
    antwort = ki.frage("claude-bruecke", "sql", "Tabelle t(a int)", text="alles")
    assert ki.sql_aus_antwort(antwort) == "SELECT 1" and "Tabelle t" in aufrufe[0][1]
    with pytest.raises(ki.KIFehler, match="kaputt"):
        ki.frage("claude-bruecke", "sql", "kaputt", text="x")


def test_ablehnungen(bruecke):
    starte, aufrufe = bruecke
    url = starte()
    assert httpx.post(f"{url}/frage", json={"prompt": "x"}).status_code == 401
    assert httpx.post(f"{url}/frage", json={"prompt": "x"}, headers={"X-Bruecke-Token": "falsch"}).status_code == 401
    assert httpx.post(f"{url}/frage", json={"prompt": "x", "modell": "a; rm"}, headers={"X-Bruecke-Token": TOKEN}).status_code == 400
    assert httpx.post(f"{url}/anders", json={"prompt": "x"}, headers={"X-Bruecke-Token": TOKEN}).status_code == 404
    fremd = starte(erlaubt=("192.168.178.215",))
    assert httpx.post(f"{fremd}/frage", json={"prompt": "x"}, headers={"X-Bruecke-Token": TOKEN}).status_code == 403
    assert not aufrufe


def test_ohne_konfig(monkeypatch):
    monkeypatch.delenv("DBSTUDIO_CLAUDE_BRUECKE_URL", raising=False)
    with pytest.raises(ki.KIFehler, match="nicht eingerichtet"):
        ki.frage("claude-bruecke", "sql", "k", text="x")


def test_eigener_systemprompt_und_schema(monkeypatch):
    """Job Agent schickt Systemprompt und JSON-Schema mit; ohne die Felder bleibt alles wie bisher."""
    gesehen = []

    def mit_system(modell, system, prompt, schema):
        gesehen.append((modell, system, prompt, schema))
        return '{"ok": true}'
    s = ThreadingHTTPServer(("127.0.0.1", 0), baue_handler(TOKEN, {"127.0.0.1"}, lambda m, p: "alt", mit_system))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{s.server_address[1]}/frage"
        r = httpx.post(url, headers={"X-Bruecke-Token": TOKEN},
                       json={"prompt": "p", "system": "sys", "json_schema": {"type": "object"}, "modell": "claude-x"})
        assert r.status_code == 200 and r.json()["antwort"] == '{"ok": true}'
        assert gesehen == [("claude-x", "sys", "p", {"type": "object"})]
        r = httpx.post(url, headers={"X-Bruecke-Token": TOKEN}, json={"prompt": "p"})
        assert r.json()["antwort"] == "alt"
        r = httpx.post(url, headers={"X-Bruecke-Token": TOKEN}, json={"prompt": "p", "system": 5})
        assert r.status_code == 400
    finally:
        s.shutdown()
