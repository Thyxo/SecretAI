"""SecretAI – usynlig hotkey-klient til DeepSeek-bridgen (kun Windows).

Start-tast (standard Ctrl+Alt+Space) → skriv din prompt (tastetryk fanges og når IKKE frem til det
aktive program) → send-tast (standard den samme) → svaret lægges i clipboardet.
Begge taster kan skiftes i vinduet.

Prik nederst til højre:  rød = optager · orange = AI tænker · grøn = svar i clipboard · lilla = fejl
Esc under optagelse = annullér. Klik på tray-ikonet åbner statusvinduet.

UI: PySide6 (Qt). Tastefangst: eget WH_KEYBOARD_LL-hook via ctypes (ingen pynput).
"""
import ctypes, ctypes.wintypes as wt, json, logging, math, os, subprocess, sys, threading, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
logging.basicConfig(filename=os.path.join(HERE, "secretai.log"), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
log = logging.getLogger("secretai")
sys.excepthook = lambda t, v, tb: log.error("Ufanget fejl", exc_info=(t, v, tb))
threading.excepthook = lambda a: log.error("Fejl i tråd", exc_info=(a.exc_type, a.exc_value, a.exc_traceback))

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMenu, QPlainTextEdit, QPushButton, QScrollArea, QSystemTrayIcon, QVBoxLayout,
                               QWidget)

# ------------------------------------------------------------------ Config
CONFIG_PATH = os.path.join(HERE, "config.json")
DEFAULTS = {
    "hotkey": "ctrl+alt+space",       # start optagelse – fx "ctrl+shift+f9", "f9", "ctrl+alt+d"
    "hotkey_send": "ctrl+alt+space",  # send prompten (må gerne være den samme som start)
    "show_window_on_start": True,      # vis statusvinduet når programmet starter
    "dot": True,                      # lille prik nederst til højre
    "suppress_keys": True,            # True = tastetryk under optagelse når IKKE frem til det aktive program
    "bridge_port": 8000,
    "request_timeout": 300,
}


def load_cfg():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    except Exception:
        log.exception("config.json kunne ikke læses – bruger standardværdier")
    save_cfg(cfg)
    return cfg


def save_cfg(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        log.exception("kunne ikke gemme config.json")


cfg = load_cfg()
BRIDGE = f"http://127.0.0.1:{cfg['bridge_port']}"

# ------------------------------------------------------------------ Windows API (fuldt typet – kræves af Python 3.14)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
LRESULT = ctypes.c_ssize_t


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.GetMessageW.restype = wt.BOOL
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetKeyState.argtypes = [ctypes.c_int]
user32.GetKeyState.restype = ctypes.c_short
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetKeyboardLayout.argtypes = [wt.DWORD]
user32.GetKeyboardLayout.restype = wt.HKL
user32.ToUnicodeEx.argtypes = [wt.UINT, wt.UINT, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_wchar_p,
                               ctypes.c_int, wt.UINT, wt.HKL]
user32.ToUnicodeEx.restype = ctypes.c_int
user32.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ctypes.c_size_t]
user32.MapVirtualKeyW.argtypes = [wt.UINT, wt.UINT]
user32.MapVirtualKeyW.restype = wt.UINT
user32.GetKeyNameTextW.argtypes = [wt.LONG, wt.LPWSTR, ctypes.c_int]
user32.GetKeyNameTextW.restype = ctypes.c_int
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetCurrentThreadId.restype = wt.DWORD

VK_MODS = {"ctrl": (0x11,), "alt": (0x12,), "shift": (0x10,), "win": (0x5B, 0x5C)}
MOD_ORDER = ("ctrl", "alt", "shift", "win")
# Taster der får lov at passere uændret (så Windows' modifier-tilstand ikke bliver forvirret)
PASS_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C, 0x14, 0x90, 0x91}
VK_DUMMY = 0xE8   # utildelt tast – sendes efter hotkey, så Alt ikke åbner menuen i det aktive program


def is_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def is_fkey(vk):
    return 0x70 <= vk <= 0x87


def parse_hotkey(text):
    """'ctrl+alt+space' → (frozenset({'ctrl','alt'}), 0x20)."""
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    mods = frozenset(p for p in parts if p in VK_MODS)
    keys = [p for p in parts if p not in VK_MODS]
    if len(keys) != 1:
        raise ValueError(f"Ugyldig hotkey: {text!r}")
    k = keys[0]
    if k == "space":
        vk = 0x20
    elif k.startswith("f") and k[1:].isdigit() and 1 <= int(k[1:]) <= 24:
        vk = 0x70 + int(k[1:]) - 1
    elif len(k) == 1 and k.isascii() and k.isalnum():
        vk = ord(k.upper())
    elif k.startswith("vk") and k[2:].isdigit() and 0 < int(k[2:]) < 256:
        vk = int(k[2:])
    else:
        raise ValueError(f"Ukendt tast i hotkey: {k!r}")
    return mods, vk


def hotkey_string(mods, vk):
    if vk == 0x20:
        k = "space"
    elif is_fkey(vk):
        k = f"f{vk - 0x6F}"
    elif 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        k = chr(vk).lower()
    else:
        k = f"vk{vk}"
    return "+".join([m for m in MOD_ORDER if m in mods] + [k])


