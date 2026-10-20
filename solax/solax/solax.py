#!/usr/bin/env python3
"""
Hauptprogramm: solax - SolaX Wechselrichter Modbus TCP
"""

import os
import sys

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

# Projektroot ermitteln
projektroot = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, projektroot)

from base_resources.startup import initialisierung


# SolaX X3-Hybrid-G4 Pro Modbus Register-Map (Input Registers)
# Basierend auf wills106/homeassistant-solax-modbus Plugin
SOLAX_REGISTER = {
    # Grundlegende Wechselrichter-Daten
    0x0: ("Wechselrichter Spannung", "V", 0.1),
    0x1: ("Wechselrichter Strom", "A", 0.1),
    0x2: ("Wechselrichter Leistung", "W", 1),
    
    # PV-Eingänge
    0x3: ("PV1 Spannung", "V", 0.1),
    0x4: ("PV2 Spannung", "V", 0.1),
    0x5: ("PV1 Strom", "A", 0.1),
    0x6: ("PV2 Strom", "A", 0.1),
    0x7: ("Wechselrichter Frequenz", "Hz", 0.01),
    0x8: ("Wechselrichter Temperatur", "°C", 1),
    0x9: ("Betriebsmodus", "", 1),
    0xA: ("PV1 Leistung", "W", 1),
    0xB: ("PV2 Leistung", "W", 1),
    
    # Batterie-Daten
    0x14: ("Batterie Spannung", "V", 0.1),
    0x15: ("Batterie Strom", "A", 0.1),
    0x16: ("Batterie Leistung", "W", 1),
    0x17: ("BMS Verbindungsstatus", "", 1),
    0x18: ("Batterie Temperatur", "°C", 1),
    0x1C: ("Batterie SOC", "%", 1),
    
    # Energie-Zähler
    0x1D: ("Batterie Entladung gesamt", "kWh", 0.1),
    0x20: ("Batterie Entladung heute", "kWh", 0.1),
    0x21: ("Batterie Ladung gesamt", "kWh", 0.1),
    0x23: ("Batterie Ladung heute", "kWh", 0.1),
    
    # Netz-Messung
    0x46: ("Gemessene Leistung", "W", 1),  # Positiv = Einspeisung, Negativ = Bezug
    0x48: ("Netz Export gesamt", "kWh", 0.01),
    0x4A: ("Netz Import gesamt", "kWh", 0.01),
    
    # EPS (Notstrom) - falls verfügbar
    0x4C: ("EPS Spannung", "V", 0.1),
    0x4D: ("EPS Strom", "A", 0.1),
    0x4E: ("EPS Leistung", "VA", 1),
    0x4F: ("EPS Frequenz", "Hz", 0.01),
    
    # Ertrag
    0x50: ("Ertrag heute", "kWh", 0.1),
    0x52: ("Ertrag gesamt", "kWh", 0.1),
    
    # Dreiphasen-Daten (L1, L2, L3)
    0x6A: ("Wechselrichter Spannung L1", "V", 0.1),
    0x6B: ("Wechselrichter Strom L1", "A", 0.1),
    0x6C: ("Wechselrichter Leistung L1", "W", 1),
    0x6D: ("Wechselrichter Frequenz L1", "Hz", 0.01),
    0x6E: ("Wechselrichter Spannung L2", "V", 0.1),
    0x6F: ("Wechselrichter Strom L2", "A", 0.1),
    0x70: ("Wechselrichter Leistung L2", "W", 1),
    0x71: ("Wechselrichter Frequenz L2", "Hz", 0.01),
    0x72: ("Wechselrichter Spannung L3", "V", 0.1),
    0x73: ("Wechselrichter Strom L3", "A", 0.1),
    0x74: ("Wechselrichter Leistung L3", "W", 1),
    0x75: ("Wechselrichter Frequenz L3", "Hz", 0.01),
    
    # Gemessene Leistung pro Phase
    0x82: ("Gemessene Leistung L1", "W", 1),
    0x84: ("Gemessene Leistung L2", "W", 1),
    0x86: ("Gemessene Leistung L3", "W", 1),
    
    # Energie heute - HIER SIND DIE TAGES-WERTE!
    0x96: ("Solar Energie heute", "kWh", 0.1),
    0x98: ("Export Energie heute", "kWh", 0.01),  # ← EXPORT HEUTE
    0x9A: ("Import Energie heute", "kWh", 0.01),  # ← IMPORT HEUTE
    
    # Zusätzliche PV-Eingänge (falls vorhanden)
    0x2A: ("PV3 Spannung", "V", 0.1),
    0x2B: ("PV3 Strom", "A", 0.1),
    0x2C: ("PV3 Leistung", "W", 1),
    0x2E: ("PV4 Spannung", "V", 0.1),
    0x2F: ("PV4 Strom", "A", 0.1),
    0x30: ("PV4 Leistung", "W", 1),
    
    # Netz-Spannungen
    0xC9: ("Netz Spannung", "V", 0.1),
    0xCA: ("Netz Spannung L1", "V", 0.1),
    0xCB: ("Netz Spannung L2", "V", 0.1),
    0xCC: ("Netz Spannung L3", "V", 0.1),
    0xC8: ("Netz Frequenz", "Hz", 0.01),
}


