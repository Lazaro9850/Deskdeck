#!/usr/bin/env python3
"""
Painel PC - agente do Windows.

Coleta dados do PC (CPU, GPU, RAM, disco, rede, musica tocando, limites de IA)
e envia ao tablet; recebe os toques dos botoes e executa as acoes.

Conexao USB sem "adb reverse" (o Android 4.1 nao tem): o app do tablet escuta
em 127.0.0.1:7001 e este agente chega ate ele com "adb forward".
Nada fica exposto na rede: o unico servidor do agente e 127.0.0.1:8765, usado
pelo hook opcional de aprovacoes do Claude Code.
"""
import asyncio
import base64
import concurrent.futures
import ctypes
import faulthandler
import datetime
import json
import logging
import logging.handlers
import os
import re
import secrets
import shutil
import unicodedata
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
import winreg
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Instancia unica, verificada ANTES das bibliotecas pesadas: a tarefa agendada tenta abrir
# o agente a cada minuto, e a copia repetida precisa sair em milissegundos.
# (A porta HTTP nao servia para isso: no Windows o Python permite dois processos na mesma porta.)
if __name__ == "__main__":
    _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\PainelPCAgent")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)

# Instalacao: <raiz>\agent (codigo), <raiz>\libs (bibliotecas), <raiz>\data (logs/cache).
# Fica fora do AppData de proposito: apps empacotados (MSIX) virtualizam o AppData.
HERE = os.path.dirname(os.path.abspath(__file__))
_LIBS = os.path.join(os.path.dirname(HERE), "libs")
if os.path.isdir(_LIBS):
    sys.path.insert(0, _LIBS)

import psutil  # noqa: E402

from usage_and_apps import ClaudeUsage, TaskbarApps  # noqa: E402

DATA = os.path.join(os.path.dirname(HERE), "data")
os.makedirs(DATA, exist_ok=True)
CLAUDE_CACHE = os.path.join(DATA, "claude_rate_limits.json")
APP_PKG = "br.local.painelpc"
APP_ACT = APP_PKG + "/.MainActivity"
NO_WINDOW = 0x08000000

log = logging.getLogger("painel")


def setup_logging():
    log.setLevel(logging.INFO)
    fh = logging.handlers.RotatingFileHandler(os.path.join(DATA, "agent.log"), maxBytes=512_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s: %(message)s"))
    log.addHandler(fh)
    if sys.stderr is not None:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        log.addHandler(sh)


def load_config():
    # utf-8-sig: aceita o arquivo salvo com BOM (Bloco de Notas antigo / PowerShell 5.1)
    with open(os.path.join(HERE, "config.json"), encoding="utf-8-sig") as f:
        return json.load(f)


# --------------------------------------------------------------------------- ADB
def find_adb(cfg):
    cands = [cfg.get("adb") or "", os.path.join(os.path.dirname(HERE), "platform-tools", "adb.exe"),
             shutil.which("adb") or "",
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools", "adb.exe"),
             os.path.join(os.environ.get("ANDROID_HOME", ""), "platform-tools", "adb.exe")]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def run(cmd, timeout=15):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


# ------------------------------------------------------------------ contadores PDH
class _FmtValue(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class _FmtItem(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _FmtValue)]


_pdh = ctypes.WinDLL("pdh.dll")
_pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(wintypes.HANDLE)]
_pdh.PdhAddEnglishCounterW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(wintypes.HANDLE)]
_pdh.PdhCollectQueryData.argtypes = [wintypes.HANDLE]
_pdh.PdhCloseQuery.argtypes = [wintypes.HANDLE]
_pdh.PdhGetFormattedCounterArrayW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                              ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
for _f in (_pdh.PdhOpenQueryW, _pdh.PdhAddEnglishCounterW, _pdh.PdhCollectQueryData, _pdh.PdhCloseQuery,
           _pdh.PdhGetFormattedCounterArrayW):
    _f.restype = ctypes.c_long
PDH_FMT = 0x200 | 0x8000  # DOUBLE | NOCAP100
PDH_MORE_DATA = ctypes.c_long(0x800007D2).value


class Pdh:
    """Le contadores de desempenho do Windows (GPU, frequencia da CPU) sem pywin32."""

    def __init__(self, paths):
        self.paths = paths
        self.q = None
        self._open()

    def _open(self):
        self.q = wintypes.HANDLE()
        _pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.q))
        self.c = {}
        for k, p in self.paths.items():
            h = wintypes.HANDLE()
            if _pdh.PdhAddEnglishCounterW(self.q, p, 0, ctypes.byref(h)) == 0:
                self.c[k] = h
        _pdh.PdhCollectQueryData(self.q)
        self.opened = time.time()
        self.fresh = True

    def collect(self):
        # recria a consulta de vez em quando para enxergar processos novos usando a GPU
        if time.time() - self.opened > 45:
            _pdh.PdhCloseQuery(self.q)
            self._open()
            return False
        _pdh.PdhCollectQueryData(self.q)
        self.fresh = False
        return True

    def values(self, key):
        return dict(self.items(key))

    def items(self, key):
        """Lista (instancia, valor) validos, na ordem do Windows."""
        return [(k, v) for k, v in self.raw(key) if v is not None]

    def raw(self, key):
        """Todas as instancias na ordem do Windows; valor None quando invalido.
        Os nomes podem se repetir (varios 'chrome'), entao contadores do mesmo objeto
        devem ser pareados pela posicao, nao pelo nome."""
        h = self.c.get(key)
        if h is None:
            return []
        size, n = wintypes.DWORD(0), wintypes.DWORD(0)
        if _pdh.PdhGetFormattedCounterArrayW(h, PDH_FMT, ctypes.byref(size), ctypes.byref(n), None) != PDH_MORE_DATA:
            return []
        buf = (ctypes.c_byte * size.value)()
        if _pdh.PdhGetFormattedCounterArrayW(h, PDH_FMT, ctypes.byref(size), ctypes.byref(n), buf) != 0:
            return []
        items = ctypes.cast(buf, ctypes.POINTER(_FmtItem))
        return [(items[i].szName, items[i].FmtValue.doubleValue if items[i].FmtValue.CStatus in (0, 1) else None)
                for i in range(n.value)]


