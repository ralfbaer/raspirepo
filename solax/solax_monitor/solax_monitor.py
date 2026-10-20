#!/usr/bin/env python3
"""
Hauptprogramm: solax_monitor - Kontinuierliche SolaX-Überwachung mit Wallbox-Erkennung
"""

import os
import sys
import time
import sqlite3
from datetime import datetime, timedelta

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

# Projektroot ermitteln
projektroot = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, projektroot)

from base_resources.startup import initialisierung


def datenbank_initialisieren(db_pfad, log):
    """Initialisiert die SQLite-Datenbank für Zeitreihen-Daten."""
    conn = sqlite3.connect(db_pfad)
    cursor = conn.cursor()
    
    # Tabelle für Messwerte
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messwerte (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            pv_leistung INTEGER,
            ac_leistung INTEGER,
            netz_leistung INTEGER,
            batterie_soc INTEGER,
            batterie_leistung INTEGER,
            eigenverbrauch INTEGER
        )
    ''')
    
    # Tabelle für Wallbox-Ladevorgänge
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wallbox_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT NOT NULL,
            end_time TEXT,
            start_eigenverbrauch INTEGER,
            max_eigenverbrauch INTEGER,
            energie_geladen REAL,
            status TEXT DEFAULT 'aktiv'
        )
    ''')
    
    conn.commit()
    conn.close()
    log.info("Datenbank initialisiert: %s", db_pfad)


def solax_daten_lesen(config, log):
    """Liest SolaX-Daten über Modbus TCP."""
    try:
        solax_cfg = config.get("solax")
        ip = solax_cfg["ip_adresse"]
        port = solax_cfg["modbus_port"]
        unit_id = solax_cfg["unit_id"]
        timeout = solax_cfg["timeout"]

        client = ModbusTcpClient(host=ip, port=port, timeout=timeout)
        
        if not client.connect():
            log.error("Modbus-Verbindung fehlgeschlagen")
            return None

        # Standard-Register lesen
        result1 = client.read_input_registers(address=0, count=100, device_id=unit_id)
        if result1.isError():
            log.error("Modbus-Lesefehler: %s", result1)
            return None
            
        result2 = client.read_input_registers(address=100, count=60, device_id=unit_id)
        if result2.isError():
            register_werte = result1.registers
        else:
            register_werte = result1.registers + result2.registers

        client.close()

        # Daten extrahieren
        daten = {
            "timestamp": datetime.now().isoformat(),
            "pv_leistung": (register_werte[10] if len(register_werte) > 10 else 0) + 
                          (register_werte[11] if len(register_werte) > 11 else 0),
            "ac_leistung": register_werte[2] if len(register_werte) > 2 else 0,
            "netz_leistung": register_werte[70] if len(register_werte) > 70 else 0,
            "batterie_soc": register_werte[28] if len(register_werte) > 28 else 0,
            "batterie_leistung": register_werte[22] if len(register_werte) > 22 else 0,
        }
        
        # Signed-Werte korrigieren
        if daten["netz_leistung"] > 32767:
            daten["netz_leistung"] -= 65536
        if daten["batterie_leistung"] > 32767:
            daten["batterie_leistung"] -= 65536
            
        # Eigenverbrauch berechnen
        daten["eigenverbrauch"] = daten["pv_leistung"] - daten["netz_leistung"]
        
        return daten

    except Exception as e:
        log.error("Fehler beim Lesen der SolaX-Daten: %s", e)
        return None


