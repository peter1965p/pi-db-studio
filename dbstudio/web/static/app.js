/* Pi DB Studio Web – Oberfläche (ohne Build, ohne Fremd-Framework). */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const PRODUKTIV = "#e05252";

const zustand = { ich: null, verbindungen: [], vid: null, info: null, schema: "", tabelle: null, seite: 0,
  sortierung: "", richtung: "asc", daten: null, aenderungen: new Map(), neue: [], geloescht: new Set(), markiert: null,
  tabs: [], tabAktiv: 0, handle: null, ergebnis: null, kiSql: "" };

// --- API ----------------------------------------------------------------------------------------------------------
async function api(pfad, opt = {}) {
  const kopf = { "X-Pi-Anfrage": "1" };
  let body = opt.body;
  if (body && !(body instanceof FormData)) { kopf["Content-Type"] = "application/json"; body = JSON.stringify(body); }
  const r = await fetch(pfad, { method: opt.method || (body ? "POST" : "GET"), headers: kopf, body, credentials: "same-origin" });
  if (r.status === 401 && !pfad.endsWith("/anmelden")) { zeigeAnmeldung(); throw new Error("Bitte anmelden."); }
  const typ = r.headers.get("content-type") || "";
  const daten = typ.includes("json") ? await r.json() : await r.text();
  if (r.status === 409 && daten.rueckfrage) { const e = new Error("rueckfrage"); e.rueckfrage = daten.rueckfrage; throw e; }
  if (!r.ok) throw new Error((daten && daten.detail) || `Fehler ${r.status}`);
  return daten;
}

function toast(text, art = "ok") {
  const el = document.createElement("div");
  el.className = `meldung ${art}`; el.textContent = text;
  $("#toast").append(el); setTimeout(() => el.remove(), art === "fehler" ? 7000 : 3500);
}

function hinweis(text) {
  const z = $("#hinweiszeile");
  z.classList.toggle("versteckt", !text); $("span", z).textContent = text || "";
}
$("#hinweiszeile button").onclick = () => hinweis("");

function rueckfrage(warnungen) {
  return new Promise(ok => {
    const d = $("#d-rueckfrage");
    $("#rf-text").innerHTML = warnungen.map(w => `<div class="meldung fehler">${esc(w)}</div>`).join("");
    $("#rf-ja").onclick = () => { d.close(); ok(true); };
    $("#rf-nein").onclick = () => { d.close(); ok(false); };
    d.showModal();
  });
}

// --- Thema --------------------------------------------------------------------------------------------------------
function setzeThema(t) {
  document.documentElement.dataset.theme = t;
  $("#thema").textContent = t === "hell" ? "☾ Dunkles Design" : "☀ Helles Design";
  try { localStorage.setItem("pi-thema", t); } catch (e) {}
}
$("#thema").onclick = () => setzeThema(document.documentElement.dataset.theme === "hell" ? "dunkel" : "hell");
try { setzeThema(localStorage.getItem("pi-thema") || "dunkel"); } catch (e) { setzeThema("dunkel"); }

// --- Anmeldung ----------------------------------------------------------------------------------------------------
function zeigeAnmeldung() { $("#app").classList.add("versteckt"); $("#anmeldung").classList.remove("versteckt"); }
$("#f-anmelden").onsubmit = async ev => {
  ev.preventDefault();
  const f = new FormData(ev.target);
  try {
    await api("/api/anmelden", { body: { benutzer: f.get("benutzer"), passwort: f.get("passwort") } });
    ev.target.reset(); $("#anmelde-fehler").classList.add("versteckt"); start();
  } catch (e) { const m = $("#anmelde-fehler"); m.textContent = e.message; m.classList.remove("versteckt"); }
};
$("#abmelden").onclick = async () => { await api("/api/abmelden", { body: {} }).catch(() => {}); location.reload(); };

// --- Navigation ---------------------------------------------------------------------------------------------------
const TITEL = {
  verbindungen: ["Verbindungen", "Gespeicherte Datenbanken. Passwörter bleiben verschlüsselt auf dem Server."],
  datenbank: ["Datenbank", "Objektbaum und Datenraster. Änderungen sammeln sich, bis du „Übernehmen“ klickst."],
  diagramm: ["Diagramm", "Tabellen und Beziehungen. Mausrad = Zoom, Ziehen auf freier Fläche = verschieben, Spalte auf Spalte ziehen = Beziehung."],
  editor: ["SQL-Editor", "Strg+Enter führt aus (Markierung oder alles). Ändernde Befehle fragen nach."],
  austausch: ["Import & Export", "CSV, JSON, Excel und SQL."],
  einstellungen: ["Einstellungen", "KI-Anbieter und Schlüssel – der Schlüssel wird verschlüsselt gespeichert."],
  rest: ["API & Rechte", "Generische REST-API für alle Tabellen. Zugriff nur mit Schlüssel und Regel: Verbindung, Tabelle, Aktionen, gesperrte Spalten, Zeilenfilter."],
};
function zeige(name) {
  $$(".nav-eintrag").forEach(b => b.classList.toggle("aktiv", b.dataset.ansicht === name));
  $$(".ansicht").forEach(s => s.classList.toggle("aktiv", s.id === "v-" + name));
  $("#titel").textContent = TITEL[name][0]; $("#untertitel").textContent = TITEL[name][1];
  if (name === "editor") editorAnzeigen();
  if (name === "diagramm") Diagramm.laden(zustand.schema);
  if (name === "einstellungen") einstellungenLaden();
  if (name === "rest") restLaden();
  if (name === "austausch") exportTabellen();
}
$$(".nav-eintrag").forEach(b => b.onclick = () => !b.disabled && zeige(b.dataset.ansicht));
function navFreigeben() { $$(".nav-eintrag[data-braucht]").forEach(b => b.disabled = !zustand.vid); }

