# SolaX Monitoring System

Ein vollständiges Monitoring-System für SolaX-Wechselrichter mit automatischer Wallbox-Erkennung und Web-Dashboard.

## 🏗️ System-Architektur

Das System besteht aus drei Hauptkomponenten:

### 1. **solax_monitor** - Datensammler
- Läuft kontinuierlich im Hintergrund
- Sammelt alle 10 Sekunden SolaX-Daten über Modbus TCP
- Speichert Zeitreihen-Daten in SQLite-Datenbank
- Erkennt automatisch Wallbox-Ladevorgänge
- Protokolliert alle Aktivitäten

### 2. **solax_web** - Web-Dashboard  
- Flask-Webserver auf localhost:8081
- Zeigt aktuelle SolaX-Daten in Echtzeit
- Interaktive Charts mit Chart.js
- Responsive Design für Desktop und Mobile
- Liest historische Daten aus Monitor-Datenbank

### 3. **solax_data.db** - Datenbank
- SQLite-Datenbank für historische Daten
- Tabelle `messwerte`: Zeitreihen-Daten (PV, Netz, Batterie, etc.)
- Tabelle `wallbox_sessions`: Erkannte Ladevorgänge

## 🚀 Schnellstart

### Voraussetzungen
```bash
# Virtual Environment erstellen
python3 -m venv .venv
source .venv/bin/activate

# Abhängigkeiten installieren
pip install -r requirements.txt
```

### System starten
```bash
# Einfacher Start mit Script
./start_solax_system.sh

# Oder manuell:
# Terminal 1 - Monitor
cd experimental/solax_monitor
python solax_monitor.py

# Terminal 2 - Web-Dashboard  
cd experimental/solax_web
python solax_web.py
```

### Dashboard aufrufen
Öffne http://localhost:8081 im Browser

## ⚙️ Konfiguration

### Umgebungsvariablen (.dev_env)
```bash
SOLAX_IP=192.168.188.110
SOLAX_PASSWORD=admin
```

### Monitor-Konfiguration (solax_monitor.yml)
```yaml
config:
  loglevel: "INFO"

solax:
  ip_adresse: "${SOLAX_IP}"
  modbus_port: 502
  unit_id: 1
  timeout: 10

monitor:
  intervall_sekunden: 10        # Datensammlung alle 10 Sekunden
  datenbank_pfad: "solax_data.db"
```

### Web-Konfiguration (solax_web.yml)
```yaml
config:
  loglevel: "INFO"

solax:
  ip_adresse: "${SOLAX_IP}"
  modbus_port: 502
  unit_id: 1
  timeout: 10

web:
  host: "localhost"
  port: 8081
  debug: false
```

## 🔋 Wallbox-Erkennung

Das System erkennt automatisch Wallbox-Ladevorgänge basierend auf Eigenverbrauchsänderungen:

### Erkennungslogik
- **Mindestleistung**: 2,5 kW (2500W)
- **Maximalleistung**: 12 kW (12000W) 
- **Stabilität**: 4 von 5 aufeinanderfolgenden Messungen müssen über/unter Schwelle sein
- **Mindestdauer**: 3 Minuten für gültigen Ladevorgang
- **Grundlast-Abzug**: ~1,2 kW werden für Hausverbrauch abgezogen

### Ladevorgang-Erkennung
```
🚗 Wallbox-Ladevorgang gestartet: 4810 W (stabil über 5 Messungen)
🔌 Wallbox-Ladevorgang beendet: 2.3 kWh in 45.2 min (stabil niedrig)
❌ Kurzer Verbrauchspeak ignoriert (132 s)
```

## 📊 Dashboard-Features

### Kacheln
- **PV-Produktion**: Gesamt + PV1/PV2 Details
- **Batterie**: SOC, Leistung, Spannung, Temperatur
- **Netz**: Ein-/Ausspeisung, Eigenverbrauch
- **Tages-Bilanz**: Export/Import/Netto heute
- **Wallbox**: Aktuelle Ladeleistung, Sessions
- **Gesamt-Statistiken**: Langzeit-Werte
- **Wechselrichter**: Technische Details

### Interaktiver Graph
- **PV-Produktion** (orange): Solarertrag
- **Netz-Einspeisung** (blau): Überschuss ins Netz
- **Wallbox-Ladung** (rot): Geschätzte Wallbox-Leistung
- **Zeitraum**: Letzten 4 Stunden
- **Update**: Alle 10 Sekunden

## 🗂️ Datenspeicherung

### Messwerte-Tabelle
```sql
CREATE TABLE messwerte (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    pv_leistung INTEGER,
    ac_leistung INTEGER, 
    netz_leistung INTEGER,
    batterie_soc INTEGER,
    batterie_leistung INTEGER,
    eigenverbrauch INTEGER
);
```

### Wallbox-Sessions-Tabelle  
```sql
CREATE TABLE wallbox_sessions (
    id INTEGER PRIMARY KEY,
    start_time TEXT NOT NULL,
    end_time TEXT,
    start_eigenverbrauch INTEGER,
    max_eigenverbrauch INTEGER,
    energie_geladen REAL,
    status TEXT DEFAULT 'aktiv'
);
```

## 🔧 Wartung

### Logs anzeigen
```bash
# Monitor-Logs
tail -f experimental/solax_monitor/logs/$(date +%Y-%m-%d)/solax_monitor.log

# Web-Logs  
tail -f experimental/solax_web/logs/$(date +%Y-%m-%d)/solax_web.log
```

### Datenbank-Größe prüfen
```bash
ls -lh experimental/solax_monitor/solax_data.db
```

### System-Status
- **Monitor läuft**: Neue Einträge in Monitor-Log
- **Web läuft**: Dashboard erreichbar unter http://localhost:8081
- **Daten aktuell**: "Letzte Aktualisierung" im Dashboard
- **Wallbox aktiv**: Status "Lädt aktiv" in Wallbox-Karte

## 🐛 Troubleshooting

### Häufige Probleme

**Modbus-Verbindung fehlgeschlagen**
```bash
# IP-Adresse prüfen
ping 192.168.188.110

# Port prüfen  
telnet 192.168.188.110 502
```

**Dashboard zeigt keine Daten**
- Monitor läuft? → `ps aux | grep solax_monitor`
- Datenbank existiert? → `ls -la experimental/solax_monitor/solax_data.db`
- Web-Server läuft? → `curl http://localhost:8081/api/data`

**Wallbox wird nicht erkannt**
- Eigenverbrauch > 2,5 kW? → Monitor-Log prüfen
- Stabile Werte? → Mindestens 4 von 5 Messungen über Schwelle
- Mindestdauer? → Ladevorgang muss > 3 Minuten dauern

## 📈 Erweiterungen

### Geplante Features
- [ ] Email-Benachrichtigungen bei Störungen
- [ ] Export zu InfluxDB/Grafana
- [ ] Mobile App (PWA)
- [ ] Wettervorhersage-Integration
- [ ] Optimierte Wallbox-Steuerung
- [ ] Backup/Restore der Datenbank

### API-Endpunkte
- `GET /api/data` - Aktuelle SolaX-Daten
- `GET /api/history` - Historische Daten (4h)
- Geplant: `GET /api/sessions` - Wallbox-Sessions
- Geplant: `GET /api/stats` - Statistiken

## 🏷️ Versionshistorie

- **v1.0** - Grundsystem mit Monitor und Web-Dashboard
- **v1.1** - Verbesserte Wallbox-Erkennung mit Stabilitätsprüfung
- **v1.2** - Optimiertes Monitoring-Intervall (10s statt 30s)