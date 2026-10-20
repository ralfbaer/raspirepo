"""
Schulportal — Liest Unterrichtsdaten aus dem Schulportal Hessen.

Ablauf:
  1. Login
  2. Übersichtsseite "Mein Unterricht" öffnen
  3. Pro Fach: auf der Übersichtsseite "alle Einträge" klicken
  4. Auf der Detailseite die Tabelle lesen
  5. Zurück zur Übersicht, nächstes Fach
  6. Zusammenfassung schreiben
"""

import os
import sys
import time

projektroot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, projektroot)

from base_resources.startup import initialisierung, beenden


def login(page, login_url, benutzername, kennwort, log):
    """Loggt sich im Schulportal ein."""
    log.info("Öffne Login-Seite: %s", login_url)
    page.goto(login_url, wait_until="networkidle")
    time.sleep(3)

    # "Login mit Schulbezug" auswählen
    try:
        loc = page.locator('a:has-text("Zum Login"):visible')
        if loc.count() > 0:
            log.info("Klicke 'Login mit Schulbezug'")
            loc.last.click()
            page.wait_for_load_state("networkidle")
            time.sleep(3)
    except Exception:
        pass

    # Benutzername
    log.info("Gebe Benutzername ein: %s", benutzername)
    for sel in ['input[name="user2"]', 'input[name="user"]',
                'input[name="username"]', 'input[type="text"]']:
        user_field = page.query_selector(sel)
        if user_field:
            break
    if not user_field:
        log.error("Benutzername-Feld nicht gefunden!")
        page.screenshot(path=os.path.join(os.path.dirname(__file__), "login_debug.png"))
        return False
    user_field.fill(benutzername)

    # Kennwort
    for sel in ['input[name="user3"]', 'input[name="password"]', 'input[type="password"]']:
        pwd_field = page.query_selector(sel)
        if pwd_field:
            break
    if not pwd_field:
        log.error("Kennwort-Feld nicht gefunden!")
        return False
    pwd_field.fill(kennwort)

    # Login-Button
    for sel in ['button:has-text("Anmelden"):visible', 'button:has-text("Login"):visible',
                'input[type="submit"]:visible', 'button[type="submit"]:visible']:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click(timeout=5000)
                break
        except Exception:
            continue
    else:
        pwd_field.press("Enter")

    page.wait_for_load_state("networkidle")
    time.sleep(3)
    log.info("Login erfolgreich")
    return True


def faecher_und_buttons_sammeln(page, log):
    """
    Sammelt auf der Übersichtsseite alle Fächer mit ihren 'alle Einträge'-Links.
    Nutzt die href-URLs der Links, um Duplikate zu erkennen und zu entfernen.
    """
    faecher = []
    gesehene_urls = set()

    # Alle "alle Einträge"-Links finden
    alle_links = page.query_selector_all(
        'a:has-text("alle Einträge"), a:has-text("Alle Einträge")'
    )

    log.info("%d 'alle Einträge'-Links gefunden (vor Deduplizierung)", len(alle_links))

    for link in alle_links:
        href = link.get_attribute("href") or ""
        if not href:
            continue

        # Relative URLs auflösen
        if href.startswith("/"):
            href = f"https://start.schulportal.hessen.de{href}"
        elif not href.startswith("http"):
            href = f"https://start.schulportal.hessen.de/{href}"

        # Duplikate überspringen
        if href in gesehene_urls:
            continue
        gesehene_urls.add(href)

        # Fachname aus dem umgebenden Container ermitteln
        fach_name = ""
        try:
            container = link.evaluate_handle(
                '(el) => el.closest(".panel, .card, .col-md-6, .col-lg-4, [class*=kurs], [class*=fach], tr, .row, div")'
            )
            if container:
                header = container.as_element().query_selector('h3, h4, h2, .panel-title, .card-title, strong, b, span.name')
                if header:
                    fach_name = header.inner_text().strip()
        except Exception:
            pass

        if not fach_name:
            fach_name = f"Fach_{len(faecher) + 1}"

        # "Abgabe"-Button im Fach-Umfeld (Tabellenzeile) suchen.
        # Auf der Übersicht sitzt über "alle Einträge" ggf. ein Warnungs-Button,
        # dessen Text "Abgabe" enthält (z.B. "Abgabe" oder "1 offene Abgabe").
        abgabe = ""
        try:
            tr = link.evaluate_handle('(el) => el.closest("tr")')
            tr_el = tr.as_element()
            if tr_el:
                for knopf in tr_el.query_selector_all("a, button"):
                    knopf_text = " ".join((knopf.inner_text() or "").split())
                    if "Abgabe" in knopf_text:
                        abgabe = knopf_text
                        break
        except Exception:
            pass

        faecher.append({"name": fach_name, "url": href, "abgabe": abgabe})
        log.info("  [%d] %s → %s%s", len(faecher), fach_name, href,
                 f"  [Abgabe: {abgabe}]" if abgabe else "")

    log.info("%d eindeutige Fächer gefunden", len(faecher))
    return faecher