// --- Verbindungen -------------------------------------------------------------------------------------------------
async function verbindungenLaden() {
  zustand.verbindungen = await api("/api/verbindungen");
  const liste = $("#verbindungsliste");
  if (!zustand.verbindungen.length) {
    liste.innerHTML = `<div class="karte gedimmt">Noch keine Verbindung. Lege mit „＋ Neue Verbindung“ die erste an.</div>`; return;
  }
  liste.innerHTML = zustand.verbindungen.map(v => {
    const art = zustand.ich.arten[v.art] || v.art;
    const ziel = ["sqlite", "duckdb"].includes(v.art) ? v.datei : `${v.benutzer ? v.benutzer + "@" : ""}${v.host}${v.port ? ":" + v.port : ""}/${v.datenbank}`;
    return `<div class="karte vkarte" style="border-left-color:${esc(v.farbe || "var(--rand)")}">
      <div class="titel">${esc(v.name || "(ohne Name)")}<span class="art">${esc(art)}</span></div>
      <div class="gedimmt mono">${esc(ziel)}</div>
      <div>${v.farbe === PRODUKTIV ? '<span class="marker rot">produktiv</span> ' : ""}${v.schreibschutz ? '<span class="marker">schreibgeschützt</span> ' : ""}${v.treiber_fehlt ? `<span class="marker rot">${esc(v.treiber_fehlt)}</span>` : ""}</div>
      <div class="knoepfe"><button class="knopf primaer klein" data-verbinden="${v.id}">Verbinden</button><button class="knopf klein" data-bearbeiten="${v.id}">Bearbeiten</button></div>
    </div>`;
  }).join("");
  $$("[data-verbinden]").forEach(b => b.onclick = () => verbinden(b.dataset.verbinden));
  $$("[data-bearbeiten]").forEach(b => b.onclick = () => verbindungDialog(zustand.verbindungen.find(v => v.id === b.dataset.bearbeiten)));
}

function verbindungDialog(v = null) {
  const d = $("#d-verbindung"), f = $("#f-verbindung");
  f.reset();
  $("#v-art").innerHTML = Object.entries(zustand.ich.arten).map(([k, n]) => `<option value="${k}">${esc(n)}</option>`).join("");
  const werte = v || { art: "postgresql", sslmode: "require" };
  for (const [k, w] of Object.entries(werte)) {
    const el = f.elements[k]; if (!el) continue;
    if (el.type === "checkbox") el.checked = !!w; else el.value = w ?? "";
  }
  f.elements.passwort.placeholder = v && v.hat_passwort ? "unverändert lassen" : "";
  $("#v-loeschen").classList.toggle("versteckt", !v);
  $("#v-test-meldung").classList.add("versteckt");
  const artWechsel = () => {
    const datei = ["sqlite", "duckdb"].includes(f.elements.art.value);
    $$(".nur-server", f).forEach(e => e.classList.toggle("versteckt", datei));
    $$(".nur-datei", f).forEach(e => e.classList.toggle("versteckt", !datei));
  };
  f.elements.art.onchange = artWechsel; artWechsel();
  const sammeln = () => {
    const o = { id: v ? v.id : "" };
    for (const el of f.elements) if (el.name) o[el.name] = el.type === "checkbox" ? el.checked : el.value;
    if (!o.passwort) delete o.passwort;
    return o;
  };
  $("#v-test").onclick = async () => {
    const m = $("#v-test-meldung"); m.className = "meldung"; m.textContent = "Teste …"; m.classList.remove("versteckt");
    try { const r = await api("/api/verbindungen/test", { body: sammeln() });
      m.className = "meldung " + (r.ok ? "ok" : "fehler"); m.textContent = r.ok ? "Verbunden: " + r.meldung : r.meldung;
    } catch (e) { m.className = "meldung fehler"; m.textContent = e.message; }
  };
  $("#v-loeschen").onclick = async () => {
    if (!(await rueckfrage([`Verbindung „${v.name}“ wirklich löschen? (Die Datenbank selbst bleibt unberührt.)`]))) return;
    await api(`/api/verbindungen/${v.id}`, { method: "DELETE" }); d.close(); if (zustand.vid === v.id) trennen(); verbindungenLaden();
  };
  d.onclose = async () => {
    if (d.returnValue !== "ok") return;
    try { await api("/api/verbindungen", { body: sammeln() }); toast("Verbindung gespeichert."); verbindungenLaden(); }
    catch (e) { toast(e.message, "fehler"); }
  };
  d.returnValue = ""; d.showModal();
}
$("#neu-verbindung").onclick = () => verbindungDialog();

