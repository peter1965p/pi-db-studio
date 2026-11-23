"""EF-Core-Sicht auf ein Schema: Entitätsnamen (PascalCase, Einzahl), C#-Typen, Navigationen, DbContext-Export.

Reine Funktionen ohne Qt – testbar ohne Datenbankserver.
"""

from __future__ import annotations

import re

from . import erm
from .treiber import Spalte, generischer_typ

# Deutsche und englische Mehrzahl-Endungen -> Einzahl (Reihenfolge: längste zuerst)
_EINZAHL_REGELN = [
    ("nisse", "nis"), ("worte", "wort"), ("izen", "iz"), ("mente", "ment"), ("ichte", "icht"), ("kten", "kt"), ("eln", "el"), ("hen", "hen"),
    ("ungen", "ung"), ("heiten", "heit"), ("keiten", "keit"), ("schaften", "schaft"), ("ionen", "ion"),
    ("uerfe", "urf"), ("uege", "ug"), ("aege", "ag"), ("ies", "y"), ("sses", "ss"), ("xes", "x"),
    ("ches", "ch"), ("shes", "sh"), ("men", "ma"), ("nnen", "nn"), ("eien", "ei"), ("en", "e"),
    ("er", "er"), ("s", ""),
]
_UNVERAENDERT = {"daten", "status", "news", "series", "person", "fakten_alt", "data", "info", "analysis"}


def pascal(name: str) -> str:
    teile = [t for t in re.split(r"[^0-9A-Za-zÄÖÜäöüß]+|(?<=[a-z0-9])(?=[A-Z])", name) if t]
    erg = "".join(t[:1].upper() + t[1:] for t in teile) or "Tabelle"
    erg = erg.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("Ä", "Ae").replace("Ö", "Oe") \
        .replace("Ü", "Ue").replace("ß", "ss")
    return ("_" + erg) if erg[0].isdigit() else erg


def einzahl(wort: str) -> str:
    w = wort.lower()
    if w in _UNVERAENDERT or len(w) <= 3:
        return wort
    for endung, ersatz in _EINZAHL_REGELN:
        if w.endswith(endung) and len(w) - len(endung) >= 2:
            if endung in ("er", "hen"):  # „Nutzer“, „gesehen“: unverändert
                return wort
            return wort[: len(wort) - len(endung)] + ersatz
    return wort


def klassenname(tabelle: str) -> str:
    """firmen -> Firma, entwuerfe -> Entwurf, cv_stationen -> CvStation, OrderItems -> OrderItem."""
    teile = [t for t in re.split(r"[_\-\s]+", tabelle) if t]
    if not teile:
        return "Tabelle"
    teile[-1] = einzahl(teile[-1])
    return pascal("_".join(teile))


def mehrzahl_name(klasse: str, tabelle: str) -> str:
    """Name einer Sammlungs-Navigation: bevorzugt der Tabellenname in PascalCase (firmen -> Firmen)."""
    p = pascal(tabelle)
    return p if p != klasse else p + "Liste"


_CS = {
    "ganzzahl": "int", "grosse_ganzzahl": "long", "kommazahl": "double", "dezimal": "decimal", "wahrheitswert": "bool",
    "datum": "DateOnly", "zeitstempel": "DateTime", "zeit": "TimeOnly", "binaer": "byte[]", "json": "string",
    "uuid": "Guid", "text": "string",
}
_REFERENZTYPEN = {"string", "byte[]"}


def cs_typ(s: Spalte) -> str:
    """C#-Typ einer Spalte inkl. „?“ für nullbare Spalten (Nullable Reference Types eingeschaltet)."""
    roh = (s.typ or "").lower()
    if roh.startswith(("smallint", "int2", "tinyint")):
        basis = "short" if "tinyint" not in roh else "byte"
    elif roh in ("real", "float4") or roh.startswith("real"):
        basis = "float"
    elif "datetimeoffset" in roh or "with time zone" in roh or roh == "timestamptz":
        basis = "DateTimeOffset"
    elif roh.startswith("bit"):
        basis = "bool"
    elif roh.startswith(("vector", "tsvector")):
        basis = "string"
    else:
        basis = _CS.get(generischer_typ(s.typ or ""), "string")
    return basis + ("?" if s.nullbar and not s.pk else "")


def eigenschaft(name: str) -> str:
    return pascal(name)


def navigationen(m: erm.Modell) -> dict[str, list[tuple[str, str, bool]]]:
    """Tabelle -> [(Navigationsname, C#-Typ, ist_sammlung)], abgeleitet aus den Fremdschlüsseln."""
    erg: dict[str, list[tuple[str, str, bool]]] = {n: [] for n in m.tabellen}
    for f in m.fks:
        if f.tabelle not in m.tabellen or f.ziel not in m.tabellen:
            continue
        kind_k, eltern_k = klassenname(f.tabelle), klassenname(f.ziel)
        # Referenz am abhängigen Typ: Name aus FK-Spalte ohne „_id“/„Id“, sonst Klassenname
        basis = re.sub(r"(_id|Id|_ID)$", "", f.spalten[0]) if f.spalten else ""
        ref = pascal(basis) if basis and basis.lower() != f.spalten[0].lower() else eltern_k
        nullbar = any(s.nullbar for s in m.tabellen[f.tabelle].spalten if s.name in f.spalten)
        erg[f.tabelle].append((ref, eltern_k + ("?" if nullbar else ""), False))
        if m.kardinalitaet(f) == "1:1":
            erg[f.ziel].append((kind_k, kind_k + "?", False))
        else:
            erg[f.ziel].append((mehrzahl_name(kind_k, f.tabelle), f"ICollection<{kind_k}>", True))
    for n, liste in erg.items():  # doppelte Namen eindeutig machen
        gesehen: dict[str, int] = {}
        neu = []
        for name, typ, sammlung in liste:
            gesehen[name] = gesehen.get(name, 0) + 1
            neu.append((name if gesehen[name] == 1 else f"{name}{gesehen[name]}", typ, sammlung))
        erg[n] = neu
    return erg