def eintraege_lesen(page, fach_name, log):
    """Liest die Tabellenzeilen auf der Fach-Detailseite."""
    import re
    eintraege = []
    try:
        zeilen = page.query_selector_all('table tbody tr')
        log.info("  %d Zeilen gefunden", len(zeilen))

        for zeile in zeilen:
            zellen = zeile.query_selector_all('td')
            if len(zellen) < 2:
                continue

            # Alle Zelltexte einzeilig machen (Zeilenumbrüche entfernen)
            texte = [" ".join(z.inner_text().strip().split()) for z in zellen]

            # Datum: nur das Datum extrahieren (DD.MM.YYYY), Stundenangabe entfernen
            datum_roh = texte[0] if len(texte) > 0 else ""
            datum_match = re.match(r"(\d{2}\.\d{2}\.\d{4})", datum_roh)
            if not datum_match:
                # Zeile ohne gültiges Datum überspringen (z.B. Hashes, Token)
                continue
            datum = datum_match.group(1)

            eintrag = {
                "datum": datum,
                "thema": texte[1] if len(texte) > 1 else "",
                "anwesenheit": texte[2] if len(texte) > 2 else "",
                "hausaufgabe": texte[3] if len(texte) > 3 else "",
            }

            # Hausaufgabe aus dem Thema-Text extrahieren (falls dort eingebettet)
            thema = eintrag["thema"]
            if not eintrag["hausaufgabe"]:
                thema_lower = thema.lower()
                if "hausaufgabe unerledigt" in thema_lower:
                    eintrag["hausaufgabe"] = "unerledigt"
                    # Hausaufgabe-Text aus Thema entfernen
                    idx = thema_lower.find("hausaufgabe unerledigt")
                    eintrag["thema"] = thema[:idx].strip()
                elif "hausaufgabe erledigt" in thema_lower:
                    eintrag["hausaufgabe"] = "erledigt"
                    idx = thema_lower.find("hausaufgabe erledigt")
                    eintrag["thema"] = thema[:idx].strip()
            eintraege.append(eintrag)

    except Exception as exc:
        log.error("Fehler beim Lesen der Einträge für %s: %s", fach_name, exc)

    log.info("  %d Einträge gelesen", len(eintraege))
    return eintraege


def klassenarbeit_ermitteln(page, log):
    """
    Sucht auf der Fach-Detailseite die erste Tabellenzeile (von oben), deren
    Thema das Wort 'Klassenarbeit' enthält, und liefert deren Datum zurück.

    Es wird nur der erste Treffer vermerkt. Kein Treffer → leerer String.
    """
    import re
    try:
        zeilen = page.query_selector_all("table tbody tr")
        for zeile in zeilen:
            zeilen_text = zeile.inner_text() or ""
            if "Klassenarbeit" not in zeilen_text:
                continue
            zellen = zeile.query_selector_all("td")
            if not zellen:
                continue
            # Datum steht in der ersten Zelle (z.B. "15.09.2026 3. - 4. Stunde")
            datum_roh = " ".join((zellen[0].inner_text() or "").strip().split())
            datum_match = re.match(r"(\d{2}\.\d{2}\.\d{4})", datum_roh)
            datum = datum_match.group(1) if datum_match else datum_roh
            log.info("  Klassenarbeit gefunden: %s", datum)
            return datum
    except Exception as exc:
        log.warning("Fehler beim Ermitteln der Klassenarbeit: %s", exc)
    return ""


