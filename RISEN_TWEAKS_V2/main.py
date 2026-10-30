from __future__ import annotations

import base64
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk, filedialog
import tkinter as tk

try:
    import customtkinter as ctk
except ImportError:
    print("Missing dependency: customtkinter. Run start.bat first.")
    raise

try:
    import psutil
except ImportError:
    print("Missing dependency: psutil. Run start.bat first.")
    raise

APP_NAME = "RISEN TWEAKS"
APP_VERSION = "2.0.0"
IS_WINDOWS = os.name == "nt"
LOCAL = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
APP_DIR = LOCAL / "RisenTweaks"
BACKUP_FILE = APP_DIR / "backup_v2.json"
LOG_FILE = APP_DIR / "risen_tweaks_v2.log"

BG = "#181818"
SIDEBAR = "#202020"
PANEL = "#202020"
CARD = "#252525"
CARD_HOVER = "#303030"
BORDER = "#292929"
TEXT = "#F5F5F5"
MUTED = "#898989"
PURPLE = "#7257D8"
PURPLE_HOVER = "#8068E6"
GREEN = "#39B980"
RED = "#C94C55"

GAME_MODE_VALUES = [
    (r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1),
    (r"Software\Microsoft\GameBar", "AllowAutoGameMode", 1),
]
GAME_DVR_VALUES = [
    (r"System\GameConfigStore", "GameDVR_Enabled", 0),
    (r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 0),
]
VISUAL_FX_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects"
MOUSE_KEY = r"Control Panel\Mouse"


def log(message: str) -> None:
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")
    except Exception:
        pass


def run_cmd(args: list[str], timeout: int = 12) -> tuple[int, str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0
    try:
        p = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, shell=False, creationflags=flags
        )
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except Exception as exc:
        return 1, str(exc)


def run_ps(script: str, timeout: int = 18) -> tuple[int, str]:
    return run_cmd(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        timeout,
    )