async function verbinden(vid) {
  try {
    const info = await api(`/api/v/${vid}/oeffnen`, { body: {} });
    zustand.vid = vid; zustand.info = info; zustand.schema = info.schema;
    const v = zustand.verbindungen.find(x => x.id === vid);
    $("#verbindungskarte").classList.remove("versteckt");
    $("#verbindungskarte").style.borderLeftColor = v.farbe || "var(--akzent)";
    $("#vk-name").textContent = v.name; $("#vk-info").textContent = info.version;
    const pill = $("#pill"); pill.classList.remove("versteckt");
    pill.className = "pill" + (info.produktiv ? " fehler" : info.schreibschutz ? " warn" : "");
    pill.textContent = `${v.name} · ${info.version.split(" ").slice(0, 2).join(" ")}${info.schreibschutz ? " · schreibgeschützt" : ""}`;
    hinweis(info.hinweis);
    navFreigeben(); schemasFuellen(); zeige("datenbank"); baumLaden();
  } catch (e) { toast(e.message, "fehler"); }
}
function trennen() {
  if (zustand.vid) api(`/api/v/${zustand.vid}/schliessen`, { body: {} }).catch(() => {});
  Object.assign(zustand, { vid: null, info: null, tabelle: null });
  $("#verbindungskarte").classList.add("versteckt"); $("#pill").classList.add("versteckt"); hinweis("");
  navFreigeben(); zeige("verbindungen");
}
$("#vk-trennen").onclick = trennen;

function schemasFuellen() {
  const opts = zustand.info.schemas.map(s => `<option value="${esc(s.name)}">${esc(s.name)} (${s.tabellen})</option>`).join("");
  for (const id of ["#schema-wahl", "#erm-schema", "#sql-schema"]) { $(id).innerHTML = opts; $(id).value = zustand.schema; }
}
async function schemaWechseln(s) {
  zustand.schema = s;
  for (const id of ["#schema-wahl", "#erm-schema", "#sql-schema"]) $(id).value = s;
  await api(`/api/v/${zustand.vid}/schema`, { body: { schema: s } }).catch(() => {});
  hinweis(""); vervollstaendigung = null;
}
$("#schema-wahl").onchange = async e => { await schemaWechseln(e.target.value); baumLaden(); };
$("#sql-schema").onchange = e => schemaWechseln(e.target.value);
$("#erm-schema").onchange = async e => { await schemaWechseln(e.target.value); Diagramm.laden(zustand.schema); };

// --- Objektbaum ---------------------------------------------------------------------------------------------------
let baumDaten = null;
async function baumLaden() {
  $("#baum").innerHTML = '<span class="gedimmt">Lade …</span>';
  try { baumDaten = await api(`/api/v/${zustand.vid}/objekte?schema=${encodeURIComponent(zustand.schema)}`); baumZeichnen(); }
  catch (e) { $("#baum").innerHTML = `<div class="meldung fehler">${esc(e.message)}</div>`; }
}
function baumZeichnen() {
  const q = $("#baum-suche").value.toLowerCase();
  const gruppe = (titel, liste, symbol, klickbar) => {
    const l = (liste || []).filter(n => n.toLowerCase().includes(q));
    if (!l.length) return "";
    return `<div class="gruppe">${titel} (${l.length})</div>` + l.map(n =>
      `<div class="eintrag${klickbar && n === zustand.tabelle ? " aktiv" : ""}" ${klickbar ? `data-tabelle="${esc(n)}"` : ""} title="${esc(n)}">${symbol} ${esc(n)}</div>`).join("");
  };
  const d = baumDaten || {};
  $("#baum").innerHTML = gruppe("Tabellen", d.tabellen, "▦", true) + gruppe("Views", d.views, "◫", true) +
    gruppe("Indizes", d.indizes, "⚡", false) + gruppe("Funktionen", d.funktionen, "ƒ", false) || '<span class="gedimmt">Keine Objekte.</span>';
  $$("#baum [data-tabelle]").forEach(e => e.onclick = () => tabelleOeffnen(e.dataset.tabelle));
}
$("#baum-suche").oninput = baumZeichnen;

