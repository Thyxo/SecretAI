"""SecretAI – usynlig hotkey-klient til DeepSeek-bridgen (kun Windows).

Hotkey (standard Ctrl+Alt+Space) → begynd at skrive din prompt (tastetryk fanges og sendes
IKKE videre til det aktive program) → tryk hotkey igen → svaret lægges i clipboardet.

Prik nederst til højre:  rød = optager · orange = AI tænker · grøn = svar i clipboard · lilla = fejl
Esc under optagelse = annullér. Tray-ikonet bruges til at slå prikken fra og afslutte.
"""
import ctypes, ctypes.wintypes as wt, json, logging, os, queue, subprocess, sys, threading
import tkinter as tk
import urllib.error, urllib.request, webbrowser

import pyperclip, pystray
from PIL import Image, ImageDraw
from pynput import keyboard

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
logging.basicConfig(filename=os.path.join(HERE, "secretai.log"), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("secretai")

CONFIG_PATH = os.path.join(HERE, "config.json")
DEFAULTS = {
    "hotkey": "ctrl+alt+space",   # fx "ctrl+shift+f9", "f9", "ctrl+alt+d"
    "dot": True,                  # lille prik nederst til højre (kan også slås fra i tray-menuen)
    "suppress_keys": True,        # True = tastetryk under optagelse når IKKE frem til det aktive program
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

# ------------------------------------------------------------------ Windows API
user32 = ctypes.windll.user32
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetKeyState.restype = ctypes.c_short
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.GetKeyboardLayout.restype = ctypes.c_void_p
user32.GetKeyboardLayout.argtypes = [ctypes.c_uint]
user32.ToUnicodeEx.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_wchar_p,
                               ctypes.c_int, ctypes.c_uint, ctypes.c_void_p]

VK_MODS = {"ctrl": (0x11,), "alt": (0x12,), "shift": (0x10,), "win": (0x5B, 0x5C)}
# Taster der får lov at passere uændret (så Windows' modifier-tilstand ikke bliver forvirret)
PASS_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C, 0x14, 0x90, 0x91}


def is_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def parse_hotkey(text):
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    mods = [p for p in parts if p in VK_MODS]
    keys = [p for p in parts if p not in VK_MODS]
    if len(keys) != 1:
        raise ValueError(f"Ugyldig hotkey: {text!r}")
    k = keys[0]
    if k == "space":
        vk = 0x20
    elif k.startswith("f") and k[1:].isdigit() and 1 <= int(k[1:]) <= 24:
        vk = 0x70 + int(k[1:]) - 1
    elif len(k) == 1 and k.isalnum():
        vk = ord(k.upper())
    else:
        raise ValueError(f"Ukendt tast i hotkey: {k!r}")
    return mods, vk


try:
    HK_MODS, HK_VK = parse_hotkey(cfg["hotkey"])
except ValueError:
    log.exception("Ugyldig hotkey i config.json – bruger ctrl+alt+space")
    HK_MODS, HK_VK = parse_hotkey(DEFAULTS["hotkey"])


def mods_held():
    return all(any(is_down(v) for v in VK_MODS[m]) for m in HK_MODS)


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
    n = user32.ToUnicodeEx(vk, scan, st, buf, 8, 4, user32.GetKeyboardLayout(tid))
    ch = buf.value[:n] if n > 0 else ""   # n<0 = dødtast (´ ` ^ ¨) → ignoreres
    return ch if ch and ord(ch[0]) >= 32 else ""


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
    out = open(os.path.join(HERE, "bridge.log"), "ab")
    bridge_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "ds_server:app", "--host", "127.0.0.1",
         "--port", str(cfg["bridge_port"])],
        cwd=HERE, stdout=out, stderr=out, stdin=subprocess.DEVNULL,
        creationflags=0x08000000 | 0x00000200)           # CREATE_NO_WINDOW | NEW_PROCESS_GROUP
    log.info("Bridge startet (pid %s)", bridge_proc.pid)


class BridgeError(Exception):
    def __init__(self, status, detail):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail


def ask_bridge(q):
    req = urllib.request.Request(BRIDGE + "/ask", data=json.dumps({"q": q}).encode("utf-8"),
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=cfg["request_timeout"]) as r:
            return json.load(r)["answer"]
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail", "")
        except Exception:
            detail = ""
        raise BridgeError(e.code, detail)


# ------------------------------------------------------------------ Prik (UI)
ui_q = queue.Queue()
COLORS = {"rec": "#e53935", "think": "#fb8c00", "ok": "#43a047", "err": "#8e24aa"}


class Dot:
    SIZE = 16

    def __init__(self, root):
        self.root, self.token = root, 0
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", "black")
        root.configure(bg="black")
        self.canvas = tk.Canvas(root, width=self.SIZE, height=self.SIZE, bg="black", highlightthickness=0)
        self.canvas.pack()
        self.oval = self.canvas.create_oval(2, 2, self.SIZE - 2, self.SIZE - 2, fill="red", outline="")
        rect = wt.RECT()
        user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)      # arbejdsområde (uden proceslinje)
        root.geometry(f"{self.SIZE}x{self.SIZE}+{rect.right - self.SIZE - 14}+{rect.bottom - self.SIZE - 14}")
        root.withdraw()

    def _no_focus(self):
        """Klik gennem prikken, og stjæl aldrig fokus fra det program du skriver i."""
        try:
            self.root.update_idletasks()
            hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            ex = user32.GetWindowLongW(hwnd, -20)
            user32.SetWindowLongW(hwnd, -20, ex | 0x80000 | 0x20 | 0x08000000 | 0x80)
        except Exception:
            log.exception("kunne ikke sætte vinduesstil på prikken")

    def show(self, color, ms=None):
        self.token += 1
        if not cfg["dot"]:
            return self.root.withdraw()
        self.canvas.itemconfig(self.oval, fill=color)
        self.root.deiconify()
        self._no_focus()
        self.root.attributes("-topmost", True)
        if ms:
            t = self.token
            self.root.after(ms, lambda: self.token == t and self.root.withdraw())

    def hide(self):
        self.token += 1
        self.root.withdraw()


