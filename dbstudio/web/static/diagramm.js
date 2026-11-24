/* Pi DB Studio Web – ER-Diagramm als SVG: Karten, rechtwinklige Linien mit Plaketten (1 / n / 0..1, EF: 1 / *),
   Mausrad-Zoom um den Zeiger, Verschieben, Hervorheben, Beziehung per Ziehen, DDL-Vorschau, Export SVG/PNG/C#. */
"use strict";
const Diagramm = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const B = 260, KOPF = 34, ZEILE = 22, RAND = 8, ABSCHNITT = 18;
  const g = { modell: null, pos: {}, karten: {}, zoom: 1, tx: 40, ty: 40, schema: "", geladen: "" };
  const $ = s => document.querySelector(s);
  const P = () => window.PiDB;
  const el = (tag, attr = {}, eltern) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attr)) e.setAttribute(k, v); if (eltern) eltern.append(e); return e; };
  const welt = () => $("#erm-welt");
  const svg = () => $("#erm-svg");

  // --- Laden -------------------------------------------------------------------------------------------------------
  async function laden(schema, erzwingen = false) {
    const z = P().zustand;
    if (!z.vid) return;
    const schluessel = `${z.vid}|${schema}`;
    if (!erzwingen && g.geladen === schluessel && g.modell) { zeichnen(); return; }
    try {
      g.modell = await P().api(`/api/v/${z.vid}/erm?schema=${encodeURIComponent(schema)}`);
      g.schema = g.modell.schema; g.geladen = schluessel; g.pos = {};
      for (const [n, p] of Object.entries(g.modell.positionen)) g.pos[n] = { x: p[0], y: p[1] };
      if (z.info && z.info.art === "mssql" && !g.stilGesetzt) { $("#erm-stil").value = "ef"; }
      zeichnen(); anpassen(true);
    } catch (e) { P().toast(e.message, "fehler"); }
  }

  // --- Karten ------------------------------------------------------------------------------------------------------
  const stil = () => $("#erm-stil").value;
  const ansicht = () => $("#erm-ansicht").value;
  function sichtbareSpalten(t) {
    if (ansicht() === "namen") return [];
    return ansicht() === "schluessel" ? t.spalten.filter(s => s.pk || s.fk) : t.spalten;
  }
  function kartenHoehe(t) {
    const sp = sichtbareSpalten(t).length;
    if (stil() === "ef") return KOPF + 12 + (ansicht() !== "namen" ? ABSCHNITT + sp * ZEILE + (t.navigationen.length ? ABSCHNITT + t.navigationen.length * ZEILE : 0) : 0) + RAND;
    return KOPF + sp * ZEILE + RAND;
  }
  function zeileY(t, spalte) {
    const i = sichtbareSpalten(t).findIndex(s => s.name === spalte);
    const basis = stil() === "ef" ? KOPF + 12 + ABSCHNITT : KOPF;
    return i < 0 ? KOPF / 2 : basis + i * ZEILE + ZEILE / 2;
  }

  function karte(t, ebene) {
    const p = g.pos[t.name] || { x: 0, y: 0 }, h = kartenHoehe(t), ef = stil() === "ef";
    const gr = el("g", { class: "erm-karte" + (t.zwischentabelle ? " zwischen" : ""), transform: `translate(${p.x},${p.y})`, "data-t": t.name }, ebene);
    el("rect", { class: "koerper", width: B, height: h, rx: 10 }, gr);
    el("rect", { class: "kopfbalken", width: B - 2, height: ef ? KOPF + 10 : KOPF - 4, x: 1, y: 1, rx: 9 }, gr);
    const titel = el("text", { class: "titel", x: 12, y: 21 }, gr); titel.textContent = ef ? t.klasse : t.name;
    if (t.zwischentabelle) { const n = el("text", { class: "unter", x: B - 12, y: 20, "text-anchor": "end" }, gr); n.textContent = "n:m"; n.style.fill = "var(--neon)"; }
    if (ef) { const u = el("text", { class: "unter", x: 12, y: 36 }, gr); u.textContent = `[${g.schema}].[${t.name}]`; }
    let y = ef ? KOPF + 12 : KOPF;
    if (ef && ansicht() !== "namen") { const a = el("text", { class: "abschnitt", x: 12, y: y + 12 }, gr); a.textContent = "EIGENSCHAFTEN"; y += ABSCHNITT; }
    for (const s of sichtbareSpalten(t)) {
      const z = el("g", { class: "zeile", "data-spalte": s.name, transform: `translate(0,${y})` }, gr);
      el("rect", { x: 2, width: B - 4, height: ZEILE }, z);
      const sym = el("text", { x: 10, y: 15 }, z); sym.textContent = s.pk ? "🔑" : s.fk ? "↗" : "";
      if (s.fk && !s.pk) sym.style.fill = "var(--blau)";
      const n = el("text", { x: 30, y: 15, class: s.nullbar ? "" : "nn" }, z); n.textContent = ef ? s.eigenschaft : s.name;
      const ty = el("text", { x: B - 10, y: 15, class: "typ", "text-anchor": "end" }, z);
      ty.textContent = ef ? s.cs_typ : `${s.typ}${s.nullbar ? "" : " · NN"}`;
      kuerzen(n, B - 60 - Math.min(110, ty.getComputedTextLength ? 0 : 0));
      y += ZEILE;
    }
    if (ef && ansicht() !== "namen" && t.navigationen.length) {
      const a = el("text", { class: "abschnitt", x: 12, y: y + 12 }, gr); a.textContent = "NAVIGATIONEN"; y += ABSCHNITT;
      for (const nv of t.navigationen) {
        const n = el("text", { x: 30, y: y + 15 }, gr); n.textContent = nv.name; n.style.fill = "var(--blau)";
        const ty = el("text", { x: B - 10, y: y + 15, class: "typ", "text-anchor": "end" }, gr); ty.textContent = nv.typ;
        y += ZEILE;
      }
    }
    g.karten[t.name] = { gr, t, h };
    return gr;
  }
  function kuerzen(textEl, max) {
    if (!textEl.getComputedTextLength) return;
    let s = textEl.textContent;
    try { while (s.length > 4 && textEl.getComputedTextLength() > max) { s = s.slice(0, -1); textEl.textContent = s + "…"; } } catch (e) {}
  }

  // --- Linien ------------------------------------------------------------------------------------------------------
  function rundePfad(pts, r = 8) {
    let d = `M${pts[0][0]},${pts[0][1]}`;
    for (let i = 1; i < pts.length - 1; i++) {
      const [x0, y0] = pts[i - 1], [x1, y1] = pts[i], [x2, y2] = pts[i + 1];
      const r1 = Math.min(r, Math.hypot(x1 - x0, y1 - y0) / 2, Math.hypot(x2 - x1, y2 - y1) / 2);
      const a = [x1 - Math.sign(x1 - x0) * r1, y1 - Math.sign(y1 - y0) * r1], b = [x1 + Math.sign(x2 - x1) * r1, y1 + Math.sign(y2 - y1) * r1];
      d += ` L${a[0]},${a[1]} Q${x1},${y1} ${b[0]},${b[1]}`;
    }
    const l = pts[pts.length - 1]; return d + ` L${l[0]},${l[1]}`;
  }
  function plakette(eltern, x, y, text) {
    const gp = el("g", { class: "plakette", transform: `translate(${x},${y})` }, eltern);
    const w = 8 + text.length * 7;
    el("rect", { x: -w / 2, y: -9, width: w, height: 18, rx: 9 }, gp);
    el("text", { x: 0, y: 0 }, gp).textContent = text;
  }
  function kraehenfuss(eltern, x, y, richtung) { // richtung: +1 = Fuß zeigt nach rechts
    el("path", { class: "strich", d: `M${x},${y - 7} L${x - 12 * richtung},${y} L${x},${y + 7} M${x - 12 * richtung},${y} L${x},${y}` }, eltern);
  }
  function linien(ebene) {
    const zaehler = {};
    for (const f of g.modell.fks) {
      const a = g.karten[f.tabelle], b = g.karten[f.ziel];
      if (!a || !b) continue;
      const pa = g.pos[f.tabelle], pb = g.pos[f.ziel];
      const ya = pa.y + zeileY(a.t, f.spalten[0]), yb = pb.y + zeileY(b.t, f.ziel_spalten[0]);
      const k = f.art === "n:m" ? "nm" : f.art === "1:1" ? "e11" : "n1";
      const gl = el("g", { class: `erm-linie ${k}`, "data-von": f.tabelle, "data-nach": f.ziel }, ebene);
      const schluessel = f.ziel; zaehler[schluessel] = (zaehler[schluessel] || 0) + 1;
      const versatz = (zaehler[schluessel] - 1) * 6;
      let pts, sa, sb;
      if (f.tabelle === f.ziel) {
        const x = pa.x + B; pts = [[x, ya], [x + 30 + versatz, ya], [x + 30 + versatz, yb + 0.01], [x, yb]]; sa = sb = 1;
      } else if (pa.x + B + 30 < pb.x) { sa = 1; sb = -1; const mx = (pa.x + B + pb.x) / 2 + versatz; pts = [[pa.x + B, ya], [mx, ya], [mx, yb], [pb.x, yb]]; }
      else if (pb.x + B + 30 < pa.x) { sa = -1; sb = 1; const mx = (pb.x + B + pa.x) / 2 - versatz; pts = [[pa.x, ya], [mx, ya], [mx, yb], [pb.x + B, yb]]; }
      else { sa = 1; sb = 1; const mx = Math.max(pa.x, pb.x) + B + 28 + versatz; pts = [[pa.x + B, ya], [mx, ya], [mx, yb], [pb.x + B, yb]]; }
      if (Math.abs(ya - yb) < 1) pts = [pts[0], pts[pts.length - 1]];
      const d = rundePfad(pts);
      el("path", { class: "fang", d }, gl);
      el("path", { class: "strich", d }, gl);
      const ef = stil() === "ef";
      const kind = ef ? f.abhaengig : (f.art === "1:1" ? "1" : "n");
      const eltern = ef ? f.haupt : (f.optional ? "0..1" : "1");
      if (kind === "n" || kind === "*") kraehenfuss(gl, pts[0][0], pts[0][1], -sa);
      plakette(gl, pts[0][0] + sa * 22, pts[0][1] - 12, kind);
      plakette(gl, pts[pts.length - 1][0] + sb * 22, pts[pts.length - 1][1] - 12, eltern);
      if (ef) { const [x, y] = pts[pts.length - 1]; el("path", { class: "strich", d: `M${x + sb * 9},${y - 5} L${x},${y} L${x + sb * 9},${y + 5}` }, gl); }
      gl.addEventListener("mousemove", ev => tooltip(ev, `<b>${P().esc(f.worte)}</b><br>${P().esc(f.tabelle)}.${P().esc(f.spalten.join(", "))} → ${P().esc(f.ziel)}.${P().esc(f.ziel_spalten.join(", "))}<br>${f.art}${f.optional ? " · optional" : ""} · ON DELETE ${P().esc(f.bei_loeschen)}`));
      gl.addEventListener("mouseleave", () => $("#erm-tooltip").classList.add("versteckt"));
    }
  }
  function tooltip(ev, html) {
    const t = $("#erm-tooltip"), r = $("#erm-rahmen").getBoundingClientRect();
    t.innerHTML = html; t.classList.remove("versteckt");
    t.style.left = Math.min(ev.clientX - r.left + 14, r.width - 370) + "px"; t.style.top = (ev.clientY - r.top + 14) + "px";
  }

  // --- Zeichnen ----------------------------------------------------------------------------------------------------
  function zeichnen() {
    if (!g.modell) return;
    const w = welt(); w.innerHTML = ""; g.karten = {};
    const lin = el("g", { id: "erm-linien" }, w), kar = el("g", { id: "erm-karten" }, w);
    for (const t of g.modell.tabellen) karte(t, kar);
    linien(lin);
    transform();
    $("#erm-zahlen").textContent = `${g.modell.tabellen.length} Tabellen · ${g.modell.fks.length} Beziehungen`;
    for (const [name, k] of Object.entries(g.karten)) {
      k.gr.addEventListener("mouseenter", () => hervorheben(name));
      k.gr.addEventListener("mouseleave", () => hervorheben(null));
    }
  }
  function hervorheben(name) {
    const s = svg(); s.classList.toggle("gedimmt-modus", !!name);
    document.querySelectorAll(".nah").forEach(e => e.classList.remove("nah"));
    if (!name) return;
    const nachbarn = new Set([name]);
    document.querySelectorAll(".erm-linie").forEach(l => {
      if (l.dataset.von === name || l.dataset.nach === name) { l.classList.add("nah"); nachbarn.add(l.dataset.von); nachbarn.add(l.dataset.nach); }
    });
    nachbarn.forEach(n => g.karten[n]?.gr.classList.add("nah"));
  }
  function transform() {
    welt().setAttribute("transform", `translate(${g.tx},${g.ty}) scale(${g.zoom})`);
    $("#z-wert").textContent = Math.round(g.zoom * 100) + " %";
  }
  function grenzen() {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const [n, k] of Object.entries(g.karten)) { const p = g.pos[n]; x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x + B + 40); y1 = Math.max(y1, p.y + k.h); }
    return isFinite(x0) ? { x0, y0, x1, y1 } : { x0: 0, y0: 0, x1: 100, y1: 100 };
  }
  function anpassen(lesbar = false) {
    const r = svg().getBoundingClientRect(), b = grenzen();
    if (!r.width) return;
    let z = Math.min((r.width - 40) / (b.x1 - b.x0), (r.height - 40) / (b.y1 - b.y0), 1.5);
    if (lesbar) z = Math.max(z, 0.6);
    g.zoom = Math.max(0.1, Math.min(4, z));
    g.tx = 20 - b.x0 * g.zoom + Math.max(0, (r.width - 40 - (b.x1 - b.x0) * g.zoom) / 2);
    g.ty = 20 - b.y0 * g.zoom;
    transform();
  }
  function zoomUm(faktor, cx, cy) {
    const neu = Math.max(0.1, Math.min(4, g.zoom * faktor));
    g.tx = cx - (cx - g.tx) * (neu / g.zoom); g.ty = cy - (cy - g.ty) * (neu / g.zoom); g.zoom = neu; transform();
  }
  function mitte() { const r = svg().getBoundingClientRect(); return [r.width / 2, r.height / 2]; }
  const weltPunkt = ev => { const r = svg().getBoundingClientRect(); return [(ev.clientX - r.left - g.tx) / g.zoom, (ev.clientY - r.top - g.ty) / g.zoom]; };

  // --- Maus --------------------------------------------------------------------------------------------------------
  let zug = null, speichernTimer = null;
  // Zoomleiste per Griff verschieben; gemerkt wird der Abstand zur rechten unteren Ecke (pro Browser)
  function zoomleisteVerschiebbar() {
    const leiste = $("#zoomleiste"), griff = $("#z-griff"), rahmen = leiste.parentElement, SCHLUESSEL = "dbstudio-zoomleiste";
    const setze = (r, b) => {
      const maxR = Math.max(0, rahmen.clientWidth - leiste.offsetWidth), maxB = Math.max(0, rahmen.clientHeight - leiste.offsetHeight);
      leiste.style.right = Math.max(0, Math.min(maxR, r)) + "px"; leiste.style.bottom = Math.max(0, Math.min(maxB, b)) + "px";
    };
    try { const a = JSON.parse(localStorage.getItem(SCHLUESSEL) || "null"); if (Array.isArray(a)) requestAnimationFrame(() => setze(a[0], a[1])); } catch (e) {}
    let start = null;
    griff.addEventListener("pointerdown", ev => {
      ev.preventDefault(); ev.stopPropagation(); griff.setPointerCapture(ev.pointerId);
      start = { x: ev.clientX, y: ev.clientY, r: parseFloat(getComputedStyle(leiste).right), b: parseFloat(getComputedStyle(leiste).bottom) };
      leiste.classList.add("zieht");
    });
    griff.addEventListener("pointermove", ev => { if (start) setze(start.r - (ev.clientX - start.x), start.b - (ev.clientY - start.y)); });
    griff.addEventListener("pointerup", () => {
      if (!start) return; start = null; leiste.classList.remove("zieht");
      try { localStorage.setItem(SCHLUESSEL, JSON.stringify([parseFloat(leiste.style.right), parseFloat(leiste.style.bottom)])); } catch (e) {}
    });
    griff.addEventListener("dblclick", ev => {
      ev.stopPropagation(); leiste.style.right = ""; leiste.style.bottom = "";
      try { localStorage.removeItem(SCHLUESSEL); } catch (e) {}
    });
    window.addEventListener("resize", () => { if (leiste.style.right) setze(parseFloat(leiste.style.right), parseFloat(leiste.style.bottom)); });
  }

  function positionenSpeichern() {
    clearTimeout(speichernTimer);
    speichernTimer = setTimeout(() => P().api(`/api/v/${P().zustand.vid}/erm/positionen`, { body: { schema: g.schema,
      positionen: Object.fromEntries(Object.entries(g.pos).map(([n, p]) => [n, [p.x, p.y]])) } }).catch(() => {}), 600);
  }
  function einrichten() {
    const s = svg();
    s.addEventListener("wheel", ev => {
      ev.preventDefault();
      const r = s.getBoundingClientRect();
      if (ev.shiftKey) { g.tx -= ev.deltaY; transform(); return; }
      zoomUm(ev.deltaY < 0 ? 1.12 : 1 / 1.12, ev.clientX - r.left, ev.clientY - r.top);
    }, { passive: false });
    s.addEventListener("mousedown", ev => {
      const zeile = ev.target.closest(".zeile"), kart = ev.target.closest(".erm-karte");
      if (zeile && kart && ev.button === 0 && !ev.altKey) {
        const [x, y] = weltPunkt(ev);
        zug = { art: "fk", von: kart.dataset.t, spalte: zeile.dataset.spalte, x0: x, y0: y, linie: el("path", { class: "ziehlinie" }, welt()) };
      } else if (kart && ev.button === 0) {
        const [x, y] = weltPunkt(ev); const p = g.pos[kart.dataset.t];
        zug = { art: "karte", name: kart.dataset.t, dx: x - p.x, dy: y - p.y };
      } else { zug = { art: "schieben", x: ev.clientX, y: ev.clientY, tx: g.tx, ty: g.ty }; s.classList.add("zieht"); }
    });
    window.addEventListener("mousemove", ev => {
      if (!zug) return;
      if (zug.art === "schieben") { g.tx = zug.tx + ev.clientX - zug.x; g.ty = zug.ty + ev.clientY - zug.y; transform(); }
      else if (zug.art === "karte") {
        const [x, y] = weltPunkt(ev);
        g.pos[zug.name] = { x: Math.round((x - zug.dx) / 20) * 20, y: Math.round((y - zug.dy) / 20) * 20 };
        g.karten[zug.name].gr.setAttribute("transform", `translate(${g.pos[zug.name].x},${g.pos[zug.name].y})`);
        const lin = $("#erm-linien"); lin.innerHTML = ""; linien(lin); zug.bewegt = true;
      } else if (zug.art === "fk") { const [x, y] = weltPunkt(ev); zug.linie.setAttribute("d", `M${zug.x0},${zug.y0} L${x},${y}`); }
    });
    window.addEventListener("mouseup", ev => {
      if (!zug) return;
      const z = zug; zug = null; s.classList.remove("zieht");
      if (z.art === "karte" && z.bewegt) positionenSpeichern();
      if (z.art === "fk") {
        z.linie.remove();
        const zeile = ev.target.closest && ev.target.closest(".zeile"), kart = ev.target.closest && ev.target.closest(".erm-karte");
        if (zeile && kart && kart.dataset.t !== z.von) fkDialog(z.von, z.spalte, kart.dataset.t, zeile.dataset.spalte);
      }
    });
    $("#z-plus").onclick = () => zoomUm(1.2, ...mitte());
    $("#z-minus").onclick = () => zoomUm(1 / 1.2, ...mitte());
    $("#z-100").onclick = () => { const b = grenzen(); g.zoom = 1; g.tx = 20 - b.x0; g.ty = 20 - b.y0; transform(); };
    $("#z-anpassen").onclick = () => anpassen(false);
    zoomleisteVerschiebbar();
    $("#z-wert").onclick = () => { const v = prompt("Zoom in %", Math.round(g.zoom * 100)); if (v && +v > 0) zoomUm((+v / 100) / g.zoom, ...mitte()); };
    document.addEventListener("keydown", ev => {
      if (!document.querySelector("#v-diagramm.aktiv") || /input|textarea|select/i.test(ev.target.tagName)) return;
      if (ev.key === "+" || ev.key === "=") zoomUm(1.2, ...mitte());
      if (ev.key === "-") zoomUm(1 / 1.2, ...mitte());
      if (ev.key === "0" && ev.ctrlKey) { ev.preventDefault(); anpassen(false); }
    });
    $("#erm-legende .kopfzeile").onclick = () => $("#erm-legende .inhalt-l").classList.toggle("versteckt");
    $("#erm-ansicht").onchange = () => { zeichnen(); };
    $("#erm-stil").onchange = () => { g.stilGesetzt = true; zeichnen(); };
    $("#erm-neu-laden").onclick = () => laden(P().zustand.schema, true);
    $("#erm-anordnen").onclick = () => { for (const [n, p] of Object.entries(g.modell.auto)) g.pos[n] = { x: p[0], y: p[1] }; zeichnen(); anpassen(true); positionenSpeichern(); };
    $("#erm-tabelle").onclick = tabelleDialog;
    $("#erm-spalte").onclick = spalteDialog;
    $("#erm-vorschlaege").onclick = vorschlaege;
    $("#erm-export").onchange = ev => { const v = ev.target.value; ev.target.value = ""; if (v === "svg") exportSvg(); if (v === "png") exportPng(); if (v === "cs") exportCs(); };
    $("#ddl-abbruch").onclick = () => $("#d-ddl").close();
  }

  // --- DDL-Dialoge -------------------------------------------------------------------------------------------------
  let ddlAnfrage = null;
  function ddlOeffnen(titel, formHtml, anfrage) {
    $("#ddl-titel").textContent = titel; $("#ddl-form").innerHTML = formHtml;
    $("#ddl-text").value = ""; $("#ddl-los").disabled = true; $("#ddl-hinweise").classList.add("versteckt");
    ddlAnfrage = anfrage;
    $("#ddl-vorschau").classList.toggle("versteckt", !anfrage);
    $("#ddl-vorschau").onclick = async () => {
      try {
        const r = await P().api(`/api/v/${P().zustand.vid}/erm/ddl`, { body: { schema: g.schema, ...ddlAnfrage() } });
        $("#ddl-text").value = r.anweisungen.join(";\n\n") + ";"; $("#ddl-los").disabled = !!g.modell.schreibschutz;
        const h = $("#ddl-hinweise"), folgen = r.folgen || [];
        h.classList.toggle("versteckt", !r.hinweise.length && !folgen.length);
        h.innerHTML = [...folgen.map(f => `<div class="folge ${f.stufe}">${f.stufe === "gefahr" ? "⚠ " : "ℹ "}${P().esc(f.text)}</div>`),
                       ...r.hinweise.map(x => `<div>${P().esc(x)}</div>`)].join("");
      } catch (e) { P().toast(e.message, "fehler"); }
    };
    $("#ddl-text").oninput = () => { $("#ddl-los").disabled = !$("#ddl-text").value.trim() || !!g.modell.schreibschutz; };
    $("#ddl-los").onclick = () => ddlAusfuehren(false);
    $("#ddl-editor").onclick = () => { P().neuerTab($("#ddl-text").value); $("#d-ddl").close(); P().zeige("editor"); };
    $("#d-ddl").showModal();
  }
  function anweisungenAusText(t) {
    return t.split(/;\s*\n/).map(s => s.trim().replace(/;$/, "")).filter(Boolean);
  }
  async function ddlAusfuehren(bestaetigt) {
    try {
      await P().api(`/api/v/${P().zustand.vid}/erm/ausfuehren`, { body: { anweisungen: anweisungenAusText($("#ddl-text").value), bestaetigt } });
      $("#d-ddl").close(); P().toast("Struktur geändert."); laden(g.schema, true);
    } catch (e) {
      if (e.rueckfrage) { if (await P().rueckfrage(e.rueckfrage)) ddlAusfuehren(true); }
      else P().toast(e.message, "fehler");
    }
  }
  const typOptionen = () => g.modell.typen.map(t => `<option>${t}</option>`).join("");
  const tabOptionen = (wert = "") => g.modell.tabellen.map(t => `<option ${t.name === wert ? "selected" : ""}>${P().esc(t.name)}</option>`).join("");
  const AKTIONEN = ["NO ACTION", "CASCADE", "SET NULL", "RESTRICT"].map(a => `<option>${a}</option>`).join("");

  function spaltenZeile(name = "", typ = "text", pk = false) {
    return `<div class="z"><input class="sp-name" placeholder="Spaltenname" value="${P().esc(name)}"><select class="sp-typ">${typOptionen()}</select>
      <label class="schalter"><input type="checkbox" class="sp-pk" ${pk ? "checked" : ""}>PK</label><label class="schalter"><input type="checkbox" class="sp-nn" ${pk ? "checked" : ""}>NOT NULL</label>
      <button class="knopf klein sp-weg" type="button">×</button></div>`;
  }
  function tabelleDialog() {
    ddlOeffnen("Neue Tabelle", `<label class="feld">Tabellenname<input id="dn-name"></label>
      <div class="spaltenliste" id="dn-spalten">${spaltenZeile("id", "grosse_ganzzahl", true)}${spaltenZeile("name", "text")}</div>
      <button class="knopf klein" type="button" id="dn-mehr">＋ Spalte</button>`, () => ({
      aktion: "tabelle", tabelle: $("#dn-name").value.trim(),
      spalten: [...document.querySelectorAll("#dn-spalten .z")].map(z => ({ name: z.querySelector(".sp-name").value.trim(), typ: z.querySelector(".sp-typ").value,
        pk: z.querySelector(".sp-pk").checked, nullbar: !z.querySelector(".sp-nn").checked })).filter(s => s.name) }));
    document.querySelectorAll("#dn-spalten .z").forEach((z, i) => { z.querySelector(".sp-typ").value = i ? "text" : "grosse_ganzzahl"; });
    $("#dn-mehr").onclick = () => { $("#dn-spalten").insertAdjacentHTML("beforeend", spaltenZeile()); weg(); };
    const weg = () => document.querySelectorAll(".sp-weg").forEach(b => b.onclick = () => b.parentElement.remove()); weg();
  }
  function spalteDialog() {
    ddlOeffnen("Spalte hinzufügen", `<div class="gitter" style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
      <label class="feld">Tabelle<select id="ds-tab">${tabOptionen()}</select></label><label class="feld">Name<input id="ds-name"></label>
      <label class="feld">Typ<select id="ds-typ">${typOptionen()}</select></label><label class="schalter" style="align-self:end"><input type="checkbox" id="ds-nn"> NOT NULL</label></div>`,
    () => ({ aktion: "spalte", tabelle: $("#ds-tab").value, spalte: { name: $("#ds-name").value.trim(), typ: $("#ds-typ").value, nullbar: !$("#ds-nn").checked } }));
    $("#ds-typ").value = "text";
  }
  function fkDialog(von, spalte, nach, zielSpalte) {
    ddlOeffnen("Beziehung anlegen", `<div class="meldung ok">${P().esc(von)}.${P().esc(spalte)} → ${P().esc(nach)}.${P().esc(zielSpalte)}</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px"><label class="feld">ON DELETE<select id="df-del">${AKTIONEN}</select></label>
      <label class="feld">ON UPDATE<select id="df-upd">${AKTIONEN}</select></label></div>`,
    () => ({ aktion: "fk", tabelle: von, fk_spalten: [spalte], ziel: nach, ziel_spalten: [zielSpalte], bei_loeschen: $("#df-del").value, bei_aendern: $("#df-upd").value }));
  }
  async function vorschlaege() {
    try {
      const liste = await P().api(`/api/v/${P().zustand.vid}/erm/vorschlaege?schema=${encodeURIComponent(g.schema)}`);
      if (!liste.length) { P().toast("Keine fehlenden Beziehungen gefunden (Namensregel). Für weitere Ideen: KI im SQL-Editor."); return; }
      ddlOeffnen("Beziehungen vorschlagen", `<div class="gedimmt">Gefunden über die Namensregel (z. B. kunde_id → kunden.id). Nichts wird automatisch ausgeführt.</div>` +
        liste.map((v, i) => `<label class="schalter"><input type="checkbox" class="vs" data-i="${i}" checked> ${P().esc(v.tabelle)}.${P().esc(v.spalten.join(","))} → ${P().esc(v.ziel)}.${P().esc(v.ziel_spalten.join(","))}</label>`).join(""), null);
      const aktualisieren = () => { $("#ddl-text").value = liste.filter((_, i) => document.querySelector(`.vs[data-i="${i}"]`).checked).flatMap(v => v.anweisungen).map(a => a + ";").join("\n\n");
        $("#ddl-los").disabled = !$("#ddl-text").value || !!g.modell.schreibschutz; };
      document.querySelectorAll(".vs").forEach(c => c.onchange = aktualisieren); aktualisieren();
    } catch (e) { P().toast(e.message, "fehler"); }
  }

  // --- Export ------------------------------------------------------------------------------------------------------
  function svgText() {
    const kopie = svg().cloneNode(true);
    const st = getComputedStyle(document.documentElement);
    const vars = ["--bg", "--karte", "--sidebar", "--rand", "--text", "--gedimmt", "--akzent", "--blau", "--neon", "--aktiv"];
    let css = [...document.styleSheets].flatMap(s => { try { return [...s.cssRules]; } catch (e) { return []; } })
      .map(r => r.cssText).filter(t => /erm-|plakette|\.zeile|\.strich|\.fang/.test(t)).join("\n");
    for (const v of vars) css = css.replaceAll(`var(${v})`, st.getPropertyValue(v).trim());
    const b = grenzen();
    kopie.querySelector("#erm-welt").setAttribute("transform", `translate(${20 - b.x0},${20 - b.y0})`);
    kopie.setAttribute("width", b.x1 - b.x0 + 40); kopie.setAttribute("height", b.y1 - b.y0 + 40);
    kopie.setAttribute("viewBox", `0 0 ${b.x1 - b.x0 + 40} ${b.y1 - b.y0 + 40}`);
    kopie.classList.remove("gedimmt-modus");
    const bg = document.createElementNS(NS, "rect"); bg.setAttribute("width", "100%"); bg.setAttribute("height", "100%"); bg.setAttribute("fill", st.getPropertyValue("--bg").trim());
    kopie.prepend(bg);
    const style = document.createElementNS(NS, "style"); style.textContent = css; kopie.prepend(style);
    kopie.querySelectorAll("[style]").forEach(e => { for (const v of vars) e.setAttribute("style", e.getAttribute("style").replaceAll(`var(${v})`, st.getPropertyValue(v).trim())); });
    return { text: new XMLSerializer().serializeToString(kopie), w: b.x1 - b.x0 + 40, h: b.y1 - b.y0 + 40 };
  }
  function laden_(blob, name) { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); }
  function exportSvg() { laden_(new Blob([svgText().text], { type: "image/svg+xml" }), `${g.schema}-diagramm.svg`); }
  function exportPng() {
    const { text, w, h } = svgText(), img = new Image(), skala = 2;
    img.onload = () => { const c = document.createElement("canvas"); c.width = w * skala; c.height = h * skala;
      const k = c.getContext("2d"); k.scale(skala, skala); k.drawImage(img, 0, 0); c.toBlob(b => laden_(b, `${g.schema}-diagramm.png`)); };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(text);
  }
  function exportCs() {
    const a = document.createElement("a"); a.href = `/api/v/${P().zustand.vid}/dbcontext?schema=${encodeURIComponent(g.schema)}`; a.download = "AppDbContext.cs"; a.click();
  }

  document.addEventListener("DOMContentLoaded", einrichten);
  if (document.readyState !== "loading") einrichten();
  return { laden, anpassen, zustand: g };
})();