// --- Datenraster --------------------------------------------------------------------------------------------------
function offeneAenderungen() { return zustand.aenderungen.size + zustand.neue.length + zustand.geloescht.size; }
async function tabelleOeffnen(name) {
  if (offeneAenderungen() && !(await rueckfrage(["Es gibt nicht übernommene Änderungen. Verwerfen?"]))) return;
  Object.assign(zustand, { tabelle: name, seite: 0, sortierung: "", richtung: "asc" });
  $("#filter").value = ""; baumZeichnen(); rasterLaden();
}
async function rasterLaden() {
  zustand.aenderungen = new Map(); zustand.neue = []; zustand.geloescht = new Set(); zustand.markiert = null;
  const n = +$("#pro-seite").value;
  const p = new URLSearchParams({ tabelle: zustand.tabelle, schema: zustand.schema, offset: zustand.seite * n, limit: n,
    sortierung: zustand.sortierung, richtung: zustand.richtung, filter: $("#filter").value });
  $("#tabellen-titel").textContent = zustand.tabelle;
  try { zustand.daten = await api(`/api/v/${zustand.vid}/zeilen?${p}`); rasterZeichnen(); }
  catch (e) { $("#raster").innerHTML = ""; toast(e.message, "fehler"); }
}
function zelle(w, typ) {
  if (w === null || w === undefined) return `<td class="null">NULL</td>`;
  const zahl = typeof w === "number";
  const text = typeof w === "object" ? JSON.stringify(w) : String(w);
  return `<td class="${zahl ? "zahl" : ""}" title="${esc(text.length > 60 ? text.slice(0, 500) : "")}">${esc(text)}</td>`;
}
function rasterZeichnen() {
  const d = zustand.daten, info = d.spalteninfo;
  const kopf = `<tr><th class="nr">#</th>${info.map(s => `<th data-spalte="${esc(s.name)}" class="${zustand.sortierung === s.name ? "sortiert" : ""}">${s.pk ? "🔑 " : ""}${esc(s.name)}<span class="typ">${esc(s.typ)}</span>${zustand.sortierung === s.name ? (zustand.richtung === "asc" ? " ▲" : " ▼") : ""}</th>`).join("")}</tr>`;
  const n = +$("#pro-seite").value;
  const koerper = d.zeilen.map((z, i) => `<tr data-i="${i}"><td class="nr">${zustand.seite * n + i + 1}</td>${z.map((w, j) => zelle(w, info[j].typ)).join("")}</tr>`).join("") +
    zustand.neue.map((z, i) => `<tr class="neu" data-neu="${i}"><td class="nr">neu</td>${info.map(s => `<td contenteditable="true" data-spalte="${esc(s.name)}">${esc(z[s.name] ?? "")}</td>`).join("")}</tr>`).join("");
  $("#raster").innerHTML = `<thead>${kopf}</thead><tbody>${koerper}</tbody>`;
  $$("#raster th[data-spalte]").forEach(th => th.onclick = () => {
    const s = th.dataset.spalte;
    zustand.richtung = zustand.sortierung === s && zustand.richtung === "asc" ? "desc" : "asc"; zustand.sortierung = s; rasterLaden();
  });
  const bearbeitbar = d.bearbeitbar;
  $$("#raster tbody tr[data-i]").forEach(tr => {
    tr.onclick = () => { $$("#raster tr.markiert").forEach(x => x.classList.remove("markiert")); zustand.markiert = +tr.dataset.i; $("#zeile-weg").disabled = !bearbeitbar; };
    if (!bearbeitbar) return;
    $$("td:not(.nr)", tr).forEach((td, j) => td.ondblclick = () => bearbeiteZelle(td, +tr.dataset.i, j));
  });
  $$("#raster tr[data-neu] td[contenteditable]").forEach(td => td.oninput = () => {
    zustand.neue[+td.parentElement.dataset.neu][td.dataset.spalte] = td.textContent; knoepfe();
  });
  zustand.geloescht.forEach(i => $(`#raster tr[data-i="${i}"]`)?.classList.add("geloescht"));
  zustand.aenderungen.forEach((_, i) => $(`#raster tr[data-i="${i}"]`)?.classList.add("geaendert"));
  const seiten = Math.max(1, Math.ceil(d.gesamt / n));
  const von = d.gesamt ? zustand.seite * n + 1 : 0, bis = Math.min(d.gesamt, (zustand.seite + 1) * n);
  $("#seiten").innerHTML = `<button class="knopf klein" id="s-zurueck" ${zustand.seite ? "" : "disabled"}>‹</button>
    Seite ${zustand.seite + 1} / ${seiten} · Zeilen ${von}–${bis} von ${d.gesamt.toLocaleString("de-DE")}
    <button class="knopf klein" id="s-vor" ${zustand.seite + 1 < seiten ? "" : "disabled"}>›</button>
    ${bearbeitbar ? "" : `<span class="marker">${zustand.info.schreibschutz ? "schreibgeschützt" : "nur lesbar (kein Primärschlüssel)"}</span>`}`;
  $("#s-zurueck").onclick = () => { zustand.seite--; rasterLaden(); };
  $("#s-vor").onclick = () => { zustand.seite++; rasterLaden(); };
  $("#zeile-neu").disabled = !bearbeitbar;
  knoepfe();
}
function bearbeiteZelle(td, i, j) {
  const s = zustand.daten.spalteninfo[j];
  const alt = zustand.aenderungen.get(i)?.[s.name] ?? zustand.daten.zeilen[i][j];
  td.contentEditable = "true"; td.classList.remove("null"); td.textContent = alt ?? ""; td.focus();
  const fertig = () => {
    td.contentEditable = "false";
    const neu = td.textContent;
    if (neu !== String(zustand.daten.zeilen[i][j] ?? "")) {
      const m = zustand.aenderungen.get(i) || {}; m[s.name] = neu; zustand.aenderungen.set(i, m);
      td.parentElement.classList.add("geaendert");
    }
    knoepfe();
  };
  td.onblur = fertig;
  td.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); td.blur(); } if (e.key === "Escape") { td.textContent = alt ?? ""; td.blur(); } };
}
function knoepfe() {
  const n = offeneAenderungen();
  $("#uebernehmen").disabled = $("#verwerfen").disabled = !n;
  $("#uebernehmen").textContent = n ? `Übernehmen (${n})` : "Übernehmen";
}
function pkVon(i) {
  const o = {}; zustand.daten.spalteninfo.forEach((s, j) => { if (s.pk) o[s.name] = zustand.daten.zeilen[i][j]; }); return o;
}
$("#zeile-neu").onclick = () => { zustand.neue.push({}); rasterZeichnen(); };
$("#zeile-weg").onclick = () => { if (zustand.markiert === null) return; zustand.geloescht.add(zustand.markiert); rasterZeichnen(); };
$("#verwerfen").onclick = () => rasterLaden();
$("#uebernehmen").onclick = async () => {
  const liste = [
    ...[...zustand.aenderungen].filter(([i]) => !zustand.geloescht.has(i)).map(([i, w]) => ({ art: "update", pk: pkVon(i), werte: w })),
    ...zustand.neue.filter(z => Object.values(z).some(v => v !== "")).map(z => ({ art: "insert", werte: Object.fromEntries(Object.entries(z).filter(([, v]) => v !== "")) })),
    ...[...zustand.geloescht].map(i => ({ art: "delete", pk: pkVon(i) })),
  ];
  if (zustand.info.produktiv && !(await rueckfrage([`Produktiv-Verbindung: ${liste.length} Änderung(en) schreiben?`]))) return;
  try { const r = await api(`/api/v/${zustand.vid}/aenderungen`, { body: { schema: zustand.schema, tabelle: zustand.tabelle, aenderungen: liste } });
    toast(`${r.anzahl} Änderung(en) übernommen.`); rasterLaden();
  } catch (e) { toast(e.message, "fehler"); }
};
$("#filter-los").onclick = () => { zustand.seite = 0; rasterLaden(); };
$("#filter").onkeydown = e => { if (e.key === "Enter") { zustand.seite = 0; rasterLaden(); } };
$("#pro-seite").onchange = () => { zustand.seite = 0; if (zustand.tabelle) rasterLaden(); };
$("#tab-export").onclick = () => zustand.tabelle && herunterladen({ tabelle: zustand.tabelle, format: "csv" });