# ------------------------------------------------------------------------ audio
class Audio:
    """Volume/mudo do alto-falante e do microfone.

    O acesso ao Core Audio (COM) roda num processo separado (audio_helper.ps1):
    o comtypes dentro do agente causava travamentos e falhas 0xc0000005 que
    derrubavam o processo. Se o auxiliar morrer, ele e recriado.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.lines = None
        self.fails = 0
        self.ok = True

    def _start(self):
        import queue
        exe = os.path.join(HERE, "audio_helper.exe")  # ~12 MB; o .ps1 (PowerShell, ~60 MB) e so reserva
        cmd = [exe] if os.path.isfile(exe) else ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                                 os.path.join(HERE, "audio_helper.ps1")]
        self.proc = subprocess.Popen(cmd,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     creationflags=NO_WINDOW, text=True, encoding="utf-8", bufsize=1)
        self.lines = queue.Queue()
        proc, q = self.proc, self.lines

        def reader():
            for ln in proc.stdout:
                q.put(ln)
            q.put(None)
        threading.Thread(target=reader, name="audio-reader", daemon=True).start()
        first = q.get(timeout=30)
        if not first or "ready" not in first:
            raise RuntimeError("auxiliar de audio nao iniciou")

    def _ask(self, cmd, timeout=4):
        import queue
        with self.lock:
            try:
                if self.proc is None or self.proc.poll() is not None:
                    if self.fails > 5 and time.time() - getattr(self, "_last_try", 0) < 60:
                        return None
                    self._last_try = time.time()
                    self._start()
                self.proc.stdin.write(cmd + "\n")
                self.proc.stdin.flush()
                ln = self.lines.get(timeout=timeout)
                if ln is None:
                    raise RuntimeError("auxiliar de audio encerrou")
                r = json.loads(ln)
                if "err" in r:
                    raise RuntimeError(r["err"])
                self.fails = 0
                self.ok = True
                return r
            except (OSError, ValueError, RuntimeError, queue.Empty) as e:
                self.fails += 1
                if self.ok:
                    log.warning("audio: %s", e)
                self.ok = False
                try:
                    if self.proc:
                        self.proc.kill()
                except OSError:
                    pass
                self.proc = None
                return None

    def state(self):
        return self._ask("state") or {}

    def toggle_mic(self):
        r = self._ask("togglemic")
        return None if not r else r.get("mic_muted")


# ------------------------------------------------------------------------ teclado
VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "esc": 0x1B, "tab": 0x09, "enter": 0x0D,
      "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
      "pageup": 0x21, "pagedown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
      "printscreen": 0x2C, "volume_up": 0xAF, "volume_down": 0xAE, "volume_mute": 0xAD,
      "media_next": 0xB0, "media_prev": 0xB1, "media_stop": 0xB2, "media_playpause": 0xB3}
EXTENDED = {0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x5B}


def press_keys(keys):
    codes = []
    for k in keys:
        k = str(k).lower()
        if k in VK:
            codes.append(VK[k])
        elif re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", k):
            codes.append(0x6F + int(k[1:]))
        elif len(k) == 1:
            codes.append(ord(k.upper()))
        else:
            raise ValueError("tecla desconhecida: " + k)
    ue = ctypes.windll.user32.keybd_event
    for c in codes:
        ue(c, 0, 1 if c in EXTENDED else 0, 0)
    time.sleep(0.03)
    for c in reversed(codes):
        ue(c, 0, (1 if c in EXTENDED else 0) | 2, 0)


# ------------------------------------------------------------------------ midia
APP_NAMES = {"spotify": "Spotify", "chrome": "Google Chrome", "msedge": "Microsoft Edge", "firefox": "Firefox",
             "308046b0af4a39cb": "Firefox", "opera": "Opera", "brave": "Brave", "vlc": "VLC",
             "zunemusic": "Media Player", "zunevideo": "Filmes e TV", "deezer": "Deezer", "tidal": "TIDAL",
             "applemusic": "Apple Music", "youtube": "YouTube Music", "discord": "Discord", "foobar": "foobar2000"}


def pretty_app(aumid):
    a = (aumid or "").lower()
    for k, v in APP_NAMES.items():
        if k in a:
            return v
    a = aumid.split("!")[0].split("\\")[-1]
    return re.sub(r"\.exe$", "", a, flags=re.I)


class Media:
    """Musica tocando agora via GlobalSystemMediaTransportControls (Windows 10/11)."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, name="media", daemon=True).start()
        self.mgr = None
        self.art_key = None
        self.art = None
        self.available = True
        try:
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager  # noqa: F401
        except Exception as e:  # noqa: BLE001
            log.warning("winrt indisponivel: %s", e)
            self.available = False

    def _run(self, coro, timeout=4):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    async def _session(self):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
        if self.mgr is None:
            self.mgr = await M.request_async()
        return self.mgr.get_current_session()

    async def _read_thumb(self, ref):
        from winrt.windows.storage.streams import DataReader
        stream = await ref.open_read_async()
        size = int(stream.size)
        if not size or size > 1_500_000:
            return None
        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(size)
        buf = bytearray(size)
        reader.read_bytes(buf)
        ctype = getattr(stream, "content_type", "") or "image/jpeg"
        if not ctype.startswith("image/"):
            ctype = "image/png" if buf[:4] == b"\x89PNG" else "image/jpeg"
        return "data:%s;base64,%s" % (ctype, base64.b64encode(bytes(buf)).decode())

    async def _info(self):
        s = await self._session()
        if s is None:
            return {"has": False}
        props = await s.try_get_media_properties_async()
        pb = s.get_playback_info()
        tl = s.get_timeline_properties()
        playing = int(pb.playback_status) == 4
        pos = dur = 0.0
        try:
            dur = (tl.end_time - tl.start_time).total_seconds()
            pos = (tl.position - tl.start_time).total_seconds()
            if playing and tl.last_updated_time:
                last = tl.last_updated_time
                now = datetime.datetime.now(last.tzinfo) if last.tzinfo else datetime.datetime.utcnow()
                drift = (now - last).total_seconds()
                if 0 < drift < 6 * 3600:
                    pos += drift
            pos = max(0.0, min(pos, dur)) if dur > 0 else 0.0
        except Exception:  # noqa: BLE001
            pass
        info = {"has": True, "title": props.title or "", "artist": props.artist or props.album_artist or "",
                "album": props.album_title or "", "app": pretty_app(s.source_app_user_model_id),
                "playing": playing, "pos": round(pos, 1), "dur": round(dur, 1)}
        key = (info["title"], info["artist"], info["album"])
        if key != self.art_key:
            self.art_key = key
            self.art = None
            if props.thumbnail is not None:
                try:
                    self.art = await self._read_thumb(props.thumbnail)
                except Exception as e:  # noqa: BLE001
                    log.info("capa: %s", e)
        return info

    def info(self):
        if not self.available:
            return {"has": False}
        try:
            return self._run(self._info())
        except Exception as e:  # noqa: BLE001
            log.info("midia: %s", e)
            self.mgr = None
            return {"has": False}

    async def _cmd(self, cmd):
        s = await self._session()
        if s is None:
            return False
        if cmd == "next":
            return await s.try_skip_next_async()
        if cmd == "prev":
            return await s.try_skip_previous_async()
        return await s.try_toggle_play_pause_async()

    def command(self, cmd):
        ok = False
        if self.available:
            try:
                ok = bool(self._run(self._cmd(cmd)))
            except Exception as e:  # noqa: BLE001
                log.info("comando de midia: %s", e)
        if not ok:  # sem sessao: usa as teclas de midia do teclado
            press_keys([{"next": "media_next", "prev": "media_prev"}.get(cmd, "media_playpause")])


