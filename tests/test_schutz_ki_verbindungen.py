import json
import stat

from dbstudio import ki, sqlschutz, treiber, verbindungen


def test_schutz_erkennt_lesen_und_aendern():
    assert not sqlschutz.pruefe("SELECT * FROM t WHERE x = 'DELETE FROM t'").aendert
    assert not sqlschutz.pruefe("-- DROP TABLE t\nWITH a AS (SELECT 1) SELECT * FROM a").aendert
    p = sqlschutz.pruefe("UPDATE t SET a = 1")
    assert p.aendert and p.gefaehrlich and "WHERE" in p.warnungen[0]
    assert not sqlschutz.pruefe("UPDATE t SET a = 1 WHERE id = 3").gefaehrlich
    assert sqlschutz.pruefe("delete from t").gefaehrlich
    assert sqlschutz.pruefe("DROP TABLE t").gefaehrlich
    assert sqlschutz.pruefe("TRUNCATE t").gefaehrlich
    assert sqlschutz.pruefe("INSERT INTO t VALUES (1)").aendert
    assert sqlschutz.pruefe("WITH x AS (SELECT 1) DELETE FROM t").gefaehrlich
    assert sqlschutz.pruefe("EXPLAIN ANALYZE DELETE FROM t WHERE id=1").aendert
    assert not sqlschutz.pruefe("EXPLAIN SELECT 1").aendert


def test_verbindungen_ohne_passwort_in_datei(tmp_path, monkeypatch):
    gespeichert = {}
    import keyring
    monkeypatch.setattr(keyring, "set_password", lambda d, k, v: gespeichert.__setitem__((d, k), v))
    monkeypatch.setattr(keyring, "get_password", lambda d, k: gespeichert.get((d, k)))
    v = verbindungen.neu(name="Test", art="postgresql", host="db.example", passwort="geheim")
    verbindungen.setze_passwort(v, "geheim")
    verbindungen.speichern([v])
    datei = verbindungen.ordner() / "verbindungen.json"
    assert "geheim" not in datei.read_text()
    assert stat.S_IMODE(datei.stat().st_mode) == 0o600
    assert verbindungen.laden()[0]["host"] == "db.example"
    assert verbindungen.passwort(v) == "geheim"
    assert gespeichert[("db-studio", f"verbindung:{v['id']}")] == "geheim"


def test_schema_kontext_ohne_daten(tmp_path):
    t = treiber.oeffne({"art": "sqlite", "datei": str(tmp_path / "k.db")})
    t.abfrage("CREATE TABLE kunde (id INTEGER PRIMARY KEY, email TEXT)")
    t.abfrage("INSERT INTO kunde VALUES (1, 'geheim@beispiel.example')")
    k = ki.schema_kontext(t, "main")
    assert "kunde(id INTEGER PK, email TEXT)" in k and "geheim" not in k
    assert "geheim@beispiel.example" in ki.schema_kontext(t, "main", beispielzeilen=2)


def test_sql_aus_antwort():
    assert ki.sql_aus_antwort("Hier:\n```sql\nSELECT 1;\n```\nfertig") == "SELECT 1;"
    assert ki.sql_aus_antwort("kein code") == ""


def test_ki_aufrufe_gehen_an_den_anbieter(monkeypatch):
    gesehen = {}

    def falsch_ollama(modell, nutzer, url=ki.OLLAMA_URL):
        gesehen["modell"], gesehen["nutzer"] = modell, nutzer
        return "```sql\nSELECT 1\n```"
    monkeypatch.setattr(ki, "_ollama", falsch_ollama)
    antwort = ki.frage("ollama:qwen", "fehler", "KONTEXT", sql="SELEC 1", fehler="syntax error")
    assert gesehen["modell"] == "qwen" and "syntax error" in gesehen["nutzer"] and "KONTEXT" in gesehen["nutzer"]
    assert ki.sql_aus_antwort(antwort) == "SELECT 1"


def test_claude_api_ohne_schluessel(monkeypatch):
    monkeypatch.setattr(ki, "api_schluessel", lambda: None)
    try:
        ki.frage("claude-api", "sql", "K", text="alle kunden")
    except ki.KIFehler as e:
        assert "Schlüssel" in str(e)
    else:
        raise AssertionError("erwartet KIFehler")


def test_einstellungen(tmp_path):
    verbindungen.setze_einstellungen({"thema": "hell"})
    assert verbindungen.einstellungen()["thema"] == "hell"
    assert json.loads((verbindungen.ordner() / "einstellungen.json").read_text())["thema"] == "hell"