function herunterladen(p) {
  const q = new URLSearchParams({ schema: zustand.schema, ...p });
  const a = document.createElement("a"); a.href = `/api/v/${zustand.vid}/export?${q}`; a.download = ""; document.body.append(a); a.click(); a.remove();
}

// --- SQL-Editor ---------------------------------------------------------------------------------------------------
let cm = null, vervollstaendigung = null;
function editorAnzeigen() {
  if (!cm) {
    cm = CodeMirror.fromTextArea($("#sql-text"), { mode: "text/x-sql", lineNumbers: true, matchBrackets: true, styleActiveLine: true,
      indentUnit: 2, extraKeys: { "Ctrl-Enter": sqlLos, "Cmd-Enter": sqlLos, "Ctrl-Space": "autocomplete" } });
    cm.on("inputRead", (ed, ch) => { if (/[\w.]/.test(ch.text[0] || "")) ed.showHint({ completeSingle: false }); });
    cm.on("change", () => { if (zustand.tabs[zustand.tabAktiv]) zustand.tabs[zustand.tabAktiv].sql = cm.getValue(); });
    if (!zustand.tabs.length) neuerTab("SELECT 1;");
  }
  setTimeout(() => cm.refresh(), 0);
  hintLaden();
}
async function hintLaden() {
  if (!zustand.vid || vervollstaendigung) return;
  try { vervollstaendigung = await api(`/api/v/${zustand.vid}/vervollstaendigung?schema=${encodeURIComponent(zustand.schema)}`);
    cm.setOption("hintOptions", { tables: vervollstaendigung, completeSingle: false }); } catch (e) {}
}
function neuerTab(sql = "") {
  zustand.tabs.push({ name: `Abfrage ${zustand.tabs.length + 1}`, sql }); zustand.tabAktiv = zustand.tabs.length - 1; tabsZeichnen();
}
function tabsZeichnen() {
  $$("#tabs .tab").forEach(t => t.remove());
  zustand.tabs.forEach((t, i) => {
    const el = document.createElement("div"); el.className = "tab" + (i === zustand.tabAktiv ? " aktiv" : "");
    el.innerHTML = `${esc(t.name)} <span class="zu" title="Schließen">×</span>`;
    el.onclick = e => {
      if (e.target.classList.contains("zu")) { zustand.tabs.splice(i, 1); if (!zustand.tabs.length) zustand.tabs.push({ name: "Abfrage 1", sql: "" });
        zustand.tabAktiv = Math.min(zustand.tabAktiv, zustand.tabs.length - 1); }
      else zustand.tabAktiv = i;
      tabsZeichnen();
    };
    $("#tab-neu").before(el);
  });
  if (cm) cm.setValue(zustand.tabs[zustand.tabAktiv].sql);
}
$("#tab-neu").onclick = () => neuerTab("");
function aktuellesSql() { return (cm.getSelection() || cm.getValue()).trim(); }
async function sqlLos(bestaetigt = false) {
  const sql = aktuellesSql(); if (!sql) return;
  $("#sql-stopp").disabled = false; $("#sql-status").innerHTML = "Läuft …";
  try {
    const r = await api(`/api/v/${zustand.vid}/sql`, { body: { sql, schema: zustand.schema, bestaetigt: bestaetigt === true, limit: 500 } });
    zustand.handle = r.handle; zustand.ergebnis = r; zustand.letzterFehler = "";
    ergebnisZeichnen(r);
    $("#sql-status").innerHTML = `<span class="ok">✓</span> ${r.zeilen.length}${r.mehr ? "+" : ""} Zeile(n) · ${(r.dauer * 1000).toFixed(0)} ms${r.meldungen.length ? " · " + esc(r.meldungen.join(" · ")) : ""}`;
    if (/^\s*(create|alter|drop)/i.test(sql)) { vervollstaendigung = null; hintLaden(); }
  } catch (e) {
    if (e.rueckfrage) { if (await rueckfrage(e.rueckfrage)) return sqlLos(true); $("#sql-status").textContent = "Abgebrochen."; }
    else { zustand.letzterFehler = e.message; $("#sql-status").innerHTML = `<span class="meldung fehler">${esc(e.message)}</span>`; }
  } finally { $("#sql-stopp").disabled = true; }
}
function ergebnisZeichnen(r, anhaengen = false) {
  if (!anhaengen) $("#sql-ergebnis").innerHTML = r.spalten.length ? `<thead><tr><th class="nr">#</th>${r.spalten.map(s => `<th>${esc(s)}</th>`).join("")}</tr></thead><tbody></tbody>` : "";
  const tb = $("#sql-ergebnis tbody"); if (!tb) return;
  const start = tb.children.length;
  tb.insertAdjacentHTML("beforeend", r.zeilen.map((z, i) => `<tr><td class="nr">${start + i + 1}</td>${z.map(w => zelle(w)).join("")}</tr>`).join(""));
  $("#sql-mehr").classList.toggle("versteckt", !r.mehr);
}
$("#sql-los").onclick = () => sqlLos();
$("#sql-stopp").onclick = () => api(`/api/v/${zustand.vid}/abbrechen`, { body: {} });
$("#sql-mehr").onclick = async () => {
  if (!zustand.handle) return;
  try { const r = await api(`/api/abfrage/${zustand.handle}/weitere`, { body: { anzahl: 500 } }); ergebnisZeichnen({ ...r, spalten: [] }, true);
    if (!r.mehr) zustand.handle = null; } catch (e) { toast(e.message, "fehler"); }
};
$("#sql-explain").onclick = async () => {
  try { const r = await api(`/api/v/${zustand.vid}/explain`, { body: { sql: aktuellesSql() } }); ergebnisZeichnen(r); $("#sql-status").textContent = "Ausführungsplan"; }
  catch (e) { $("#sql-status").innerHTML = `<span class="meldung fehler">${esc(e.message)}</span>`; }
};
$("#sql-export").onclick = () => { const sql = aktuellesSql(); if (sql) herunterladen({ sql, format: "csv" }); };