# ------------------------------------------------------------- dados do sistema
def cpu_name():
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        n = winreg.QueryValueEx(k, "ProcessorNameString")[0]
    except OSError:
        return "CPU"
    n = re.sub(r"\((R|TM|tm|r)\)", "", n)
    n = re.sub(r"\s+with Radeon.*$|\s+CPU\s*@.*$|\s+\d+-Core Processor$|Processor", "", n)
    n = n.replace("AMD ", "").replace("Intel ", "").replace("Core ", "")
    return re.sub(r"\s+", " ", n).strip()


def gpu_name():
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                              r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}")
        names = []
        for i in range(32):
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            try:
                names.append(winreg.QueryValueEx(winreg.OpenKey(root, sub), "DriverDesc")[0])
            except OSError:
                pass
        real = [n for n in names if not re.search(r"IDD|Virtual|Basic|Remote|Parsec|Luminon", n, re.I)]
        n = (real or names or ["GPU"])[0]
        return n.replace("(TM)", "").replace("AMD ", "").replace("NVIDIA ", "").replace("  ", " ").strip()
    except OSError:
        return "GPU"


class System:
    def __init__(self):
        self.pdh = Pdh({
            "gpu": r"\GPU Engine(*)\Utilization Percentage",
            "gpu_ded": r"\GPU Adapter Memory(*)\Dedicated Usage",
            "gpu_sh": r"\GPU Adapter Memory(*)\Shared Usage",
            "perf": r"\Processor Information(_Total)\% Processor Performance",
            "freq": r"\Processor Information(_Total)\Processor Frequency",
        })
        self.cpu = cpu_name()
        self.gpu = gpu_name()
        psutil.cpu_percent(None)
        self.net_prev = (time.time(), psutil.net_io_counters())
        self.last_gpu = 0.0
        self.last_ghz = None

    def _sum(self, key):
        v = self.pdh.values(key)
        return sum(v.values()) if v else None

    def snapshot(self):
        ok = self.pdh.collect()
        if ok:
            eng = self.pdh.values("gpu")
            self.last_eng = eng  # reaproveitado pela aba Processos (GPU por processo)
            by_type = {}
            for name, val in eng.items():
                t = name.rsplit("engtype_", 1)[-1] if "engtype_" in name else "?"
                by_type[t] = by_type.get(t, 0.0) + val
            self.last_gpu = min(100.0, max(by_type.values())) if by_type else 0.0
            perf, base = self.pdh.values("perf"), self.pdh.values("freq")
            if perf and base:
                self.last_ghz = list(perf.values())[0] / 100.0 * list(base.values())[0] / 1000.0
        mem = (self._sum("gpu_ded") or 0) + (self._sum("gpu_sh") or 0)
        vm = psutil.virtual_memory()
        if time.time() - getattr(self, "_disk_t", 0) > 30:  # espaco em disco quase nao muda
            try:
                du = psutil.disk_usage("C:\\")
                self._disk = {"p": du.percent, "free": du.free}
            except Exception:  # noqa: BLE001
                self._disk = None
            self._disk_t = time.time()
        disk = self._disk
        t, n = time.time(), psutil.net_io_counters()
        pt, pn = self.net_prev
        dt = max(0.2, t - pt)
        self.net_prev = (t, n)
        self.last = {
            "t": "stats",
            "now": int(time.time() * 1000),
            "cpu": round(psutil.cpu_percent(None), 1),
            "cpuname": self.cpu,
            "ghz": round(self.last_ghz, 2) if self.last_ghz else None,
            "gpu": {"p": round(self.last_gpu, 1), "name": self.gpu, "mem": int(mem) if mem else None},
            "ram": {"p": vm.percent, "used": vm.total - vm.available, "total": vm.total},
            "disk": disk,
            "net": {"down": int((n.bytes_recv - pn.bytes_recv) / dt), "up": int((n.bytes_sent - pn.bytes_sent) / dt)},
            "up": int(time.time() - psutil.boot_time()),
        }
        return self.last


# ------------------------------------------------ aba Processos (gerenciador)
_ver = ctypes.WinDLL("version")
_ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
_ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
_ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
_ver.GetFileVersionInfoW.restype = wintypes.BOOL
_ver.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
_ver.VerQueryValueW.restype = wintypes.BOOL