def modbus_daten_lesen(config, log):
    """Liest SolaX-Daten über Modbus TCP."""
    solax_cfg = config.get("solax")
    ip = solax_cfg["ip_adresse"]
    port = solax_cfg["modbus_port"]
    unit_id = solax_cfg["unit_id"]
    timeout = solax_cfg["timeout"]

    log.info("SolaX Modbus-Verbindung zu %s:%d (Unit %d)", ip, port, unit_id)

    try:
        # Modbus TCP Client erstellen
        client = ModbusTcpClient(host=ip, port=port, timeout=timeout)
        
        if not client.connect():
            log.error("Modbus-Verbindung fehlgeschlagen")
            return None

        log.info("✓ Modbus-Verbindung erfolgreich")

        # Input Register lesen (Function Code 4)
        # Lese Standard-Register (0-199) und Wallbox-Register (0x3000-0x30C2)
        result1 = client.read_input_registers(address=0, count=100, device_id=unit_id)
        if result1.isError():
            log.error("Modbus-Lesefehler Block 1: %s", result1)
            return None
            
        result2 = client.read_input_registers(address=100, count=100, device_id=unit_id)
        if result2.isError():
            register_werte = result1.registers
        else:
            register_werte = result1.registers + result2.registers
            
        # Wallbox-Register lesen (0x3000 = 12288 dezimal)
        # Versuche verschiedene Unit IDs für die Wallbox
        wallbox_found = False
        for unit_id_wb in [2, 3, 4, 5]:  # Wallbox könnte andere Unit ID haben
            try:
                wallbox_result = client.read_input_registers(address=12288, count=20, device_id=unit_id_wb)
                if not wallbox_result.isError():
                    log.info("✓ Wallbox-Register gefunden auf Unit ID %d: %d Register", unit_id_wb, len(wallbox_result.registers))
                    # Wallbox-Daten analysieren
                    for i, wert in enumerate(wallbox_result.registers):
                        if wert != 0:
                            reg_addr = 0x3000 + i
                            signed_wert = wert if wert <= 32767 else wert - 65536
                            log.info("0x%04X (Unit %d) Wallbox: %d (0x%04X) [signed: %d]", reg_addr, unit_id_wb, wert, wert, signed_wert)
                    wallbox_found = True
                    break
            except Exception as e:
                continue
                
        if not wallbox_found:
            # Versuche Standard-Register für Wallbox-Daten
            log.info("Wallbox-Register 0x3000+ nicht verfügbar, prüfe Standard-Register...")
            # Möglicherweise sind Wallbox-Daten in den normalen Registern versteckt

        log.info("✓ %d Register gelesen", len(register_werte))
        
        # Daten ausgeben
        _modbus_daten_ausgeben(register_werte, log)
        
        return register_werte

    except ModbusException as e:
        log.error("Modbus-Fehler: %s", e)
        return None
    except Exception as e:
        log.error("Unerwarteter Fehler: %s", e)
        return None
    finally:
        if 'client' in locals():
            client.close()