// KI
$$("[data-ki]").forEach(b => b.onclick = async () => {
  const art = b.dataset.ki, ziel = $("#ki-antwort");
  ziel.innerHTML = '<span class="gedimmt">Denke nach …</span>'; $("#ki-uebernehmen").classList.add("versteckt");
  try {
    const r = await api(`/api/v/${zustand.vid}/ki`, { body: { art, schema: zustand.schema, text: $("#ki-text").value,
      sql: cm ? aktuellesSql() : "", fehler: zustand.letzterFehler || "", beispiele: $("#ki-beispiele").checked } });
    ziel.innerHTML = esc(r.antwort).replace(/```(?:sql)?\n([\s\S]*?)```/g, "<pre>$1</pre>");
    zustand.kiSql = r.sql; $("#ki-uebernehmen").classList.toggle("versteckt", !r.sql);
  } catch (e) { ziel.innerHTML = `<div class="meldung fehler">${esc(e.message)}</div>`; }
});
$("#ki-uebernehmen").onclick = () => { neuerTab(zustand.kiSql); toast("SQL in neuem Tab – wird nicht automatisch ausgeführt."); };

// --- Import/Export ------------------------------------------------------------------------------------------------
async function exportTabellen() {
  if (!zustand.vid) return;
  const o = baumDaten || await api(`/api/v/${zustand.vid}/objekte?schema=${encodeURIComponent(zustand.schema)}`);
  $("#export-tabelle").innerHTML = [...(o.tabellen || []), ...(o.views || [])].map(n => `<option>${esc(n)}</option>`).join("");
}
async function importSenden(vorschau) {
  const f = $("#f-import"), fd = new FormData(f);
  fd.set("schema", zustand.schema); fd.set("neu", f.elements.neu.checked ? "true" : "false"); fd.set("nur_vorschau", vorschau ? "true" : "false");
  try {
    const r = await api(`/api/v/${zustand.vid}/import`, { body: fd });
    if (vorschau) $("#import-tabelle").innerHTML = `<thead><tr>${r.spalten.map(s => `<th>${esc(s)}</th>`).join("")}</tr></thead><tbody>${r.zeilen.map(z => `<tr>${z.map(w => zelle(w)).join("")}</tr>`).join("")}</tbody>`;
    else { toast(`${r.zeilen} Zeilen importiert (${r.spalten} Spalten).`); baumDaten = null; baumLaden(); }
  } catch (e) { toast(e.message, "fehler"); }
}
$("#import-vorschau").onclick = () => importSenden(true);
$("#f-import").onsubmit = e => { e.preventDefault(); importSenden(false); };
$("#f-export").onsubmit = e => { e.preventDefault(); const f = new FormData(e.target); herunterladen({ tabelle: f.get("tabelle"), format: f.get("format") }); };