def is_admin() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def fmt_bytes(value: float | int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"


def safe_json_from_powershell(text: str):
    text = text.strip().lstrip("\ufeff")
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # PowerShell can occasionally prepend a warning; keep only the JSON object/array.
        start_obj, start_arr = text.find("{"), text.find("[")
        starts = [x for x in (start_obj, start_arr) if x >= 0]
        if not starts:
            return None
        start = min(starts)
        end = max(text.rfind("}"), text.rfind("]"))
        if end <= start:
            return None
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None


class BackupManager:
    """Backs up only user-scoped registry values and the active power plan."""
    def __init__(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.data = {"registry": {}, "power_plan": None}
        self.load()

    def load(self):
        try:
            if BACKUP_FILE.exists():
                loaded = json.loads(BACKUP_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
        except Exception as exc:
            log(f"Backup read error: {exc}")

    def save(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        temp = BACKUP_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(BACKUP_FILE)

    @staticmethod
    def _encode_value(value):
        if isinstance(value, bytes):
            return {"__bytes__": base64.b64encode(value).decode("ascii")}
        return value

    @staticmethod
    def _decode_value(value):
        if isinstance(value, dict) and "__bytes__" in value:
            return base64.b64decode(value["__bytes__"])
        return value

    def set_user_dword(self, key_path: str, name: str, value: int):
        if not IS_WINDOWS:
            raise RuntimeError("Diese Änderung ist nur unter Windows verfügbar.")
        import winreg
        key_id = key_path + "|" + name
        if key_id not in self.data["registry"]:
            record = {"key": key_path, "name": name, "existed": False, "type": None, "value": None}
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                    old_value, old_type = winreg.QueryValueEx(key, name)
                    record.update({"existed": True, "type": int(old_type), "value": self._encode_value(old_value)})
            except FileNotFoundError:
                pass
            except OSError as exc:
                log(f"Registry read warning {key_id}: {exc}")
            self.data["registry"][key_id] = record
            self.save()
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(value))
        log(f"Registry: HKCU\\{key_path}\\{name}={value}")

    def set_user_string(self, key_path: str, name: str, value: str):
        if not IS_WINDOWS:
            raise RuntimeError("Diese Änderung ist nur unter Windows verfügbar.")
        import winreg
        key_id = key_path + "|" + name
        if key_id not in self.data["registry"]:
            record = {"key": key_path, "name": name, "existed": False, "type": None, "value": None}
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                    old_value, old_type = winreg.QueryValueEx(key, name)
                    record.update({"existed": True, "type": int(old_type), "value": self._encode_value(old_value)})
            except FileNotFoundError:
                pass
            except OSError as exc:
                log(f"Registry read warning {key_id}: {exc}")
            self.data["registry"][key_id] = record
            self.save()
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
        log(f"Registry: HKCU\\{key_path}\\{name}={value}")

    def restore_registry(self) -> tuple[int, int]:
        if not IS_WINDOWS:
            return 0, len(self.data.get("registry", {}))
        import winreg
        restored = failed = 0
        remaining = {}
        for key_id, record in list(self.data.get("registry", {}).items()):
            try:
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, record["key"], 0, winreg.KEY_SET_VALUE) as key:
                    if record.get("existed"):
                        old = self._decode_value(record.get("value"))
                        winreg.SetValueEx(key, record["name"], 0, int(record["type"]), old)
                    else:
                        try:
                            winreg.DeleteValue(key, record["name"])
                        except FileNotFoundError:
                            pass
                restored += 1
            except Exception as exc:
                failed += 1
                remaining[key_id] = record
                log(f"Registry restore failed {key_id}: {exc}")
        self.data["registry"] = remaining
        self.save()
        return restored, failed

    def remember_power_plan(self, guid: str):
        if not self.data.get("power_plan"):
            self.data["power_plan"] = guid
            self.save()

    def restore_power_plan(self) -> bool:
        guid = self.data.get("power_plan")
        if not guid:
            return False
        code, output = run_cmd(["powercfg", "/setactive", guid], 10)
        if code == 0:
            self.data["power_plan"] = None
            self.save()
            log(f"Restored power plan {guid}")
            return True
        log(f"Power plan restore failed: {output}")
        return False


BACKUPS = BackupManager()


class RisenTweaks(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} V{APP_VERSION}  •  System Optimization")
        self.geometry("1320x850")
        self.minsize(1120, 720)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.alive = True
        self.active_page = "GPU Optimization"
        self.sort_by = "cpu"
        self.filter_text = ""
        self.process_rows: dict[str, tuple] = {}
        self.hw_data = {}
        self.last_net = psutil.net_io_counters()
        self.last_net_time = time.time()
        self.net_rates = (0.0, 0.0)
        self.last_disk = psutil.disk_io_counters()
        self.last_disk_time = time.time()
        self.disk_rates = (0.0, 0.0)
        self.gpu_data = None
        self._set_theme()
        self._build_shell()
        self._build_pages()
        self.show_page("GPU Optimization")
        self.refresh_live()
        self.refresh_processes()
        self.refresh_hardware_async()
        self.after(2200, self.periodic)

    def _set_theme(self):
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background="#202020", foreground="#eeeeee", fieldbackground="#202020", rowheight=30, borderwidth=0, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background="#292929", foreground="#dddddd", relief="flat", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#493d79")], foreground=[("selected", "#ffffff")])
        style.configure("Vertical.TScrollbar", background="#303030", troughcolor="#202020", bordercolor="#202020", arrowcolor="#eeeeee")

    def _build_shell(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        # Slim left navigation, matching the reference screenshot.
        self.sidebar = ctk.CTkFrame(self, width=64, corner_radius=0, fg_color=SIDEBAR)
        self.sidebar.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.nav_buttons = {}
        nav_items = [
            ("Home", "⌂"), ("Windows Tweaks", "⊞"), ("Performance", "▥"),
            ("Cleanup", "▤"), ("GPU Optimization", "▣"), ("Fortnite", "F"),
            ("Processes", "☷"), ("Hardware", "◈"), ("Tools", "⚙"),
        ]
        ctk.CTkLabel(self.sidebar, text="R", text_color=PURPLE_HOVER, font=ctk.CTkFont("Segoe UI", 22, "bold")).pack(pady=(13, 18))
        for name, glyph in nav_items:
            btn = ctk.CTkButton(
                self.sidebar, text=glyph, width=46, height=45, corner_radius=10,
                fg_color="transparent", hover_color="#343434", text_color="#f4f4f4",
                font=ctk.CTkFont("Segoe UI Symbol", 22, "bold"), command=lambda p=name: self.show_page(p)
            )
            btn.pack(padx=8, pady=5)
            self.nav_buttons[name] = btn

        self.header = ctk.CTkFrame(self, height=38, corner_radius=0, fg_color="#191919")
        self.header.grid(row=0, column=1, sticky="ew")
        self.header.grid_columnconfigure(0, weight=1)
        self.header.grid_columnconfigure(2, weight=1)
        self.page_title = ctk.CTkLabel(self.header, text="GPU Optimization", text_color="#eeeeee", font=ctk.CTkFont("Segoe UI", 12, "bold"))
        self.page_title.grid(row=0, column=1, padx=10, pady=8)
        self.admin_text = "ADMINISTRATOR" if is_admin() else "NORMAL MODE"
        self.admin_label = ctk.CTkLabel(self.header, text=f"● {self.admin_text}", text_color=GREEN if is_admin() else MUTED, font=ctk.CTkFont("Segoe UI", 9, "bold"))
        self.admin_label.grid(row=0, column=2, sticky="e", padx=16)

        self.page_host = ctk.CTkFrame(self, corner_radius=0, fg_color=BG)
        self.page_host.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(4, 0))
        self.page_host.grid_rowconfigure(0, weight=1)
        self.page_host.grid_columnconfigure(0, weight=1)

        self.status_bar = ctk.CTkLabel(self, text="Bereit · Lokale Systemdaten", anchor="w", height=25, fg_color="#202020", text_color="#a0a0a0", font=ctk.CTkFont("Segoe UI", 9))
        self.status_bar.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(4, 0))

    def _new_page(self):
        return ctk.CTkScrollableFrame(self.page_host, fg_color=BG, corner_radius=0, scrollbar_button_color="#444444", scrollbar_button_hover_color="#666666")

    def _build_pages(self):
        self.pages = {}
        for name in ["Home", "Windows Tweaks", "Performance", "Cleanup", "GPU Optimization", "Fortnite", "Processes", "Hardware", "Tools"]:
            self.pages[name] = self._new_page()
        self._build_gpu_page()
        self._build_windows_page()
        self._build_fortnite_page()
        self._build_home_page()
        self._build_performance_page()
        self._build_cleanup_page()
        self._build_hardware_page()
        self._build_process_page()
        self._build_tools_page()

    def show_page(self, name: str):
        self.active_page = name
        for page in self.pages.values():
            page.grid_forget()
        self.pages[name].grid(row=0, column=0, sticky="nsew")
        self.page_title.configure(text=name)
        for nav, btn in self.nav_buttons.items():
            btn.configure(fg_color=PURPLE if nav == name else "transparent", hover_color=PURPLE_HOVER if nav == name else "#343434")
        if name == "Processes":
            self.refresh_processes()
        elif name == "Hardware":
            self.refresh_hardware_async()
        elif name == "Home":
            self.refresh_live()

    def group(self, parent, title: str, row: int, col: int, columnspan: int = 1):
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=13, border_width=1, border_color=BORDER)
        panel.grid(row=row, column=col, columnspan=columnspan, sticky="nsew", padx=7, pady=7)
        panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(panel, text=title, text_color="#929292", font=ctk.CTkFont("Segoe UI", 10), anchor="center").pack(fill="x", padx=12, pady=(10, 9))
        body = ctk.CTkFrame(panel, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        return body

    def action_card(self, parent, title: str, description: str, button_text: str, callback, *, accent: bool = False, note: str = ""):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=11, border_width=1, border_color="#2a2a2a")
        card.pack(fill="x", pady=5)
        ctk.CTkLabel(card, text=title, text_color=TEXT, font=ctk.CTkFont("Segoe UI", 12, "bold"), anchor="w").pack(fill="x", padx=13, pady=(11, 3))
        ctk.CTkLabel(card, text=description, text_color="#a5a5a5", font=ctk.CTkFont("Segoe UI", 9), anchor="w", justify="left", wraplength=510).pack(fill="x", padx=13, pady=(0, 7))
        btn = ctk.CTkButton(card, text=button_text, command=callback, height=39, corner_radius=9,
                            fg_color=PURPLE if accent else "#292929", hover_color=PURPLE_HOVER if accent else "#393939",
                            text_color="#ffffff", font=ctk.CTkFont("Segoe UI", 10, "bold"))
        btn.pack(fill="x", padx=9, pady=(0, 8))
        if note:
            ctk.CTkLabel(card, text=note, text_color=MUTED, font=ctk.CTkFont("Segoe UI", 8), anchor="w", justify="left", wraplength=510).pack(fill="x", padx=13, pady=(0, 9))
        return card

    def add_page_heading(self, parent, title, subtitle):
        ctk.CTkLabel(parent, text=title, text_color=TEXT, font=ctk.CTkFont("Segoe UI", 22, "bold"), anchor="w").pack(fill="x", padx=8, pady=(9, 2))
        ctk.CTkLabel(parent, text=subtitle, text_color=MUTED, font=ctk.CTkFont("Segoe UI", 10), anchor="w").pack(fill="x", padx=8, pady=(0, 9))

    def _build_gpu_page(self):
        p = self.pages["GPU Optimization"]
        self.add_page_heading(p, "GPU Optimization", "GPU-Status, Treiber und Hersteller-Tools · Einstellungen werden nicht blind in der Registry verändert.")
        grid = ctk.CTkFrame(p, fg_color="transparent")
        grid.pack(fill="x", expand=True)
        grid.grid_columnconfigure((0, 1), weight=1, uniform="gpu")
        nvidia = self.group(grid, "NVIDIA GPU TWEAKS", 0, 0)
        self.action_card(nvidia, "GPU Live-Telemetrie", "Liest GPU-Auslastung, VRAM, Temperatur und Leistungsaufnahme über NVIDIA-SMI, sofern der Treiber es bereitstellt.", "GPU-Daten aktualisieren", self.show_gpu_telemetry, accent=True)
        self.action_card(nvidia, "NVIDIA Control Panel", "Öffnet das offizielle NVIDIA Control Panel. Stelle dort pro Spiel bevorzugte maximale Leistung und V-Sync nur bewusst ein.", "Control Panel öffnen", self.open_nvidia_panel)
        self.action_card(nvidia, "NVIDIA Treiber herunterladen", "Öffnet die offizielle NVIDIA-Treiberseite. Für eine saubere Neuinstallation im Installer 'Benutzerdefiniert' und bei Bedarf 'Neuinstallation vornehmen' auswählen.", "Offizielle Treiberseite", lambda: webbrowser.open("https://www.nvidia.com/Download/index.aspx"))
        self.action_card(nvidia, "NVIDIA System-Check", "Prüft, ob NVIDIA-SMI verfügbar ist und welcher Treiber die GPU meldet. Es wird nichts am Treiber geändert.", "System-Check starten", self.nvidia_check)
        amd = self.group(grid, "RADEON GPU TWEAKS", 0, 1)
        self.action_card(amd, "AMD Radeon Software", "Öffnet AMD Software: Adrenalin Edition, falls installiert. Bei deinem RTX-System ist dieser Bereich normalerweise nicht anwendbar.", "AMD Software öffnen", self.open_amd_software)
        self.action_card(amd, "AMD Treiber & Support", "Offizielle AMD-Seite für Radeon-Treiber. Nur relevant, wenn ein AMD-Grafikgerät verwendet wird.", "Offizielle AMD-Seite", lambda: webbrowser.open("https://www.amd.com/en/support"))
        self.action_card(amd, "Radeon Kompatibilität", "Erkennt die vom Windows-System gemeldeten Grafikkarten und zeigt, ob ein AMD-Gerät vorhanden ist.", "Grafikkarten erkennen", self.refresh_hardware_async)
        info = self.group(grid, "GPU STATUS & SCHEDULING", 1, 0, 2)
        self.gpu_status_label = ctk.CTkLabel(info, text="GPU-Informationen werden geladen …", text_color="#bdbdbd", justify="left", anchor="w", font=ctk.CTkFont("Segoe UI", 10))
        self.gpu_status_label.pack(fill="x", padx=7, pady=7)
        self.action_card(info, "Windows Grafik-Einstellungen", "Dort kannst du Fortnite manuell auf 'Hohe Leistung' (RTX 5060 Ti) setzen. Das ist eine Windows-Zuweisung pro App.", "Grafik-Einstellungen öffnen", lambda: self.open_uri("ms-settings:display-advancedgraphics"))

    def _build_windows_page(self):
        p = self.pages["Windows Tweaks"]
        self.add_page_heading(p, "Windows Tweaks", "Mehrere übersichtliche Tweaks – jede unterstützte Registry-Änderung wird vorab gesichert.")
        grid = ctk.CTkFrame(p, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1), weight=1, uniform="windows")
        general = self.group(grid, "WINDOWS GAMING", 0, 0)
        self.action_card(general, "Windows Game Mode", "Aktiviert den Windows-Spielemodus für deinen Benutzer. Der Effekt hängt von Windows, Treibern und Hintergrundlast ab.", "Game Mode aktivieren", self.apply_game_mode, accent=True)
        self.action_card(general, "Game DVR / Hintergrundaufnahmen", "Deaktiviert Windows-Aufnahmefunktionen für deinen Benutzer. Xbox/Windows-Hintergrundaufnahmen sind danach nicht mehr verfügbar.", "Game DVR deaktivieren", self.apply_game_dvr)
        self.action_card(general, "Animationen & visuelle Effekte", "Setzt den Windows-Effektmodus auf 'Beste Leistung'. Fensteranimationen und einige optische Effekte können verschwinden.", "Auf beste Leistung setzen", self.apply_visual_performance)
        self.action_card(general, "Windows Grafik-Einstellungen", "Weist Fortnite in Windows manuell der dedizierten Hochleistungs-GPU zu.", "Grafik-Einstellungen öffnen", lambda: self.open_uri("ms-settings:display-advancedgraphics"))
        power = self.group(grid, "POWER & PERFORMANCE", 0, 1)
        self.action_card(power, "Höchstleistung aktivieren", "Aktiviert den eingebauten Windows-Energiesparplan 'Höchstleistung'. Mehr Stromverbrauch und Wärme möglich; FPS-Gewinn nicht garantiert.", "Höchstleistung aktivieren", self.apply_high_performance, accent=True)
        self.action_card(power, "Ausbalanciert aktivieren", "Aktiviert den Windows-Standardplan 'Ausbalanciert'. Nutze 'Gesicherte Änderungen zurücksetzen', um den zuvor aktiven Plan wiederherzustellen.", "Ausbalanciert aktivieren", self.apply_balanced)
        self.action_card(power, "Aktiven Energieplan anzeigen", "Zeigt den gerade aktiven Windows-Energiesparplan.", "Energieplan prüfen", self.show_power_plan)
        advanced = self.group(grid, "WINDOWS & DIAGNOSE", 1, 0)
        self.action_card(advanced, "Task-Manager", "Zeigt Prozesse, Autostart, Leistung und App-Verbrauch in Windows.", "Task-Manager öffnen", lambda: self.launch_tool("taskmgr.exe"))
        self.action_card(advanced, "Geräte-Manager", "Prüfe Gerätetreiber, Warnsymbole und erkannte Hardware.", "Geräte-Manager öffnen", lambda: self.launch_tool("devmgmt.msc"))
        self.action_card(advanced, "Windows Sicherheit", "Öffnet die Windows-Sicherheitsübersicht. RISEN deaktiviert Defender oder Firewall nicht.", "Windows Sicherheit öffnen", lambda: self.open_uri("windowsdefender:"))
        maintenance = self.group(grid, "WIEDERHERSTELLUNG", 1, 1)
        self.action_card(maintenance, "Gesicherte Tweaks zurücksetzen", "Stellt die ursprünglichen gesicherten Registry-Werte und den zuvor aktiven Energieplan wieder her.", "Alle Änderungen zurücksetzen", self.restore_all, accent=True)
        self.action_card(maintenance, "Backup-Ordner öffnen", "Öffnet den lokalen Ordner, in dem RISEN deine Sicherung ablegt.", "Backup öffnen", lambda: self.open_path(APP_DIR))

    def _build_fortnite_page(self):
        p = self.pages["Fortnite"]
        self.add_page_heading(p, "Fortnite Competitive Optimizer", "Fokus: stabile Frametime, Eingabelatenz und Netzwerkdiagnose – keine erfundenen FPS- oder Ping-Versprechen.")
        self.fortnite_state = ctk.CTkLabel(p, text="Fortnite-Prozess wird gesucht …", fg_color="#242424", corner_radius=8, text_color="#d4d4d4", anchor="w", height=39)
        self.fortnite_state.pack(fill="x", padx=7, pady=(0, 9))
        grid = ctk.CTkFrame(p, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1), weight=1, uniform="fn")
        game = self.group(grid, "FORTNITE PERFORMANCE", 0, 0)
        self.action_card(game, "Fortnite Prozess-Priorität: HOCH", "Setzt nur den laufenden Fortnite-Spielprozess auf 'Hoch'. Kann auf manchen Systemen helfen, kann aber auch andere Prozesse verdrängen. Nicht Echtzeit verwenden.", "Priorität auf HOCH setzen", self.set_fortnite_high, accent=True)
        self.action_card(game, "Priorität auf NORMAL", "Stellt die Standard-Priorität des laufenden Fortnite-Prozesses wieder her.", "Auf NORMAL zurücksetzen", self.set_fortnite_normal)
        self.action_card(game, "Fortnite Config-Ordner", "Öffnet die lokale WindowsClient-Konfiguration. Erstelle vor manuellen Änderungen selbst eine Kopie der Dateien.", "Config-Ordner öffnen", self.open_fortnite_config)
        self.action_card(game, "Windows Mausbeschleunigung AUS", "Setzt die Windows-Zeigerbeschleunigung auf aus. Fortnite kann Raw Input verwenden; deshalb ist kein messbarer Ingame-Vorteil garantiert. Die alten Werte werden gesichert.", "Mausbeschleunigung deaktivieren", self.apply_mouse_acceleration_off)
        self.action_card(game, "Epic Games Launcher", "Öffnet den Epic Games Launcher, falls installiert.", "Epic Games öffnen", self.open_epic)
        network = self.group(grid, "NETWORK & LATENCY LAB", 0, 1)
        self.network_result = ctk.CTkLabel(network, text="Noch kein Netzwerktest ausgeführt.", text_color="#bdbdbd", anchor="w", justify="left", font=ctk.CTkFont("Segoe UI", 9))
        self.network_result.pack(fill="x", padx=8, pady=(4, 7))
        self.action_card(network, "Cloudflare Ping-Test", "Misst 5 ICMP-Pings zu 1.1.1.1 und berechnet Durchschnitt, Schwankung und Paketverlust. Das ist NICHT dein Fortnite-Server-Ping.", "Ping-Test starten", lambda: self.run_ping_test("1.1.1.1", "Cloudflare"), accent=True)
        self.action_card(network, "Google DNS Ping-Test", "Vergleichstest zu 8.8.8.8. Allgemeiner Internet-Test, keine Messung der Fortnite-Serverroute.", "Vergleich testen", lambda: self.run_ping_test("8.8.8.8", "Google DNS"))
        self.action_card(network, "DNS-Cache leeren", "Leert den lokalen DNS-Cache. Hilft bei manchen Namensauflösungsproblemen, senkt normalerweise nicht den Ingame-Ping.", "DNS-Cache leeren", self.flush_dns)
        self.action_card(network, "Netzwerkadapter anzeigen", "Zeigt aktive Adapter, Link-Speed und Verbindungsstatus aus Windows.", "Adapter-Status anzeigen", self.show_network_adapters)

    def _build_home_page(self):
        p = self.pages["Home"]
        self.add_page_heading(p, "System Overview", "Live-Überblick über deinen Gaming-PC. Aktualisierung alle 2–3 Sekunden.")
        grid = ctk.CTkFrame(p, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="overview")
        self.overview_labels = {}
        for idx, (key, title) in enumerate([("cpu", "CPU USAGE"), ("gpu", "GPU USAGE"), ("ram", "RAM USAGE"), ("disk", "DISK SPACE"), ("net", "NETWORK"), ("gpu_temp", "GPU TEMP")]):
            panel = ctk.CTkFrame(grid, fg_color=PANEL, corner_radius=12, border_width=1, border_color=BORDER)
            panel.grid(row=idx // 3, column=idx % 3, sticky="nsew", padx=7, pady=7)
            ctk.CTkLabel(panel, text=title, text_color=MUTED, font=ctk.CTkFont("Segoe UI", 9, "bold")).pack(anchor="w", padx=15, pady=(13, 4))
            value = ctk.CTkLabel(panel, text="—", text_color=TEXT, font=ctk.CTkFont("Segoe UI", 23, "bold"))
            value.pack(anchor="w", padx=15)
            detail = ctk.CTkLabel(panel, text="Wird geladen …", text_color=MUTED, font=ctk.CTkFont("Segoe UI", 9))
            detail.pack(anchor="w", padx=15, pady=(0, 13))
            self.overview_labels[key] = (value, detail)
        lower = ctk.CTkFrame(p, fg_color="transparent")
        lower.pack(fill="x", pady=(8, 0))
        lower.grid_columnconfigure((0, 1), weight=1, uniform="home")
        quick = self.group(lower, "QUICK ACTIONS", 0, 0)
        self.action_card(quick, "Fortnite Optimizer", "Öffne Performance- und Netzwerkfunktionen.", "Fortnite öffnen", lambda: self.show_page("Fortnite"), accent=True)
        self.action_card(quick, "Hardware Monitor", "Sieh dir die erkannten PC-Komponenten an.", "Hardware öffnen", lambda: self.show_page("Hardware"))
        system = self.group(lower, "SYSTEM INFORMATION", 0, 1)
        self.home_system_label = ctk.CTkLabel(system, text=f"OS: {platform.platform()}\nCPU: {platform.processor() or 'Erkennung läuft'}\nRAM: {fmt_bytes(psutil.virtual_memory().total)}\nBackup: {BACKUP_FILE}", text_color="#bbbbbb", anchor="w", justify="left", font=ctk.CTkFont("Segoe UI", 9))
        self.home_system_label.pack(fill="x", padx=9, pady=8)

    def _build_performance_page(self):
        p = self.pages["Performance"]
        self.add_page_heading(p, "Performance Monitor", "Live-Ressourcenverbrauch und I/O-Durchsatz. Hardware-Sensorwerte hängen vom Treiber ab.")
        grid = ctk.CTkFrame(p, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1), weight=1, uniform="perf")
        left = self.group(grid, "LIVE SYSTEM LOAD", 0, 0)
        self.perf_labels = {}
        for key, title in [("cpu", "CPU"), ("ram", "RAM"), ("gpu", "GPU"), ("disk", "DISK I/O"), ("network", "NETWORK I/O")]:
            row = ctk.CTkFrame(left, fg_color="transparent")
            row.pack(fill="x", padx=7, pady=6)
            ctk.CTkLabel(row, text=title, text_color="#dddddd", width=105, anchor="w", font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(side="left")
            bar = ctk.CTkProgressBar(row, height=10, progress_color=PURPLE)
            bar.set(0)
            bar.pack(side="left", fill="x", expand=True, padx=8)
            label = ctk.CTkLabel(row, text="—", text_color="#aaaaaa", width=135, anchor="e", font=ctk.CTkFont("Segoe UI", 9))
            label.pack(side="right")
            self.perf_labels[key] = (bar, label)
        right = self.group(grid, "PERFORMANCE NOTES", 0, 1)
        ctk.CTkLabel(right, text="• CPU-Auslastung kommt von psutil / Windows.\n\n• GPU-Auslastung, VRAM und Temperatur werden nur angezeigt, wenn NVIDIA-SMI oder ein kompatibler Sensor sie meldet.\n\n• Hohe Datenträger- oder Netzwerkraten zeigen Aktivität, nicht automatisch ein Problem.\n\n• Keine App kann allein durch einen Registry-Schalter einen garantierten FPS-Boost erzeugen.", text_color="#bdbdbd", justify="left", anchor="w", wraplength=470, font=ctk.CTkFont("Segoe UI", 10)).pack(fill="x", padx=10, pady=10)

    def _build_cleanup_page(self):
        p = self.pages["Cleanup"]
        self.add_page_heading(p, "Cleanup & Maintenance", "Nur temporäre Dateien und Diagnosefunktionen. Keine Registry-Cleaner oder automatisches Löschen von Systemdateien.")
        grid = ctk.CTkFrame(p, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1), weight=1, uniform="clean")
        temp = self.group(grid, "TEMP FILES", 0, 0)
        self.action_card(temp, "Benutzer-Temp leeren", "Löscht Inhalte aus deinem Benutzer-Temp-Ordner. Dateien, die Windows oder Apps gerade verwenden, werden übersprungen.", "Temp-Dateien bereinigen", self.clean_temp, accent=True)
        self.action_card(temp, "Temp-Ordner öffnen", "Öffnet den Temp-Ordner, damit du Dateien selbst prüfen kannst.", "Temp-Ordner öffnen", lambda: self.open_path(Path(os.environ.get("TEMP", str(Path.home() / "AppData/Local/Temp")))))
        dns = self.group(grid, "NETWORK MAINTENANCE", 0, 1)
        self.action_card(dns, "DNS-Cache leeren", "Nur lokaler DNS-Cache. Kein normaler Fortnite-Ping-Booster.", "DNS-Cache leeren", self.flush_dns)
        self.action_card(dns, "Netzwerk-Einstellungen", "Öffnet die Windows-Netzwerk- und Interneteinstellungen.", "Einstellungen öffnen", lambda: self.open_uri("ms-settings:network-status"))
        self.action_card(dns, "Windows Update", "Öffnet Windows Update. RISEN deaktiviert Updates nicht.", "Windows Update öffnen", lambda: self.open_uri("ms-settings:windowsupdate"))

    def _build_hardware_page(self):
        p = self.pages["Hardware"]
        self.add_page_heading(p, "Hardware & Components", "Erkannte Komponenten, Live-Auslastung und Gerätestatus. Nicht jedes Gerät stellt einen eigenen Nutzungs-Sensor bereit.")
        top = ctk.CTkFrame(p, fg_color="transparent")
        top.pack(fill="x", padx=7, pady=(0, 8))
        ctk.CTkButton(top, text="Hardware neu erkennen", command=self.refresh_hardware_async, fg_color=PURPLE, hover_color=PURPLE_HOVER, width=175).pack(side="left")
        ctk.CTkButton(top, text="Geräte-Manager öffnen", command=lambda: self.launch_tool("devmgmt.msc"), fg_color="#292929", hover_color="#383838", width=175).pack(side="left", padx=8)
        ctk.CTkButton(top, text="Alle Geräte auflisten", command=self.show_all_devices, fg_color="#292929", hover_color="#383838", width=175).pack(side="left", padx=0)
        grid = ctk.CTkFrame(p, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1), weight=1, uniform="hardware")
        self.hw_labels = {}
        for idx, (key, title) in enumerate([
            ("cpu", "PROCESSOR"), ("gpu", "GRAPHICS"), ("ram", "MEMORY"), ("board", "MOTHERBOARD & BIOS"),
            ("drives", "STORAGE DEVICES"), ("network", "NETWORK ADAPTERS"), ("os", "WINDOWS"), ("displays", "DISPLAY")
        ]):
            body = self.group(grid, title, idx // 2, idx % 2)
            label = ctk.CTkLabel(body, text="Daten werden erkannt …", text_color="#cccccc", justify="left", anchor="w", font=ctk.CTkFont("Segoe UI", 9))
            label.pack(fill="x", padx=7, pady=7)
            self.hw_labels[key] = label

    def _build_process_page(self):
        p = self.pages["Processes"]
        self.add_page_heading(p, "Process Manager", "Sortiere Prozesse nach CPU oder RAM. Das Beenden von Prozessen erfordert eine zusätzliche Bestätigung.")
        toolbar = ctk.CTkFrame(p, fg_color="transparent")
        toolbar.pack(fill="x", padx=7, pady=(0, 8))
        self.process_search = ctk.CTkEntry(toolbar, placeholder_text="Prozess suchen …", width=260, height=34)
        self.process_search.pack(side="left", padx=(0, 8))
        self.process_search.bind("<KeyRelease>", lambda _e: self.refresh_processes())
        ctk.CTkButton(toolbar, text="CPU sortieren", command=lambda: self.set_process_sort("cpu"), width=115, fg_color="#292929", hover_color="#383838").pack(side="left", padx=3)
        ctk.CTkButton(toolbar, text="RAM sortieren", command=lambda: self.set_process_sort("memory"), width=115, fg_color="#292929", hover_color="#383838").pack(side="left", padx=3)
        ctk.CTkButton(toolbar, text="Aktualisieren", command=self.refresh_processes, width=115, fg_color=PURPLE, hover_color=PURPLE_HOVER).pack(side="left", padx=3)
        self.process_count = ctk.CTkLabel(toolbar, text="", text_color=MUTED, font=ctk.CTkFont("Segoe UI", 9))
        self.process_count.pack(side="right")
        table_frame = ctk.CTkFrame(p, fg_color=PANEL, corner_radius=10)
        table_frame.pack(fill="both", expand=True, padx=7, pady=(0, 8))
        cols = ("name", "pid", "cpu", "memory", "status")
        self.process_tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse", height=18)
        for col, label, width, anchor in [
            ("name", "PROCESS", 360, "w"), ("pid", "PID", 80, "center"), ("cpu", "CPU %", 100, "center"),
            ("memory", "RAM MB", 120, "center"), ("status", "STATUS", 150, "center")
        ]:
            self.process_tree.heading(col, text=label)
            self.process_tree.column(col, width=width, anchor=anchor)
        self.process_tree.pack(fill="both", expand=True, padx=7, pady=7)
        footer = ctk.CTkFrame(p, fg_color="transparent")
        footer.pack(fill="x", padx=7)
        ctk.CTkButton(footer, text="Ausgewählten Prozess beenden", command=self.end_selected_process, fg_color="#7a3036", hover_color="#983d45", width=220).pack(side="left")
        ctk.CTkLabel(footer, text="GPU-Auslastung pro Prozess wird nicht auf jeder Windows-/Treiberkombination bereitgestellt.", text_color=MUTED, font=ctk.CTkFont("Segoe UI", 9)).pack(side="left", padx=12)

    def _build_tools_page(self):
        p = self.pages["Tools"]
        self.add_page_heading(p, "Tools, Backup & Settings", "Wiederherstellung, Diagnose und Windows-Werkzeuge.")
        grid = ctk.CTkFrame(p, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1), weight=1, uniform="tools")
        backup = self.group(grid, "BACKUP & RESTORE", 0, 0)
        self.backup_label = ctk.CTkLabel(backup, text=self.backup_summary(), text_color="#bdbdbd", justify="left", anchor="w", font=ctk.CTkFont("Segoe UI", 9))
        self.backup_label.pack(fill="x", padx=8, pady=7)
        self.action_card(backup, "Gesicherte Änderungen wiederherstellen", "Stellt gespeicherte Registry-Werte im Benutzerbereich und den vorherigen Energieplan wieder her.", "Jetzt wiederherstellen", self.restore_all, accent=True)
        self.action_card(backup, "Backup-Verzeichnis", "Öffnet den lokalen AppData-Ordner.", "Ordner öffnen", lambda: self.open_path(APP_DIR))
        tools = self.group(grid, "WINDOWS TOOLS", 0, 1)
        self.action_card(tools, "Systeminformationen", "Öffnet msinfo32 mit einer ausführlichen Windows- und Hardwareübersicht.", "Systeminformationen öffnen", lambda: self.launch_tool("msinfo32.exe"))
        self.action_card(tools, "Ressourcenmonitor", "Öffnet den Windows-Ressourcenmonitor für CPU, Speicher, Datenträger und Netzwerk.", "Ressourcenmonitor öffnen", lambda: self.launch_tool("resmon.exe"))
        self.action_card(tools, "DirectX-Diagnose", "Öffnet dxdiag zur Anzeige von DirectX- und Grafiktreiberinformationen.", "dxdiag öffnen", lambda: self.launch_tool("dxdiag.exe"))
        self.action_card(tools, "Autostart-Programme prüfen", "Liest die Windows-Run-Schlüssel und Autostart-Ordner aus. Die Übersicht ist zunächst nur lesend – es werden keine Programme automatisch deaktiviert.", "Autostart anzeigen", self.show_startup_apps)
        diag = self.group(grid, "EXPORT & LOGS", 1, 0)
        self.action_card(diag, "Systembericht exportieren", "Speichert einen Textbericht mit Hardware-, Windows-, RAM- und Netzwerkdaten.", "Bericht exportieren", self.export_report)
        self.action_card(diag, "RISEN Log öffnen", "Zeigt das lokale Diagnoseprotokoll.", "Log öffnen", lambda: self.open_path(LOG_FILE))
        about = self.group(grid, "ABOUT RISEN TWEAKS", 1, 1)
        ctk.CTkLabel(about, text=f"RISEN TWEAKS v{APP_VERSION}\nWindows 10/11 · Python / CustomTkinter\n\nBackup: {BACKUP_FILE}\nLog: {LOG_FILE}\n\nHinweis: Änderungen sind lokal. Es werden keine Prozesse automatisch beendet und keine Sicherheitsfunktionen deaktiviert.", text_color="#bdbdbd", anchor="w", justify="left", font=ctk.CTkFont("Segoe UI", 9)).pack(fill="x", padx=8, pady=7)

    # --------------------------- live data ---------------------------
    def refresh_live(self):
        if not self.alive:
            return
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            disk_pct = None
            try:
                root = Path.home().anchor or "C:\\"
                disk_pct = psutil.disk_usage(root).percent
            except Exception:
                pass
            now = time.time()
            net = psutil.net_io_counters()
            dt = max(0.001, now - self.last_net_time)
            down = max(0, net.bytes_recv - self.last_net.bytes_recv) / dt
            up = max(0, net.bytes_sent - self.last_net.bytes_sent) / dt
            self.net_rates = (down, up)
            self.last_net, self.last_net_time = net, now
            disk = psutil.disk_io_counters()
            dt_disk = max(0.001, now - self.last_disk_time)
            if disk and self.last_disk:
                read = max(0, disk.read_bytes - self.last_disk.read_bytes) / dt_disk
                write = max(0, disk.write_bytes - self.last_disk.write_bytes) / dt_disk
                self.disk_rates = (read, write)
            self.last_disk, self.last_disk_time = disk, now

            gpu = self.gpu_data or {}
            gpu_usage = gpu.get("usage")
            gpu_temp = gpu.get("temp")
            total_disk_detail = f"{disk_pct:.0f}% used" if disk_pct is not None else "Not available"
            values = {
                "cpu": (f"{cpu:.0f}%", f"{psutil.cpu_count(logical=False) or '?'} cores / {psutil.cpu_count(logical=True) or '?'} threads"),
                "gpu": (f"{gpu_usage:.0f}%" if gpu_usage is not None else "N/A", safe_gpu_detail(gpu)),
                "ram": (f"{mem.percent:.0f}%", f"{fmt_bytes(mem.used)} / {fmt_bytes(mem.total)}"),
                "disk": (f"{disk_pct:.0f}%" if disk_pct is not None else "N/A", total_disk_detail),
                "net": (f"↓ {fmt_bytes(down)}/s", f"↑ {fmt_bytes(up)}/s"),
                "gpu_temp": (f"{gpu_temp} °C" if gpu_temp is not None else "N/A", "GPU sensor / NVIDIA-SMI" if gpu_temp is not None else "Sensor not reported"),
            }
            if hasattr(self, "overview_labels"):
                for key, (value, detail) in values.items():
                    self.overview_labels[key][0].configure(text=value)
                    self.overview_labels[key][1].configure(text=detail)
            if hasattr(self, "perf_labels"):
                for key, (value, detail) in {
                    "cpu": (cpu / 100, f"{cpu:.1f}%"),
                    "ram": (mem.percent / 100, f"{mem.percent:.1f}% · {fmt_bytes(mem.used)}"),
                    "gpu": ((gpu_usage or 0) / 100 if gpu_usage is not None else 0, f"{gpu_usage:.1f}%" if gpu_usage is not None else "N/A"),
                    "disk": (0, f"R {fmt_bytes(self.disk_rates[0])}/s · W {fmt_bytes(self.disk_rates[1])}/s"),
                    "network": (0, f"↓ {fmt_bytes(down)}/s · ↑ {fmt_bytes(up)}/s"),
                }.items():
                    bar, label = self.perf_labels[key]
                    bar.set(max(0, min(1, value)))
                    label.configure(text=detail)
            if hasattr(self, "fortnite_state"):
                found = self.find_fortnite()
                if found:
                    self.fortnite_state.configure(text=f"Fortnite läuft · {len(found)} Prozess(e) erkannt", text_color=GREEN)
                else:
                    self.fortnite_state.configure(text="Fortnite läuft gerade nicht · Starte das Spiel für Prozess-Tweaks", text_color="#d1b26b")
        except Exception as exc:
            log(f"Live refresh: {exc}")

    def periodic(self):
        if not self.alive:
            return
        self.refresh_live()
        if self.active_page == "Processes":
            self.refresh_processes()
        if int(time.time()) % 8 < 3:
            self.refresh_gpu_async()
        self.after(2200, self.periodic)

    def refresh_gpu_async(self):
        def worker():
            result = self.read_gpu_data()
            if self.alive:
                self.after(0, lambda: self._accept_gpu_data(result))
        threading.Thread(target=worker, daemon=True).start()

    def read_gpu_data(self):
        nvsmi = shutil.which("nvidia-smi")
        if not nvsmi:
            return {"available": False, "name": "NVIDIA-SMI not found"}
        code, output = run_cmd([nvsmi, "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw", "--format=csv,noheader,nounits"], 5)
        if code != 0 or not output:
            return {"available": False, "name": "NVIDIA telemetry unavailable", "error": output[:250]}
        parts = [x.strip() for x in output.splitlines()[0].split(",")]
        if len(parts) < 5:
            return {"available": False, "name": output[:180]}
        def number(i):
            try:
                return float(parts[i])
            except Exception:
                return None
        return {
            "available": True, "name": parts[0], "usage": number(1),
            "mem_used": number(2), "mem_total": number(3), "temp": number(4),
            "power": number(5) if len(parts) > 5 else None,
        }

    def _accept_gpu_data(self, data):
        self.gpu_data = data
        if hasattr(self, "gpu_status_label"):
            self.gpu_status_label.configure(text=safe_gpu_detail(data, verbose=True))
        if data.get("available"):
            self.status_bar.configure(text=f"GPU: {data['name']} · {data.get('usage') if data.get('usage') is not None else 'N/A'}% · Live monitoring")

    def refresh_hardware_async(self):
        self.set_status("Hardware-Erkennung läuft …")
        def worker():
            script = r'''
$ErrorActionPreference = 'SilentlyContinue'
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed
$board = Get-CimInstance Win32_BaseBoard | Select-Object -First 1 Manufacturer,Product,Version
$bios = Get-CimInstance Win32_BIOS | Select-Object -First 1 SMBIOSBIOSVersion,ReleaseDate
$video = @(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,VideoModeDescription,CurrentRefreshRate)
$drives = @(Get-CimInstance Win32_DiskDrive | Select-Object Model,MediaType,Size,Status,InterfaceType)
$net = @(Get-NetAdapter -ErrorAction SilentlyContinue | Select-Object Name,InterfaceDescription,Status,LinkSpeed)
$os = Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture
$display = @(Get-CimInstance Win32_DesktopMonitor | Select-Object Name,ScreenWidth,ScreenHeight,Status)
$o = [pscustomobject]@{CPU=$cpu;Board=$board;BIOS=$bios;Video=$video;Drives=$drives;Network=$net;OS=$os;Display=$display}
$o | ConvertTo-Json -Depth 5 -Compress
'''
            code, output = run_ps(script, 24)
            data = safe_json_from_powershell(output) if code == 0 else None
            if self.alive:
                self.after(0, lambda: self._accept_hardware(data, output))
        threading.Thread(target=worker, daemon=True).start()
        self.refresh_gpu_async()

    def _accept_hardware(self, data, raw=""):
        if not data:
            self.set_status("Hardware-Erkennung teilweise nicht verfügbar · Prüfe PowerShell/CIM")
            log(f"Hardware CIM parse error: {raw[:500]}")
            return
        self.hw_data = data
        def obj(key):
            val = data.get(key)
            if isinstance(val, list):
                return val
            return [val] if isinstance(val, dict) else []
        cpu = obj("CPU")
        board = obj("Board")
        bios = obj("BIOS")
        videos = obj("Video")
        drives = obj("Drives")
        nets = obj("Network")
        osinfo = obj("OS")
        displays = obj("Display")
        self._set_hw("cpu", "\n".join([f"{x.get('Name', 'CPU')}" for x in cpu]) or "Nicht erkannt")
        gpu_lines = []
        for x in videos:
            gpu_lines.append(f"{x.get('Name', 'GPU')}\nDriver: {x.get('DriverVersion', 'N/A')}\nMode: {x.get('VideoModeDescription', 'N/A')} · {x.get('CurrentRefreshRate', 'N/A')} Hz")
        self._set_hw("gpu", "\n\n".join(gpu_lines) or "Nicht erkannt")
        self._set_hw("ram", f"{fmt_bytes(psutil.virtual_memory().total)} installed\nUsage: {psutil.virtual_memory().percent:.1f}% · {fmt_bytes(psutil.virtual_memory().used)} used")
        b = board[0] if board else {}
        bi = bios[0] if bios else {}
        self._set_hw("board", f"{b.get('Manufacturer', 'N/A')} {b.get('Product', '')}\nBIOS: {bi.get('SMBIOSBIOSVersion', 'N/A')}\nVersion / Date: {b.get('Version', 'N/A')} / {bi.get('ReleaseDate', 'N/A')}")
        disk_lines = []
        for x in drives:
            disk_lines.append(f"{x.get('Model', 'Disk')} · {fmt_bytes(x.get('Size') or 0)}\n{x.get('MediaType', '')} · {x.get('InterfaceType', '')} · {x.get('Status', '')}")
        # Also show mounted volumes and their usage.
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disk_lines.append(f"{part.device} · {fmt_bytes(usage.total)}\nUsed {usage.percent:.1f}% · Free {fmt_bytes(usage.free)}")
            except Exception:
                continue
        self._set_hw("drives", "\n\n".join(disk_lines) or "Keine Laufwerke gemeldet")
        net_lines = [f"{x.get('Name', 'Adapter')} · {x.get('Status', 'N/A')} · {x.get('LinkSpeed', 'N/A')}\n{x.get('InterfaceDescription', '')}" for x in nets]
        self._set_hw("network", "\n\n".join(net_lines) or "Adapterdaten nicht verfügbar")
        oi = osinfo[0] if osinfo else {}
        self._set_hw("os", f"{oi.get('Caption', platform.platform())}\nVersion {oi.get('Version', platform.version())} · Build {oi.get('BuildNumber', 'N/A')}\n{oi.get('OSArchitecture', platform.machine())}")
        disp_lines = [f"{x.get('Name', 'Display')} · {x.get('ScreenWidth', 'N/A')} × {x.get('ScreenHeight', 'N/A')} · {x.get('Status', '')}" for x in displays]
        if not disp_lines:
            disp_lines = ["Display-Informationen werden vom Monitor-Treiber bereitgestellt."]
        self._set_hw("displays", "\n".join(disp_lines))
        self.set_status("Hardware-Erkennung abgeschlossen")
        if hasattr(self, "home_system_label"):
            cpus = cpu[0].get("Name", "N/A") if cpu else platform.processor()
            self.home_system_label.configure(text=f"OS: {oi.get('Caption', platform.platform())}\nCPU: {cpus}\nRAM: {fmt_bytes(psutil.virtual_memory().total)}\nBackup: {BACKUP_FILE}")

    def _set_hw(self, key, text):
        if key in getattr(self, "hw_labels", {}):
            self.hw_labels[key].configure(text=text)

    # --------------------------- processes ---------------------------
    def set_process_sort(self, key):
        self.sort_by = key
        self.refresh_processes()

    def refresh_processes(self):
        if not hasattr(self, "process_tree") or not self.alive:
            return
        query = self.process_search.get().strip().lower() if hasattr(self, "process_search") else ""
        rows = []
        for proc in psutil.process_iter(["pid", "name", "memory_info", "status"]):
            try:
                info = proc.info
                name = info.get("name") or "Unknown"
                if query and query not in name.lower():
                    continue
                cpu = proc.cpu_percent(interval=None)
                mem = info.get("memory_info")
                mem_mb = (mem.rss / (1024 * 1024)) if mem else 0
                rows.append((name, int(info["pid"]), cpu, mem_mb, info.get("status", "")))
            except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
                continue
            except Exception:
                continue
        rows.sort(key=lambda r: r[2] if self.sort_by == "cpu" else r[3], reverse=True)
        wanted = set()
        for name, pid, cpu, mem, status in rows[:500]:
            iid = str(pid)
            wanted.add(iid)
            vals = (name, pid, f"{cpu:.1f}", f"{mem:.1f}", status)
            if self.process_tree.exists(iid):
                self.process_tree.item(iid, values=vals)
            else:
                self.process_tree.insert("", "end", iid=iid, values=vals)
        for iid in self.process_tree.get_children():
            if iid not in wanted:
                self.process_tree.delete(iid)
        self.process_count.configure(text=f"{min(len(rows), 500)} Prozesse · Sortiert: {self.sort_by.upper()}")

    def end_selected_process(self):
        selected = self.process_tree.selection()
        if not selected:
            messagebox.showinfo(APP_NAME, "Wähle zuerst einen Prozess aus.")
            return
        pid = int(selected[0])
        try:
            proc = psutil.Process(pid)
            name = proc.name()
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Prozess nicht mehr verfügbar: {exc}")
            return
        protected = {"system", "system idle process", "registry", "smss.exe", "csrss.exe", "wininit.exe", "services.exe", "lsass.exe", "winlogon.exe", "svchost.exe", "fontdrvhost.exe", "dwm.exe"}
        if pid <= 4 or name.lower() in protected:
            messagebox.showwarning(APP_NAME, "Dieser Windows-Systemprozess ist geschützt und kann über RISEN nicht beendet werden.")
            return
        if not messagebox.askyesno("Prozess beenden?", f"Soll '{name}' (PID {pid}) wirklich beendet werden?\n\nUngespeicherte Daten können verloren gehen."):
            return
        try:
            proc.terminate()
            self.set_status(f"Beenden angefordert: {name} (PID {pid})")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Prozess konnte nicht beendet werden: {exc}")

    # --------------------------- tweak actions ---------------------------
    def _apply_registry_values(self, entries):
        if not IS_WINDOWS:
            raise RuntimeError("Registry-Tweaks sind nur auf Windows verfügbar.")
        for key, name, value in entries:
            BACKUPS.set_user_dword(key, name, value)
        self.update_backup_label()

    def apply_game_mode(self):
        try:
            self._apply_registry_values(GAME_MODE_VALUES)
            messagebox.showinfo(APP_NAME, "Windows Game Mode wurde aktiviert. Die ursprünglichen Werte wurden gesichert.")
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def apply_game_dvr(self):
        if not messagebox.askyesno("Game DVR deaktivieren?", "Windows Game DVR und Hintergrundaufnahmen werden für deinen Benutzer deaktiviert. Fortfahren?"):
            return
        try:
            self._apply_registry_values(GAME_DVR_VALUES)
            messagebox.showinfo(APP_NAME, "Game DVR wurde deaktiviert. Die alten Werte sind gesichert.")
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def apply_visual_performance(self):
        if not messagebox.askyesno("Visuelle Effekte ändern?", "Windows wird auf 'Beste Leistung' gestellt. Animationen und einige Effekte werden reduziert. Die vorherige Einstellung wird gesichert. Fortfahren?"):
            return
        try:
            self._apply_registry_values([(VISUAL_FX_KEY, "VisualFXSetting", 2)])
            messagebox.showinfo(APP_NAME, "Windows-Effekte auf beste Leistung gesetzt. Eventuell ab- und wieder anmelden, damit alle Änderungen sichtbar werden.")
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def _current_power_plan(self):
        code, out = run_cmd(["powercfg", "/getactivescheme"], 8)
        m = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", out)
        return m.group(1) if code == 0 and m else None, out

    def _set_power_plan(self, scheme: str):
        current, output = self._current_power_plan()
        if not current:
            messagebox.showerror(APP_NAME, f"Aktiver Energieplan konnte nicht gelesen werden.\n{output}")
            return
        BACKUPS.remember_power_plan(current)
        code, out = run_cmd(["powercfg", "/setactive", scheme], 10)
        if code == 0:
            self.update_backup_label()
            messagebox.showinfo(APP_NAME, "Energieplan geändert. Der zuvor aktive Plan wurde gesichert.")
        else:
            messagebox.showerror(APP_NAME, f"Energieplan konnte nicht geändert werden:\n{out}")

    def apply_high_performance(self):
        if messagebox.askyesno("Höchstleistung aktivieren?", "Der Energieverbrauch und die Wärme können steigen. Mehr FPS sind nicht garantiert. Fortfahren?"):
            self._set_power_plan("SCHEME_MIN")

    def apply_balanced(self):
        if messagebox.askyesno("Ausbalanciert aktivieren?", "Der zuvor aktive Energieplan wird gesichert. Fortfahren?"):
            self._set_power_plan("SCHEME_BALANCED")

    def show_power_plan(self):
        _, out = self._current_power_plan()
        messagebox.showinfo("Aktiver Energieplan", out or "Keine Information verfügbar.")

    def restore_all(self):
        reg_count = len(BACKUPS.data.get("registry", {}))
        has_power = bool(BACKUPS.data.get("power_plan"))
        if not reg_count and not has_power:
            messagebox.showinfo(APP_NAME, "Es sind keine gesicherten Tweaks vorhanden.")
            return
        if not messagebox.askyesno("Änderungen wiederherstellen?", "RISEN stellt alle gespeicherten Registry-Werte und den vorherigen Energieplan wieder her. Fortfahren?"):
            return
        restored, failed = BACKUPS.restore_registry()
        plan_ok = BACKUPS.restore_power_plan() if has_power else None
        self.update_backup_label()
        messagebox.showinfo(APP_NAME, f"Wiederherstellung beendet.\nRegistry-Werte wiederhergestellt: {restored}\nFehler: {failed}\nEnergieplan: {'wiederhergestellt' if plan_ok else ('nicht gesichert' if plan_ok is None else 'fehlgeschlagen')}")

    def backup_summary(self):
        return f"Gesicherte Registry-Werte: {len(BACKUPS.data.get('registry', {}))}\nVorheriger Energieplan: {'gesichert' if BACKUPS.data.get('power_plan') else 'keine Sicherung'}\nDatei: {BACKUP_FILE}"

    def update_backup_label(self):
        if hasattr(self, "backup_label"):
            self.backup_label.configure(text=self.backup_summary())

    def find_fortnite(self):
        found = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if (proc.info.get("name") or "").lower() == "fortniteclient-win64-shipping.exe":
                    found.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return found

    def set_fortnite_high(self):
        procs = self.find_fortnite()
        if not procs:
            messagebox.showwarning(APP_NAME, "Fortnite läuft gerade nicht. Starte erst Fortnite und versuche es erneut.")
            return
        changed = failed = 0
        for proc in procs:
            try:
                proc.nice(psutil.HIGH_PRIORITY_CLASS)
                changed += 1
            except Exception as exc:
                failed += 1
                log(f"Fortnite priority error: {exc}")
        messagebox.showinfo(APP_NAME, f"Priorität auf HOCH gesetzt: {changed}\nFehlgeschlagen: {failed}\n\nNicht 'Echtzeit' verwenden.")

    def set_fortnite_normal(self):
        procs = self.find_fortnite()
        if not procs:
            messagebox.showinfo(APP_NAME, "Fortnite läuft gerade nicht. Nach dem nächsten Start gilt wieder die Standardpriorität.")
            return
        changed = 0
        for proc in procs:
            try:
                proc.nice(psutil.NORMAL_PRIORITY_CLASS)
                changed += 1
            except Exception as exc:
                log(f"Fortnite normal priority error: {exc}")
        messagebox.showinfo(APP_NAME, f"Auf NORMAL zurückgesetzt: {changed} Prozess(e).")

    def run_ping_test(self, address: str, label: str):
        self.network_result.configure(text=f"Teste {label} ({address}) …")
        self.set_status(f"Ping-Test zu {address} läuft …")
        def worker():
            code, out = run_cmd(["ping", "-n", "5", "-w", "1200", address], 10)
            samples = [int(x) for x in re.findall(r"(?:time|zeit)[=<]\s*(\d+)\s*ms", out, re.IGNORECASE)]
            avg = sum(samples) / len(samples) if samples else None
            jitter = (max(samples) - min(samples)) if len(samples) > 1 else None
            loss_match = re.search(r"(\d+)\s*%", out)
            loss = f"{loss_match.group(1)}%" if loss_match else ("0%" if len(samples) == 5 else "nicht ermittelt")
            if avg is None:
                result = f"{label}: Keine ICMP-Antwort · Paketverlust {loss}"
            else:
                result = f"{label}: Ø {avg:.1f} ms · Schwankung (max–min) {jitter} ms · Verlust {loss} · {len(samples)}/5 Antworten"
            if self.alive:
                self.after(0, lambda: self.network_result.configure(text=result + "\nHinweis: nicht der Fortnite-Server-Ping."))
                self.after(0, lambda: self.set_status("Netzwerktest abgeschlossen"))
        threading.Thread(target=worker, daemon=True).start()

    def apply_mouse_acceleration_off(self):
        if not messagebox.askyesno("Mausbeschleunigung deaktivieren?", "Windows MouseSpeed und die beiden Schwellenwerte werden für deinen Benutzer auf 0 gesetzt. Die ursprünglichen Registry-Werte werden gespeichert. Fortfahren?"):
            return
        try:
            for name in ("MouseSpeed", "MouseThreshold1", "MouseThreshold2"):
                BACKUPS.set_user_string(MOUSE_KEY, name, "0")
            self.update_backup_label()
            messagebox.showinfo(APP_NAME, "Windows-Mausbeschleunigung wurde deaktiviert. Die alten Werte kannst du unter Tools → Wiederherstellen zurücksetzen.\n\nHinweis: Fortnite-Raw-Input und die Ingame-Sensitivität werden dadurch nicht direkt verändert.")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Maus-Einstellung konnte nicht geändert werden:\n{exc}")

    def show_all_devices(self):
        script = "Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Sort-Object Class,FriendlyName | Select-Object -First 100 Class,FriendlyName,Status | Format-Table -AutoSize | Out-String -Width 220"
        code, out = run_ps(script, 20)
        if code == 0 and out:
            messagebox.showinfo("Erkannte Geräte (erste 100)", out[:11500])
        else:
            messagebox.showwarning(APP_NAME, "Die Windows-Geräteliste konnte nicht gelesen werden. Öffne stattdessen den Geräte-Manager.")

    def show_startup_apps(self):
        if not IS_WINDOWS:
            return
        import winreg
        found = []
        registry_paths = [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKCU Run"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "HKCU RunOnce"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKLM Run"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "HKLM Run 32-bit"),
        ]
        for hive, key_path, label in registry_paths:
            try:
                with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ) as key:
                    count = winreg.QueryInfoKey(key)[1]
                    for i in range(count):
                        name, value, _ = winreg.EnumValue(key, i)
                        found.append(f"[{label}] {name}\n{value}")
            except OSError:
                continue
        startup_dirs = [
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup",
            Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs/Startup",
        ]
        for folder in startup_dirs:
            try:
                for item in folder.iterdir():
                    found.append(f"[Startup folder] {item.name}\n{item}")
            except Exception:
                pass
        text = "\n\n".join(found) if found else "Keine Autostart-Einträge gefunden oder auslesbar."
        messagebox.showinfo("Autostart-Übersicht", text[:12000] + ("\n\n… Ausgabe gekürzt." if len(text) > 12000 else ""))

    def flush_dns(self):
        if not messagebox.askyesno("DNS-Cache leeren?", "Der lokale DNS-Namenscache wird geleert. Das senkt normalerweise nicht den Ingame-Ping. Fortfahren?"):
            return
        code, out = run_cmd(["ipconfig", "/flushdns"], 10)
        if code == 0:
            messagebox.showinfo(APP_NAME, out[-900:] or "DNS-Cache geleert.")
        else:
            messagebox.showerror(APP_NAME, f"DNS-Cache konnte nicht geleert werden:\n{out[-900:]}")

    def show_network_adapters(self):
        script = "Get-NetAdapter | Format-Table -AutoSize Name,Status,LinkSpeed,InterfaceDescription | Out-String -Width 220"
        code, out = run_ps(script, 12)
        messagebox.showinfo("Netzwerkadapter", out[:3500] if code == 0 and out else "Keine Adapterdaten verfügbar.")

    def clean_temp(self):
        temp = Path(os.environ.get("TEMP", str(Path.home() / "AppData/Local/Temp")))
        if not temp.exists() or not temp.is_dir():
            messagebox.showinfo(APP_NAME, "Temp-Ordner nicht gefunden.")
            return
        if not messagebox.askyesno("Temporäre Dateien löschen?", f"Es werden nur Inhalte dieses Ordners gelöscht:\n{temp}\n\nGeöffnete/gesperrte Dateien werden übersprungen. Fortfahren?"):
            return
        deleted = skipped = 0
        for item in temp.iterdir():
            try:
                if item.is_symlink():
                    skipped += 1
                elif item.is_dir():
                    shutil.rmtree(item)
                    deleted += 1
                else:
                    item.unlink()
                    deleted += 1
            except Exception:
                skipped += 1
        messagebox.showinfo(APP_NAME, f"Temp-Bereinigung abgeschlossen.\nGelöschte Einträge: {deleted}\nÜbersprungen: {skipped}")

    # --------------------------- launchers / tools ---------------------------
    def open_fortnite_config(self):
        path = LOCAL / "FortniteGame" / "Saved" / "Config" / "WindowsClient"
        if path.exists():
            self.open_path(path)
        else:
            messagebox.showinfo(APP_NAME, f"Fortnite Config nicht gefunden:\n{path}\n\nStarte Fortnite mindestens einmal.")

    def open_epic(self):
        candidates = [
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                subprocess.Popen([str(candidate)], close_fds=True)
                return
        try:
            os.startfile("com.epicgames.launcher://apps/Fortnite?action=launch&silent=true")
        except Exception:
            webbrowser.open("https://store.epicgames.com/")

    def show_gpu_telemetry(self):
        data = self.gpu_data or self.read_gpu_data()
        self._accept_gpu_data(data)
        messagebox.showinfo("GPU Live-Telemetrie", safe_gpu_detail(data, verbose=True))

    def nvidia_check(self):
        data = self.read_gpu_data()
        self._accept_gpu_data(data)
        if data.get("available"):
            messagebox.showinfo("NVIDIA System-Check", safe_gpu_detail(data, verbose=True))
        else:
            messagebox.showwarning("NVIDIA System-Check", "NVIDIA-SMI konnte keine Daten liefern. Prüfe NVIDIA-Treiberinstallation.\n\n" + str(data.get("error", data.get("name", "Unbekannter Fehler"))))

    def open_nvidia_panel(self):
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation/Control Panel Client/nvcplui.exe",
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32/nvcplui.exe",
        ]
        for path in candidates:
            if path.exists():
                subprocess.Popen([str(path)], close_fds=True)
                return
        messagebox.showinfo(APP_NAME, "NVIDIA Control Panel wurde nicht an den Standardpfaden gefunden. Öffne die Windows-Grafikeinstellungen oder installiere die NVIDIA-App / den Treiber neu.")

    def open_amd_software(self):
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "AMD/CNext/CNext/RadeonSoftware.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "AMD/CNext/CNext/RadeonSoftware.exe",
        ]
        for path in candidates:
            if path.exists():
                subprocess.Popen([str(path)], close_fds=True)
                return
        messagebox.showinfo(APP_NAME, "AMD Software wurde nicht gefunden. Bei deinem NVIDIA-PC ist dieser Bereich nicht erforderlich.")

    def launch_tool(self, executable: str):
        try:
            if IS_WINDOWS:
                subprocess.Popen(["cmd.exe", "/c", "start", "", executable], close_fds=True)
            else:
                raise RuntimeError("Nur unter Windows verfügbar.")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Tool konnte nicht geöffnet werden:\n{exc}")

    def open_uri(self, uri: str):
        try:
            if IS_WINDOWS:
                os.startfile(uri)
            else:
                webbrowser.open(uri)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Einstellung konnte nicht geöffnet werden:\n{exc}")

    def open_path(self, path: Path):
        try:
            path = Path(path)
            if path.is_file() and not path.exists():
                messagebox.showinfo(APP_NAME, "Die Datei wurde noch nicht erstellt.")
                return
            if not path.exists() and path.suffix:
                messagebox.showinfo(APP_NAME, "Die Datei wurde noch nicht erstellt.")
                return
            if path.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            if IS_WINDOWS:
                os.startfile(str(path))
            else:
                messagebox.showinfo(APP_NAME, str(path))
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def export_report(self):
        default_name = f"RISEN_Systemreport_{datetime.now():%Y%m%d_%H%M%S}.txt"
        destination = filedialog.asksaveasfilename(defaultextension=".txt", initialfile=default_name, filetypes=[("Textdatei", "*.txt")])
        if not destination:
            return
        vm = psutil.virtual_memory()
        lines = [
            f"{APP_NAME} v{APP_VERSION}", f"Generated: {datetime.now().isoformat(sep=' ', timespec='seconds')}",
            f"Windows: {platform.platform()}", f"Machine: {platform.machine()}", f"Processor: {platform.processor()}",
            f"CPU logical cores: {psutil.cpu_count(logical=True)}", f"RAM: {fmt_bytes(vm.total)} · {vm.percent:.1f}% used",
            f"GPU: {safe_gpu_detail(self.gpu_data or {})}", f"Backup: {BACKUP_FILE}", "",
            "NOTE: ICMP internet ping is not the same as Fortnite server ping.",
        ]
        try:
            Path(destination).write_text("\n".join(lines), encoding="utf-8")
            messagebox.showinfo(APP_NAME, f"Systembericht gespeichert:\n{destination}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Export fehlgeschlagen:\n{exc}")

    def set_status(self, text: str):
        self.status_bar.configure(text=text)

    def on_close(self):
        self.alive = False
        self.destroy()