def multiplizitaet(m: erm.Modell, f: erm.Fremdschluessel) -> tuple[str, str]:
    """(Hauptentität, abhängige Entität) wie EF/DGML: („1“|„0..1“, „*“|„0..1“|„1“)."""
    nullbar = any(s.nullbar for s in m.tabellen[f.tabelle].spalten if s.name in f.spalten)
    haupt = "0..1" if nullbar else "1"
    abh = "0..1" if m.kardinalitaet(f) == "1:1" else "*"
    return haupt, abh


def dbcontext(m: erm.Modell, namespace: str = "Daten", context: str = "AppDbContext") -> str:
    """C#-Quelltext: Entitätsklassen + DbContext mit Fluent-API (Tabellen, Schlüssel, Beziehungen)."""
    nav = navigationen(m)
    z: list[str] = ["// Erzeugt von Pi DB Studio – EF Core (Nullable Reference Types an)",
                    "using Microsoft.EntityFrameworkCore;", "", f"namespace {namespace};", ""]
    for n, t in m.tabellen.items():
        k = klassenname(n)
        z.append(f"public class {k}")
        z.append("{")
        for s in t.spalten:
            typ = cs_typ(s)
            init = " = null!;" if typ in _REFERENZTYPEN else ""
            z.append(f"    public {typ} {eigenschaft(s.name)} {{ get; set; }}{init}")
        if nav[n]:
            z.append("")
        for name, typ, sammlung in nav[n]:
            init = f" = new List<{typ[12:-1]}>();" if sammlung else (" = null!;" if not typ.endswith("?") else "")
            z.append(f"    public virtual {typ} {name} {{ get; set; }}{init}")
        z.append("}")
        z.append("")
    z.append(f"public class {context} : DbContext")
    z.append("{")
    z.append(f"    public {context}(DbContextOptions<{context}> options) : base(options) {{ }}")
    z.append("")
    for n in m.tabellen:
        z.append(f"    public DbSet<{klassenname(n)}> {pascal(n)} => Set<{klassenname(n)}>();")
    z.append("")
    z.append("    protected override void OnModelCreating(ModelBuilder modelBuilder)")
    z.append("    {")
    for n, t in m.tabellen.items():
        k = klassenname(n)
        z.append(f"        modelBuilder.Entity<{k}>(e =>")
        z.append("        {")
        z.append(f'            e.ToTable("{n}"' + (f', "{m.schema}"' if m.schema and m.schema not in ("main",) else "") + ");")
        if t.pk:
            schluessel = ", ".join(f"x.{eigenschaft(p)}" for p in t.pk)
            z.append(f"            e.HasKey(x => {('new { ' + schluessel + ' }') if len(t.pk) > 1 else schluessel});")
        else:
            z.append("            e.HasNoKey();")
        for s in t.spalten:
            if eigenschaft(s.name) != s.name:
                z.append(f'            e.Property(x => x.{eigenschaft(s.name)}).HasColumnName("{s.name}");')
        z.append("        });")
    for f in m.fks:
        if f.tabelle not in m.tabellen or f.ziel not in m.tabellen:
            continue
        kind_k, eltern_k = klassenname(f.tabelle), klassenname(f.ziel)
        ref = next((nm for nm, typ, sm in nav[f.tabelle] if typ.rstrip("?") == eltern_k and not sm), eltern_k)
        rueck = next((nm for nm, typ, sm in nav[f.ziel] if kind_k in typ), None)
        fk_prop = ", ".join(f"x.{eigenschaft(s)}" for s in f.spalten)
        if m.kardinalitaet(f) == "1:1":
            z.append(f"        modelBuilder.Entity<{kind_k}>().HasOne(x => x.{ref}).WithOne"
                     f"({'x => x.' + rueck if rueck else ''}).HasForeignKey<{kind_k}>(x => "
                     f"{('new { ' + fk_prop + ' }') if len(f.spalten) > 1 else fk_prop})"
                     f"{_loeschen(f)};")
        else:
            z.append(f"        modelBuilder.Entity<{kind_k}>().HasOne(x => x.{ref}).WithMany"
                     f"({'x => x.' + rueck if rueck else ''}).HasForeignKey(x => "
                     f"{('new { ' + fk_prop + ' }') if len(f.spalten) > 1 else fk_prop})"
                     f"{_loeschen(f)};")
    z.append("    }")
    z.append("}")
    return "\n".join(z) + "\n"


def _loeschen(f: erm.Fremdschluessel) -> str:
    regel = (f.bei_loeschen or "").upper()
    return {"CASCADE": ".OnDelete(DeleteBehavior.Cascade)", "SET NULL": ".OnDelete(DeleteBehavior.SetNull)",
            "RESTRICT": ".OnDelete(DeleteBehavior.Restrict)", "NO ACTION": ".OnDelete(DeleteBehavior.NoAction)"}.get(regel, "")