// --- SQL-Dump-Import -----------------------------------------------------------------------------------------------
async function sqlImport(ausfuehren) {
  const f = $("#f-sqlimport"), fd = new FormData(f);
  if (!fd.get("datei") || !fd.get("datei").name) { toast("Erst eine .sql-Datei wählen.", "fehler"); return; }
  if (ausfuehren && !confirm("Struktur jetzt in die geöffnete Verbindung einspielen?")) return;
  fd.append("ausfuehren", ausfuehren ? "true" : "false");
  try {
    const r = await api(`/api/v/${zustand.vid}/sqlimport`, { body: fd });
    const h = $("#sqlimport-hinweise"); h.classList.remove("versteckt"); h.innerHTML = r.hinweise.map(x => `<div>${esc(x)}</div>`).join("");
    $("#sqlimport-text").value = r.anweisungen.join(";\n\n") + ";";
    if (ausfuehren) { toast(`${r.ausgefuehrt} Anweisungen eingespielt.`); if (typeof Diagramm !== "undefined") Diagramm.laden(zustand.schema, true); }
  } catch (e) { toast(e.message, "fehler"); }
}
$("#sqlimport-vorschau").onclick = () => sqlImport(false);
$("#f-sqlimport").onsubmit = ev => { ev.preventDefault(); sqlImport(true); };

