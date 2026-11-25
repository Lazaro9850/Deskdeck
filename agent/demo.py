"""
Modo demonstracao (painel_agent.py --demo).

Troca TODAS as fontes de dados do agente por dados ficticios: apps genericos, uma musica de exemplo,
uso do Claude simulado, processos inventados e um Jarvis que encena conversas. Serve para tirar prints e
gravar GIFs do projeto sem mostrar nada do PC de verdade. Nenhum botao executa acoes no PC.

Os icones e a capa do album sao desenhados aqui mesmo (PNG gerado em Python puro, sem bibliotecas).
"""
import base64
import math
import struct
import threading
import time
import zlib

HOST = "DESKDECK-PC"


# ------------------------------------------------------------------ PNG minimo
def _png(w, h, rgba):
    raw = b"".join(b"\x00" + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


def _seg_dist(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / float(dx * dx + dy * dy or 1)))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def _inside(shape, x, y):
    k = shape[0]
    if k == "circle":
        _, cx, cy, r = shape
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r
    if k == "ring":
        _, cx, cy, r1, r2 = shape
        d = (x - cx) ** 2 + (y - cy) ** 2
        return r1 * r1 <= d <= r2 * r2
    if k == "ering":  # anel eliptico (meridiano do globo)
        _, cx, cy, rx, ry, w = shape
        d = math.hypot((x - cx) / rx, (y - cy) / ry)
        return abs(d - 1.0) * min(rx, ry) <= w / 2.0
    if k == "rrect":
        _, x0, y0, x1, y1, rad = shape
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return False
        cx, cy = min(max(x, x0 + rad), x1 - rad), min(max(y, y0 + rad), y1 - rad)
        return (x - cx) ** 2 + (y - cy) ** 2 <= rad * rad
    if k == "seg":
        _, x0, y0, x1, y1, w = shape
        return _seg_dist(x, y, x0, y0, x1, y1) <= w / 2.0
    if k == "tri":
        _, (ax, ay), (bx, by), (cx, cy) = shape
        s = lambda px, py, qx, qy: (x - qx) * (py - qy) - (px - qx) * (y - qy)  # noqa: E731
        d1, d2, d3 = s(ax, ay, bx, by), s(bx, by, cx, cy), s(cx, cy, ax, ay)
        return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))
    return False


def _draw(size, top, bottom, layers, rounded=True, aa=3):
    """Fundo com degrade (quadrado arredondado) + camadas [(cor_rgba, [formas])]. Antisserrilhado aa x aa."""
    out = bytearray(size * size * 4)
    bg = ("rrect", 0, 0, size, size, size * 0.22) if rounded else ("rrect", 0, 0, size, size, 0.01)
    offs = [(i + 0.5) / aa for i in range(aa)]
    n = float(aa * aa)
    for y in range(size):
        f = y / float(size - 1)
        base = [top[i] + (bottom[i] - top[i]) * f for i in range(3)]
        for x in range(size):
            r, g, b, a = 0.0, 0.0, 0.0, 0.0
            for oy in offs:
                for ox in offs:
                    px, py = x + ox, y + oy
                    if not _inside(bg, px, py):
                        continue
                    c = list(base)
                    for col, shapes in layers:
                        if any(_inside(s, px, py) for s in shapes):
                            al = col[3] / 255.0
                            c = [c[i] * (1 - al) + col[i] * al for i in range(3)]
                    r, g, b, a = r + c[0], g + c[1], b + c[2], a + 1
            i = (y * size + x) * 4
            if a:
                out[i:i + 4] = bytes((int(r / a), int(g / a), int(b / a), int(255 * a / n)))
    return _png(size, size, out)


W = (255, 255, 255, 255)
DARK = (20, 24, 32, 255)