def wallbox_erkennung(daten, db_pfad, log):
    """Erkennt Wallbox-Ladevorgänge basierend auf Eigenverbrauchsänderungen."""
    if not daten:
        return
        
    conn = sqlite3.connect(db_pfad)
    cursor = conn.cursor()
    
    eigenverbrauch = daten["eigenverbrauch"]
    timestamp = daten["timestamp"]
    
    # Prüfe aktive Ladesession
    cursor.execute("SELECT * FROM wallbox_sessions WHERE status = 'aktiv' ORDER BY id DESC LIMIT 1")
    aktive_session = cursor.fetchone()
    
    # Optimierte Wallbox-Schwellwerte
    WALLBOX_MIN_LEISTUNG = 2500   # Mindestens 2,5 kW für Wallbox-Erkennung
    WALLBOX_MAX_LEISTUNG = 12000  # Maximal 12 kW (Wallbox-Limit)
    WALLBOX_MIN_DAUER = 180       # Mindestens 3 Minuten hoher Verbrauch
    WALLBOX_STABILITÄT = 5        # Anzahl aufeinanderfolgende Messungen für Stabilität
    
    # Prüfe die letzten 5 Messwerte für bessere Stabilität
    cursor.execute('''
        SELECT eigenverbrauch FROM messwerte 
        ORDER BY timestamp DESC 
        LIMIT ?
    ''', (WALLBOX_STABILITÄT,))
    letzte_werte = [row[0] for row in cursor.fetchall()]
    
    # Stabilität prüfen - mindestens 4 von 5 Werten müssen über/unter Schwelle sein
    if len(letzte_werte) >= 4:
        hohe_werte = sum(1 for w in letzte_werte if w >= WALLBOX_MIN_LEISTUNG)
        niedrige_werte = sum(1 for w in letzte_werte if w < WALLBOX_MIN_LEISTUNG)
        
        ist_stabil_hoch = hohe_werte >= 4  # 4 von 5 Werten hoch
        ist_stabil_niedrig = niedrige_werte >= 4  # 4 von 5 Werte niedrig
        
        # Durchschnitt der letzten 3 Werte für Glättung
        avg_eigenverbrauch = sum(letzte_werte[:3]) / min(3, len(letzte_werte))
    else:
        # Nicht genug Daten - konservativ sein
        ist_stabil_hoch = False
        ist_stabil_niedrig = eigenverbrauch < WALLBOX_MIN_LEISTUNG
        avg_eigenverbrauch = eigenverbrauch
    
    # Ladevorgang starten
    if ist_stabil_hoch and WALLBOX_MIN_LEISTUNG <= avg_eigenverbrauch <= WALLBOX_MAX_LEISTUNG:
        if not aktive_session:
            # Neue Ladesession starten (nur wenn stabil hoch)
            cursor.execute('''
                INSERT INTO wallbox_sessions (start_time, start_eigenverbrauch, max_eigenverbrauch)
                VALUES (?, ?, ?)
            ''', (timestamp, int(avg_eigenverbrauch), int(avg_eigenverbrauch)))
            log.info("🚗 Wallbox-Ladevorgang gestartet: %d W (stabil über %d Messungen)", 
                    int(avg_eigenverbrauch), len(letzte_werte))
        else:
            # Bestehende Session aktualisieren
            session_id = aktive_session[0]
            max_verbrauch = max(aktive_session[4], int(avg_eigenverbrauch))
            cursor.execute('''
                UPDATE wallbox_sessions 
                SET max_eigenverbrauch = ?
                WHERE id = ?
            ''', (max_verbrauch, session_id))
    
    # Ladevorgang beenden
    elif aktive_session and ist_stabil_niedrig:
        # Prüfe ob Ladevorgang beendet (nur wenn stabil niedrig)
        start_time = datetime.fromisoformat(aktive_session[1])
        current_time = datetime.fromisoformat(timestamp)
        dauer_sekunden = (current_time - start_time).total_seconds()
        
        if dauer_sekunden > WALLBOX_MIN_DAUER:  # Mindestdauer erreicht
            # Ladevorgang beenden
            session_id = aktive_session[0]
            dauer_stunden = dauer_sekunden / 3600
            # Geschätzte Energie: (Durchschnittsleistung - Grundlast) * Zeit
            avg_leistung = (aktive_session[3] + aktive_session[4]) / 2
            geschaetzte_energie = max(0, (avg_leistung - 1200) * dauer_stunden / 1000)  # kWh
            
            cursor.execute('''
                UPDATE wallbox_sessions 
                SET end_time = ?, energie_geladen = ?, status = 'beendet'
                WHERE id = ?
            ''', (timestamp, geschaetzte_energie, session_id))
            
            log.info("🔌 Wallbox-Ladevorgang beendet: %.1f kWh in %.1f min (stabil niedrig)", 
                    geschaetzte_energie, dauer_sekunden/60)
        elif dauer_sekunden < WALLBOX_MIN_DAUER:
            # Zu kurz - wahrscheinlich kein echter Ladevorgang, Session löschen
            session_id = aktive_session[0]
            cursor.execute('DELETE FROM wallbox_sessions WHERE id = ?', (session_id,))
            log.info("❌ Kurzer Verbrauchspeak ignoriert (%.0f s)", dauer_sekunden)
    
    conn.commit()
    conn.close()


def messwerte_speichern(daten, db_pfad):
    """Speichert Messwerte in der Datenbank."""
    if not daten:
        return
        
    conn = sqlite3.connect(db_pfad)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO messwerte (timestamp, pv_leistung, ac_leistung, netz_leistung, 
                              batterie_soc, batterie_leistung, eigenverbrauch)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        daten["timestamp"],
        daten["pv_leistung"],
        daten["ac_leistung"],
        daten["netz_leistung"],
        daten["batterie_soc"],
        daten["batterie_leistung"],
        daten["eigenverbrauch"]
    ))
    
    conn.commit()
    conn.close()


def main(config, log):
    """Hauptfunktion - kontinuierliche Überwachung."""
    monitor_cfg = config.get("monitor")
    intervall = monitor_cfg["intervall_sekunden"]
    db_pfad = monitor_cfg["datenbank_pfad"]
    
    # Datenbank initialisieren
    datenbank_initialisieren(db_pfad, log)
    
    log.info("SolaX Monitor gestartet - Intervall: %d Sekunden", intervall)
    log.info("Datenbank: %s", db_pfad)
    
    try:
        while True:
            # Daten lesen
            daten = solax_daten_lesen(config, log)
            
            if daten:
                # Wallbox-Erkennung
                wallbox_erkennung(daten, db_pfad, log)
                
                # Messwerte speichern
                messwerte_speichern(daten, db_pfad)
                
                # Status ausgeben
                log.info("PV: %d W, Netz: %d W, Eigenverbrauch: %d W, Akku: %d%%", 
                        daten["pv_leistung"], daten["netz_leistung"], 
                        daten["eigenverbrauch"], daten["batterie_soc"])
            
            time.sleep(intervall)
            
    except KeyboardInterrupt:
        log.info("SolaX Monitor beendet")


if __name__ == "__main__":
    config, log = initialisierung(projektroot)
    main(config, log)