def key_name(vk):
    if vk == 0x20:
        return "Space"
    if is_fkey(vk):
        return f"F{vk - 0x6F}"
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    scan = user32.MapVirtualKeyW(vk, 0)
    buf = ctypes.create_unicode_buffer(32)
    if scan and user32.GetKeyNameTextW(scan << 16, buf, 32) > 0:
        return buf.value.capitalize() if len(buf.value) > 1 else buf.value.upper()
    return f"Tast {vk}"


def hk_label(text):
    try:
        mods, vk = parse_hotkey(text)
    except ValueError:
        return text
    return " + ".join([m.capitalize() for m in MOD_ORDER if m in mods] + [key_name(vk)])


def safe_hotkey(key):
    try:
        return parse_hotkey(cfg[key])
    except Exception:
        log.exception("Ugyldig %s i config.json – bruger standard", key)
        cfg[key] = DEFAULTS[key]
        return parse_hotkey(DEFAULTS[key])


def mods_held():
    return frozenset(m for m in MOD_ORDER if any(is_down(v) for v in VK_MODS[m]))


def translate(vk, scan):
    """Oversæt en tast til tegn med det aktive tastaturlayout (æøå, shift, AltGr osv.)."""
    st = (ctypes.c_ubyte * 256)()
    for k in (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5):
        if is_down(k):
            st[k] = 0x80
    if user32.GetKeyState(0x14) & 1:
        st[0x14] = 1
    ctrl, alt = bool(st[0x11]), bool(st[0x12])
    if ctrl != alt:                      # kun Ctrl eller kun Alt = genvej, ikke tekst (Ctrl+Alt = AltGr)
        return ""
    tid = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    buf = ctypes.create_unicode_buffer(8)
    # flag 4 = rør ikke kernens tastaturtilstand (så dødtaster i det aktive program ikke ødelægges)
    n = user32.ToUnicodeEx(vk, scan, st, buf, 8, 4, user32.GetKeyboardLayout(tid))
    ch = buf.value[:n] if n > 0 else ""   # n<0 = dødtast (´ ` ^ ¨) → ignoreres
    return ch if ch and ord(ch[0]) >= 32 else ""


class KeyHook:
    """Low-level tastatur-hook i sin egen tråd med egen beskedløkke."""

    def __init__(self, handler):
        self.handler, self.tid, self.hook = handler, None, None
        self.ready = threading.Event()

    def start(self):
        threading.Thread(target=self._run, name="keyhook", daemon=True).start()
        self.ready.wait(3)
        return bool(self.hook)

    def _run(self):
        self.tid = kernel32.GetCurrentThreadId()
        self._proc = HOOKPROC(self._cb)          # behold reference, ellers garbage-collectes den
        self.hook = user32.SetWindowsHookExW(13, self._proc, kernel32.GetModuleHandleW(None), 0)
        if not self.hook:
            log.error("SetWindowsHookExW fejlede (%s)", ctypes.get_last_error())
        self.ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        if self.hook:
            user32.UnhookWindowsHookEx(self.hook)

    def stop(self):
        if self.tid:
            user32.PostThreadMessageW(self.tid, 0x0012, 0, 0)   # WM_QUIT

    def _cb(self, code, wparam, lparam):
        if code == 0:
            try:
                d = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if self.handler(wparam, d):
                    return 1                     # slå tasten ihjel
            except Exception:
                log.exception("fejl i tastefilter")
        return user32.CallNextHookEx(None, code, wparam, lparam)


# ------------------------------------------------------------------ Bridge
bridge_proc = None


def bridge_up():
    try:
        urllib.request.urlopen(BRIDGE + "/health", timeout=1.5).read()
        return True
    except Exception:
        return False


def start_bridge():
    """Start ds_server (usynligt) hvis den ikke allerede kører."""
    global bridge_proc
    if bridge_up():
        log.info("Bridge kørte allerede")
        return
    exe = sys.executable
    if exe.lower().endswith("python.exe") and os.path.exists(exe[:-10] + "pythonw.exe"):
        exe = exe[:-10] + "pythonw.exe"
    out = open(os.path.join(HERE, "bridge.log"), "ab")
    bridge_proc = subprocess.Popen(
        [exe, "-m", "uvicorn", "ds_server:app", "--host", "127.0.0.1", "--port", str(cfg["bridge_port"])],
        cwd=HERE, stdout=out, stderr=out, stdin=subprocess.DEVNULL,
        creationflags=0x08000000 | 0x00000200)           # CREATE_NO_WINDOW | NEW_PROCESS_GROUP
    log.info("Bridge startet (pid %s)", bridge_proc.pid)


def stop_bridge():
    if bridge_proc is None or bridge_proc.poll() is not None:   # luk kun bridgen hvis det var os der startede den
        return
    try:
        post_json("/admin/quit", {}, timeout=5)
        bridge_proc.wait(timeout=10)
    except Exception:   # svarer ikke: dræb bridgen OG dens Chrome, så der ikke ligger en usynlig Chrome tilbage
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(bridge_proc.pid)],
                       creationflags=0x08000000, capture_output=True)


class BridgeError(Exception):
    def __init__(self, status, detail):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail


def _http_detail(e):
    try:
        return json.loads(e.read()).get("detail", "") or str(e)
    except Exception:
        return str(e)