def _icons(s=96):
    u = s / 96.0
    S = lambda *v: tuple(x * u if isinstance(x, (int, float)) else x for x in v)  # noqa: E731
    return [
        ("Navegador", _draw(s, (66, 133, 244), (25, 84, 200), [
            (W, [S("ring", 48, 48, 24, 29), S("ering", 48, 48, 12, 26.5, 4.5), S("seg", 21, 48, 75, 48, 4.5),
                 S("seg", 48, 20, 48, 76, 4.5)])])),
        ("Chat", _draw(s, (139, 92, 246), (91, 52, 200), [
            (W, [S("rrect", 18, 22, 78, 64, 14), ("tri", S(30, 60), S(46, 62), S(28, 78))]),
            ((139, 92, 246, 255), [S("circle", 34, 43, 5), S("circle", 48, 43, 5), S("circle", 62, 43, 5)])])),
        ("Música", _draw(s, (52, 211, 153), (16, 150, 100), [
            (W, [S("circle", 36, 66, 11), S("circle", 64, 58, 11), S("seg", 45, 66, 45, 26, 6), S("seg", 73, 58, 73, 18, 6),
                 S("seg", 45, 28, 73, 20, 9)])])),
        ("Código", _draw(s, (40, 60, 110), (18, 30, 64), [
            ((96, 205, 255, 255), [S("seg", 36, 30, 20, 48, 7), S("seg", 20, 48, 36, 66, 7),
                                   S("seg", 60, 30, 76, 48, 7), S("seg", 76, 48, 60, 66, 7)]),
            (W, [S("seg", 54, 24, 42, 72, 6)])])),
        ("Arquivos", _draw(s, (251, 191, 36), (217, 140, 10), [
            ((255, 236, 170, 255), [S("rrect", 16, 24, 46, 40, 5)]),
            (W, [S("rrect", 16, 32, 80, 74, 7)])])),
        ("Jogos", _draw(s, (244, 63, 94), (190, 24, 60), [
            (W, [S("rrect", 14, 32, 82, 66, 17)]),
            ((244, 63, 94, 255), [S("seg", 26, 49, 40, 49, 5), S("seg", 33, 42, 33, 56, 5),
                                  S("circle", 62, 44, 4.5), S("circle", 71, 53, 4.5)])])),
        ("Terminal", _draw(s, (55, 65, 81), (17, 24, 39), [
            ((74, 222, 128, 255), [S("seg", 24, 34, 40, 48, 6), S("seg", 40, 48, 24, 62, 6)]),
            (W, [S("seg", 48, 64, 72, 64, 6)])])),
        ("Fotos", _draw(s, (45, 212, 191), (14, 140, 150), [
            ((255, 230, 120, 255), [S("circle", 66, 32, 9)]),
            (W, [("tri", S(14, 74), S(40, 40), S(64, 74)), ("tri", S(44, 74), S(62, 52), S(82, 74))])])),
    ]


def _album_art():
    s = 150
    return _draw(s, (255, 94, 160), (60, 20, 110), [
        ((255, 214, 90, 255), [("circle", 75, 78, 40)]),
        ((120, 30, 120, 255), [("seg", 20, 70 + i * 9, 130, 70 + i * 9, 3 + i) for i in range(5)]),
        ((30, 10, 60, 255), [("tri", (0, 150), (45, 100), (90, 150)), ("tri", (60, 150), (110, 95), (150, 150))]),
    ], rounded=False, aa=1)


# ------------------------------------------------------------------ dados
GB = 1024 ** 3
SONGS = [("Neon Skyline", "Os Demonstradores", 214), ("Café às Três", "Trio Ficção", 187)]
CONVERSAS = [
    ("Como vai estar o tempo amanhã?",
     "Amanhã deve fazer entre dezenove e vinte e sete graus, com pouca chance de chuva."),
    ("Abre a calculadora.", "Pronto, abri a calculadora."),
    ("O que está pesando no PC agora?",
     "O navegador é o que mais usa, com cerca de doze por cento da CPU. O resto está tranquilo."),
]


def _wave(t, period, lo, hi, phase=0.0):
    return lo + (hi - lo) * (0.5 + 0.5 * math.sin(2 * math.pi * t / period + phase))