def ist_auffaellig(eintrag):
    """Prüft ob ein Eintrag auffällig ist (nicht anwesend/entschuldigt oder Hausaufgabe unerledigt)."""
    anwesenheit = eintrag.get("anwesenheit", "").lower().strip()
    hausaufgabe = eintrag.get("hausaufgabe", "").lower().strip()

    # Auffällig wenn nicht "anwesend" und nicht "entschuldigt" (und nicht leer)
    if anwesenheit and anwesenheit not in ("anwesend", "entschuldigt", "nicht erfasst", "-", ""):
        return True
    # Auffällig wenn Hausaufgabe "unerledigt" enthält
    if hausaufgabe and "unerledigt" in hausaufgabe:
        return True
    return False


def sichtbare_eintraege(eintraege, immer_anzeigen, max_zeilen_pro_fach):
    """
    Ermittelt die anzuzeigenden Einträge eines Fachs.

    Regel: Die ersten `immer_anzeigen` Einträge werden immer angezeigt, danach
    nur noch auffällige (siehe `ist_auffaellig`). `max_zeilen_pro_fach` begrenzt
    die Gesamtzahl (0 = unbegrenzt). So zeigen .txt und PDF garantiert dieselben
    Zeilen.
    """
    sichtbare = []
    for i, eintrag in enumerate(eintraege):
        if i >= immer_anzeigen and not ist_auffaellig(eintrag):
            continue
        sichtbare.append(eintrag)

    if max_zeilen_pro_fach and len(sichtbare) > max_zeilen_pro_fach:
        sichtbare = sichtbare[:max_zeilen_pro_fach]

    return sichtbare


def zusammenfassung_schreiben(alle_daten, ausgabe_pfad, immer_anzeigen, max_zeilen_pro_fach, log):
    """Schreibt die Zusammenfassung als Textdatei und als PDF-Tabelle."""
    from datetime import datetime
    heute = datetime.now().strftime("%d.%m.%Y")

    zeilen = []
    zeilen.append("=" * 110)
    zeilen.append("SCHULPORTAL — ZUSAMMENFASSUNG")
    zeilen.append("=" * 110)
    zeilen.append(f"{'Fach':<30} | {'Datum':<14} | {'Thema':<80} | {'Anwesenheit':<12} | {'Hausaufgabe':<12}")
    zeilen.append("-" * 110)

    for fach_daten in alle_daten:
        fach = fach_daten["fach"]
        sichtbare = sichtbare_eintraege(fach_daten["eintraege"], immer_anzeigen, max_zeilen_pro_fach)

        erste_zeile_fach = True
        for j, eintrag in enumerate(sichtbare):
            marker = "->" if eintrag["datum"] == heute else "  "
            datum_str = f"{marker}{eintrag['datum']}"

            # Fachname nur in der ersten Zeile
            fach_anzeige = fach[:30] if erste_zeile_fach else ""
            erste_zeile_fach = False

            # Trennzeichen: ┬ für erste Zeile, ┴ für letzte, | dazwischen
            if len(sichtbare) == 1:
                sep = "┬┴"
            elif j == 0:
                sep = "┬"
            elif j == len(sichtbare) - 1:
                sep = "┴"
            else:
                sep = "|"

            zeilen.append(
                f"{fach_anzeige:<30} {sep} "
                f"{datum_str:<14} {sep} "
                f"{eintrag['thema'][:80]:<80} {sep} "
                f"{eintrag['anwesenheit'][:12]:<12} {sep} "
                f"{eintrag['hausaufgabe'][:12]}"
            )

    zeilen.append("")

    with open(ausgabe_pfad, "w", encoding="utf-8") as f:
        f.write("\n".join(zeilen) + "\n")

    log.info("Zusammenfassung geschrieben: %s (%d Zeilen)", ausgabe_pfad, len(zeilen))

    # PDF als echte Tabelle erzeugen
    pdf_pfad = ausgabe_pfad.replace(".txt", ".pdf")
    pdf_tabelle_schreiben(alle_daten, pdf_pfad, immer_anzeigen, max_zeilen_pro_fach, heute, log)