def post_json(path, body, timeout=90):
    req = urllib.request.Request(BRIDGE + path, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=timeout).read()
        return True, ""
    except urllib.error.HTTPError as e:
        return False, _http_detail(e)
    except Exception:
        return False, "Bridgen svarer ikke."


def ask_stream(q, on_text):
    """Spørg via /ask/stream (SSE). Kalder on_text(hele_teksten_indtil_nu) løbende. Returnerer svaret."""
    req = urllib.request.Request(BRIDGE + "/ask/stream", data=json.dumps({"q": q}).encode("utf-8"),
                                 headers={"content-type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=cfg["request_timeout"])
    except urllib.error.HTTPError as e:
        raise BridgeError(e.code, _http_detail(e))
    txt, event = "", None
    with r:
        for raw in r:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                event = None
            elif line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                j = json.loads(data)
                if event == "error" or "error" in j:
                    raise BridgeError(500, j.get("error") or "Ukendt fejl")
                txt = j["replace"] if "replace" in j else txt + j.get("delta", "")
                on_text(txt)
    return txt


# ------------------------------------------------------------------ Udseende
COL = {"rec": "#ef4444", "think": "#f59e0b", "ok": "#22c55e", "err": "#a855f7", "idle": "#94a3b8"}
THEMES = {
    "light": dict(bg="#f3f4f7", card="#ffffff", border="#e4e7ec", tx="#111827", mut="#6b7280",
                  input="#f8f9fb", ac="#4f46e5", ach="#4338ca", acs="#eef2ff", chiptx="#4338ca"),
    "dark": dict(bg="#0e1014", card="#171a21", border="#262b35", tx="#e6e8ec", mut="#9aa3b2",
                 input="#0e1014", ac="#6366f1", ach="#7c7ff5", acs="#1f1d47", chiptx="#c7d2fe"),
}


def is_dark():
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def stylesheet(t):
    return f"""
    QWidget#root, QScrollArea {{ background: {t['bg']}; border: 0; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QLabel {{ color: {t['tx']}; background: transparent; }}
    QLabel#muted {{ color: {t['mut']}; }}
    QLabel#title {{ font-size: 20pt; font-weight: 700; }}
    QLabel#subtitle {{ color: {t['mut']}; }}
    QLabel#cardTitle {{ color: {t['mut']}; font-size: 8.5pt; font-weight: 700; }}
    QLabel#num {{ background: {t['ac']}; color: white; border-radius: 11px; font-weight: 700; }}
    QLabel#heroText {{ font-size: 11.5pt; font-weight: 600; }}
    QFrame#card {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 14px; }}
    QPushButton {{ background: {t['ac']}; color: white; border: 0; border-radius: 10px; padding: 10px 14px;
                   font-weight: 600; }}
    QPushButton:hover {{ background: {t['ach']}; }}
    QPushButton:disabled {{ background: {t['border']}; color: {t['mut']}; }}
    QPushButton#secondary {{ background: transparent; color: {t['ac']}; border: 1px solid {t['ac']}; }}
    QPushButton#secondary:hover {{ background: {t['acs']}; }}
    QPushButton#ghost {{ background: transparent; color: {t['mut']}; border: 1px solid {t['border']};
                         padding: 7px 12px; }}
    QPushButton#ghost:hover {{ color: {t['tx']}; border-color: {t['mut']}; }}
    QPushButton#key {{ background: {t['acs']}; color: {t['chiptx']}; border: 1px solid {t['acs']};
                       border-radius: 9px; padding: 7px 14px; font-weight: 700; min-width: 150px; }}
    QPushButton#key:hover {{ border-color: {t['ac']}; }}
    QPushButton#key[capturing="true"] {{ background: {t['ac']}; color: white; border-color: {t['ac']}; }}
    QLineEdit, QPlainTextEdit {{ background: {t['input']}; color: {t['tx']}; border: 1px solid {t['border']};
                   border-radius: 10px; padding: 8px 10px; selection-background-color: {t['ac']}; }}
    QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {t['ac']}; }}
    QCheckBox {{ color: {t['tx']}; spacing: 8px; }}
    QMenu {{ background: {t['card']}; color: {t['tx']}; border: 1px solid {t['border']}; padding: 4px; }}
    QMenu::item {{ padding: 6px 22px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {t['acs']}; }}
    """


def circle_icon(color, size=64):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    halo = QColor(c)
    halo.setAlpha(70)
    p.setPen(Qt.NoPen)
    p.setBrush(halo)
    p.drawEllipse(QRectF(2, 2, size - 4, size - 4))
    p.setBrush(c)
    p.setPen(QPen(QColor(255, 255, 255), size / 16))
    m = size * 0.2
    p.drawEllipse(QRectF(m, m, size - 2 * m, size - 2 * m))
    p.end()
    return QIcon(pm)


class Pip(QWidget):
    """Lille farvet statusprik."""

    def __init__(self, d=10):
        super().__init__()
        self.setFixedSize(d + 6, d + 6)
        self.d, self.color = d, QColor(COL["idle"])

    def set(self, color):
        self.color = QColor(color)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        halo = QColor(self.color)
        halo.setAlpha(55)
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QRectF(0, 0, self.d + 6, self.d + 6))
        p.setBrush(self.color)
        p.drawEllipse(QRectF(3, 3, self.d, self.d))


class Dot(QWidget):
    """Prikken nederst til højre. Klikker igennem og stjæler aldrig fokus."""
    S = 30

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                         Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(self.S, self.S)
        self.color, self.key, self.t0 = QColor(COL["idle"]), "idle", time.monotonic()
        self.anim = QTimer(self)
        self.anim.setInterval(33)
        self.anim.timeout.connect(self.update)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)

    def flash(self, key, ms=None):
        self.hide_timer.stop()
        if not cfg["dot"]:
            return self.hide()
        self.key, self.color, self.t0 = key, QColor(COL[key]), time.monotonic()
        g = QGuiApplication.primaryScreen().availableGeometry()
        self.move(g.right() - self.S - 8, g.bottom() - self.S - 8)
        self.anim.start() if key in ("rec", "think") else self.anim.stop()
        self.show()
        self.raise_()
        self.update()
        if ms:
            self.hide_timer.start(ms)

    def hideEvent(self, e):
        self.anim.stop()
        super().hideEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c, t = self.S / 2, time.monotonic() - self.t0
        if self.key == "rec":
            k = 0.5 + 0.5 * math.sin(t * 5)
        elif self.key == "think":
            k = 0.5 + 0.5 * math.sin(t * 3)
        else:
            k = 1.0
        glow = QRadialGradient(c, c, c)
        g0 = QColor(self.color)
        g0.setAlpha(int(60 + 110 * k))
        g1 = QColor(self.color)
        g1.setAlpha(0)
        glow.setColorAt(0.0, g0)
        glow.setColorAt(0.35, g0)
        glow.setColorAt(1.0, g1)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(0, 0, self.S, self.S))
        r = 6.5
        p.setBrush(self.color)
        p.setPen(QPen(QColor(255, 255, 255, 230), 1.6))
        p.drawEllipse(QRectF(c - r, c - r, 2 * r, 2 * r))