def _modbus_daten_ausgeben(register_werte, log):
    """Gibt Modbus-Register strukturiert aus."""
    log.info("--- SolaX Echtzeit-Daten (Modbus) ---")
    
    # Bekannte Register ausgeben
    for reg_nr, wert in enumerate(register_werte):
        if reg_nr in SOLAX_REGISTER:
            beschreibung, einheit, faktor = SOLAX_REGISTER[reg_nr]
            
            # Signed 16-bit Werte behandeln
            if wert > 32767:
                wert = wert - 65536
            
            echter_wert = wert * faktor
            
            if faktor == 1:
                log.info("R%03d %-25s: %8d %s", reg_nr, beschreibung, int(echter_wert), einheit)
            else:
                log.info("R%03d %-25s: %8.2f %s", reg_nr, beschreibung, echter_wert, einheit)
    
    # Suche nach Wallbox-Registern (typisch ab Register 160+)
    log.info("")
    log.info("--- Potentielle Wallbox-Register (160-199) ---")
    for reg_nr in range(160, min(200, len(register_werte))):
        if reg_nr < len(register_werte):
            wert = register_werte[reg_nr]
            if wert != 0:  # Nur nicht-null Werte anzeigen
                signed_wert = wert if wert <= 32767 else wert - 65536
                log.info("R%03d Unbekannt: %d (0x%04X) [signed: %d]", reg_nr, wert, wert, signed_wert)
    
    # Wallbox-Register anzeigen (falls vorhanden)
    if len(register_werte) > 200:
        log.info("")
        log.info("--- Wallbox-Register (0x3000+) ---")
        wallbox_start = 200  # Index wo Wallbox-Register beginnen
        for i, wert in enumerate(register_werte[wallbox_start:wallbox_start+50]):
            if wert != 0:  # Nur nicht-null Werte anzeigen
                reg_addr = 0x3000 + i
                signed_wert = wert if wert <= 32767 else wert - 65536
                log.info("0x%04X (W%02d) Wallbox: %d (0x%04X) [signed: %d]", reg_addr, i, wert, wert, signed_wert)

    # Zusammenfassung der wichtigsten Werte basierend auf den echten Registern
    if len(register_werte) >= 29:
        log.info("")
        log.info("=== Zusammenfassung ===")
        
        # PV-Leistung (Register 10 + 11)
        pv1_leistung = register_werte[10] if 10 < len(register_werte) else 0
        pv2_leistung = register_werte[11] if 11 < len(register_werte) else 0
        pv_gesamt = pv1_leistung + pv2_leistung
        log.info("PV-Gesamtleistung: %d W (PV1: %d W, PV2: %d W)", pv_gesamt, pv1_leistung, pv2_leistung)
        
        # AC-Ausgangsleistung (Register 2)
        ac_leistung = register_werte[2] if 2 < len(register_werte) else 0
        log.info("AC-Ausgangsleistung: %d W", ac_leistung)
        
        # Batterie-Daten (Register 20-28)
        if len(register_werte) > 28:
            akku_soc = register_werte[28] if 28 < len(register_werte) else 0
            akku_leistung = register_werte[22] if 22 < len(register_werte) else 0
            if akku_leistung > 32767:
                akku_leistung = akku_leistung - 65536
            akku_spannung = register_werte[20] * 0.1 if 20 < len(register_werte) else 0
            log.info("Batterie: %d%% SOC, %.1f V, %d W", akku_soc, akku_spannung, akku_leistung)
        
        # Erweiterte Netz-Analyse - KORRIGIERT basierend auf User-Feedback
        if len(register_werte) > 70:
            gemessene_leistung_raw = register_werte[70] if 70 < len(register_werte) else 0
            if gemessene_leistung_raw > 32767:
                gemessene_leistung_raw = gemessene_leistung_raw - 65536
            
            # Tages-Import/Export (Register 0x98 = 152, 0x9A = 154)
            export_heute = register_werte[152] * 0.01 if 152 < len(register_werte) else 0
            import_heute = register_werte[154] * 0.01 if 154 < len(register_werte) else 0
            
            # Gesamt-Import/Export
            netz_export_gesamt = register_werte[72] * 0.01 if 72 < len(register_werte) else 0
            netz_import_gesamt = register_werte[74] * 0.01 if 74 < len(register_werte) else 0
            
            log.info("Netz-Analyse:")
            log.info("  Aktuelle Leistung (R70): %d W", gemessene_leistung_raw)
            log.info("")
            log.info("  === HEUTE ===")
            log.info("  Export heute (R152): %.2f kWh", export_heute)
            log.info("  Import heute (R154): %.2f kWh", import_heute)
            log.info("  Netto heute: %.2f kWh", export_heute - import_heute)
            log.info("")
            log.info("  === GESAMT ===")
            log.info("  Export gesamt (R72): %.2f kWh", netz_export_gesamt)
            log.info("  Import gesamt (R74): %.2f kWh", netz_import_gesamt)
            log.info("  Netto gesamt: %.2f kWh", netz_export_gesamt - netz_import_gesamt)
            log.info("")
            
            # KORREKTUR: Bei SolaX ist oft positiv = Einspeisung, nicht Bezug
            # User bestätigt: 9,1kW Einspeisung, System zeigt ~9148W positiv
            if gemessene_leistung_raw > 0:
                log.info("  → Aktuell: %d W EINSPEISUNG ins Netz", gemessene_leistung_raw)
                eigenverbrauch = pv_gesamt - gemessene_leistung_raw
            elif gemessene_leistung_raw < 0:
                log.info("  → Aktuell: %d W BEZUG aus dem Netz", abs(gemessene_leistung_raw))
                eigenverbrauch = pv_gesamt + abs(gemessene_leistung_raw)
            else:
                log.info("  → Aktuell: ausgeglichen (kein Netz-Bezug/Einspeisung)")
                eigenverbrauch = pv_gesamt
                
            log.info("  Eigenverbrauch: %d W", eigenverbrauch)


def main(config, log):
    """Hauptfunktion."""
    modbus_daten_lesen(config, log)


if __name__ == "__main__":
    config, log = initialisierung(projektroot)
    main(config, log)