def pdf_tabelle_schreiben(alle_daten, pdf_pfad, immer_anzeigen, max_zeilen_pro_fach, heute, log):
    """
    Erzeugt das Zusammenfassungs-PDF als echte Tabelle (fpdf2 table()-API).

    Spalten: Fach | Datum | Thema | Anwesenheit | Hausaufgabe | Abgabe | Klassenarbeit
    Fach/Abgabe/Klassenarbeit erscheinen nur in der ersten Zeile des jeweiligen Fachs.
    Heutige Einträge werden dezent hinterlegt.
    """
    try:
        from fpdf import FPDF
        from fpdf.fonts import FontFace

        schrift_regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        schrift_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

        pdf = FPDF(orientation="L", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=10)
        pdf.add_page()
        pdf.add_font("DejaVu", "", schrift_regular)
        pdf.add_font("DejaVu", "B", schrift_bold)

        # Titel
        pdf.set_font("DejaVu", "B", 12)
        pdf.cell(0, 8, "Schulportal — Zusammenfassung", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("DejaVu", "", 8)
        pdf.cell(0, 5, f"Stand: {heute}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        spalten = ["Fach", "Datum", "Thema", "Anwesenheit", "Hausaufgabe", "Abgabe", "Klassenarbeit"]
        # Spaltenbreiten in mm (Summe ~277 mm nutzbare Breite im A4-Querformat)
        breiten = (48, 22, 108, 24, 24, 24, 27)

        with pdf.table(
            col_widths=breiten,
            text_align=("LEFT", "LEFT", "LEFT", "LEFT", "LEFT", "LEFT", "LEFT"),
            line_height=5,
            first_row_as_headings=True,
            headings_style=FontFace(emphasis="BOLD", fill_color=(60, 90, 130), color=(255, 255, 255)),
            borders_layout="ALL",
        ) as tabelle:
            # Kopfzeile
            kopf = tabelle.row()
            for titel in spalten:
                kopf.cell(titel)

            for fach_daten in alle_daten:
                fach = fach_daten["fach"]
                abgabe = fach_daten.get("abgabe", "")
                klassenarbeit = fach_daten.get("klassenarbeit", "")
                sichtbare = sichtbare_eintraege(fach_daten["eintraege"], immer_anzeigen, max_zeilen_pro_fach)

                erste = True
                for eintrag in sichtbare:
                    # Heutige Einträge dezent blau hinterlegen (Zeilen-Style)
                    zeilen_stil = FontFace(fill_color=(235, 245, 255)) if eintrag["datum"] == heute else None
                    zeile = tabelle.row(style=zeilen_stil)

                    hausaufgabe = eintrag["hausaufgabe"]
                    abgabe_zelle = abgabe if erste else ""
                    klassenarbeit_zelle = klassenarbeit if erste else ""

                    # Dezent rot: Hausaufgabe nicht "erledigt" (aber nicht leer),
                    # Anwesenheit "fehlend", sowie Abgabe/Klassenarbeit wenn
                    # etwas eingetragen ist.
                    rot = FontFace(fill_color=(255, 224, 224))
                    anwesenheit = eintrag["anwesenheit"]
                    stil_anwesenheit = rot if "fehlend" in anwesenheit.lower() else None
                    stil_hausaufgabe = rot if hausaufgabe.strip() and hausaufgabe.strip().lower() != "erledigt" else None
                    stil_abgabe = rot if abgabe_zelle.strip() else None
                    stil_klassenarbeit = rot if klassenarbeit_zelle.strip() else None

                    zeile.cell(fach if erste else "")
                    zeile.cell(eintrag["datum"])
                    zeile.cell(eintrag["thema"])
                    zeile.cell(anwesenheit, style=stil_anwesenheit)
                    zeile.cell(hausaufgabe, style=stil_hausaufgabe)
                    zeile.cell(abgabe_zelle, style=stil_abgabe)
                    zeile.cell(klassenarbeit_zelle, style=stil_klassenarbeit)
                    erste = False

        pdf.output(pdf_pfad)
        log.info("PDF geschrieben: %s", pdf_pfad)
    except Exception as exc:
        log.warning("PDF konnte nicht erstellt werden: %s", exc)


def fehlend_schreiben(alle_daten, ausgabe_pfad, log):
    """Schreibt eine Liste aller Einträge mit Anwesenheit 'fehlend' in eine Textdatei."""
    zeilen = []
    zeilen.append("=" * 60)
    zeilen.append("FEHLEND — Unentschuldigte Abwesenheiten")
    zeilen.append("=" * 60)
    zeilen.append(f"{'Fach':<30} | {'Datum':<14} | {'Anwesenheit':<12}")
    zeilen.append("-" * 60)

    letztes_fach = ""
    for fach_daten in alle_daten:
        fach = fach_daten["fach"]
        for eintrag in fach_daten["eintraege"]:
            if "fehlend" in eintrag.get("anwesenheit", "").lower():
                fach_anzeige = fach[:30] if fach != letztes_fach else ""
                letztes_fach = fach
                zeilen.append(
                    f"{fach_anzeige:<30} | "
                    f"{eintrag['datum']:<14} | "
                    f"{eintrag['anwesenheit'][:12]}"
                )

    zeilen.append("")

    with open(ausgabe_pfad, "w", encoding="utf-8") as f:
        f.write("\n".join(zeilen) + "\n")

    log.info("Fehlend-Liste geschrieben: %s", ausgabe_pfad)


def themen_schreiben(alle_daten, ausgabe_pfad, log):
    """
    Schreibt alle Themen in eine Textdatei (Fach, Datum, Thema).

    Beim ersten Lauf wird die Datei komplett erstellt.
    Bei weiteren Läufen werden neue Einträge pro Fach oben in die
    jeweilige Fach-Sektion eingefügt (neueste zuerst).
    Bereits vorhandene Einträge (anhand Fach+Datum) werden nicht dupliziert.
    """
    # Alle aktuellen Einträge pro Fach sammeln
    fach_eintraege = {}
    for fach_daten in alle_daten:
        fach = fach_daten["fach"]
        if fach not in fach_eintraege:
            fach_eintraege[fach] = []
        for eintrag in fach_daten["eintraege"]:
            datum = eintrag.get("datum", "")
            if datum:
                fach_eintraege[fach].append((datum, eintrag.get("thema", "")))

    # Bestehende Datei einlesen und pro Fach parsen
    bestehende_faecher = {}  # fach → [(datum, thema), ...]
    if os.path.exists(ausgabe_pfad):
        aktuelles_fach = ""
        with open(ausgabe_pfad, "r", encoding="utf-8") as f:
            for zeile in f:
                z = zeile.rstrip("\n")
                # Header-Zeilen überspringen
                if z.startswith("=") or z.startswith("-") or z.startswith("Fach") or z.startswith("THEMEN"):
                    continue
                teile = z.split("|")
                if len(teile) >= 3:
                    fach_teil = teile[0].strip()
                    datum_teil = teile[1].strip()
                    thema_teil = teile[2].strip()
                    if fach_teil:
                        aktuelles_fach = fach_teil
                    if aktuelles_fach and datum_teil:
                        if aktuelles_fach not in bestehende_faecher:
                            bestehende_faecher[aktuelles_fach] = []
                        bestehende_faecher[aktuelles_fach].append((datum_teil, thema_teil))

    # Pro Fach: nur Einträge einfügen, die neuer sind als der neueste in der Datei
    ergebnis_faecher = {}
    neue_gesamt = 0
    alle_fach_namen = list(fach_eintraege.keys())

    for fach in alle_fach_namen:
        bestehende = bestehende_faecher.get(fach, [])
        bestehende_daten = {d for d, _ in bestehende}

        # Neuestes Datum in der bestehenden Datei ermitteln
        neuestes_bestehendes = ""
        for d, _ in bestehende:
            # Datum im Format DD.MM.YYYY → vergleichbar machen
            try:
                teile = d.split(".")
                if len(teile) == 3:
                    vergleich = f"{teile[2]}{teile[1]}{teile[0]}"
                    if vergleich > neuestes_bestehendes:
                        neuestes_bestehendes = vergleich
            except Exception:
                pass

        # Neue Einträge: im Portal vorhanden, nicht in der Datei, UND neuer als der neueste bestehende
        neue = []
        for d, t in fach_eintraege[fach]:
            if d in bestehende_daten:
                continue
            # Nur einfügen wenn neuer als der neueste bestehende Eintrag
            try:
                teile = d.split(".")
                if len(teile) == 3:
                    vergleich = f"{teile[2]}{teile[1]}{teile[0]}"
                    if neuestes_bestehendes and vergleich <= neuestes_bestehendes:
                        continue
            except Exception:
                pass
            neue.append((d, t))

        neue_gesamt += len(neue)

        # Neue oben, bestehende unten
        ergebnis_faecher[fach] = neue + bestehende

    # Fächer die nur in der bestehenden Datei sind (nicht mehr im Portal)
    for fach, eintraege in bestehende_faecher.items():
        if fach not in ergebnis_faecher:
            ergebnis_faecher[fach] = eintraege

    # Datei komplett neu schreiben
    zeilen = []
    zeilen.append("=" * 130)
    zeilen.append("THEMEN — Alle Unterrichtsthemen")
    zeilen.append("=" * 130)
    zeilen.append(f"{'Fach':<30} | {'Datum':<14} | {'Thema':<80}")
    zeilen.append("-" * 130)

    for fach in ergebnis_faecher:
        erste_zeile = True
        for datum, thema in ergebnis_faecher[fach]:
            fach_anzeige = fach[:30] if erste_zeile else ""
            erste_zeile = False
            zeilen.append(
                f"{fach_anzeige:<30} | "
                f"{datum:<14} | "
                f"{thema[:80]}"
            )

    with open(ausgabe_pfad, "w", encoding="utf-8") as f:
        f.write("\n".join(zeilen) + "\n")

    if neue_gesamt > 0:
        log.info("Themen-Liste aktualisiert: %s (%d neue Einträge)", ausgabe_pfad, neue_gesamt)
    else:
        log.info("Themen-Liste: Keine neuen Einträge")


def mail_senden(mail_config, pdf_pfad, log):
    """
    Verschickt das Zusammenfassungs-PDF als E-Mail-Anhang.

    Verbindung über SMTP mit SSL (Port 465). Absender ist der Login-Benutzer.
    Fehler werden sichtbar geloggt (log.error), brechen das Programm aber nicht ab.
    """
    import smtplib
    from datetime import datetime
    from email.message import EmailMessage

    smtp_server = mail_config.get("smtp_server")
    port = int(mail_config.get("port", 465))
    user = mail_config.get("user")
    password = mail_config.get("password")
    empfaenger = mail_config.get("empfaenger")

    if not all([smtp_server, user, password, empfaenger]):
        log.error("Mail-Konfiguration unvollständig — Mail wird nicht gesendet")
        return

    if not os.path.exists(pdf_pfad):
        log.error("PDF nicht gefunden, keine Mail gesendet: %s", pdf_pfad)
        return

    heute = datetime.now().strftime("%d.%m.%Y")

    nachricht = EmailMessage()
    nachricht["Subject"] = f"Schulportal-Zusammenfassung vom {heute}"
    nachricht["From"] = user
    nachricht["To"] = empfaenger
    nachricht.set_content(
        f"Anbei die aktuelle Schulportal-Zusammenfassung vom {heute}.\n\n"
        "Diese Mail wurde automatisch erstellt."
    )

    # PDF anhängen
    with open(pdf_pfad, "rb") as f:
        nachricht.add_attachment(
            f.read(),
            maintype="application",
            subtype="pdf",
            filename=os.path.basename(pdf_pfad),
        )

    log.info("Sende Mail an %s über %s:%d", empfaenger, smtp_server, port)
    try:
        with smtplib.SMTP_SSL(smtp_server, port, timeout=30) as server:
            server.login(user, password)
            server.send_message(nachricht)
        log.info("Mail erfolgreich gesendet an %s", empfaenger)
    except Exception as exc:
        log.error("Mailversand fehlgeschlagen: %s", exc)


def main(config, log):
    """Hauptfunktion — Schulportal auslesen."""
    from playwright.sync_api import sync_playwright

    sp_config = config.get("schulportal")
    if not sp_config:
        log.error("Kein 'schulportal'-Abschnitt in der Konfiguration gefunden")
        return

    login_url = sp_config.get("login_url")
    unterricht_url = sp_config.get("unterricht_url")
    benutzername = sp_config.get("benutzername")
    kennwort = sp_config.get("kennwort")
    headless = sp_config.get("headless", True)
    immer_anzeigen = int(sp_config.get("immer_anzeigen", 2))

    programm_verzeichnis = os.path.dirname(os.path.abspath(__file__))
    ausgabe_datei = sp_config.get("ausgabe_datei", "zusammenfassung.txt")
    ausgabe_pfad = os.path.join(programm_verzeichnis, ausgabe_datei)

    if not benutzername or not kennwort:
        log.error("Benutzername oder Kennwort nicht konfiguriert")
        return

    log.info("=== Schulportal Auswertung ===")
    log.info("Benutzer: %s", benutzername)
    log.info("Headless: %s", headless)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

        try:
            # 1. Login
            if not login(page, login_url, benutzername, kennwort, log):
                log.error("Login fehlgeschlagen — Abbruch")
                return

            # 2. Übersichtsseite öffnen und Fächer sammeln
            log.info("Öffne Mein Unterricht: %s", unterricht_url)
            page.goto(unterricht_url, wait_until="networkidle")
            time.sleep(2)

            faecher = faecher_und_buttons_sammeln(page, log)
            if not faecher:
                log.warning("Keine Fächer gefunden — Abbruch")
                page.screenshot(path=os.path.join(programm_verzeichnis, "debug_uebersicht.png"), full_page=True)
                return

            # 3. Pro Fach: per URL zur Detailseite, Tabelle lesen
            alle_daten_roh = []
            max_faecher = sp_config.get("max_faecher", 0)  # 0 = alle
            for i, fach in enumerate(faecher):
                if max_faecher and i >= max_faecher:
                    log.info("Abbruch nach %d Fächern (max_faecher)", max_faecher)
                    break

                log.info("--- Fach: %s ---", fach["name"])
                log.info("Öffne: %s", fach["url"])
                page.goto(fach["url"], wait_until="networkidle")
                time.sleep(2)

                # Fachname von der Detailseite lesen (falls auf Übersicht nicht erkannt)
                if fach["name"].startswith("Fach_"):
                    try:
                        header = page.query_selector('h1, h2, h3, .page-header, .panel-title')
                        if header:
                            erkannter_name = header.inner_text().strip()
                            if erkannter_name:
                                log.info("  Fachname von Detailseite: %s", erkannter_name)
                                fach["name"] = erkannter_name
                    except Exception:
                        pass

                # Tabelle auf der Detailseite lesen
                eintraege = eintraege_lesen(page, fach["name"], log)

                # Klassenarbeit-Datum auf der Detailseite ermitteln (erster Treffer)
                klassenarbeit = klassenarbeit_ermitteln(page, log)

                alle_daten_roh.append({
                    "fach": fach["name"],
                    "eintraege": eintraege,
                    "abgabe": fach.get("abgabe", ""),
                    "klassenarbeit": klassenarbeit,
                })

            # Gleiche Fächer zusammenführen
            alle_daten = []
            fach_index = {}
            for fd in alle_daten_roh:
                name = fd["fach"]
                if name in fach_index:
                    ziel = alle_daten[fach_index[name]]
                    ziel["eintraege"].extend(fd["eintraege"])
                    # Abgabe/Klassenarbeit übernehmen, falls beim Erst-Eintrag leer
                    if not ziel.get("abgabe"):
                        ziel["abgabe"] = fd.get("abgabe", "")
                    if not ziel.get("klassenarbeit"):
                        ziel["klassenarbeit"] = fd.get("klassenarbeit", "")
                else:
                    fach_index[name] = len(alle_daten)
                    alle_daten.append({
                        "fach": name,
                        "eintraege": list(fd["eintraege"]),
                        "abgabe": fd.get("abgabe", ""),
                        "klassenarbeit": fd.get("klassenarbeit", ""),
                    })

            # 4. Zusammenfassung schreiben
            zusammenfassung_schreiben(alle_daten, ausgabe_pfad, immer_anzeigen,
                                int(sp_config.get("max_zeilen_pro_fach", 0)), log)

            # 5. Fehlend-Liste schreiben
            fehlend_pfad = os.path.join(programm_verzeichnis, "fehlend.txt")
            fehlend_schreiben(alle_daten, fehlend_pfad, log)

            # 6. Themen-Liste schreiben (inkrementell)
            themen_pfad = os.path.join(programm_verzeichnis, "themen.txt")
            themen_schreiben(alle_daten, themen_pfad, log)

        except Exception as exc:
            log.error("Fehler bei der Schulportal-Auswertung: %s", exc)
        finally:
            browser.close()
            log.info("Browser geschlossen")

    # 7. Zusammenfassungs-PDF per Mail versenden (falls mail-Rubrik vorhanden)
    mail_config = config.get("mail")
    if mail_config:
        pdf_pfad = ausgabe_pfad.replace(".txt", ".pdf")
        mail_senden(mail_config, pdf_pfad, log)
    else:
        log.info("Keine 'mail'-Konfiguration — Mailversand übersprungen")

    log.info("=== Schulportal Auswertung abgeschlossen ===")


if __name__ == "__main__":
    config, log = initialisierung(projektroot)
    try:
        main(config, log)
    finally:
        beenden(config, log)
