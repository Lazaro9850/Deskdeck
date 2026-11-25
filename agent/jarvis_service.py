#!/usr/bin/env python3
"""
Jarvis: assistente de voz do DeskDeck (processo separado do agente do painel).

Comunicacao com o agente (painel_agent.py) por stdin/stdout, uma mensagem JSON por linha.

Agente -> Jarvis (comandos):
  {"cmd": "listen"}            comecar a ouvir (botao "Falar" do tablet; depois, wake word)
  {"cmd": "stop"}              parar o que estiver fazendo (ouvir, pensar ou falar)
  {"cmd": "wake", "on": bool}  liga/desliga a wake word "hey jarvis" (fase 5)
  {"cmd": "claps", "on": bool} liga/desliga abrir com palmas (v2)
  {"cmd": "status"}            reenviar o estado atual

Jarvis -> agente (eventos; o agente repassa ao tablet como {"t": "jarvis", ...}):
  {"ev": "state", "state": "parado|ouvindo|transcrevendo|pensando|falando|erro", ...}
  {"ev": "level", "v": 0.0-1.0}        volume do microfone enquanto ouve (anima o reator)
  {"ev": "heard", "text": "..."}       o que foi entendido
  {"ev": "reply", "text": "...", "final": bool}   resposta (em partes, conforme e falada)

Fase 3: ouvir, pensar e falar de verdade. Ouvido e voz sao locais; o texto vai ao Claude Code.
  ouvido: microfone (headset) com deteccao de fim de fala + faster-whisper "small" (pt)
  voz:    Kokoro v1.0 (onnx, voz PT-BR), frase a frase
  cerebro: Claude Code (assinatura do usuario), resposta em streaming; Haiku ou Sonnet conforme o pedido
Modelos ficam em <raiz>\\models (jarvis_models.py) e saem da memoria apos alguns minutos sem uso.
"""
import gc
import json
import os
import queue
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (os.path.join(ROOT, "libs-jarvis"), os.path.join(ROOT, "libs")):
    if os.path.isdir(_p):
        sys.path.insert(0, _p)
MODELS = os.path.join(ROOT, "models")
PHASE = 6
VIRTUAL_MICS = re.compile(r"droidcam|virtual|cable|stereo mix|mixagem|voicemeeter|nvidia broadcast|iriun", re.I)


LOG = os.path.join(ROOT, "data", "jarvis.log")


def log(fmt, *args):
    """Log simples em data\\jarvis.log (o stdout e o canal de eventos com o agente)."""
    try:
        if os.path.getsize(LOG) > 512_000:
            os.replace(LOG, LOG + ".1")
    except OSError:
        pass
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + (fmt % args) + "\n")
    except OSError:
        pass


class Cancelled(Exception):
    """O usuario pediu para parar (botao no tablet ou "Jarvis, para")."""


class NoSpeech(Exception):
    """Ninguem falou (ou nada foi entendido)."""


def load_cfg():
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8-sig") as f:
            c = json.load(f).get("jarvis") or {}
    except (OSError, ValueError):
        c = {}
    d = {"mic": "", "voice": "pf_dora", "speed": 1.05, "threads": 4, "unload_after": 300,
         "max_listen": 15, "silence_end": 0.9, "no_speech_timeout": 7,
         "wake_threshold": 0.5, "game_mode": True, "barge_in": True,
         "claps": 5, "clap_rise": 25, "clap_level": -36, "clap_decay": 10, "clap_flat": 0.01}
    d.update(c)
    return d


STATE_FILE = os.path.join(ROOT, "data", "jarvis_state.json")  # lembra se o "Hey Jarvis" esta ligado
IMPORT_LOCK = threading.Lock()  # bibliotecas nativas carregadas uma de cada vez


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(**kv):
    st = load_state()
    st.update(kv)
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f)
    except OSError:
        pass