class FakeJarvis:
    """Encena o Jarvis na aba do tablet: estado, nivel do microfone, transcricao e resposta."""

    def __init__(self, app):
        self.app, self.n, self.busy, self.claps = app, 2, threading.Event(), True  # 1a cena: pergunta nova

    def emit(self, **ev):
        self.app.link.send(dict(ev, t="jarvis"))

    def state(self, st, **extra):
        self.emit(ev="state", state=st, claps=self.claps, model="haiku", game=False, phase=6, **extra)

    def send(self, cmd):
        c = cmd.get("cmd")
        if c == "status":
            self.state("parado")
            self.emit(ev="history", items=[{"you": y, "jar": j} for y, j in CONVERSAS[:2]])
        elif c == "claps":
            self.claps = bool(cmd.get("on", not self.claps))
            self.state("parado")
        elif c == "listen" and not self.busy.is_set():
            threading.Thread(target=self._scene, daemon=True).start()
        elif c == "stop":
            self.busy.clear()

    def stop(self):
        pass

    def _scene(self):
        self.busy.set()
        you, jar = CONVERSAS[self.n % len(CONVERSAS)]
        self.n += 1
        self.state("ouvindo")
        t0 = time.time()
        while time.time() - t0 < 2.2 and self.busy.is_set():
            self.emit(ev="level", v=round(abs(math.sin((time.time() - t0) * 7)) * 0.8, 2))
            time.sleep(0.08)
        self.emit(ev="level", v=0)
        self.state("transcrevendo")
        time.sleep(0.5)
        self.emit(ev="heard", text=you)
        self.state("pensando")
        time.sleep(1.1)
        self.state("falando")
        words, said = jar.split(), []
        for w in words:
            if not self.busy.is_set():
                break
            said.append(w)
            self.emit(ev="reply", text=" ".join(said), final=False)
            time.sleep(0.16)
        self.emit(ev="reply", text=" ".join(said), final=True)
        time.sleep(0.4)
        self.busy.clear()
        self.state("parado")