def file_description(path):
    """Nome amigavel do programa (o mesmo que o Gerenciador de Tarefas mostra)."""
    size = _ver.GetFileVersionInfoSizeW(path, None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not _ver.GetFileVersionInfoW(path, 0, size, buf):
        return None
    p, n = ctypes.c_void_p(), wintypes.UINT()
    langs = []
    if _ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(p), ctypes.byref(n)) and n.value >= 4:
        arr = ctypes.cast(p, ctypes.POINTER(ctypes.c_ushort * (n.value // 2))).contents
        langs = ["%04x%04x" % (arr[i], arr[i + 1]) for i in range(0, len(arr) - 1, 2)]
    for lc in langs + ["041604b0", "040904b0", "040904e4"]:
        if _ver.VerQueryValueW(buf, "\\StringFileInfo\\%s\\FileDescription" % lc, ctypes.byref(p), ctypes.byref(n)) and n.value > 1:
            s = ctypes.wstring_at(p.value, n.value - 1).strip()
            if s:
                return s
    return None


GPU_INST = re.compile(r"pid_(\d+)_.*?phys_(\d+)_eng_\d+_engtype_(.+)$")
POWER = ((0.5, "Muito baixo"), (3, "Baixo"), (10, "Moderado"), (30, "Alto"))


def power_label(score):
    for lim, txt in POWER:
        if score < lim:
            return txt
    return "Muito alto"


class ProcView:
    """Top 10 processos agrupados por programa, como a aba Processos do Gerenciador de Tarefas.
    So e calculado enquanto a aba esta aberta no tablet."""

    def __init__(self, system):
        self.system = system
        self.ncpu = psutil.cpu_count() or 1
        self.pdh = None
        self.exe = {}       # pid -> caminho do executavel
        self.names = {}     # caminho -> nome amigavel
        self.io_prev = {}   # pid -> (t, bytes)
        self.trend = {}     # programa -> [pontuacoes recentes de energia]
        self.sort = "cpu"

    def _mem(self):
        # "Memoria" do Gerenciador = conjunto de trabalho privado
        if self.pdh is None:
            self.pdh = Pdh({"ws": r"\Process(*)\Working Set - Private", "pid": r"\Process(*)\ID Process"})
        else:
            self.pdh.collect()
        ws, ids = self.pdh.raw("ws"), self.pdh.raw("pid")
        if len(ws) != len(ids):
            return {}
        out = {}
        for (n1, mem), (n2, pid) in zip(ws, ids):
            if mem is not None and pid is not None and n1 == n2:
                out[int(pid)] = mem
        return out

    def close(self):
        if self.pdh is not None:
            _pdh.PdhCloseQuery(self.pdh.q)
            self.pdh = None

    def _gpu(self):
        per = {}
        for inst, val in (getattr(self.system, "last_eng", None) or {}).items():
            m = GPU_INST.search(inst)
            if m and val > 0:
                key = (int(m.group(1)), "GPU %s - %s" % (m.group(2), m.group(3)))
                per[key] = per.get(key, 0.0) + val
        gpu, eng = {}, {}
        for (pid, e), v in per.items():
            if v > gpu.get(pid, 0.0):
                gpu[pid], eng[pid] = v, e
        return gpu, eng

    def _name(self, exe, name):
        if exe not in self.names:
            desc = None
            if exe:
                try:
                    desc = file_description(exe)
                except Exception:  # noqa: BLE001
                    desc = None
            self.names[exe] = desc or re.sub(r"\.exe$", "", name, flags=re.I)
        return self.names[exe] if exe else re.sub(r"\.exe$", "", name, flags=re.I)

    def snapshot(self):
        now = time.time()
        mem = self._mem()
        gpu, eng = self._gpu()
        groups, alive = {}, set()
        for p in psutil.process_iter(["name"]):
            pid = p.pid
            if pid == 0:
                continue
            alive.add(pid)
            try:
                cpu = p.cpu_percent(None) / self.ncpu
            except psutil.Error:
                continue
            if pid not in self.exe:
                try:
                    self.exe[pid] = p.exe()
                except psutil.Error:
                    self.exe[pid] = ""
            disk = 0.0
            try:
                io = p.io_counters()
                b = io.read_bytes + io.write_bytes
                prev = self.io_prev.get(pid)
                if prev:
                    disk = max(0.0, (b - prev[1]) / max(0.5, now - prev[0]))
                self.io_prev[pid] = (now, b)
            except psutil.Error:
                pass
            name = p.info.get("name") or "?"
            exe = self.exe[pid]
            key = (exe or name).lower()
            g = groups.get(key)
            if g is None:
                g = groups[key] = {"n": self._name(exe, name), "c": 0, "cpu": 0.0, "mem": 0.0, "disk": 0.0,
                                   "gpu": 0.0, "eng": "", "_g": 0.0}
            g["c"] += 1
            g["cpu"] += cpu
            g["mem"] += mem.get(pid, 0.0)
            g["disk"] += disk
            gp = gpu.get(pid, 0.0)
            g["gpu"] += gp
            if gp > g["_g"]:
                g["_g"], g["eng"] = gp, eng[pid]
        for d in (self.exe, self.io_prev):
            for pid in [k for k in d if k not in alive]:
                del d[pid]
        rows = []
        for key, g in groups.items():
            g["gpu"] = min(100.0, g["gpu"])
            score = g["cpu"] + g["gpu"] * 0.5 + min(g["disk"] / 1e6, 100) * 0.1
            hist = self.trend.setdefault(key, [])
            hist.append(score)
            del hist[:-60]  # ~2 min com atualizacao a cada 2 s
            g["pw"] = power_label(score)
            g["pwt"] = power_label(sum(hist) / len(hist))
            del g["_g"]
            rows.append(g)
        for key in [k for k in self.trend if k not in groups]:
            del self.trend[key]
        sk = self.sort if self.sort in ("cpu", "mem", "disk", "gpu", "n") else "cpu"
        rows.sort(key=lambda r: r[sk].lower() if sk == "n" else -r[sk])
        for r in rows:
            r["cpu"], r["gpu"] = round(r["cpu"], 1), round(r["gpu"], 1)
            r["mem"], r["disk"] = int(r["mem"]), int(r["disk"])
        st = getattr(self.system, "last", None) or {}
        net = st.get("net") or {}
        tot = {"cpu": st.get("cpu"), "mem": (st.get("ram") or {}).get("p"), "gpu": (st.get("gpu") or {}).get("p"),
               "disk": int(sum(r["disk"] for r in rows)), "net": int((net.get("down", 0) + net.get("up", 0)) * 8)}
        return {"t": "procs", "sort": sk, "rows": rows[:7], "tot": tot, "count": len(alive)}


# -------------------------------------------------------------- link com o tablet
class TabletLink:
    def __init__(self, cfg, on_message, on_connect):
        self.cfg = cfg
        self.on_message = on_message
        self.on_connect = on_connect
        self.adb = find_adb(cfg)
        self.sock = None
        self.lock = threading.Lock()
        self.connected = False
        self.status = "iniciando"
        self.serial = None

    def send(self, obj):
        s = self.sock
        if s is None:
            return False
        data = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with self.lock:
                s.sendall(data)
            return True
        except OSError as e:
            log.info("envio falhou: %s", e)
            self._drop()
            return False

    def _drop(self):
        s, self.sock = self.sock, None
        self.connected = False
        if s:
            try:
                s.close()
            except OSError:
                pass

    def _set(self, status):
        if status != self.status:
            log.info("status: %s", status)
        self.status = status

    def _device(self):
        rc, out = run([self.adb, "devices"])
        if rc != 0:
            return None, "adb falhou"
        want = self.cfg.get("serial") or ""
        for line in out.splitlines()[1:]:
            if line.startswith("*"):  # "* daemon started successfully" (o adb acabou de abrir)
                continue
            parts = line.split()
            if len(parts) >= 2 and (not want or parts[0] == want):
                if parts[1] == "device":
                    return parts[0], "ok"
                return None, "tablet " + parts[1] + " (autorize a depuração USB no tablet)"
        return None, "tablet não encontrado no USB"

    def _adb_recover(self):
        """Logo depois de o PC ligar, o adb as vezes nao enxerga o tablet ate o cabo ser reconectado.
        Se o tablet sumir por mais de 20 s, reinicia o servidor do adb (no maximo 1 vez por minuto)."""
        now = time.time()
        if getattr(self, "missing_since", None) is None:
            self.missing_since = now
            return
        if now - self.missing_since < 20 or now - getattr(self, "last_recover", 0) < 60:
            return
        self.last_recover = now
        log.info("tablet sumiu do adb: reiniciando o servidor do adb")
        run([self.adb, "kill-server"])
        run([self.adb, "start-server"], timeout=20)

    def _ensure_app(self, serial):
        rc, out = run([self.adb, "-s", serial, "shell", "pm", "path", APP_PKG])
        if "package:" not in out:
            apk = os.path.join(HERE, "PainelPC.apk")
            if os.path.isfile(apk):
                log.info("instalando o app no tablet")
                run([self.adb, "-s", serial, "install", "-r", apk], timeout=120)
        run([self.adb, "-s", serial, "shell", "am", "start", "-n", APP_ACT])

    def _open(self):
        wifi = self.cfg.get("wifi_host")
        if wifi:
            return socket.create_connection((wifi, 7001), timeout=5), "wifi"
        if not self.adb:
            self._set("adb não encontrado")
            return None, None
        serial, why = self._device()
        if not serial:
            self._set(why)
            self._adb_recover()
            return None, None
        self.missing_since = None
        self.serial = serial
        local = int(self.cfg.get("local_port", 17001))
        rc, out = run([self.adb, "-s", serial, "forward", "tcp:%d" % local, "tcp:7001"])
        if rc != 0:
            self._set("adb forward falhou: " + out.strip())
            return None, None
        return socket.create_connection(("127.0.0.1", local), timeout=5), "usb"

    def loop(self):
        fails = 0
        while True:
            try:
                s, mode = self._open()
            except OSError as e:
                s, mode = None, None
                self._set("conexão recusada: %s" % e)
            if s is None:
                time.sleep(3)
                continue
            try:
                s.settimeout(5)
                f = s.makefile("r", encoding="utf-8", newline="\n")
                first = f.readline()
                if not first:
                    raise ConnectionError("app não respondeu")
                hi = json.loads(first)
                if hi.get("app") != "painelpc":
                    raise ConnectionError("resposta inesperada")
                if mode == "wifi":
                    s.sendall((json.dumps({"t": "auth", "token": self.cfg.get("wifi_token", "")}) + "\n").encode())
                s.settimeout(None)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                self.sock = s
                self.connected = True
                fails = 0
                self._set("conectado (%s)" % mode)
                self.on_connect()
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        self.on_message(json.loads(line))
                    except Exception as e:  # noqa: BLE001
                        log.warning("mensagem do tablet: %s", e)
                raise ConnectionError("tablet fechou a conexão")
            except Exception as e:  # noqa: BLE001
                was = self.connected
                self._drop()
                try:
                    s.close()
                except OSError:
                    pass
                if was:
                    self._set("desconectado: %s" % e)
                    time.sleep(1)
                    continue
                fails += 1
                self._set("app do tablet não respondeu (%s)" % e)
                if self.serial and not self.cfg.get("wifi_host") and fails <= 3 or fails % 10 == 0:
                    self._ensure_app(self.serial)
                    time.sleep(4)
                else:
                    time.sleep(3)


# ------------------------------------------------------------------- Jarvis
class JarvisProc:
    """Processo do Jarvis (jarvis_service.py). So existe com a aba Jarvis aberta no tablet: abre ao entrar
    na aba e fecha alguns segundos depois de sair dela (terminando antes a conversa em andamento).
    Fora da aba, o Jarvis nao gasta nada no PC. Eventos vao para o tablet."""

    def __init__(self, on_event):
        self.on_event = on_event
        self.proc = None
        self.conn = None
        self.lock = threading.Lock()
        self.last_state = {"ev": "state", "state": "desligado"}

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def _start(self):
        # Comandos vao por um socket local, NAO pelo stdin: no Windows, enquanto uma thread fica
        # bloqueada lendo o pipe do stdin, o carregamento de DLLs nativas (numpy/OpenBLAS, FFmpeg)
        # em outra thread trava. Os eventos voltam pelo stdout, que nao tem esse problema.
        script = os.path.join(HERE, "jarvis_service.py")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        srv.settimeout(15)
        token = uuid.uuid4().hex
        self.proc = subprocess.Popen([sys.executable, script, "--port", str(srv.getsockname()[1]), "--token", token],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=open(os.path.join(DATA, "jarvis_stderr.log"), "a"),
                                     creationflags=NO_WINDOW, env=env,
                                     text=True, encoding="utf-8", bufsize=1, cwd=HERE)
        proc = self.proc
        try:
            conn, _ = srv.accept()
            conn.settimeout(5)
            hello = conn.makefile("r", encoding="utf-8").readline().strip()
            if hello != token:  # so aceita o processo que acabamos de abrir
                conn.close()
                raise OSError("Jarvis: conexao local nao autenticada")
            conn.settimeout(None)
            self.conn = conn
        finally:
            srv.close()

        def reader():
            for line in proc.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("ev") == "state":
                    self.last_state = ev
                self.on_event(ev)
            self.last_state = {"ev": "state", "state": "desligado"}
            self.on_event(self.last_state)
        threading.Thread(target=reader, name="jarvis-leitor", daemon=True).start()
        log.info("Jarvis iniciado (PID %s)", proc.pid)

    def send(self, cmd):
        with self.lock:
            try:
                if not self.running():
                    self._start()
                self.conn.sendall((json.dumps(cmd) + "\n").encode("utf-8"))
            except (OSError, ValueError) as e:
                log.warning("Jarvis: %s", e)
                if self.proc and self.proc.poll() is None:
                    self.proc.kill()
                self.proc = None

    def stop(self):
        with self.lock:
            if self.running():
                try:
                    self.conn.close()  # o servico sai quando a conexao fecha
                    self.proc.wait(3)
                except Exception:  # noqa: BLE001
                    self.proc.kill()
            self.proc = None


# ------------------------------------------------------------- aprovacoes (hook)
class Approvals:
    def __init__(self, app):
        self.app = app
        self.pending = {}
        self.lock = threading.Lock()

    @staticmethod
    def describe(data):
        tool = data.get("tool_name") or "?"
        ti = data.get("tool_input") or {}
        if not isinstance(ti, dict):
            return tool, str(ti)[:900]
        if tool.startswith("mcp__painel__"):  # acoes do Jarvis: texto amigavel em vez do nome tecnico
            acao = tool[len("mcp__painel__"):]
            nomes = {"fechar_app": "Fechar um app"}
            return nomes.get(acao, acao.replace("_", " ").capitalize()), (ti.get("nome") or json.dumps(ti, ensure_ascii=False))
        for key in ("command", "file_path", "url", "pattern", "query", "path", "prompt", "description"):
            if ti.get(key):
                txt = str(ti[key])
                if key == "command" and ti.get("description"):
                    txt = ti["description"] + "\n\n$ " + txt
                return tool, txt[:900]
        return tool, json.dumps(ti, ensure_ascii=False, indent=1)[:900]

    def request(self, data):
        if not self.app.link.connected:
            return None
        timeout = float(self.app.cfg.get("approval_timeout", 60))
        rid = uuid.uuid4().hex[:12]
        ev = threading.Event()
        with self.lock:
            self.pending[rid] = {"ev": ev, "decision": None}
        tool, detail = self.describe(data)
        cwd = data.get("cwd") or ""
        self.app.link.send({"t": "approval", "id": rid, "tool": tool, "detail": detail, "cwd": cwd,
                            "timeout": timeout,
                            "agent": "Jarvis" if os.path.basename(cwd.rstrip("\\/")).lower() == "jarvis"
                            else (data.get("agent") or "Claude Code")})
        log.info("aprovacao %s pedida: %s", rid, tool)
        ev.wait(timeout)
        with self.lock:
            item = self.pending.pop(rid, None)
        decision = item and item["decision"]
        if decision is None:
            self.app.link.send({"t": "approval_done", "id": rid})
        log.info("aprovacao %s: %s", rid, decision)
        return decision

    def resolve(self, rid, decision):
        with self.lock:
            item = self.pending.get(rid)
            if item and decision in ("allow", "deny"):
                item["decision"] = decision
                item["ev"].set()


class Handler(BaseHTTPRequestHandler):
    app = None

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/status":
            return self._json(200, {"link": self.app.link.status, "connected": self.app.link.connected})
        self._json(404, {})

    def do_POST(self):
        if self.path not in ("/approval", "/jarvis/tool"):
            return self._json(404, {})
        # So aceita chamadas locais e sem cabecalho Origin (bloqueia paginas web).
        if self.headers.get("Origin"):
            return self._json(403, {})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(min(n, 200_000)) or b"{}")
        except ValueError:
            return self._json(400, {})
        if self.path == "/jarvis/tool":
            # ferramentas do Jarvis (servidor MCP "painel"): exigem o token desta execucao do agente
            if not secrets.compare_digest(self.headers.get("X-Painel-Token", ""), self.app.token):
                return self._json(403, {})
            return self._json(200, self.app.jarvis_tool(data.get("tool", ""), data.get("args") or {}))
        self._json(200, {"decision": self.app.approvals.request(data)})


# --------------------------------------------------------------------- aplicacao
def wol_info():
    """Endereco da placa de rede com cabo (MAC + broadcast da rede): o tablet guarda e usa para
    ligar o PC pela rede (Wake-on-LAN) quando ele estiver desligado."""
    try:
        stats, addrs = psutil.net_if_stats(), psutil.net_if_addrs()
        best = None
        for name, lst in addrs.items():
            st = stats.get(name)
            if not st or not st.isup or re.search(r"loopback|virtual|vethernet|vpn|bluetooth|wsl", name, re.I):
                continue
            mac = next((a.address for a in lst if a.family == psutil.AF_LINK), None)
            ip4 = next((a for a in lst if a.family == socket.AF_INET and not a.address.startswith("169.254.")), None)
            if not mac or not ip4 or not ip4.netmask:
                continue
            ip = [int(x) for x in ip4.address.split(".")]
            mask = [int(x) for x in ip4.netmask.split(".")]
            bcast = ".".join(str(i | (255 ^ m)) for i, m in zip(ip, mask))
            score = (2 if "ethernet" in name.lower() else 0) + (1 if st.speed >= 100 else 0)
            if best is None or score > best[0]:
                best = (score, {"mac": mac.replace("-", ":").upper(), "bcast": bcast})
        return best[1] if best else None
    except Exception as e:  # noqa: BLE001
        log.info("wake-on-lan: %s", e)
        return None


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.system = System()
        self.audio = Audio()
        self.media = Media()
        self.claude = ClaudeUsage()
        self.apps = TaskbarApps()
        self.apps.refresh()
        self.approvals = Approvals(self)
        self.link = TabletLink(cfg, self.on_message, self.on_connect)
        self.actions = concurrent.futures.ThreadPoolExecutor(2, thread_name_prefix="acao")
        self.force_media = threading.Event()
        self.force_ai = threading.Event()
        self.procs = ProcView(self.system)
        self.proc_page = False      # a aba Processos esta aberta no tablet?
        self.page = 1               # aba aberta no tablet (0 Apps, 1 Painel, 2 Processos, 3 Jarvis)
        self.token = secrets.token_hex(16)  # autoriza as ferramentas do Jarvis (/jarvis/tool)
        self.jarvis = JarvisProc(self.on_jarvis_event)
        self.force_procs = threading.Event()
        self.buttons = {b["id"]: b for b in cfg.get("buttons", [])}

    # ---- eventos
    def on_connect(self):
        tz = datetime.datetime.now().astimezone().utcoffset().total_seconds() / 60
        btns = [{k: b.get(k) for k in ("id", "label", "icon", "color")} for b in self.cfg.get("buttons", [])]
        self.link.send({"t": "hello", "host": socket.gethostname(), "now": int(time.time() * 1000), "tz": tz,
                        "cfg": {"buttons": btns, "cols": self.cfg.get("cols", 3), "apps": self.apps.public()},
                        "wol": wol_info()})
        self.media.art_key = None  # reenviar a capa
        self.force_media.set()
        self.force_ai.set()

    def on_message(self, m):
        t = m.get("t")
        if t == "press":
            self.actions.submit(self.do_button, m.get("id"))
        elif t == "media":
            self.actions.submit(self.do_media, m.get("cmd"))
        elif t == "decide":
            self.approvals.resolve(m.get("id"), m.get("decision"))
        elif t == "page":
            self.page = m.get("n", 1)
            self.proc_page = self.page == 2
            if self.page == 3:      # aba Jarvis: inicia o servico (se preciso) e pede o estado atual
                self.actions.submit(self.jarvis.send, {"cmd": "status"})
            else:                   # saiu da aba: o Jarvis fecha (depois de terminar a conversa, se houver)
                self.jarvis_leave()
            if self.page == 1:      # voltou ao Painel: atualiza musica e Claude na hora
                self.force_media.set()
                self.force_ai.set()
            elif self.page == 2:
                self.force_procs.set()
        elif t == "procsort":
            self.procs.sort = m.get("key") or "cpu"
            self.force_procs.set()
        elif t == "jarvis":
            cmd = {k: v for k, v in m.items() if k != "t"}
            if cmd.get("cmd") in ("listen", "stop", "claps", "status"):
                self.actions.submit(self.jarvis.send, cmd)
        elif t == "launch":
            self.actions.submit(self.do_launch, m.get("id"))
        elif t == "ready":
            log.info("tablet pronto: tela %sx%s", m.get("w"), m.get("h"))

    # ---- Jarvis so com a aba aberta
    JARVIS_IDLE = ("parado", "erro", "desligado")

    def on_jarvis_event(self, ev):
        self.link.send(dict(ev, t="jarvis"))
        if ev.get("ev") == "state" and ev.get("state") in ("parado", "erro") and self.page != 3:
            self.jarvis_leave()  # terminou a conversa com outra aba aberta

    def jarvis_leave(self, delay=5.0):
        """Fecha o Jarvis se a aba continuar fechada por alguns segundos (troca rapida de aba nao reinicia)."""
        def check():
            if self.page != 3 and self.jarvis.running() and                     self.jarvis.last_state.get("state") in self.JARVIS_IDLE:
                log.info("aba Jarvis fechada: encerrando o Jarvis")
                self.jarvis.stop()
        t = threading.Timer(delay, check)
        t.daemon = True
        t.start()

    def do_launch(self, aid):
        try:
            label = self.apps.launch(aid)
            if label:
                log.info("abrindo app %s", label)
                self.toast("Abrindo " + label)
        except Exception as e:  # noqa: BLE001
            log.warning("abrir app %s: %s", aid, e)
            self.toast("Não foi possível abrir")

    def toast(self, text):
        self.link.send({"t": "toast", "text": text})

    # ---- ferramentas do Jarvis (chamadas pelo servidor MCP "painel" via /jarvis/tool)
    BUILTIN_APPS = {"calculadora": "calc.exe", "bloco de notas": "notepad.exe", "notas": "notepad.exe",
                    "explorador": "explorer.exe", "arquivos": "explorer.exe", "gerenciador de tarefas": "taskmgr.exe",
                    "configuracoes": "ms-settings:", "paint": "mspaint.exe", "prompt": "cmd.exe",
                    "terminal": "wt.exe"}

    @staticmethod
    def _norm(s):
        s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
        return re.sub(r"[^a-z0-9 ]+", " ", s).strip()

    def _find_app(self, nome):
        """Procura o app pelo nome falado: apps da barra de tarefas primeiro, depois os do Windows."""
        import difflib
        n = self._norm(nome)
        if not n:
            return None
        cands = [(self._norm(a["label"]), ("taskbar", a)) for a in self.apps.apps]
        cands += [(k, ("builtin", v)) for k, v in self.BUILTIN_APPS.items()]
        for key, val in cands:  # nome contido (ex.: "code" -> "vs code", "discord" -> "discord")
            if n == key or (len(n) >= 3 and (n in key or key in n)):
                return val
        best = difflib.get_close_matches(n, [k for k, _ in cands], n=1, cutoff=0.6)
        return dict(cands)[best[0]] if best else None

    def jarvis_tool(self, tool, args):
        try:
            return {"ok": True, "text": self._jarvis_tool(tool, args)}
        except Exception as e:  # noqa: BLE001
            log.warning("ferramenta %s: %s", tool, e)
            return {"ok": False, "text": "Falhou: %s" % e}

    def _jarvis_tool(self, tool, args):
        log.info("Jarvis usou a ferramenta %s %s", tool, json.dumps(args, ensure_ascii=False)[:120])
        if tool == "status_pc":
            s = getattr(self.system, "last", None) or self.system.snapshot()
            g, r, d = s.get("gpu") or {}, s.get("ram") or {}, s.get("disk") or {}
            return ("CPU %s%% (%s); GPU %s%%; RAM %s%% (%.1f de %.1f GB); disco C: %s%% usado, %.0f GB livres." % (
                round(s.get("cpu") or 0), s.get("cpuname", ""), round(g.get("p") or 0), round(r.get("p") or 0),
                (r.get("used") or 0) / 2**30, (r.get("total") or 0) / 2**30, round(d.get("p") or 0),
                (d.get("free") or 0) / 1e9))
        if tool == "processos":
            n = max(1, min(10, int(args.get("quantidade") or 5)))
            self.procs.sort = "mem" if args.get("ordenar_por") == "memoria" else "cpu"
            p = self.procs.snapshot()
            if self.page != 2:
                self.procs.close()
            return "; ".join("%s: CPU %.1f%%, %.0f MB" % (r["n"], r["cpu"], r["mem"] / 2**20) for r in p["rows"][:n])
        if tool == "lista_apps":
            abertos = set(self.apps.running())
            return "; ".join("%s (%s)" % (a["label"], "aberto" if a["id"] in abertos else "fechado") for a in self.apps.apps)
        if tool == "abrir_app":
            hit = self._find_app(args.get("nome", ""))
            if not hit:
                return "Não encontrei um app chamado '%s' na barra de tarefas." % args.get("nome", "")
            kind, val = hit
            if kind == "taskbar":
                self.apps.launch(val["id"])
                return "Abri o %s." % val["label"]
            os.startfile(val)
            return "Abri %s." % val
        if tool == "fechar_app":
            hit = self._find_app(args.get("nome", ""))
            exe = (hit[1].get("exe") if hit and hit[0] == "taskbar" else hit[1] if hit else None) or ""
            exe = {"calc.exe": "CalculatorApp.exe"}.get(exe.lower(), exe)  # apps da loja abrem outro processo
            if not exe.lower().endswith(".exe"):
                return "Não sei qual programa fechar para '%s'." % args.get("nome", "")
            rc, out = run(["taskkill", "/IM", os.path.basename(exe)])  # sem /F: pede para fechar, como o X da janela
            return ("Pedi para o %s fechar." % os.path.basename(exe)) if rc == 0 else ("Não consegui fechar: %s" % out.strip()[:150])
        if tool == "midia":
            acao = args.get("acao", "play_pause")
            if acao == "estado":
                i = self.media.info()
                if not i.get("has"):
                    return "Nada tocando no momento."
                return "%s: %s, de %s, no %s." % ("Tocando" if i.get("playing") else "Pausado", i.get("title"),
                                                   i.get("artist") or "artista desconhecido", i.get("app"))
            self.do_media({"proxima": "next", "anterior": "prev"}.get(acao, "playpause"))
            return {"proxima": "Pulei para a próxima.", "anterior": "Voltei para a anterior."}.get(acao, "Play/pause acionado.")
        if tool == "volume":
            acao = args.get("acao", "estado")
            if acao in ("aumentar", "diminuir"):
                passos = max(1, min(25, int(args.get("passos") or 3)))  # cada passo = 2% no Windows
                for _ in range(passos):
                    press_keys(["volume_up" if acao == "aumentar" else "volume_down"])
                    time.sleep(0.02)
            elif acao == "mudo":
                press_keys(["volume_mute"])
            time.sleep(0.2)
            st = self.audio.state() or {}
            return "Volume em %s%%%s." % (st.get("vol", "?"), ", mudo" if st.get("muted") else "")
        if tool == "recorte_tela":
            press_keys(["win", "shift", "s"])
            return "Abri a ferramenta de recorte."
        raise ValueError("ferramenta desconhecida: %s" % tool)

    def do_media(self, cmd):
        self.media.command(cmd)
        time.sleep(0.4)
        self.force_media.set()

    def do_button(self, bid):
        b = self.buttons.get(bid)
        if not b:
            return
        typ = b.get("type")
        log.info("botao %s (%s)", bid, typ)
        try:
            if typ == "run":
                cmds = b["cmd"] if isinstance(b["cmd"], list) else [b["cmd"]]
                exe = next((c for c in cmds if shutil.which(c) or os.path.exists(os.path.expandvars(c))), cmds[0])
                args = b.get("args") or []
                if args:
                    subprocess.Popen([os.path.expandvars(exe)] + args, creationflags=0x00000008)  # DETACHED
                else:
                    os.startfile(os.path.expandvars(exe))
                self.toast("Abrindo " + b.get("label", ""))
            elif typ == "url":
                webbrowser.open(b["url"])
                self.toast("Abrindo " + b.get("label", ""))
            elif typ == "keys":
                press_keys(b["keys"])
            elif typ == "media":
                self.do_media(b.get("cmd", "playpause"))
            elif typ == "volume":
                press_keys([{"up": "volume_up", "down": "volume_down"}.get(b.get("cmd"), "volume_mute")])
                if b.get("cmd") == "mute":
                    time.sleep(0.2)
                    st = self.audio.state()
                    if st:
                        self.link.send({"t": "key", "id": bid, "on": bool(st.get("muted"))})
                        self.toast("Som desligado" if st.get("muted") else "Som ligado")
            elif typ == "mic":
                r = self.audio.toggle_mic()
                if r is None:
                    self.toast("Microfone não encontrado")
                else:
                    self.link.send({"t": "key", "id": bid, "on": r})
                    self.toast("Microfone MUDO" if r else "Microfone ligado")
            elif typ == "lock":
                ctypes.windll.user32.LockWorkStation()
            elif typ == "obs":
                self.do_obs(b)
            else:
                self.toast("Tipo de botão desconhecido: %s" % typ)
        except Exception as e:  # noqa: BLE001
            log.warning("botao %s: %s", bid, e)
            self.toast("Erro: %s" % e)

    def do_obs(self, b):
        try:
            import obsws_python as obs
        except ImportError:
            self.toast("Instale o OBS e o pacote obsws-python")
            return
        o = self.cfg.get("obs", {})
        try:
            cl = obs.ReqClient(host=o.get("host", "localhost"), port=o.get("port", 4455), password=o.get("password", ""), timeout=3)
            r = cl.toggle_record()
            active = getattr(r, "output_active", None)
            self.link.send({"t": "key", "id": b["id"], "on": bool(active)})
            self.toast("Gravando" if active else "Gravação parada")
        except Exception as e:  # noqa: BLE001
            self.toast("OBS não respondeu (abra o OBS e ative o WebSocket)")
            log.info("obs: %s", e)

    # ---- laco de envio
    def toggles(self):
        st = self.audio.state() or {}
        out = {}
        for b in self.cfg.get("buttons", []):
            if b.get("type") == "mic" and st.get("mic_muted") is not None:
                out[b["id"]] = st["mic_muted"]
            elif b.get("type") == "volume" and b.get("cmd") == "mute" and "muted" in st:
                out[b["id"]] = st["muted"]
        return out

    def sender(self):
        """Coleta SO o que a aba aberta no tablet mostra:
        Apps -> lista de apps abertos (3 s) | Painel -> sistema, musica, Claude (1,5 s)
        Processos -> tabela (~3 s) | tablet desconectado -> nada."""
        interval = float(self.cfg.get("interval", 1.5))
        last_ai_t = last_apps_t = last_proc_t = last_tog_t = 0
        toggles = {}
        while True:
            t0 = time.time()
            page = self.page if self.link.connected else -1
            # Nenhuma excecao pode derrubar este laco (antes, um erro aqui encerrava o agente).
            try:
                if page == 0:
                    self.link.send({"t": "stats", "now": int(t0 * 1000), "running": self.apps.running()})
                elif page == 3:  # aba Jarvis: so mantem a conexao e o relogio (o Jarvis manda os proprios eventos)
                    self.link.send({"t": "stats", "now": int(t0 * 1000)})
                elif page == 1:
                    s = self.system.snapshot()
                    if t0 - last_tog_t > 4:  # estado do audio (botao Mudo) nao precisa ser tao frequente
                        toggles, last_tog_t = self.toggles(), t0
                    s["toggles"] = toggles
                    self.link.send(s)
                    if self.force_ai.is_set() or t0 - last_ai_t > 20:
                        self.force_ai.clear()
                        self.link.send(self.claude.snapshot())
                        last_ai_t = t0
                elif page == 2:
                    self.system.snapshot()  # totais do cabecalho e GPU por processo
                    if self.force_procs.is_set() or t0 - last_proc_t >= 2.8:
                        self.force_procs.clear()
                        p = self.procs.snapshot()
                        p["now"] = int(t0 * 1000)
                        self.link.send(p)
                        last_proc_t = t0
                if page != 2 and self.procs.pdh is not None:
                    self.procs.close()
                if t0 - last_apps_t > 60:
                    last_apps_t = t0
                    if self.apps.refresh() and self.link.connected:
                        self.on_connect()
            except Exception:  # noqa: BLE001
                log.exception("erro no laco de envio")
            wait = {0: 3.0, 1: interval, 2: 1.4, 3: 3.0}.get(page, 2.0)
            time.sleep(max(0.2, wait - (time.time() - t0)))

    def media_watch(self):
        """Consulta a musica a cada 1 s; envia quando muda (e a cada 5 s para sincronizar a posicao)."""
        last_sig, last_track, last_t = None, None, 0
        while True:
            self.force_media.wait(1.0)
            forced = self.force_media.is_set()
            self.force_media.clear()
            if not self.link.connected or self.page != 1:  # musica so aparece na aba Painel
                last_sig = None
                continue
            info = self.media.info()
            sig = (info.get("title"), info.get("artist"), info.get("playing"), info.get("app"))
            now = time.time()
            if forced or sig != last_sig or now - last_t > 5:
                msg = dict(info, t="media")
                if forced or sig[:2] != last_track:
                    msg["art"] = self.media.art
                    last_track = sig[:2]
                self.link.send(msg)
                last_sig, last_t = sig, now


def main():
    setup_logging()
    faulthandler.enable(open(os.path.join(DATA, "crash.log"), "a"), all_threads=True)
    # Registra qualquer falha inesperada (o pythonw nao tem console).
    sys.excepthook = lambda *a: log.critical("falha fatal", exc_info=a)
    threading.excepthook = lambda a: log.error("falha na thread %s", a.thread.name if a.thread else "?",
                                                exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    cfg = load_config()
    try:
        ThreadingHTTPServer.allow_reuse_address = False  # no Windows, reuse permitiria 2 agentes na porta
        srv = ThreadingHTTPServer(("127.0.0.1", int(cfg.get("http_port", 8765))), Handler)
    except OSError:
        log.error("Outro agente do Painel PC ja esta rodando (porta %s ocupada).", cfg.get("http_port", 8765))
        return 1
    app = App(cfg)
    Handler.app = app
    if "--demo" in sys.argv:  # dados ficticios para prints/GIFs; nenhuma acao no PC
        import demo
        demo.install(app)
        log.info("MODO DEMONSTRACAO: dados ficticios")
        threading.Thread(target=srv.serve_forever, name="http", daemon=True).start()
        threading.Thread(target=app.link.loop, name="link", daemon=True).start()
        threading.Thread(target=app.media_watch, name="media-watch", daemon=True).start()
        app.sender()
        return 0
    # token das ferramentas do Jarvis: novo a cada execucao, legivel so pela pasta de dados do usuario
    with open(os.path.join(DATA, "agent_token"), "w", encoding="ascii") as f:
        f.write(app.token)
    log.info("Painel PC iniciado. adb=%s", app.link.adb)
    threading.Thread(target=srv.serve_forever, name="http", daemon=True).start()
    threading.Thread(target=app.link.loop, name="link", daemon=True).start()
    threading.Thread(target=app.media_watch, name="media-watch", daemon=True).start()
    try:
        app.sender()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