# ------------------------------------------------------------------ Tilstand + hotkey-logik
IDLE, RECORDING, THINKING = "idle", "rec", "think"
state, buf = IDLE, []
suppressed_down = set()          # taster hvis keydown vi slugte → slug også keyup


def toggle():
    global state
    if state == IDLE:
        buf.clear()
        state = RECORDING
        ui_q.put(("dot", COLORS["rec"], None))
    elif state == RECORDING:
        text = "".join(buf).strip()
        buf.clear()
        if not text:
            state = IDLE
            ui_q.put(("hide",))
            return
        state = THINKING
        ui_q.put(("dot", COLORS["think"], None))
        threading.Thread(target=run_query, args=(text,), daemon=True).start()
    # THINKING: ignorer, vi venter på svaret


def cancel():
    global state
    buf.clear()
    state = IDLE
    ui_q.put(("hide",))


def run_query(text):
    global state
    try:
        log.info("Sender prompt (%d tegn)", len(text))
        answer = ask_bridge(text).strip()
        pyperclip.copy(answer)
        log.info("Svar i clipboard (%d tegn)", len(answer))
        ui_q.put(("dot", COLORS["ok"], 2500))
    except BridgeError as e:
        log.error("Bridge-fejl %s", e)
        if e.status in (401, 409):                 # logget ud / login-tilstand → åbn GUI
            webbrowser.open(BRIDGE)
        ui_q.put(("dot", COLORS["err"], 4000))
    except Exception:
        log.exception("Fejl under forespørgsel (kører bridgen?)")
        ui_q.put(("dot", COLORS["err"], 4000))
    finally:
        state = IDLE


def process(msg, d):
    """Returnér True hvis tasten skal slås ihjel (ikke nå frem til det aktive program)."""
    if d.flags & 0x10:                              # injiceret tast (fx fra andre programmer) – rør ikke
        return False
    down, up = msg in (0x100, 0x104), msg in (0x101, 0x105)
    vk = d.vkCode
    if up:
        if vk in suppressed_down:
            suppressed_down.discard(vk)
            return True
        return False
    if not down:
        return False
    if vk == HK_VK and mods_held():
        suppressed_down.add(vk)
        toggle()
        return True
    if state != RECORDING or vk in PASS_VKS:
        return False
    swallow = cfg["suppress_keys"]
    if vk == 0x1B:
        cancel()
    elif vk == 0x08:
        if buf:
            buf.pop()
    elif vk == 0x0D:
        buf.append("\n")
    else:
        ch = translate(vk, d.scanCode)
        if ch:
            buf.append(ch)
    if swallow:
        suppressed_down.add(vk)
    return swallow


listener = None


def win_filter(msg, data):
    try:
        swallow = process(msg, data)
    except Exception:
        log.exception("fejl i tastefilter")
        swallow = False
    if swallow:
        listener.suppress_event()       # rejser bevidst en intern undtagelse (pynput's måde at slå tasten ihjel)
    return False                        # vi har selv håndteret alt – ingen on_press nødvendig


# ------------------------------------------------------------------ Main
def tray_icon():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((10, 10, 54, 54), fill=(67, 160, 71, 255))

    def toggle_dot(icon, item):
        cfg["dot"] = not cfg["dot"]
        save_cfg(cfg)
        ui_q.put(("refresh",))

    menu = pystray.Menu(
        pystray.MenuItem("Vis prik", toggle_dot, checked=lambda item: cfg["dot"]),
        pystray.MenuItem("Åbn login / status", lambda icon, item: webbrowser.open(BRIDGE)),
        pystray.MenuItem("Afslut", lambda icon, item: ui_q.put(("quit",))))
    return pystray.Icon("SecretAI", img, f"SecretAI ({cfg['hotkey']})", menu)


def main():
    global listener
    # Kun én kopi ad gangen
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\SecretAI_single_instance")
    if ctypes.windll.kernel32.GetLastError() == 183:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    start_bridge()
    root = tk.Tk()
    dot = Dot(root)
    icon = tray_icon()
    listener = keyboard.Listener(win32_event_filter=win_filter)
    listener.start()
    icon.run_detached()
    log.info("SecretAI kører. Hotkey: %s", cfg["hotkey"])

    def shutdown():
        listener.stop()
        if bridge_proc is not None:                # luk kun bridgen hvis det var os der startede den
            try:
                urllib.request.urlopen(urllib.request.Request(BRIDGE + "/admin/quit", data=b"{}",
                                       headers={"content-type": "application/json"}), timeout=5).read()
                bridge_proc.wait(timeout=10)
            except Exception:
                bridge_proc.kill()
        icon.stop()
        root.destroy()

    def pump():
        try:
            while True:
                m = ui_q.get_nowait()
                if m[0] == "dot":
                    dot.show(m[1], m[2])
                elif m[0] == "hide" or (m[0] == "refresh" and not cfg["dot"]):
                    dot.hide()
                elif m[0] == "quit":
                    return shutdown()
        except queue.Empty:
            pass
        root.after(80, pump)

    root.after(80, pump)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("SecretAI crashede")
        raise