class Card(QFrame):
    def __init__(self, title=None):
        super().__init__()
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(18, 14, 18, 16)
        self.lay.setSpacing(10)
        if title:
            lb = QLabel(title.upper())
            lb.setObjectName("cardTitle")
            self.lay.addWidget(lb)


def label(text="", name=None, wrap=False):
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def button(text, name=None):
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    b.setCursor(Qt.PointingHandCursor)
    return b


# ------------------------------------------------------------------ Signaler mellem tråde og UI
class Bus(QObject):
    phase = Signal(str)            # idle / rec / think
    typed = Signal(int)            # antal tegn optaget
    partial = Signal(str)          # svartekst indtil nu
    done = Signal(str)             # færdigt svar
    failed = Signal(int, str)      # status, besked
    status = Signal(object)        # dict fra /status
    mode_msg = Signal(str)
    captured = Signal(str, str, str)   # hvilken tast (start/send), ny hotkey-tekst, fejlbesked
    hotkeys_changed = Signal()


IDLE, RECORDING, THINKING = "idle", "rec", "think"


class Engine:
    """Hotkeys + tastefangst + forespørgsler. process() kører i hook-tråden og skal være hurtig."""

    def __init__(self, bus):
        self.bus, self.state, self.buf, self.suppressed = bus, IDLE, [], set()
        self.capture = None            # "start"/"send" mens brugeren vælger en ny tast i vinduet
        self.reload_hotkeys()

    def reload_hotkeys(self):
        self.hk_start = safe_hotkey("hotkey")
        self.hk_send = safe_hotkey("hotkey_send")

    # -- fra hook-tråden
    def process(self, msg, d):
        if d.flags & 0x10:                              # injiceret tast (fx fra andre programmer) – rør ikke
            return False
        down, up = msg in (0x100, 0x104), msg in (0x101, 0x105)
        vk = d.vkCode
        if up:
            if vk in self.suppressed:
                self.suppressed.discard(vk)
                return True
            return False
        if not down:
            return False
        if self.capture:
            return self._capture(vk)
        if vk not in PASS_VKS:
            combo = (mods_held(), vk)
            hit = None
            if self.state == RECORDING and combo == self.hk_send:
                hit = "send"
            elif combo == self.hk_start:
                hit = "start"
            if hit:
                self.suppressed.add(vk)
                user32.keybd_event(VK_DUMMY, 0, 0, 0)
                user32.keybd_event(VK_DUMMY, 0, 2, 0)
                if hit == "send":
                    self.submit()
                elif self.state == IDLE:
                    self.start_recording()
                return True                              # start-tast under optagelse/tænkning: ignoreres
        if self.state != RECORDING or vk in PASS_VKS:
            return False
        if vk == 0x1B:
            self.cancel()
        elif vk == 0x08:
            if self.buf:
                self.buf.pop()
        elif vk == 0x0D:
            self.buf.append("\n")
        else:
            ch = translate(vk, d.scanCode)
            if ch:
                self.buf.append(ch)
        self.bus.typed.emit(len(self.buf))
        swallow = bool(cfg["suppress_keys"])
        if swallow:
            self.suppressed.add(vk)
        return swallow

    def _capture(self, vk):
        """Næste tastetryk bliver den nye hotkey."""
        if vk in PASS_VKS:                               # vent på selve tasten, modifiers må gerne holdes
            return False
        target, self.capture = self.capture, None
        self.suppressed.add(vk)
        mods = mods_held()
        if vk == 0x1B and not mods:
            self.bus.captured.emit(target, "", "")
        elif not mods and not is_fkey(vk):
            self.bus.captured.emit(target, "", "Brug mindst én af Ctrl, Alt, Shift eller Win (eller en F-tast).")
        else:
            self.bus.captured.emit(target, hotkey_string(mods, vk), "")
        return True

    def start_recording(self):
        self.buf.clear()
        self.bus.typed.emit(0)
        self.set_state(RECORDING)

    def submit(self):
        text = "".join(self.buf).strip()
        self.buf.clear()
        if text:
            self.ask(text)
        else:
            self.set_state(IDLE)

    def cancel(self):
        self.buf.clear()
        self.set_state(IDLE)

    def set_state(self, s):
        self.state = s
        self.bus.phase.emit(s)

    # -- forespørgsel (bruges også af testboksen)
    def ask(self, text):
        if self.state == THINKING:
            return False
        self.set_state(THINKING)
        threading.Thread(target=self._run, args=(text,), daemon=True).start()
        return True

    def _run(self, text):
        try:
            log.info("Sender prompt (%d tegn)", len(text))
            answer = ask_stream(text, self.bus.partial.emit).strip()
            log.info("Svar modtaget (%d tegn)", len(answer))
            self.state = IDLE
            self.bus.done.emit(answer)
        except BridgeError as e:
            log.error("Bridge-fejl %s", e)
            msg = ("Ikke logget ind på DeepSeek – brug «Åbn login-vindue»." if e.status in (401, 409)
                   else (e.detail or f"Fejl {e.status}"))
            self.state = IDLE
            self.bus.failed.emit(e.status, msg)
        except Exception:
            log.exception("Fejl under forespørgsel (kører bridgen?)")
            self.state = IDLE
            self.bus.failed.emit(0, "Bridgen svarer ikke. Se bridge.log.")


