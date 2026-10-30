RISEN TWEAKS V2.0.0
===================

DESIGN
- Dunkle Oberfläche nach der bereitgestellten Referenz: schmale Icon-Seitenleiste,
  zentrierter Titel, dunkle Gruppenfelder und breite Aktionstasten.
- Bereiche: Home, Windows Tweaks, Performance, Cleanup, GPU Optimization,
  Fortnite, Processes, Hardware und Tools.

FUNKTIONEN
- Live CPU- und RAM-Auslastung
- NVIDIA-SMI: GPU-Last, VRAM, Temperatur und Leistungsaufnahme (wenn verfügbar)
- Datenträger- und Netzwerkdurchsatz
- Hardware-Erkennung: CPU, GPU(s), RAM, Mainboard, BIOS, Laufwerke,
  Netzwerkadapter, Windows und Display-Informationen
- Liste der aktuell erkannten Plug-and-Play-Geräte (Windows)
- Prozessliste nach CPU/RAM sortierbar, Suche und geschütztes Beenden ausgewählter Prozesse
- Fortnite-Priorität HOCH/NORMAL für den laufenden Spielprozess
- Ping-/Paketverlust-/Schwankungs-Test zu öffentlichen IP-Adressen
- Windows Game Mode, Game DVR, visuelle Effekte, Energiepläne und Mausbeschleunigung
- Benutzer-Temp-Bereinigung und DNS-Cache leeren
- NVIDIA/AMD-Hersteller-Tools, Treiberseiten und Windows-Grafikeinstellungen
- Autostart-Übersicht (lesend), Windows-Systemtools, Systembericht
- Backup/Wiederherstellung für die geänderten HKCU-Registry-Werte und den vorherigen Energieplan

INSTALLATION / START
1. ZIP vollständig entpacken.
2. Python 3.10 oder neuer für Windows installieren: https://www.python.org/downloads/
   Beim Setup nach Möglichkeit "Add Python to PATH" aktivieren.
3. start.bat doppelklicken. Das Skript installiert CustomTkinter und psutil.
4. RISEN TWEAKS öffnet sich danach automatisch.

WINDOWS-EXE ERSTELLEN (OHNE PYTHON AUF DEM EIGENEN PC)
- Folge BUILD_EXE_OHNE_PYTHON_DE.txt und nutze den enthaltenen GitHub-Actions-Workflow.
- GitHub baut die portable dist\RISEN_TWEAKS.exe auf einem Windows-Cloud-Rechner.
- Danach den Artifact RISEN_TWEAKS-Windows-EXE herunterladen und entpacken.
- Alternativ kann build_exe.bat lokal auf Windows mit installiertem Python ausgefuehrt werden.

BACKUP / LOG
- %LOCALAPPDATA%\RisenTweaks\backup_v2.json
- %LOCALAPPDATA%\RisenTweaks\risen_tweaks_v2.log
- Tools -> Änderungen wiederherstellen stellt alle gespeicherten Werte wieder her.

WICHTIGE HINWEISE
- Die App ist für Windows 10/11 vorgesehen.
- Ein Teil der Sensorwerte wird vom jeweiligen Grafiktreiber bereitgestellt. Wenn
  NVIDIA-SMI keine Daten meldet, zeigt RISEN N/A statt erfundene Werte.
- GPU-Auslastung pro Prozess ist nicht über alle Windows-/Treiberkombinationen
  einheitlich verfügbar und wird daher nicht als Fake-Wert angezeigt.
- Ein Ping-Test zu Cloudflare/Google ist KEIN Fortnite-Server-Ping. Fortnite kann
  über eine andere Route und andere Server antworten.
- CPU-/GPU-Temperaturen und Taktraten werden nur angezeigt, wenn eine geeignete
  Sensorquelle die Daten liefert. Diese Version zeigt keine erfundenen Werte.
- Keine Funktion deaktiviert Defender, Firewall, Windows Update, Secure Boot oder
  Anti-Cheat. Keine MSI-Mode-, HPET-, Nagle-, TCP- oder pauschalen Telemetrie-Hacks.
- Es gibt keine Garantie auf zusätzliche FPS oder geringeren Ping. Vor Änderungen
  werden relevante Registry-Werte und der vorherige Energieplan gesichert.
- Änderungen an Windows-Mauswerten können bei Fortnite mit Raw Input keinen
  spürbaren Effekt haben.

PROJEKTDATEIEN
- main.py: Anwendung
- requirements.txt: Python-Abhängigkeiten
- start.bat: Abhängigkeiten installieren und App starten
- build_exe.bat: optionaler lokaler Windows-EXE-Build
- .github/workflows/build-windows.yml: automatischer Windows-Cloud-Build
- BUILD_EXE_OHNE_PYTHON_DE.txt: Anleitung fuer den Build ohne Python lokal
- reference_ui.png: Screenshot als Designreferenz für die nächste KI
- PROMPT_FUER_NAECHSTE_KI.txt: Folgeauftrag für Cursor Agent
