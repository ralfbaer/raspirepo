class SolaxDashboard {
    constructor() {
        this.lastData = {};
        this.updateInterval = 10000; // 10 Sekunden
        this.chart = null;
        this.chartData = {
            labels: [],
            pv: [],
            netz: [],
            wallbox: [],
            eigenverbrauch: []
        };
        this.init();
    }

    init() {
        this.initChart();
        this.initDateControls();
        this.loadHistoryData();
        this.loadData();
        setInterval(() => this.loadData(), this.updateInterval);
    }

    initDateControls() {
        // Standardwerte setzen (letzte 4 Stunden)
        const now = new Date();
        const fourHoursAgo = new Date(now.getTime() - 4 * 60 * 60 * 1000);
        
        document.getElementById('start-date').value = this.formatDateTimeLocal(fourHoursAgo);
        document.getElementById('end-date').value = this.formatDateTimeLocal(now);
        
        // Event Listener
        document.getElementById('update-graph').addEventListener('click', () => {
            this.loadCustomHistoryData();
        });
        
        document.getElementById('reset-graph').addEventListener('click', () => {
            const now = new Date();
            const fourHoursAgo = new Date(now.getTime() - 4 * 60 * 60 * 1000);
            
            document.getElementById('start-date').value = this.formatDateTimeLocal(fourHoursAgo);
            document.getElementById('end-date').value = this.formatDateTimeLocal(now);
            
            this.loadHistoryData();
        });
    }

    formatDateTimeLocal(date) {
        // Format für datetime-local input: YYYY-MM-DDTHH:MM
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        
        return `${year}-${month}-${day}T${hours}:${minutes}`;
    }

    async loadHistoryData() {
        try {
            const response = await fetch('/api/history');
            if (response.ok) {
                const historyData = await response.json();
                
                // Chart mit historischen Daten initialisieren
                this.chartData.labels = historyData.labels;
                this.chartData.pv = historyData.pv;
                this.chartData.netz = historyData.netz;
                this.chartData.wallbox = historyData.wallbox;
                this.chartData.eigenverbrauch = historyData.eigenverbrauch;
                
                this.chart.data.labels = this.chartData.labels;
                this.chart.data.datasets[0].data = this.chartData.pv;
                this.chart.data.datasets[1].data = this.chartData.netz;
                this.chart.data.datasets[2].data = this.chartData.wallbox;
                this.chart.data.datasets[3].data = this.chartData.eigenverbrauch;
                
                this.chart.update();
            }
        } catch (error) {
            console.log('Keine historischen Daten verfügbar:', error);
        }
    }

    async loadCustomHistoryData() {
        try {
            const startDate = document.getElementById('start-date').value;
            const endDate = document.getElementById('end-date').value;
            
            if (!startDate || !endDate) {
                alert('Bitte beide Datumsfelder ausfüllen');
                return;
            }
            
            const startTime = new Date(startDate).toISOString();
            const endTime = new Date(endDate).toISOString();
            
            const response = await fetch(`/api/history?start=${encodeURIComponent(startTime)}&end=${encodeURIComponent(endTime)}`);
            if (response.ok) {
                const historyData = await response.json();
                
                // Chart mit benutzerdefinierten Daten aktualisieren
                this.chartData.labels = historyData.labels;
                this.chartData.pv = historyData.pv;
                this.chartData.netz = historyData.netz;
                this.chartData.wallbox = historyData.wallbox;
                this.chartData.eigenverbrauch = historyData.eigenverbrauch;
                
                this.chart.data.labels = this.chartData.labels;
                this.chart.data.datasets[0].data = this.chartData.pv;
                this.chart.data.datasets[1].data = this.chartData.netz;
                this.chart.data.datasets[2].data = this.chartData.wallbox;
                this.chart.data.datasets[3].data = this.chartData.eigenverbrauch;
                
                this.chart.update();
                
                console.log(`Daten geladen: ${historyData.labels.length} Datenpunkte von ${startDate} bis ${endDate}`);
            } else {
                alert('Fehler beim Laden der Daten für den gewählten Zeitraum');
            }
        } catch (error) {
            console.error('Fehler beim Laden der benutzerdefinierten Daten:', error);
            alert('Fehler beim Laden der Daten');
        }
    }

    initChart() {
        const ctx = document.getElementById('tagesChart').getContext('2d');
        
        this.chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'PV-Produktion',
                        data: [],
                        borderColor: '#ff9800',
                        backgroundColor: 'rgba(255, 152, 0, 0.1)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.4
                    },
                    {
                        label: 'Netz-Einspeisung',
                        data: [],
                        borderColor: '#2196F3',
                        backgroundColor: 'rgba(33, 150, 243, 0.1)',
                        borderWidth: 2,
                        fill: false,
                        tension: 0.4
                    },
                    {
                        label: 'Wallbox-Ladung',
                        data: [],
                        borderColor: '#FF5722',
                        backgroundColor: 'rgba(255, 87, 34, 0.1)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.4
                    },
                    {
                        label: 'Eigenverbrauch',
                        data: [],
                        borderColor: '#9C27B0',
                        backgroundColor: 'rgba(156, 39, 176, 0.1)',
                        borderWidth: 2,
                        fill: false,
                        tension: 0.4
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false // Verwende eigene Legende
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Leistung (W)'
                        },
                        grid: {
                            color: 'rgba(0,0,0,0.1)'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: 'Uhrzeit'
                        },
                        grid: {
                            color: 'rgba(0,0,0,0.1)'
                        }
                    }
                },
                interaction: {
                    intersect: false,
                    mode: 'index'
                }
            }
        });
    }

    updateChart(data) {
        const now = new Date();
        const timeLabel = now.toLocaleTimeString('de-DE', { 
            hour: '2-digit', 
            minute: '2-digit' 
        });

        // Neue Datenpunkte hinzufügen
        this.chartData.labels.push(timeLabel);
        this.chartData.pv.push(data.pv.gesamt_leistung);
        this.chartData.netz.push(Math.max(0, data.netz.aktuelle_leistung)); // Nur positive Werte (Einspeisung)
        this.chartData.wallbox.push(data.wallbox.aktuelle_leistung);
        this.chartData.eigenverbrauch.push(data.eigenverbrauch);

        // Maximal 50 Datenpunkte behalten (ca. 8 Stunden bei 10s Intervall)
        const maxPoints = 50;
        if (this.chartData.labels.length > maxPoints) {
            this.chartData.labels.shift();
            this.chartData.pv.shift();
            this.chartData.netz.shift();
            this.chartData.wallbox.shift();
            this.chartData.eigenverbrauch.shift();
        }

        // Chart aktualisieren
        this.chart.data.labels = this.chartData.labels;
        this.chart.data.datasets[0].data = this.chartData.pv;
        this.chart.data.datasets[1].data = this.chartData.netz;
        this.chart.data.datasets[2].data = this.chartData.wallbox;
        this.chart.data.datasets[3].data = this.chartData.eigenverbrauch;
        
        this.chart.update('none'); // Keine Animation für bessere Performance
    }

    async loadData() {
        try {
            const response = await fetch('/api/data');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const data = await response.json();
            this.updateUI(data);
            this.updateStatus('online', data.timestamp);
            
        } catch (error) {
            console.error('Fehler beim Laden der Daten:', error);
            this.updateStatus('error', 'Verbindungsfehler');
        }
    }

    updateUI(data) {
        // PV-Daten
        this.updateValue('pv-gesamt', data.pv.gesamt_leistung, 0, 'W');
        this.updateValue('pv1-leistung', data.pv.pv1_leistung, 0, 'W');
        this.updateValue('pv1-spannung', data.pv.pv1_spannung, 1, 'V');
        this.updateValue('pv1-strom', data.pv.pv1_strom, 1, 'A');
        this.updateValue('pv2-leistung', data.pv.pv2_leistung, 0, 'W');
        this.updateValue('pv2-spannung', data.pv.pv2_spannung, 1, 'V');
        this.updateValue('pv2-strom', data.pv.pv2_strom, 1, 'A');

        // Batterie
        this.updateValue('batterie-soc', data.batterie.soc, 0, '%');
        this.updateValue('batterie-leistung', data.batterie.leistung, 0, 'W');
        this.updateValue('batterie-spannung', data.batterie.spannung, 1, 'V');
        this.updateValue('batterie-temperatur', data.batterie.temperatur, 0, '°C');
        
        // Batterie-Balken aktualisieren
        const batteryFill = document.getElementById('battery-fill');
        batteryFill.style.width = `${Math.max(0, Math.min(100, data.batterie.soc))}%`;

        // Netz-Daten
        const netzLeistung = data.netz.aktuelle_leistung;
        this.updateValue('netz-leistung', Math.abs(netzLeistung), 0, 'W');
        this.updateValue('eigenverbrauch', data.eigenverbrauch, 0, 'W');
        this.updateValue('wr-leistung', data.wechselrichter.leistung, 0, 'W');

        // Netz-Status
        const netzStatus = document.getElementById('netz-status');
        const netzHauptwert = document.getElementById('netz-hauptwert');
        
        if (netzLeistung > 100) {
            netzStatus.textContent = 'Einspeisung ins Netz';
            netzStatus.className = 'netz-status einspeisung';
            netzHauptwert.style.color = '#2e7d32';
        } else if (netzLeistung < -100) {
            netzStatus.textContent = 'Bezug aus dem Netz';
            netzStatus.className = 'netz-status bezug';
            netzHauptwert.style.color = '#c62828';
        } else {
            netzStatus.textContent = 'Ausgeglichen';
            netzStatus.className = 'netz-status ausgeglichen';
            netzHauptwert.style.color = '#7b1fa2';
        }

        // Tages-Daten
        this.updateValue('export-heute', data.netz.export_heute, 2, 'kWh');
        this.updateValue('import-heute', data.netz.import_heute, 2, 'kWh');
        this.updateValue('netto-heute', data.netz.netto_heute, 2, 'kWh');
        this.updateValue('ertrag-heute', data.ertrag.heute, 1, 'kWh');

        // Gesamt-Daten
        this.updateValue('export-gesamt', data.netz.export_gesamt, 1, 'kWh');
        this.updateValue('import-gesamt', data.netz.import_gesamt, 1, 'kWh');
        this.updateValue('netto-gesamt', data.netz.netto_gesamt, 1, 'kWh');
        this.updateValue('ertrag-gesamt', data.ertrag.gesamt, 1, 'kWh');

        // Wechselrichter
        this.updateValue('wr-spannung', data.wechselrichter.spannung, 1, 'V');
        this.updateValue('wr-strom', data.wechselrichter.strom, 1, 'A');
        this.updateValue('wr-temperatur', data.wechselrichter.temperatur, 0, '°C');

        // Wallbox (mit Monitor-Daten)
        this.updateValue('wallbox-leistung', data.wallbox.aktuelle_leistung, 0, 'W');
        this.updateValue('wallbox-ladung-heute', data.wallbox.ladung_heute, 1, 'kWh');
        this.updateValue('wallbox-ladung-gesamt', data.wallbox.ladung_gesamt, 1, 'kWh');

        // Wallbox-Status
        const wallboxStatus = document.getElementById('wallbox-status');
        const wallboxHauptwert = document.getElementById('wallbox-hauptwert');
        
        wallboxStatus.textContent = data.wallbox.status;
        
        if (data.wallbox.aktuelle_leistung > 100) {
            wallboxStatus.className = 'wallbox-status laedt';
            wallboxHauptwert.style.color = '#f57c00';
        } else {
            wallboxStatus.className = 'wallbox-status nicht-verbunden';
            wallboxHauptwert.style.color = '#757575';
        }

        // Wallbox-Sessions aktualisieren - ENTFERNT (Graph zeigt es besser)
        // this.updateWallboxSessions(data.wallbox.sessions_heute);

        // Chart aktualisieren
        this.updateChart(data);

        this.lastData = data;
    }

    updateValue(elementId, newValue, decimals = 0, unit = '') {
        const element = document.getElementById(elementId);
        if (!element) return;

        const formattedValue = this.formatNumber(newValue, decimals);
        const oldValue = element.textContent;

        if (oldValue !== formattedValue) {
            element.textContent = formattedValue;
            element.parentElement.classList.add('value-change');
            setTimeout(() => {
                element.parentElement.classList.remove('value-change');
            }, 500);
        }
    }

    formatNumber(value, decimals) {
        if (typeof value !== 'number') return '0';
        return value.toFixed(decimals);
    }

    updateStatus(status, message) {
        const statusElement = document.getElementById('last-update');
        const indicatorElement = document.getElementById('status-indicator');
        
        if (status === 'online') {
            statusElement.textContent = `Letzte Aktualisierung: ${message}`;
            indicatorElement.className = 'status-indicator';
        } else {
            statusElement.textContent = `Fehler: ${message}`;
            indicatorElement.className = 'status-indicator error';
        }
    }
}

// Dashboard initialisieren wenn die Seite geladen ist
document.addEventListener('DOMContentLoaded', () => {
    new SolaxDashboard();
});