# ------------------------------------------------------------------ Statusvindue (liggende)
class MainWindow(QWidget):
    def __init__(self, bus, engine, on_quit):
        super().__init__()
        self.bus, self.engine, self.on_quit = bus, engine, on_quit
        self.setWindowTitle("SecretAI")
        self.setWindowIcon(circle_icon(THEMES["light"]["ac"]))
        self.status, self.started, self.typed, self.answer = {"up": False}, time.time(), 0, ""
        self.told_tray = False

        # Indholdet ligger i et scroll-område, så vinduet også passer på små skærme / høj skalering
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("root")
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        root = QVBoxLayout(inner)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(14)

        # ---- Top: titel + status-banner
        top = QHBoxLayout()
        top.setSpacing(18)
        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        tcol.addWidget(label("SecretAI", "title"))
        tcol.addWidget(label("DeepSeek direkte i dit clipboard", "subtitle"))
        top.addLayout(tcol)
        self.hero = QFrame()
        self.hero.setObjectName("hero")
        hl = QHBoxLayout(self.hero)
        hl.setContentsMargins(16, 12, 16, 12)
        hl.setSpacing(12)
        self.hero_pip = Pip(12)
        self.hero_text = label("", "heroText", wrap=True)
        hl.addWidget(self.hero_pip, 0, Qt.AlignVCenter)
        hl.addWidget(self.hero_text, 1)
        top.addWidget(self.hero, 1)
        root.addLayout(top)

        # ---- To kolonner
        cols = QHBoxLayout()
        cols.setSpacing(14)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.setSpacing(14)
        right.setSpacing(14)
        cols.addLayout(left, 5)
        cols.addLayout(right, 6)
        root.addLayout(cols, 1)

        # Status
        st = Card("Status")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.rows = []
        for i, name in enumerate(("Program", "Bridge til DeepSeek", "DeepSeek-login")):
            pip, val = Pip(9), label("…", "muted")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(pip, i, 0)
            grid.addWidget(label(name), i, 1)
            grid.addWidget(val, i, 2)
            self.rows.append((pip, val))
        grid.setColumnStretch(1, 1)
        st.lay.addLayout(grid)
        left.addWidget(st)

        # Taster
        kc = Card("Taster")
        kg = QGridLayout()
        kg.setHorizontalSpacing(12)
        kg.setVerticalSpacing(8)
        self.key_btns = {}
        for i, (target, name) in enumerate((("start", "Start optagelse"), ("send", "Send prompt"))):
            b = button("", "key")
            b.clicked.connect(lambda _=False, t=target: self.begin_capture(t))
            kg.addWidget(label(name), i, 0)
            kg.addWidget(b, i, 1, Qt.AlignRight)
            self.key_btns[target] = b
        kg.addWidget(label("Annullér optagelse"), 2, 0)
        esc = label("Esc", "muted")
        esc.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        kg.addWidget(esc, 2, 1)
        kg.setColumnStretch(0, 1)
        kc.lay.addLayout(kg)
        krow = QHBoxLayout()
        self.key_msg = label("Klik på en tast, og tryk den nye kombination.", "muted", wrap=True)
        b_reset = button("Nulstil", "ghost")
        b_reset.clicked.connect(self.reset_keys)
        krow.addWidget(self.key_msg, 1)
        krow.addWidget(b_reset, 0, Qt.AlignTop)
        kc.lay.addLayout(krow)
        self.cb_suppress = QCheckBox("Bloker tastetryk i andre programmer under optagelse")
        self.cb_suppress.setChecked(cfg["suppress_keys"])
        self.cb_suppress.toggled.connect(self.save_opts)
        kc.lay.addWidget(self.cb_suppress)
        left.addWidget(kc)

        # Login
        lg = Card("DeepSeek-login")
        lg.lay.addWidget(label("Første gang, eller hvis login udløber: åbn login-vinduet, log ind på "
                               "DeepSeek i Chrome, og tryk så «Jeg er logget ind».", "muted", wrap=True))
        brow = QHBoxLayout()
        self.b_login = button("Åbn login-vindue")
        self.b_run = button("Jeg er logget ind", "secondary")
        brow.addWidget(self.b_login)
        brow.addWidget(self.b_run)
        self.b_login.clicked.connect(lambda: self.set_mode(False))
        self.b_run.clicked.connect(lambda: self.set_mode(True))
        lg.lay.addLayout(brow)
        self.mode_lbl = label("", "muted", wrap=True)
        self.mode_lbl.hide()
        lg.lay.addWidget(self.mode_lbl)
        left.addWidget(lg)
        left.addStretch(1)

        # Sådan gør du
        how = Card("Sådan gør du")
        self.steps = []
        for n in (1, 2, 3):
            row = QHBoxLayout()
            row.setSpacing(10)
            num = label(str(n), "num")
            num.setFixedSize(22, 22)
            num.setAlignment(Qt.AlignCenter)
            txt = label("", wrap=True)
            row.addWidget(num, 0, Qt.AlignTop)
            row.addWidget(txt, 1)
            how.lay.addLayout(row)
            self.steps.append(txt)
        right.addWidget(how)

        # Test
        ts = Card("Prøv det her")
        trow = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Fx: Hvornår lukker Tivoli i aften?")
        self.entry.returnPressed.connect(self.send_test)
        self.b_send = button("Send")
        self.b_send.clicked.connect(self.send_test)
        trow.addWidget(self.entry, 1)
        trow.addWidget(self.b_send)
        ts.lay.addLayout(trow)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setPlaceholderText("Svaret kommer her – og i clipboardet.")
        self.out.setMinimumHeight(120)
        ts.lay.addWidget(self.out, 1)
        orow = QHBoxLayout()
        self.out_info = label("", "muted")
        self.b_copy = button("Kopiér svar", "ghost")
        self.b_copy.clicked.connect(lambda: self.answer and QGuiApplication.clipboard().setText(self.answer))
        orow.addWidget(self.out_info, 1)
        orow.addWidget(self.b_copy)
        ts.lay.addLayout(orow)
        right.addWidget(ts, 1)

        # ---- Fod
        foot = QHBoxLayout()
        self.cb_dot = QCheckBox("Vis prik")
        self.cb_start = QCheckBox("Vis vindue ved start")
        self.cb_dot.setChecked(cfg["dot"])
        self.cb_start.setChecked(cfg["show_window_on_start"])
        self.cb_dot.toggled.connect(self.save_opts)
        self.cb_start.toggled.connect(self.save_opts)
        b_quit = button("Afslut", "ghost")
        b_quit.clicked.connect(on_quit)
        foot.addWidget(self.cb_dot)
        foot.addSpacing(10)
        foot.addWidget(self.cb_start)
        foot.addStretch()
        foot.addWidget(b_quit)
        root.addLayout(foot)

        bus.status.connect(self.on_status)
        bus.typed.connect(self.on_typed)
        bus.phase.connect(lambda _: self.refresh())
        bus.partial.connect(self.on_partial)
        bus.done.connect(self.on_done)
        bus.failed.connect(self.on_failed)
        bus.mode_msg.connect(self.on_mode_msg)
        bus.captured.connect(self.on_captured)
        self.apply_theme()
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _: self.apply_theme())
        except Exception:
            pass
        avail = QGuiApplication.primaryScreen().availableGeometry()
        self.setMinimumSize(min(860, avail.width() - 20), 420)
        self.resize(min(1020, avail.width() - 40), min(660, avail.height() - 60))
        self.update_key_texts()

    # -- udseende
    def apply_theme(self):
        dark = is_dark()
        self.theme = THEMES["dark" if dark else "light"]
        self.setStyleSheet(stylesheet(self.theme))
        try:   # mørk titellinje på Windows 10/11
            v = ctypes.c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(wt.HWND(int(self.winId())), 20, ctypes.byref(v), 4)
        except Exception:
            pass
        self.refresh()

    def set_hero(self, color, text):
        c = QColor(color)
        self.hero.setStyleSheet(
            f"QFrame#hero {{ background: rgba({c.red()},{c.green()},{c.blue()},0.13);"
            f" border: 1px solid rgba({c.red()},{c.green()},{c.blue()},0.40); border-radius: 14px; }}")
        self.hero_pip.set(color)
        self.hero_text.setText(text)

    def update_key_texts(self):
        start, send = hk_label(cfg["hotkey"]), hk_label(cfg["hotkey_send"])
        self.key_btns["start"].setText(start)
        self.key_btns["send"].setText(send)
        same = cfg["hotkey"] == cfg["hotkey_send"]
        self.steps[0].setText(f"Tryk {start} – prikken nederst til højre bliver rød")
        self.steps[1].setText(f"Skriv din prompt, og tryk {send}{' igen' if same else ''}")
        self.steps[2].setText("Når prikken er grøn, ligger svaret i clipboardet: Ctrl+V")
        self.refresh()

    # -- vindue
    def show_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):                    # X skjuler kun – programmet kører videre
        e.ignore()
        self.cancel_capture()
        self.hide()
        if not self.told_tray:
            self.told_tray = True
            tray = QApplication.instance().property("tray")
            if tray is not None:
                tray.showMessage("SecretAI kører videre", f"Tryk {hk_label(cfg['hotkey'])} for at bruge det. "
                                 "Klik på ikonet for at åbne vinduet.", QSystemTrayIcon.Information, 4000)

    def save_opts(self):
        cfg["dot"], cfg["show_window_on_start"] = self.cb_dot.isChecked(), self.cb_start.isChecked()
        cfg["suppress_keys"] = self.cb_suppress.isChecked()
        save_cfg(cfg)

    # -- taster
    def set_capturing(self, target):
        for t, b in self.key_btns.items():
            b.setProperty("capturing", t == target)
            b.style().unpolish(b)
            b.style().polish(b)

    def begin_capture(self, target):
        if self.engine.state != IDLE:
            self.key_msg.setText("Vent til optagelsen/svaret er færdigt.")
            return
        self.engine.capture = target
        self.set_capturing(target)
        self.key_btns[target].setText("Tryk tasterne …")
        self.key_msg.setText("Hold fx Ctrl+Alt nede, og tryk en tast. Esc annullerer.")

    def cancel_capture(self):
        if self.engine.capture:
            self.engine.capture = None
            self.set_capturing(None)
            self.update_key_texts()

    def on_captured(self, target, hotkey, error):
        self.set_capturing(None)
        if error:
            self.key_msg.setText(error)
        elif not hotkey:
            self.key_msg.setText("Annulleret.")
        else:
            cfg["hotkey" if target == "start" else "hotkey_send"] = hotkey
            save_cfg(cfg)
            self.engine.reload_hotkeys()
            self.key_msg.setText(f"Gemt: {'start' if target == 'start' else 'send'} = {hk_label(hotkey)}")
            log.info("Ny %s-tast: %s", target, hotkey)
            self.bus.hotkeys_changed.emit()
        self.update_key_texts()

    def reset_keys(self):
        self.cancel_capture()
        cfg["hotkey"], cfg["hotkey_send"] = DEFAULTS["hotkey"], DEFAULTS["hotkey_send"]
        save_cfg(cfg)
        self.engine.reload_hotkeys()
        self.key_msg.setText("Nulstillet til " + hk_label(DEFAULTS["hotkey"]) + ".")
        self.bus.hotkeys_changed.emit()
        self.update_key_texts()

    # -- handlinger
    def set_mode(self, headless):
        self.b_login.setEnabled(False)
        self.b_run.setEnabled(False)
        self.on_mode_msg("Arbejder … (kan tage et par sekunder)")

        def work():
            ok, detail = post_json("/admin/mode", {"headless": headless})
            if not ok:
                self.bus.mode_msg.emit("Fejl: " + detail)
            elif headless:
                self.bus.mode_msg.emit("Færdig. Chrome kører nu usynligt i baggrunden.")
            else:
                self.bus.mode_msg.emit("Chrome er åbnet. Log ind på DeepSeek der, og tryk så «Jeg er logget ind».")
        threading.Thread(target=work, daemon=True).start()

    def on_mode_msg(self, text):
        if not text.startswith("Arbejder"):
            self.b_login.setEnabled(True)
            self.b_run.setEnabled(True)
        self.mode_lbl.setText(text)
        self.mode_lbl.show()

    def send_test(self):
        text = self.entry.text().strip()
        if text and self.engine.ask(text):
            self.out.clear()
            self.out_info.setText("DeepSeek tænker …")

    # -- signaler
    def on_status(self, s):
        self.status = s
        self.refresh()

    def on_typed(self, n):
        self.typed = n
        if self.engine.state == RECORDING:
            self.refresh()

    def on_partial(self, txt):
        if txt != self.out.toPlainText():
            self.out.setPlainText(txt)
            self.out.verticalScrollBar().setValue(self.out.verticalScrollBar().maximum())
        self.out_info.setText("DeepSeek skriver …")

    def on_done(self, answer):
        self.answer = answer
        self.out.setPlainText(answer)
        self.out_info.setText(f"✓ I clipboardet · {len(answer)} tegn · {time.strftime('%H:%M')}")

    def on_failed(self, status, msg):
        self.out.setPlainText("Fejl: " + msg)
        self.out_info.setText("")
        if status in (401, 409):
            self.show_front()

    # -- status
    def row(self, i, color, text):
        self.rows[i][0].set(color)
        self.rows[i][1].setText(text)

    def refresh(self):
        if not hasattr(self, "b_send"):
            return
        s = self.status
        up, mode, login = s.get("up"), s.get("mode"), s.get("login")
        starting = not up and time.time() - self.started < 40
        st = self.engine.state
        start, send = hk_label(cfg["hotkey"]), hk_label(cfg["hotkey_send"])

        self.row(0, COL["ok"], "kører")
        if up:
            self.row(1, COL["ok"], "kører")
        elif starting:
            self.row(1, COL["think"], "starter …")
        else:
            self.row(1, COL["rec"], "kører ikke – se bridge.log")
        if not up:
            self.row(2, COL["idle"], "–")
        elif mode == "starting":
            self.row(2, COL["think"], "Chrome starter …")
        elif mode == "login":
            self.row(2, COL["think"], "log ind i Chrome-vinduet")
        elif login == "ja":
            self.row(2, COL["ok"], "logget ind")
        elif login == "nej":
            self.row(2, COL["rec"], "ikke logget ind")
        else:
            self.row(2, COL["think"], "ukendt – prøv en test")

        if st == RECORDING:
            self.set_hero(COL["rec"], f"Optager … {self.typed} tegn · {send} sender · Esc annullerer")
        elif st == THINKING:
            self.set_hero(COL["think"], "DeepSeek tænker …")
        elif not up:
            self.set_hero(COL["think"] if starting else COL["rec"],
                          "Starter bridgen …" if starting else "Bridgen kører ikke")
        elif s.get("error"):
            self.set_hero(COL["rec"], "Fejl: " + str(s["error"]))
        elif mode == "starting":
            self.set_hero(COL["think"], "Starter Chrome i baggrunden …")
        elif mode == "login":
            self.set_hero(COL["think"], "Log ind på DeepSeek i Chrome-vinduet, og tryk så «Jeg er logget ind»")
        elif login == "nej":
            self.set_hero(COL["rec"], "Ikke logget ind – tryk «Åbn login-vindue»")
        else:
            self.set_hero(COL["ok"], f"Klar – tryk {start}")
        self.b_send.setEnabled(st != THINKING)