// --- Einstellungen ------------------------------------------------------------------------------------------------
async function einstellungenLaden() {
  const e = await api("/api/einstellungen"), f = $("#f-einstellungen");
  $("#ki-anbieter").innerHTML = e.anbieter.map(a => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join("");
  f.elements.ki_anbieter.value = e.ki_anbieter; f.elements.ki_modell.value = e.ki_modell; f.elements.ollama_url.value = e.ollama_url;
  $("#api-status").textContent = e.hat_api_schluessel ? "(hinterlegt)" : "(fehlt)";
}
$("#f-einstellungen").onsubmit = async ev => {
  ev.preventDefault(); const f = new FormData(ev.target);
  await api("/api/einstellungen", { body: Object.fromEntries(f) }); ev.target.elements.api_schluessel.value = ""; toast("Gespeichert."); einstellungenLaden();
};
$("#api-loeschen").onclick = async () => { await api("/api/einstellungen", { body: { api_schluessel_loeschen: true } }); einstellungenLaden(); };

// --- REST-API und Rechte ------------------------------------------------------------------------------------------
async function restLaden() {
  const [d, prot] = await Promise.all([api("/api/rest/schluessel"), api("/api/rest/protokoll")]);
  const namen = Object.fromEntries(zustand.verbindungen.map(v => [v.id, v.name]));
  $("#rest-verbindung").innerHTML = zustand.verbindungen.map(v => `<option value="${esc(v.id)}">${esc(v.name)}</option>`).join("");
  const regeltext = r => `${esc(namen[r.verbindung] || r.verbindung)} · ${esc(r.tabelle)} · ${esc(r.aktionen.join(", "))}`
    + (r.spalten_gesperrt.length ? ` · ohne ${esc(r.spalten_gesperrt.join(", "))}` : "")
    + (Object.keys(r.zeilenfilter).length ? ` · nur ${esc(Object.entries(r.zeilenfilter).map(([k, v]) => k + "=" + v).join(", "))}` : "");
  $("#rest-liste").innerHTML = "<tr><th>Name</th><th>Schlüssel</th><th>Regeln</th><th>Limit/min</th><th>Zuletzt</th><th>Aktiv</th><th></th></tr>"
    + (d.schluessel.map(k => `<tr><td>${esc(k.name)}</td><td><code>${esc(k.anfang)}…</code></td><td>${k.regeln.map(regeltext).join("<br>")}</td>
      <td class="zahl">${k.limit_minute}</td><td>${esc((k.zuletzt || "–").replace("T", " ").slice(0, 16))}</td>
      <td><input type="checkbox" data-aktiv="${esc(k.id)}" ${k.aktiv ? "checked" : ""}></td>
      <td><button class="knopf gefahr klein" data-weg="${esc(k.id)}">Löschen</button></td></tr>`).join("")
      || '<tr><td colspan="7" class="null">Noch keine Schlüssel.</td></tr>');
  $$("[data-aktiv]").forEach(c => c.onchange = async () => { await api("/api/rest/schluessel/" + c.dataset.aktiv, { method: "PATCH", body: { aktiv: c.checked } }); toast(c.checked ? "Aktiviert." : "Gesperrt."); });
  $$("[data-weg]").forEach(b => b.onclick = async () => { if (!confirm("Schlüssel endgültig löschen?")) return; await api("/api/rest/schluessel/" + b.dataset.weg, { method: "DELETE" }); restLaden(); });
  $("#rest-protokoll").innerHTML = "<tr><th>Zeit</th><th>Schlüssel</th><th>Aktion</th><th>Tabelle</th><th>Status</th><th>Grund / betroffen</th></tr>"
    + (prot.slice(0, 100).map(p => `<tr><td>${esc((p.zeit || "").replace("T", " ").slice(0, 19))}</td><td>${esc(p.name || p.schluessel || "–")}</td>
      <td>${esc(p.aktion || p.methode || "")}</td><td>${esc(p.tabelle || p.pfad || "")}</td><td class="zahl">${p.status}</td>
      <td>${esc(p.grund || (p.betroffen ?? ""))}</td></tr>`).join("") || '<tr><td colspan="6" class="null">Noch nichts.</td></tr>');
  const vid = zustand.verbindungen[0]?.id || "VERBINDUNG";
  $("#rest-beispiel").textContent = [
    `curl -H "Authorization: Bearer pi_…" "${location.origin}/rest/v1/${vid}/kunden?ort=eq.Osnabrück&order=name.asc&limit=50"`,
    `Filter: spalte=${d.operatoren.join("|")}.wert  oder  spalte=is.null / is.notnull   ·   select=a,b   ·   order=spalte.desc   ·   limit / offset`,
    `Einzeln: GET/PATCH/DELETE …/{tabelle}/{primärschlüssel}   ·   Anlegen: POST …/{tabelle} mit JSON`,
    `OpenAPI (nur die Tabellen des Schlüssels): ${location.origin}/rest/v1/openapi.json`].join("\n");
}
$("#f-rest").onsubmit = async ev => {
  ev.preventDefault(); const f = new FormData(ev.target);
  const liste = t => String(t || "").split(",").map(x => x.trim()).filter(Boolean);
  const zeilenfilter = Object.fromEntries(liste(f.get("zeilenfilter")).map(x => { const [k, ...v] = x.split("="); return [k.trim(), v.join("=").trim()]; }));
  try {
    const r = await api("/api/rest/schluessel", { body: { name: f.get("name"), limit_minute: Number(f.get("limit_minute") || 120),
      regeln: [{ verbindung: f.get("verbindung"), tabelle: f.get("tabelle") || "*", rolle: f.get("rolle"),
                 spalten_gesperrt: liste(f.get("spalten_gesperrt")), zeilenfilter }] } });
    const box = $("#rest-geheim");
    box.innerHTML = `<b>Dein Schlüssel – nur jetzt sichtbar:</b><br><code id="rest-geheim-text" style="word-break:break-all">${esc(r.geheim)}</code>
      <div class="leiste" style="margin-top:8px"><button class="knopf klein" type="button" id="rest-kopieren">Kopieren</button><button class="knopf klein" type="button" id="rest-zu">Ausblenden</button></div>`;
    box.hidden = false;
    $("#rest-kopieren").onclick = () => navigator.clipboard.writeText(r.geheim).then(() => toast("Kopiert."));
    $("#rest-zu").onclick = () => { box.hidden = true; box.innerHTML = ""; };
    ev.target.reset(); restLaden();
  } catch (e) { toast(e.message, "fehler"); }
};

// --- Start --------------------------------------------------------------------------------------------------------
async function start() {
  try { zustand.ich = await api("/api/ich"); } catch (e) { zeigeAnmeldung(); return; }
  $("#anmeldung").classList.add("versteckt"); $("#app").classList.remove("versteckt");
  $("#version").textContent = "Version " + zustand.ich.version;
  navFreigeben(); await verbindungenLaden();
}
window.PiDB = { api, zustand, toast, rueckfrage, esc, zeige, neuerTab, schemaWechseln };
start();
