#!/bin/bash
# SolaX System Starter
# Startet sowohl Monitor als auch Web-Dashboard

echo "🚀 SolaX System wird gestartet..."

# Prüfe ob Python Virtual Environment existiert
if [ ! -d "../.venv" ]; then
    echo "❌ Virtual Environment nicht gefunden. Bitte zuerst erstellen:"
    echo "   python3 -m venv ../.venv"
    echo "   source ../.venv/bin/activate"
    echo "   pip install -r ../requirements.txt"
    exit 1
fi

# Aktiviere Virtual Environment
source ../.venv/bin/activate

# Prüfe ob alle Abhängigkeiten installiert sind
echo "📦 Prüfe Abhängigkeiten..."
python -c "import pymodbus, flask, sqlite3" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "❌ Abhängigkeiten fehlen. Installiere sie:"
    pip install -r ../requirements.txt
fi

# Starte Monitor im Hintergrund
echo "📊 Starte SolaX Monitor..."
cd solax_monitor
python solax_monitor.py &
MONITOR_PID=$!
cd ..

# Warte kurz
sleep 2

# Starte Web-Dashboard
echo "🌐 Starte Web-Dashboard auf http://localhost:8081"
cd solax_web
python solax_web.py &
WEB_PID=$!
cd ..

echo ""
echo "✅ SolaX System gestartet!"
echo "   📊 Monitor PID: $MONITOR_PID"
echo "   🌐 Web-Dashboard PID: $WEB_PID"
echo "   🌐 Dashboard URL: http://localhost:8081"
echo ""
echo "Zum Beenden: Ctrl+C oder kill $MONITOR_PID $WEB_PID"

# Warte auf Benutzer-Eingabe
trap "echo ''; echo '🛑 Beende SolaX System...'; kill $MONITOR_PID $WEB_PID 2>/dev/null; exit 0" INT

# Halte das Script am Leben
wait