def install(app):
    """Substitui as fontes de dados do App por dados ficticios."""
    import socket
    t_start = time.time()
    icons = _icons()
    art = _album_art()
    apps = [{"id": "a%d" % i, "label": n, "icon": ic, "path": "", "exe": ""} for i, (n, ic) in enumerate(icons)]
    socket.gethostname = lambda: HOST  # nome mostrado no tablet

    # apps da "barra de tarefas"
    app.apps.apps = apps
    app.apps.refresh = lambda: False
    app.apps.public = lambda: [{"id": a["id"], "label": a["label"], "icon": a["icon"]} for a in apps]
    app.apps.running = lambda: ["a0", "a1", "a2", "a3"]

    # sistema
    def stats():
        t = time.time() - t_start
        cpu = _wave(t, 23, 14, 31) + 4 * math.sin(t * 1.7)
        s = {"t": "stats", "now": int(time.time() * 1000), "cpu": round(cpu, 1),
             "cpuname": "AMD Ryzen 7 5800X 8-Core Processor", "ghz": round(_wave(t, 11, 3.8, 4.6), 2),
             "gpu": {"p": round(_wave(t, 31, 22, 48, 1.0), 1), "name": "NVIDIA GeForce RTX 3070",
                     "mem": int(_wave(t, 40, 3.1, 3.6) * GB)},
             "ram": {"p": round(_wave(t, 60, 44, 47), 1), "used": int(_wave(t, 60, 7.0, 7.5) * GB), "total": 16 * GB},
             "disk": {"p": 58.0, "free": int(402 * GB)},
             "net": {"down": int(_wave(t, 9, 0.2, 3.5) * 1e6), "up": int(_wave(t, 13, 20, 380) * 1e3)},
             "up": int(3 * 3600 + 17 * 60 + t)}
        app.system.last = s
        return s
    app.system.snapshot = stats
    app.toggles = lambda: {}

    # musica
    def media():
        t = time.time() - t_start
        total = sum(d for _, _, d in SONGS)
        k, pos = 0, t % total
        while pos > SONGS[k][2]:
            pos -= SONGS[k][2]
            k += 1
        title, artist, dur = SONGS[k]
        return {"has": True, "title": title, "artist": artist, "album": "Demo", "app": "Spotify",
                "playing": True, "pos": round(pos, 1), "dur": float(dur)}
    app.media.info = media
    app.media.art = art
    app.media.command = lambda cmd: True

    # uso do Claude
    def claude():
        now = time.time()
        hour0 = now - (now % 3600) - 23 * 3600
        hourly = [0] * 24
        for i, v in enumerate((3, 8, 14, 9, 5, 0, 0, 0, 0, 0, 2, 6, 11, 18, 22, 16, 9, 12, 20, 25, 17, 10, 7, 4)):
            hourly[i] = v * 1000
        start = now - (now % 3600) - 2 * 3600
        return {"t": "claude", "block": {"tokens": 61000, "out": 22000, "inp": 39000, "cache": 0, "msgs": 48,
                                         "start": start, "end": start + 5 * 3600},
                "today": 148000, "week": 912000, "hourly": hourly, "hour0": hour0,
                "real": {"5h": {"p": 42, "reset": start + 5 * 3600}, "7d": {"p": 63, "reset": now + 3 * 86400 + 5 * 3600}}}
    app.claude.snapshot = claude

    # processos
    procs = [("Jogo (demo)", 6, 9.0, 2.1 * GB, 1.2e6, 41.0), ("Navegador", 14, 6.0, 1.4 * GB, 0.4e6, 3.0),
             ("Editor de código", 9, 3.0, 0.9 * GB, 0.1e6, 0.5), ("Chat", 5, 1.5, 0.45 * GB, 0.02e6, 1.0),
             ("Música", 4, 1.0, 0.3 * GB, 0.01e6, 0.3), ("Explorador do Windows", 1, 0.6, 0.12 * GB, 0.0, 0.0),
             ("Gerenciador de Janelas da Área de Trabalho", 1, 0.8, 0.09 * GB, 0.0, 2.2),
             ("Antimalware Service Executable", 1, 0.4, 0.2 * GB, 0.05e6, 0.0)]

    def proc_snapshot():
        t = time.time() - t_start
        rows = []
        for i, (n, c, cpu, mem, disk, gpu) in enumerate(procs):
            w = 0.75 + 0.5 * (0.5 + 0.5 * math.sin(t / (3 + i) + i))
            rows.append({"n": n, "c": c, "cpu": round(cpu * w, 1), "mem": int(mem * (0.98 + 0.04 * w)),
                         "disk": int(disk * w), "gpu": round(gpu * w, 1), "eng": "3D" if gpu else "",
                         "pw": "Baixo", "pwt": "Baixo"})
        sk = app.procs.sort if app.procs.sort in ("cpu", "mem", "disk", "gpu", "n") else "cpu"
        rows.sort(key=lambda r: r[sk].lower() if sk == "n" else -r[sk])
        st = app.system.last if isinstance(getattr(app.system, "last", None), dict) else stats()
        tot = {"cpu": st["cpu"], "mem": st["ram"]["p"], "gpu": st["gpu"]["p"],
               "disk": int(sum(r["disk"] for r in rows)), "net": int((st["net"]["down"] + st["net"]["up"]) * 8)}
        return {"t": "procs", "sort": sk, "rows": rows[:7], "tot": tot, "count": 187}
    app.procs.snapshot = proc_snapshot
    app.procs.pdh = None
    app.procs.close = lambda: None

    # nenhuma acao de verdade no PC
    def no_action(*_a, **_k):
        app.toast("Modo demonstração")
    app.do_button = app.do_launch = app.do_media = no_action
    app.jarvis = FakeJarvis(app)
    # os botoes do Painel (Volume -, Volume +, Mudo, Recorte) vem do config.json e ja sao genericos