def safe_gpu_detail(data: dict, verbose: bool = False) -> str:
    if not data or not data.get("available"):
        name = data.get("name", "GPU-Telemetrie nicht verfügbar") if isinstance(data, dict) else "GPU-Telemetrie nicht verfügbar"
        return str(name)
    lines = [f"GPU: {data.get('name', 'NVIDIA GPU')}", f"Load: {data.get('usage') if data.get('usage') is not None else 'N/A'}%",
             f"VRAM: {data.get('mem_used') if data.get('mem_used') is not None else 'N/A'} / {data.get('mem_total') if data.get('mem_total') is not None else 'N/A'} MiB",
             f"Temperature: {data.get('temp') if data.get('temp') is not None else 'N/A'} °C"]
    if verbose:
        lines.append(f"Power draw: {data.get('power') if data.get('power') is not None else 'N/A'} W")
    return "\n".join(lines)


def main():
    if not IS_WINDOWS:
        print("RISEN TWEAKS is designed for Windows 10/11.")
        return 1
    try:
        app = RisenTweaks()
        app.mainloop()
        return 0
    except Exception as exc:
        log(f"Fatal error: {exc}")
        try:
            messagebox.showerror(APP_NAME, f"App konnte nicht gestartet werden:\n{exc}\n\nLog: {LOG_FILE}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