# ------------------------------------------------------------------ modo jogo
def fullscreen_app():
    """True se o app em primeiro plano ocupa a tela inteira (jogo, video em tela cheia, apresentacao)."""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    st = ctypes.c_int(0)
    # 2 = app em tela cheia, 3 = Direct3D exclusivo, 4 = modo apresentacao
    if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(st)) == 0 and st.value in (2, 3, 4):
        return True
    u32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = u32.GetForegroundWindow()
    if not hwnd:
        return False
    cls = ctypes.create_unicode_buffer(64)
    u32.GetClassNameW(hwnd, cls, 64)
    if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        return False  # area de trabalho e barra de tarefas nao contam

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]
    r = wintypes.RECT()
    if not u32.GetWindowRect(hwnd, ctypes.byref(r)):
        return False
    u32.MonitorFromWindow.restype = wintypes.HMONITOR
    u32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    mon = u32.MonitorFromWindow(hwnd, 2)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    u32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    if not mon or not u32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        return False
    m = mi.rcMonitor  # janela sem borda cobrindo o monitor inteiro (jogos em "tela cheia sem bordas")
    return r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom


class Jarvis:
    def __init__(self, out):
        self.out = out
        self.lock = threading.Lock()
        self.cfg = load_cfg()
        self.state = "parado"
        st = load_state()
        self.wake = bool(st.get("wake"))
        self.claps = bool(st.get("claps"))  # abrir com palmas
        self.model = "haiku"
        self.game = False
        self.cancel = threading.Event()
        self.turn = None
        self.whisper = None
        self.kokoro = None
        self.wakemodel = None
        self.models_lock = threading.Lock()
        self.last_use = time.time()
        threading.Thread(target=self._janitor, name="jarvis-limpeza", daemon=True).start()
        threading.Thread(target=self._game_watch, name="jarvis-modo-jogo", daemon=True).start()
        threading.Thread(target=self._wake_loop, name="jarvis-hey-jarvis", daemon=True).start()

    # ------------------------------------------------------------- saida
    def emit(self, **ev):
        line = json.dumps(ev, ensure_ascii=False, separators=(",", ":"))
        with self.lock:
            self.out.write(line + "\n")
            self.out.flush()

    def set_state(self, state, **extra):
        self.state = state
        self.emit(ev="state", state=state, wake=self.wake, claps=self.claps, model=self.model, game=self.game,
                  phase=PHASE, **extra)

    def check(self):
        if self.cancel.is_set():
            raise Cancelled()

    def sleep(self, secs):
        if self.cancel.wait(secs):
            raise Cancelled()

    # ------------------------------------------------------------- comandos
    def handle(self, msg):
        cmd = msg.get("cmd")
        if cmd == "listen":
            if self.turn and self.turn.is_alive():
                return
            self.cancel.clear()
            self.turn = threading.Thread(target=self.run_turn, name="jarvis-turno", daemon=True)
            self.turn.start()
        elif cmd == "stop":
            self.cancel.set()
            p = getattr(self, "claude_proc", None)
            if p is not None and p.poll() is None:
                p.kill()  # interrompe o Claude no meio da resposta
            try:
                import sounddevice as sd
                sd.stop()  # corta a fala na hora
            except Exception:  # noqa: BLE001
                pass
        elif cmd == "selftest":
            # autoteste (so pelo canal interno; o agente nao repassa do tablet): uma frase sintetizada
            # entra no lugar do microfone e percorre transcricao -> resposta -> fala
            if self.turn and self.turn.is_alive():
                return
            self.cancel.clear()
            self._fake = msg.get("text") or "Jarvis, isto é um teste."
            self.turn = threading.Thread(target=self.run_turn, name="jarvis-autoteste", daemon=True)
            self.turn.start()
        elif cmd == "wake":
            self.wake = bool(msg.get("on"))
            save_state(wake=self.wake)
            log("hey jarvis %s", "ligado" if self.wake else "desligado")
            self.set_state(self.state)
        elif cmd == "claps":
            self.claps = bool(msg.get("on"))
            save_state(claps=self.claps)
            log("palmas %s", "ligado" if self.claps else "desligado")
            self.set_state(self.state)
        elif cmd == "status":
            self.set_state(self.state)
            if not hasattr(self, "history"):
                self.history = self._load_history()
            # ultimas trocas para o tablet (que pode ter sido reiniciado)
            self.emit(ev="history", items=[{"you": h["you"], "jar": h["jar"]} for h in self.history[-3:]])

    # ------------------------------------------------------------- uma interacao
    STOP_WORDS = re.compile(r"^(ei |hey )?(jarvis[,.!]? *)?(para|pare|parar|chega|cancela|cancelar|sil[eê]ncio|"
                            r"esquece|deixa pra l[aá]|nada|obrigad[oa]|valeu)[.!]*$", re.I)

    def run_turn(self):
        """Uma interacao. Se voce disser "Hey Jarvis" enquanto ele fala, ele para e escuta de novo."""
        self.last_use = time.time()
        while True:
            self._barge = False
            try:
                self._one_turn()
                return
            except Cancelled:
                if self._barge and not getattr(self, "_fake", None):
                    log("interrompido por \"Hey Jarvis\": ouvindo de novo")
                    self._chime()
                    self.cancel.clear()
                    continue  # nova interacao, ja ouvindo
                self.set_state("parado", detail="interrompido")
                return
            except NoSpeech as e:
                self.set_state("parado", detail=str(e) or "não ouvi nada")
                return
            except Exception as e:  # noqa: BLE001
                import traceback
                log("erro na interacao: %s", traceback.format_exc())
                self.set_state("erro", detail=str(e)[:200])
                time.sleep(3)
                self.set_state("parado")
                return
            finally:
                self.last_use = time.time()

    def _one_turn(self):
        self.set_state("ouvindo")
        # Bibliotecas do microfone antes de carregar o Whisper em paralelo (evita duas threads
        # carregando DLLs nativas ao mesmo tempo).
        with IMPORT_LOCK:
            import numpy  # noqa: F401
            import sounddevice  # noqa: F401
        threading.Thread(target=self._load_whisper, daemon=True).start()  # carrega enquanto voce fala
        audio = self.capture()
        self.set_state("transcrevendo")
        text = self.transcribe(audio)
        self.emit(ev="heard", text=text)
        if self.STOP_WORDS.match(text.strip()):  # "para", "chega", "obrigado"...: encerra sem perguntar ao Claude
            self.remember(text, "")
            self.set_state("parado", detail="ok")
            return
        self.remember(text, None)
        self.model = self.pick_model(text)
        self.set_state("pensando")
        # o Claude responde em streaming; cada frase completa ja vai para a voz
        frases = queue.Queue()
        threading.Thread(target=self._think_to_queue, args=(text, frases), name="jarvis-cerebro",
                         daemon=True).start()
        self.speak_queue(frases)
        self.set_state("parado")

    # ------------------------------------------------------------- historico
    HISTORY_FILE = os.path.join(ROOT, "data", "jarvis_historico.json")

    def remember(self, you, jar):
        """Guarda as ultimas conversas (no PC, em data\\jarvis_historico.json) para o tablet mostrar."""
        if not hasattr(self, "history"):
            self.history = self._load_history()
        if you is None:  # resposta do ultimo pedido (fala sem pedido antes nao entra no historico)
            if not self.history or self.history[-1]["jar"]:
                return
            self.history[-1]["jar"] = jar
        elif jar is None:  # pedido novo; a resposta chega depois
            self.history.append({"you": you, "jar": "", "t": int(time.time())})
        else:
            self.history.append({"you": you, "jar": jar, "t": int(time.time())})
        self.history = self.history[-20:]
        try:
            with open(self.HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False)
        except OSError:
            pass

    def _load_history(self):
        try:
            with open(self.HISTORY_FILE, encoding="utf-8") as f:
                return json.load(f)[-20:]
        except (OSError, ValueError):
            return []

    # ------------------------------------------------------------- ouvido
    def _mic(self):
        import sounddevice as sd
        devs, apis = sd.query_devices(), sd.query_hostapis()
        mme = [i for i, d in enumerate(devs) if d["max_input_channels"] > 0 and apis[d["hostapi"]]["name"] == "MME"
               and "mapper" not in d["name"].lower()]
        want = (self.cfg.get("mic") or "").lower()
        if want:
            for i in mme:
                if want in devs[i]["name"].lower():
                    return i
        try:
            default = sd.query_devices(kind="input")
            if not VIRTUAL_MICS.search(default["name"]):
                return None  # o microfone padrao do Windows e real: usa ele
        except Exception:  # noqa: BLE001
            pass
        try:  # padrao e virtual (ex.: DroidCam): prefere o mesmo aparelho da saida de som (headset)
            out_name = sd.query_devices(kind="output")["name"].lower()
            m = re.search(r"\(([^)]+)\)", out_name)
            key = (m.group(1) if m else out_name)[:12]
            for i in mme:
                if key and key in devs[i]["name"].lower() and not VIRTUAL_MICS.search(devs[i]["name"]):
                    return i
        except Exception:  # noqa: BLE001
            pass
        for i in mme:
            if not VIRTUAL_MICS.search(devs[i]["name"]):
                return i
        raise RuntimeError("nenhum microfone encontrado")

    def capture(self):
        """Grava ate a pessoa parar de falar (deteccao por energia, com piso de ruido medido na hora)."""
        import numpy as np
        import sounddevice as sd
        fake, self._fake = getattr(self, "_fake", None), None
        if fake:  # autoteste: voz sintetica no lugar do microfone
            a, asr = self._load_kokoro().create(fake, voice="pm_alex", lang="pt-br")
            return np.interp(np.arange(0, len(a), asr / 16000.0), np.arange(len(a)), a).astype(np.float32)
        sr, block = 16000, 480  # 30 ms
        q = queue.Queue()

        def cb(data, frames, t, status):
            q.put(data[:, 0].copy())

        frames, noise, speaking = [], [], False
        voiced = silent = 0
        t0 = time.time()
        last_level = 0.0
        mic = self._mic()
        log("ouvindo pelo microfone %s", mic)
        with sd.InputStream(device=mic, samplerate=sr, channels=1, dtype="float32", blocksize=block, callback=cb):
            last_block = time.time()
            while True:
                self.check()
                now = time.time()
                # os limites de tempo valem mesmo se o microfone nao mandar audio nenhum
                if not speaking and now - t0 > self.cfg["no_speech_timeout"]:
                    raise NoSpeech("não ouvi nada")
                if now - t0 > self.cfg["max_listen"]:
                    break
                try:
                    b = q.get(timeout=0.3)
                except queue.Empty:
                    if time.time() - last_block > 3:
                        raise RuntimeError("o microfone não está enviando áudio")
                    continue
                last_block = time.time()
                rms = float(np.sqrt(np.mean(b * b)) + 1e-9)
                if now - last_level > 0.11:
                    self.emit(ev="level", v=round(min(1.0, rms / 0.08), 2))
                    last_level = now
                if len(noise) < 10:  # primeiros 300 ms: mede o ruido do ambiente
                    noise.append(rms)
                    frames.append(b)
                    continue
                thr = max(0.012, float(np.median(noise)) * 3.0)
                frames.append(b)
                if rms > thr:
                    voiced += 1
                    silent = 0
                    if voiced >= 3:
                        speaking = True
                else:
                    voiced = 0
                    silent += 1
                if speaking and silent * 0.03 >= self.cfg["silence_end"]:
                    break
        self.emit(ev="level", v=0)
        return np.concatenate(frames)

    def _load_whisper(self):
        with self.models_lock:
            if self.whisper is None:
                with IMPORT_LOCK:
                    from faster_whisper import WhisperModel
                self.whisper = WhisperModel(os.path.join(MODELS, "whisper-small"), device="cpu",
                                            compute_type="int8", cpu_threads=int(self.cfg["threads"]))
        return self.whisper

    def transcribe(self, audio):
        w = self._load_whisper()
        # initial_prompt: contexto que ensina o nome "Jarvis" (sem ele, sai "Já viz", "Jarbas"...)
        segs, _info = w.transcribe(audio, language="pt", beam_size=1, vad_filter=True,
                                   vad_parameters={"min_silence_duration_ms": 400},
                                   initial_prompt="Conversa em português com o assistente Jarvis.")
        text = " ".join(s.text.strip() for s in segs).strip()
        self.check()
        if not text:
            raise NoSpeech("não entendi")
        return text

    # ------------------------------------------------------------- cerebro (Claude Code)
    # verbos/palavras INTEIROS que indicam raciocinio ("calcule" sim; "calculadora" nao)
    COMPLEX = re.compile(r"\b(expli(ca|que|car)|compar(a|e|ar)|analis(a|e|ar)|planej(a|e|ar)|c[oó]digo|por que|"
                         r"resum(a|e|o|ir)|escrev(a|e|er)|crie|criar|detalh(a|e|ar)|estrat[eé]gia|calcul(e|ar)|"
                         r"traduz(a|ir)?)\b", re.I)

    def pick_model(self, text):
        """Haiku para pedidos rapidos; Sonnet para os que pedem raciocinio (gasta mais do limite)."""
        forced = (self.cfg.get("model") or "").strip()
        if forced:
            return forced
        return "sonnet" if len(text) > 140 or self.COMPLEX.search(text) else "haiku"

    FREE_TOOLS = ("status_pc", "processos", "lista_apps", "abrir_app", "midia", "volume", "recorte_tela")

    def _mcp_config(self):
        """Arquivo de configuracao do servidor MCP "painel" (as acoes no PC)."""
        exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.isfile(exe):
            exe = sys.executable
        path = os.path.join(ROOT, "data", "jarvis_mcp.json")
        cfg = {"mcpServers": {"painel": {"type": "stdio", "command": exe,
                                         "args": [os.path.join(HERE, "mcp_painel.py")]}}}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return path

    def _claude_exe(self):
        import shutil
        exe = shutil.which("claude") or os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
        if not os.path.isfile(exe):
            raise RuntimeError("Claude Code não encontrado (instale e faça login)")
        return exe

    def think_stream(self, text):
        """Gera o texto da resposta conforme o Claude Code escreve (stream-json).
        Usa a assinatura do usuario (login do Claude Code), sem chave de API. A conversa continua
        (mesma sessao) enquanto houver menos de 10 min de silencio."""
        import subprocess
        import uuid
        home = os.path.join(os.path.expanduser("~"), "Jarvis")
        os.makedirs(home, exist_ok=True)
        persona = os.path.join(HERE, "jarvis_persona.md")
        if time.time() - getattr(self, "session_t", 0) > float(self.cfg.get("session_timeout", 600)):
            self.session_id = None
        cmd = [self._claude_exe(), "-p", time.strftime("[%d/%m/%Y %H:%M] ") + text,
               "--output-format", "stream-json", "--verbose", "--include-partial-messages",
               "--model", self.model, "--tools", "WebSearch,WebFetch",
               "--mcp-config", self._mcp_config(), "--strict-mcp-config",
               # liberadas sem perguntar: pesquisa e acoes reversiveis que voce pediu por voz.
               # mcp__painel__fechar_app fica de fora DE PROPOSITO: o pedido de permissao vai para o
               # tablet (hook PermissionRequest) com Permitir/Negar.
               "--allowedTools", " ".join(["WebSearch", "WebFetch"] + ["mcp__painel__" + t for t in self.FREE_TOOLS]),
               "--append-system-prompt-file", persona]
        if self.session_id:
            cmd += ["--resume", self.session_id]
        else:
            self.session_id = str(uuid.uuid4())
            cmd += ["--session-id", self.session_id]
        log("claude: modelo=%s sessao=%s nova=%s", self.model, self.session_id[:8], "--session-id" in cmd)
        t0 = time.time()
        proc = subprocess.Popen(cmd, cwd=home, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, creationflags=0x08000000, text=True, encoding="utf-8")
        self.claude_proc = proc
        got_text, result, warned = False, None, False
        try:
            for line in proc.stdout:
                if self.cancel.is_set():
                    raise Cancelled()
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if o.get("type") == "stream_event":
                    ev = o.get("event") or {}
                    d = ev.get("delta") or {}
                    if ev.get("type") == "content_block_delta" and d.get("type") == "text_delta" and d.get("text"):
                        if not got_text:
                            log("claude: primeiro texto em %.1f s", time.time() - t0)
                        got_text = True
                        yield d["text"]
                    elif ev.get("type") == "content_block_start":
                        blk = ev.get("content_block") or {}
                        if blk.get("type") in ("tool_use", "server_tool_use"):
                            log("claude: ferramenta %s em %.1f s", blk.get("name"), time.time() - t0)
                            if blk.get("name") in ("WebSearch", "WebFetch", "web_search") and not warned and not got_text:
                                # pesquisa demora alguns segundos: avisa em vez de ficar em silencio
                                warned = True
                                yield "Um momento, vou pesquisar. "
                        elif got_text:
                            yield " "  # novo bloco de texto (ex.: depois de uma pesquisa)
                    elif ev.get("type") == "content_block_stop" and got_text:
                        yield "\n"  # fim do bloco: a ultima frase ja pode ir para a voz
                elif o.get("type") == "result":
                    result = o
        finally:
            if proc.poll() is None:
                proc.kill()
            self.claude_proc = None
        self.session_t = time.time()
        log("claude: resposta completa em %.1f s", time.time() - t0)
        if result is None or result.get("is_error"):
            err = (result or {}).get("result") or (proc.stderr.read() if proc.stderr else "") or "sem resposta"
            log("claude falhou: %s", str(err)[:300])
            self.session_id = None
            if not got_text and re.search(r"limit", str(err), re.I):
                # limite do plano: avisa falando, com o horario de volta quando o Claude informa
                m = re.search(r"resets\s+(\d{1,2})(?::(\d\d))?\s*(am|pm)", str(err), re.I)
                volta = ""
                if m:
                    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
                    volta = " Ele volta às %d%s." % (h, (" e " + m.group(2)) if m.group(2) and m.group(2) != "00" else " horas")
                yield "O limite do seu plano do Claude acabou por agora." + volta + "\n"
                return
            if not got_text:
                raise RuntimeError("o Claude não respondeu agora")

    def _think_to_queue(self, text, q):
        """Junta o streaming em frases completas e as entrega para a voz."""
        buf = ""
        try:
            for chunk in self.think_stream(text):
                if chunk == "\n":  # fim de um bloco de texto: entrega o que sobrou sem esperar o processo acabar
                    if buf.strip():
                        q.put(buf.strip())
                    buf = ""
                    continue
                buf += chunk
                while True:  # frase completa = pontuacao final seguida de espaco (nao corta "3.5")
                    m = re.search(r"[.!?…:;]\s+", buf)
                    if not m:
                        break
                    sent, buf = buf[:m.end()].strip(), buf[m.end():]
                    if sent:
                        q.put(sent)
            if buf.strip():
                q.put(buf.strip())
            q.put(None)
        except Exception as e:  # noqa: BLE001 (inclui Cancelled)
            q.put(e)

    @staticmethod
    def for_voice(s):
        """Deixa o texto bom de ouvir: sem markdown, links e emojis; simbolos viram palavras."""
        s = re.sub(r"https?://\S+", "", s)
        s = re.sub(r"[*_`#>|~]+", "", s)
        s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
        for a, b in ((" × ", " vezes "), ("×", " vezes "), ("÷", " dividido por "), ("%", " por cento"),
                     ("°C", " graus"), ("°", " graus"), (" = ", " igual a "), ("&", " e "), ("→", ", ")):
            s = s.replace(a, b)
        s = re.sub(r"R\$\s?(\d[\d.,]*)", r"\1 reais", s)
        s = re.sub(r"[\U00010000-\U0010ffff☀-➿]", "", s)  # emojis e simbolos
        return re.sub(r"\s+", " ", s).strip()

    # ------------------------------------------------------------- voz
    def _load_kokoro(self):
        with self.models_lock:
            if self.kokoro is None:
                with IMPORT_LOCK:
                    from kokoro_onnx import Kokoro
                k = os.path.join(MODELS, "kokoro")
                self.kokoro = Kokoro(os.path.join(k, "kokoro-v1.0.onnx"), os.path.join(k, "voices-v1.0.bin"))
        return self.kokoro

    def speak(self, reply):
        """Fala um texto pronto (frase a frase)."""
        q = queue.Queue()
        for p in re.split(r"(?<=[.!?…:;])\s+", reply.strip()):
            if p:
                q.put(p)
        q.put(None)
        self.speak_queue(q)

    def speak_queue(self, frases):
        """Fala as frases conforme chegam na fila (str; None = fim; Exception = erro).
        A voz da frase seguinte e gerada enquanto a atual toca. Interrompivel a qualquer momento."""
        import sounddevice as sd
        kokoro = self._load_kokoro()
        ready = queue.Queue(maxsize=2)

        def producer():
            while True:
                p = frases.get()
                if p is None or isinstance(p, Exception) or self.cancel.is_set():
                    ready.put(p)
                    return
                falar = self.for_voice(p)
                if not falar:
                    continue
                try:
                    audio, sr = kokoro.create(falar, voice=self.cfg["voice"], speed=float(self.cfg["speed"]),
                                              lang="pt-br")
                except Exception as e:  # noqa: BLE001
                    ready.put(e)
                    return
                ready.put((p, audio, sr))

        threading.Thread(target=producer, name="jarvis-voz", daemon=True).start()
        said = []
        barge_stop = threading.Event()
        try:
            while True:
                self.check()
                try:
                    item = ready.get(timeout=0.2)
                except queue.Empty:
                    continue
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                p, audio, sr = item
                if not said:
                    self.set_state("falando")
                    if self.cfg.get("barge_in", True) and not self.game:  # "Hey Jarvis" interrompe a fala
                        threading.Thread(target=self._barge_listen, args=(barge_stop,), name="jarvis-interromper",
                                         daemon=True).start()
                said.append(p)
                self.emit(ev="reply", text=" ".join(said), final=False)
                sd.play(audio, sr)
                end = time.time() + len(audio) / float(sr) + 0.05
                while time.time() < end:
                    if self.cancel.wait(0.05):
                        sd.stop()
                        raise Cancelled()
            if said:
                self.emit(ev="reply", text=" ".join(said), final=True)
        finally:
            barge_stop.set()
            if said:
                self.remember(None, " ".join(said))  # guarda o que foi dito (mesmo se interrompido)
            self.last_use = time.time()

    def _barge_listen(self, stop):
        """Enquanto o Jarvis fala: se ouvir "Hey Jarvis", corta a fala e volta a escutar (ver run_turn)."""
        try:
            with IMPORT_LOCK:
                import sounddevice as sd
            m = self._load_wake()
            m.reset()
            q = queue.Queue()
            thr = float(self.cfg["wake_threshold"])
            with sd.InputStream(device=self._mic(), samplerate=16000, channels=1, dtype="int16", blocksize=1280,
                                callback=lambda d, f, t, s: q.put(d[:, 0].copy())):
                while not stop.is_set() and not self.cancel.is_set():
                    try:
                        b = q.get(timeout=0.3)
                    except queue.Empty:
                        continue
                    score = m.predict(b).get("hey_jarvis_v0.1", 0.0)
                    if score >= thr:
                        log("\"Hey Jarvis\" durante a fala (%.2f): interrompendo", score)
                        self._barge = True
                        self.cancel.set()
                        sd.stop()
                        return
        except Exception as e:  # noqa: BLE001
            log("interromper por voz: %s", e)

    # ------------------------------------------------------------- "Hey Jarvis"
    def _load_wake(self):
        if self.wakemodel is None:
            with IMPORT_LOCK:
                import types
                # o pacote importa o modulo de TREINO (scipy/scikit-learn, ~150 MB) no __init__;
                # para so detectar a frase ele nao e necessario
                sys.modules.setdefault("openwakeword.custom_verifier_model",
                                       types.SimpleNamespace(train_custom_verifier=None))
                from openwakeword.model import Model
                w = os.path.join(MODELS, "wakeword")
                self.wakemodel = Model(wakeword_models=[os.path.join(w, "hey_jarvis_v0.1.onnx")],
                                       inference_framework="onnx",
                                       melspec_model_path=os.path.join(w, "melspectrogram.onnx"),
                                       embedding_model_path=os.path.join(w, "embedding_model.onnx"))
        return self.wakemodel

    def _wake_active(self):
        return (self.wake or self.claps) and not self.game and not (self.turn and self.turn.is_alive())

    def _wake_loop(self):
        """Escuta continua da frase "Hey Jarvis" (~2% de um nucleo) e/ou das palmas (~0,1%). Pausa sozinha em jogo,
        durante uma conversa e quando a chave esta desligada."""
        while True:
            if not self._wake_active():
                time.sleep(0.5)
                continue
            try:
                self._listen_for_wake()
            except Exception as e:  # noqa: BLE001
                log("hey jarvis: %s", e)
                time.sleep(5)

    def _listen_for_wake(self):
        """Um so fluxo do microfone alimenta o "Hey Jarvis" (se ligado) e o detector de palmas (se ligado)."""
        with IMPORT_LOCK:
            import sounddevice as sd
        from palmas import ClapDetector
        c = self.cfg
        m = None
        if self.wake:
            m = self._load_wake()
            m.reset()
        clap = ClapDetector(c.get("claps", 5), c.get("clap_rise", 25), c.get("clap_level", -36),
                            c.get("clap_decay", 10), c.get("clap_flat", 0.01))
        q = queue.Queue()
        thr = float(c["wake_threshold"])
        mode = (self.wake, self.claps)
        with sd.InputStream(device=self._mic(), samplerate=16000, channels=1, dtype="int16", blocksize=1280,
                            callback=lambda d, f, t, s: q.put(d[:, 0].copy())):
            while self._wake_active() and (self.wake, self.claps) == mode:
                try:
                    b = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if self.claps:
                    new, fired = clap.feed(b)
                    if new:
                        self.emit(ev="clap", n=clap.count(), need=clap.need)  # contador no tablet
                    if fired:
                        log("%d palmas detectadas", clap.need)
                        break
                if m is not None:
                    score = m.predict(b).get("hey_jarvis_v0.1", 0.0)
                    if score >= thr:
                        log("hey jarvis detectado (%.2f)", score)
                        break
            else:
                return  # pausou (desligado, jogo, conversa) ou a chave mudou: recomeca no laco
        self._chime()
        self.handle({"cmd": "listen"})
        time.sleep(1.0)

    @staticmethod
    def _chime():
        """Bipe curto e suave: avisa que ouviu o "Hey Jarvis" e ja esta escutando o pedido."""
        try:
            import numpy as np
            import sounddevice as sd
            sr = 24000
            t = np.arange(int(sr * 0.09)) / sr
            env = np.minimum(1, np.minimum(t, t[::-1]) / 0.01)
            tone = np.concatenate([np.sin(2 * np.pi * 880 * t), np.sin(2 * np.pi * 1320 * t)]) * np.tile(env, 2) * 0.25
            sd.play(tone.astype(np.float32), sr)
            time.sleep(0.25)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------- modo jogo
    def _game_watch(self):
        """A cada 2 s ve se ha um app em tela cheia. Em jogo: pausa o "Hey Jarvis" e tira os modelos
        de voz da memoria (~750 MB livres para o jogo). O botao Falar do tablet continua funcionando."""
        while True:
            time.sleep(2)
            if not self.cfg.get("game_mode", True):
                continue
            try:
                g = fullscreen_app()
            except Exception:  # noqa: BLE001
                g = False
            if g == self.game:
                continue
            self.game = g
            log("modo jogo %s", "ligado" if g else "desligado")
            if g and not (self.turn and self.turn.is_alive()):
                with self.models_lock:
                    self.whisper = self.kokoro = None
                gc.collect()
            self.set_state(self.state)

    # ------------------------------------------------------------- memoria
    def _janitor(self):
        """Tira os modelos da memoria depois de alguns minutos sem uso."""
        while True:
            time.sleep(30)
            if (self.whisper or self.kokoro) and time.time() - self.last_use > float(self.cfg["unload_after"]) \
                    and not (self.turn and self.turn.is_alive()):
                with self.models_lock:
                    self.whisper = self.kokoro = None
                gc.collect()


def main():
    """Eventos saem pelo stdout; comandos chegam por um socket local (--port/--token).
    NAO ler comandos do stdin: no Windows, uma leitura bloqueada no pipe do stdin trava o
    carregamento de DLLs nativas (numpy/OpenBLAS, FFmpeg) em qualquer outra thread."""
    import argparse
    import socket
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    ap.add_argument("--token", default="")
    args = ap.parse_args()
    out = open(sys.stdout.fileno(), "w", encoding="utf-8", buffering=1, closefd=False)
    jarvis = Jarvis(out)
    if args.port:
        sock = socket.create_connection(("127.0.0.1", args.port), timeout=10)
        sock.settimeout(None)
        sock.sendall((args.token + "\n").encode("utf-8"))
        commands = sock.makefile("r", encoding="utf-8")
    else:  # modo de teste manual (python jarvis_service.py): comandos pelo stdin
        commands = sys.stdin
    jarvis.set_state("parado")
    for line in commands:
        line = line.strip().lstrip("﻿")
        if not line:
            continue
        try:
            jarvis.handle(json.loads(line))
        except ValueError:
            pass
    jarvis.cancel.set()  # conexao fechada = o agente encerrou: sai junto


if __name__ == "__main__":
    main()
