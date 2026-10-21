"use strict";

/* Gemeinsames Skript für Übersicht und Einzelansicht.
 *
 * Ohne JavaScript funktioniert der Stream trotzdem: Das Bild steckt in
 * einem gewöhnlichen <img>-Tag. Dieses Skript ergänzt nur das
 * Wiederverbinden nach Abbruch, Pause, Vollbild und die Statusanzeige.
 */

function webcamStart(einstellungen) {
  const bilder = Array.from(einstellungen.bilder || []);
  const meldung = document.getElementById("meldung");
  const statusbereich = document.getElementById("status");
  const knopfPause = einstellungen.pause || null;
  const knopfVollbild = einstellungen.vollbild || null;
  const kennung = einstellungen.kennung || null;

  let pausiert = false;

  const sagen = (text, art) => {
    if (!meldung) return;
    meldung.textContent = text;
    if (art) { meldung.dataset.art = art; } else { delete meldung.dataset.art; }
  };

  const streamAdresse = (bild) =>
    "/kamera/" + bild.dataset.kennung + "/stream.mjpg?t=" + Date.now();

  const neuVerbinden = (bild) => {
    if (pausiert) return;
    bild.src = streamAdresse(bild);
  };

  // Jedes Bild bekommt seine eigene Fehlerbehandlung. Auf der Übersicht
  // soll eine ausgefallene Kamera die anderen nicht mitnehmen.
  bilder.forEach((bild) => {
    let versuche = 0;

    bild.addEventListener("load", () => {
      versuche = 0;
      if (!pausiert) sagen("");
    });

    bild.addEventListener("error", () => {
      if (pausiert) return;
      versuche += 1;
      // Wartezeit wächst bis 30 s, damit eine dauerhaft fehlende Kamera
      // nicht endlos im Sekundentakt angefragt wird.
      const wartezeit = Math.min(3000 * versuche, 30000);
      const name = bild.dataset.kennung || "Kamera";
      sagen(
        "Kein Bild von " + name + ". Neuer Versuch in " +
        Math.round(wartezeit / 1000) + " Sekunden \u2026",
        "fehler"
      );
      setTimeout(() => neuVerbinden(bild), wartezeit);
    });
  });

  if (knopfPause) {
    knopfPause.addEventListener("click", () => {
      pausiert = !pausiert;
      knopfPause.textContent = pausiert ? "Weiter" : "Pause";
      knopfPause.setAttribute("aria-pressed", String(pausiert));
      bilder.forEach((bild) => {
        if (pausiert) {
          // Das Einzelbild beendet die Streamverbindung, die Kamera wird
          // nach der Leerlaufzeit freigegeben.
          bild.src = "/kamera/" + bild.dataset.kennung +
                     "/snapshot.jpg?t=" + Date.now();
        } else {
          bild.src = streamAdresse(bild);
        }
      });
      sagen(pausiert ? "Angehalten. Es wird nur das letzte Einzelbild gezeigt." : "");
    });
  }

  if (knopfVollbild) {
    knopfVollbild.addEventListener("click", () => {
      const rahmen = bilder[0] ? bilder[0].parentElement : null;
      if (document.fullscreenElement) {
        document.exitFullscreen();
      } else if (rahmen && rahmen.requestFullscreen) {
        rahmen.requestFullscreen().catch(
          () => sagen("Vollbild nicht möglich.", "fehler")
        );
      }
    });
  }

  /* --- Statusanzeige --- */

  const beschriftung = {
    name: "Name",
    kamera_laeuft: "Kamera aktiv",
    zuschauer: "Zuschauer",
    geraet: "Gerät",
    "auflösung": "Auflösung",
    bildrate_soll: "Bildrate (Soll)",
    bildrate_ist: "Bildrate (gemessen)",
    jpeg_qualitaet: "JPEG-Qualität",
    frames_gesamt: "Bilder gesamt",
    letzter_frame_alter_s: "Letztes Bild vor (s)",
    laufzeit_s: "Laufzeit (s)",
    letzter_fehler: "Letzter Fehler"
  };

  const alsText = (wert) => {
    if (wert === true) return "ja";
    if (wert === false) return "nein";
    if (wert === null || wert === undefined) return "\u2013";
    return String(wert);
  };

  const listeBauen = (daten) => {
    const liste = document.createElement("dl");
    liste.className = "status";
    for (const [schluessel, wert] of Object.entries(daten)) {
      const dt = document.createElement("dt");
      dt.textContent = beschriftung[schluessel] || schluessel;
      const dd = document.createElement("dd");
      dd.textContent = alsText(wert);
      liste.append(dt, dd);
    }
    return liste;
  };

  const statusHolen = async () => {
    if (!statusbereich) return;
    try {
      const antwort = await fetch("/status.json", { cache: "no-store" });
      if (!antwort.ok) throw new Error(String(antwort.status));
      const daten = await antwort.json();

      const neu = document.createDocumentFragment();

      const allgemein = listeBauen({
        "Streams aktiv": daten.streams_aktiv,
        "Streams Grenze": daten.streams_grenze,
        "Anmeldung": daten.authentifizierung
      });
      neu.append(allgemein);

      // Auf der Einzelansicht nur die eigene Kamera zeigen.
      const eintraege = Object.entries(daten.kameras || {}).filter(
        ([kurz]) => !kennung || kurz === kennung
      );
      for (const [kurz, zustand] of eintraege) {
        const block = document.createElement("section");
        block.className = "statusblock";
        const titel = document.createElement("h3");
        titel.textContent = zustand.name || kurz;
        block.append(titel, listeBauen(zustand));
        neu.append(block);
      }

      statusbereich.replaceChildren(neu);
    } catch (fehler) {
      const hinweis = document.createElement("p");
      hinweis.className = "unterzeile";
      hinweis.textContent = "Status nicht abrufbar.";
      statusbereich.replaceChildren(hinweis);
    }
  };

  statusHolen();
  setInterval(statusHolen, 5000);
}