# ------------------------------------------------------------------ App
class App(QObject):
    def __init__(self, qapp):
        super().__init__()
        self.qapp = qapp
        self.bus = Bus()
        self.engine = Engine(self.bus)
        self.dot = Dot()
        self.win = MainWindow(self.bus, self.engine, self.quit)
        self.polling = False

        # Tray
        self.tray = QSystemTrayIcon(circle_icon(COL["idle"]), self)
        self.update_tooltip()
        menu = QMenu()
        menu.addAction("Åbn vindue", self.win.show_front)
        self.act_dot = menu.addAction("Vis prik")
        self.act_dot.setCheckable(True)
        self.act_dot.setChecked(cfg["dot"])
        self.act_dot.toggled.connect(self.win.cb_dot.setChecked)
        self.win.cb_dot.toggled.connect(self.act_dot.setChecked)
        menu.addSeparator()
        menu.addAction("Afslut", self.quit)
        menu.setStyleSheet(stylesheet(self.win.theme))
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray)
        self.tray.show()
        qapp.setProperty("tray", self.tray)

        self.bus.phase.connect(self.on_phase)
        self.bus.done.connect(self.on_done)
        self.bus.failed.connect(lambda *_: self.flash("err", 4000))
        self.bus.hotkeys_changed.connect(self.update_tooltip)

        self.hook = KeyHook(self.engine.process)
        if not self.hook.start():
            self.tray.showMessage("SecretAI", "Kunne ikke fange tastaturet. Se secretai.log.",
                                  QSystemTrayIcon.Warning, 6000)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(2500)
        self.poll()
        log.info("SecretAI kører. Start: %s · Send: %s", cfg["hotkey"], cfg["hotkey_send"])
        if cfg["show_window_on_start"]:
            self.win.show_front()

    def update_tooltip(self):
        self.tray.setToolTip(f"SecretAI – start {hk_label(cfg['hotkey'])}")

    def on_tray(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.win.show_front()

    def flash(self, key, ms=None):
        self.dot.flash(key, ms)
        self.tray.setIcon(circle_icon(COL[key]))
        if ms:
            QTimer.singleShot(ms, lambda: self.engine.state == IDLE and self.tray.setIcon(circle_icon(COL["idle"])))

    def on_phase(self, s):
        if s == RECORDING:
            self.flash("rec")
        elif s == THINKING:
            self.flash("think")
        else:
            self.dot.hide()
            self.tray.setIcon(circle_icon(COL["idle"]))

    def on_done(self, answer):
        QGuiApplication.clipboard().setText(answer)
        self.flash("ok", 2500)
        self.win.refresh()

    def poll(self):
        if self.polling:
            return
        self.polling = True

        def work():
            try:
                with urllib.request.urlopen(BRIDGE + "/status", timeout=3) as r:
                    st = json.load(r)
                st["up"] = True
            except Exception:
                st = {"up": False}
            self.polling = False
            self.bus.status.emit(st)
        threading.Thread(target=work, daemon=True).start()

    def quit(self):
        log.info("Afslutter")
        self.hook.stop()
        self.tray.hide()
        self.dot.hide()
        self.win.hide()
        stop_bridge()
        self.qapp.quit()


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName("SecretAI")
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setStyle("Fusion")
    f = QFont()
    f.setFamilies(["Segoe UI Variable Text", "Segoe UI"])
    f.setPointSizeF(10)
    qapp.setFont(f)

    # Kun én kopi: kører den allerede, så bed den om at vise sit vindue
    name = "SecretAI-" + os.environ.get("USERNAME", "user")
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(400):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(400)
        return 0
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.listen(name)

    start_bridge()
    app = App(qapp)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), app.win.show_front()))
    return qapp.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log.exception("SecretAI crashede")
        raise
