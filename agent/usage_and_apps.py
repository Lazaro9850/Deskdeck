"""Uso do Claude Code (tokens locais) e apps fixados na barra de tarefas do Windows."""
import datetime
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import winreg

import psutil

log = logging.getLogger("painel")
NO_WINDOW = 0x08000000
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
CLAUDE_CACHE = os.path.join(DATA, "claude_rate_limits.json")


# --------------------------------------------------------------- Claude Code
class ClaudeUsage:
    """Soma os tokens registrados pelo Claude Code em ~/.claude/projects/**/*.jsonl."""

    def __init__(self):
        self.base = os.path.join(os.path.expanduser("~"), ".claude", "projects")
        self.files = {}  # caminho -> (mtime, posicao ja lida, linhas)

    def _scan(self, path):
        """Le so o trecho novo do arquivo (os logs do Claude Code so crescem no final)."""
        st = os.stat(path)
        old = self.files.get(path)
        if old and old[0] == st.st_mtime and old[1] == st.st_size:
            return old[2]
        if old and st.st_size >= old[1]:
            start, rows = old[1], list(old[2])
        else:  # arquivo novo ou reescrito: le tudo
            start, rows = 0, []
        with open(path, "rb") as f:
            f.seek(start)
            data = f.read()
        end = data.rfind(b"\n") + 1  # so linhas completas; o resto fica para a proxima leitura
        pos = start + end
        for raw in data[:end].splitlines():
            if b'"usage"' not in raw or b'"assistant"' not in raw:
                continue
            try:
                o = json.loads(raw)
                u = o["message"]["usage"]
                ts = datetime.datetime.fromisoformat(o["timestamp"].replace("Z", "+00:00")).timestamp()
            except Exception:  # noqa: BLE001
                continue
            inp = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            out = u.get("output_tokens", 0)
            cache = u.get("cache_read_input_tokens", 0)
            rows.append((ts, inp, out, cache, (o["message"].get("id"), o.get("requestId"))))
        self.files[path] = (st.st_mtime if pos == st.st_size else 0, pos, rows)
        return rows

    def _rows(self, now):
        rows = []
        if not os.path.isdir(self.base):
            return rows
        for root, _d, files in os.walk(self.base):
            for fn in files:
                if not fn.endswith(".jsonl"):
                    continue
                p = os.path.join(root, fn)
                try:
                    if now - os.path.getmtime(p) < 8 * 86400:
                        rows.extend(self._scan(p))
                except OSError:
                    pass
        seen, uniq = set(), []
        for r in sorted(rows):
            if r[4] in seen:
                continue
            seen.add(r[4])
            uniq.append(r)
        return uniq

    _renew_t = 0.0
    _renewing = False

    @classmethod
    def renew_login(cls, wait=False):
        """Renova o login rodando o proprio Claude Code uma vez (modelo Haiku, resposta de uma
        palavra): e o Claude Code que renova o token, do jeito oficial. No maximo 1x a cada 30 min."""
        if cls._renewing or time.time() - cls._renew_t < 1800:
            return False
        exe = shutil.which("claude") or os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
        if not os.path.isfile(exe):
            log.info("renovacao do login: Claude Code nao encontrado")
            return False
        cls._renew_t, cls._renewing = time.time(), True

        def run():
            try:
                p = subprocess.run([exe, "-p", "Responda apenas: ok", "--model", "haiku"], capture_output=True,
                                   timeout=180, creationflags=NO_WINDOW, cwd=os.path.expanduser("~"))
                log.info("renovacao do login: %s", "ok" if p.returncode == 0 else "falhou (codigo %s)" % p.returncode)
                cls._plan_next = 0.0  # consulta o uso de novo na proxima volta
            except Exception as e:  # noqa: BLE001
                log.info("renovacao do login falhou: %s", type(e).__name__)
            finally:
                cls._renewing = False
        if wait:
            run()
        else:
            threading.Thread(target=run, name="renova-login", daemon=True).start()
        return True

    PLAN_EVERY = 300   # consulta a cada 5 min (de minuto em minuto a Anthropic responde 429)
    PLAN_KEEP = 1800   # se uma consulta falhar, mostra o ultimo valor bom por ate 30 min
    PLAN_FILE = os.path.join(DATA, "plan_usage.json")  # so percentuais e horarios; nunca o token
    _plan_next = 0.0
    _plan_good = None  # (quando, valor)
    _backoff = 0       # espera atual apos respostas 429

    @classmethod
    def _plan(cls):
        """Percentuais reais do plano, com cache: consulta no maximo a cada 5 min e guarda o
        ultimo valor bom em disco (uma reinicializacao do agente nao gera consulta nova)."""
        now = time.time()
        if cls._plan_good is None:
            try:
                with open(cls.PLAN_FILE, encoding="utf-8") as f:
                    c = json.load(f)
                cls._plan_good = (c["t"], c["val"])
                cls._plan_next = max(cls._plan_next, c["t"] + cls.PLAN_EVERY)
            except (OSError, ValueError, KeyError):
                cls._plan_good = (0.0, None)
        if now >= cls._plan_next:
            cls._plan_next = now + cls.PLAN_EVERY
            val = cls._fetch_plan()
            if val:
                cls._backoff = 0
                cls._plan_good = (now, val)
                try:
                    with open(cls.PLAN_FILE, "w", encoding="utf-8") as f:
                        json.dump({"t": now, "val": val}, f)
                except OSError:
                    pass
        t, val = cls._plan_good
        if not val or now - t > cls.PLAN_KEEP:
            return None
        out = {}
        for k, w in val.items():  # janela que ja reiniciou desde a ultima consulta: volta a 0%
            out[k] = {"p": 0.0, "reset": None} if w.get("reset") and w["reset"] < now else w
        return out

    @classmethod
    def _fetch_plan(cls):
        """Consulta a Anthropic com o login do Claude Code (~/.claude/.credentials.json).
        O token so e lido aqui, enviado apenas para api.anthropic.com e nunca registrado
        em log nem enviado ao tablet. Login vencido: pede a renovacao e tenta de novo em 1 min."""
        import urllib.error
        val = None
        try:
            path = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
            with open(path, encoding="utf-8") as f:
                o = json.load(f).get("claudeAiOauth") or {}
            tok, exp = o.get("accessToken"), (o.get("expiresAt") or 0) / 1000
            if tok and exp <= time.time() + 30:
                cls.renew_login()  # vencido: renova em segundo plano; usa os tokens locais ate la
                cls._plan_next = time.time() + 60
            elif tok:
                import urllib.request
                req = urllib.request.Request("https://api.anthropic.com/api/oauth/usage", headers={
                    "Authorization": "Bearer " + tok, "anthropic-beta": "oauth-2025-04-20",
                    "Accept": "application/json", "User-Agent": "painel-pc/1.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = json.load(r)
                val = {}
                for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
                    w = data.get(key) or {}
                    p = w.get("utilization", w.get("used_percentage"))
                    reset = w.get("resets_at")
                    if isinstance(reset, str):
                        try:
                            reset = datetime.datetime.fromisoformat(reset.replace("Z", "+00:00")).timestamp()
                        except ValueError:
                            reset = None
                    if p is not None:
                        val[label] = {"p": float(p), "reset": reset}
                val = val or None
        except urllib.error.HTTPError as e:
            log.info("uso do plano indisponivel: HTTP %s", e.code)
            if e.code == 429:  # muitas consultas: espera dobra a cada 429 seguido (10, 20, 40 min... ate 1 h)
                cls._backoff = min(3600, cls._backoff * 2 if cls._backoff else 600)
                cls._plan_next = time.time() + cls._backoff
            val = None
        except Exception as e:  # noqa: BLE001  (sem rede etc.: segue com o ultimo valor bom)
            log.info("uso do plano indisponivel: %s", type(e).__name__)
            val = None
        return val

    @classmethod
    def _real(cls):
        """Percentuais reais: consulta do plano (login) ou o que a status line do terminal gravou."""
        plan = cls._plan()
        if plan:
            return plan
        return cls._statusline()

    @staticmethod
    def _statusline():
        """Percentuais reais, se a status line do Claude Code (terminal) os tiver gravado."""
        try:
            with open(CLAUDE_CACHE, encoding="utf-8") as f:
                c = json.load(f)
        except (OSError, ValueError):
            return None
        rl = c.get("rate_limits") or {}
        if not rl or time.time() - c.get("saved", 0) > 6 * 3600:
            return None
        out = {}
        for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
            w = rl.get(key)
            if w and w.get("used_percentage") is not None:
                reset = w.get("resets_at")
                p = w["used_percentage"] if not reset or reset > time.time() else 0
                out[label] = {"p": p, "reset": reset}
        return out or None

    def snapshot(self):
        now = time.time()
        rows = self._rows(now)
        # Tokens "novos" (entrada + saida). A leitura de cache fica de fora do total: ela costuma
        # ser 80-90% do volume, mas pesa bem menos no limite do plano e inflava o numero.
        tot = lambda r: r[1] + r[2]  # noqa: E731
        # bloco de 5 h (como o limite do plano): comeca na hora cheia da 1a mensagem
        start = end = None
        b = {"tokens": 0, "out": 0, "inp": 0, "cache": 0, "msgs": 0}
        for r in rows:
            if end is None or r[0] >= end:
                start = r[0] - (r[0] % 3600)
                end = start + 5 * 3600
                b = {"tokens": 0, "out": 0, "inp": 0, "cache": 0, "msgs": 0}
            b["tokens"] += tot(r)
            b["inp"] += r[1]
            b["out"] += r[2]
            b["cache"] += r[3]
            b["msgs"] += 1
        block = dict(b, start=start, end=end) if end and now < end else None
        midnight = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        today = sum(tot(r) for r in rows if r[0] >= midnight)
        week = sum(tot(r) for r in rows if now - r[0] < 7 * 86400)
        hour0 = now - (now % 3600) - 23 * 3600
        hourly = [0] * 24
        for r in rows:
            i = int((r[0] - hour0) // 3600)
            if 0 <= i < 24:
                hourly[i] += tot(r)
        return {"t": "claude", "block": block, "today": today, "week": week, "hourly": hourly,
                "hour0": hour0, "real": self._real()}


# ----------------------------------------------------- barra de tarefas do PC
PINNED = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Internet Explorer", "Quick Launch",
                      "User Pinned", "TaskBar")
LABELS = {"File Explorer": "Explorador", "Explorador de Arquivos": "Explorador", "Visual Studio Code": "VS Code",
          "Google Chrome": "Chrome"}


class TaskbarApps:
    def __init__(self):
        self.apps = []
        self.sig = None
        self._running = []
        self._running_t = 0

    @classmethod
    def _signature(cls):
        import hashlib
        try:
            lnks = sorted((f, os.path.getmtime(os.path.join(PINNED, f))) for f in os.listdir(PINNED) if f.endswith(".lnk"))
        except OSError:
            lnks = []
        # o registro Taskband muda quando se fixa/desafixa um app da Store
        return [lnks, hashlib.sha1(cls._order()).hexdigest()]

    @staticmethod
    def _order():
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Taskband")
            return winreg.QueryValueEx(k, "Favorites")[0] or b""
        except OSError:
            return b""

    @staticmethod
    def _exe(item):
        name, target, args = item.get("name", ""), item.get("target") or "", item.get("args") or ""
        aumid = (item.get("aumid") or "").lower()
        if aumid:  # apps da Store: nome do executavel conhecido
            for key, exe in (("whatsapp", "WhatsApp.exe"), ("claude", "claude.exe"), ("spotify", "Spotify.exe"),
                             ("telegram", "Telegram.exe")):
                if key in aumid:
                    return exe
            return None
        base = os.path.basename(target)
        m = re.search(r"--processStart\s+\"?([^\s\"]+)", args)
        if m:
            return m.group(1)
        if "riotclient" in base.lower() and "valorant" in args.lower():
            return "VALORANT-Win64-Shipping.exe"
        if name.lower().startswith("amd software"):
            return "RadeonSoftware.exe"
        if base.lower() in ("explorer.exe", ""):
            return None
        return base

    def _fetch(self):
        cache = os.path.join(DATA, "apps_cache.json")
        sig = self._signature()
        try:
            with open(cache, encoding="utf-8") as f:
                c = json.load(f)
            if c.get("sig") == json.loads(json.dumps(sig)):
                return c["items"], sig
        except (OSError, ValueError, KeyError):
            pass
        script = os.path.join(HERE, "taskbar_apps.ps1")
        p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
                           capture_output=True, timeout=90, creationflags=NO_WINDOW)
        items = json.loads(p.stdout.decode("utf-8-sig") or "[]")
        if isinstance(items, dict):
            items = [items]
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({"sig": sig, "items": items}, f)
        return items, sig

    def refresh(self):
        """Recarrega a lista se os atalhos fixados mudaram. Retorna True se mudou."""
        sig = self._signature()
        if sig == self.sig:
            return False
        try:
            items, sig = self._fetch()
        except Exception as e:  # noqa: BLE001
            log.warning("barra de tarefas: %s", e)
            return False
        blob = self._order()

        def pos(it):
            i = blob.find(it["file"].encode("utf-16-le")) if blob else -1
            return i if i >= 0 else 1 << 30

        apps = []
        for n, it in enumerate(sorted(items, key=pos)):
            label = re.split(r"[:꞉]", it.get("name", ""))[0].strip()
            apps.append({"id": "a%d" % n, "label": LABELS.get(label, label), "path": it["path"],
                         "exe": self._exe(it), "icon": "data:image/png;base64," + it["png"] if it.get("png") else None})
        self.apps, self.sig = apps, sig
        log.info("apps da barra de tarefas: %s", ", ".join(a["label"] for a in apps))
        return True

    def running(self):
        if time.time() - self._running_t < 3:
            return self._running
        names = set()
        for p in psutil.process_iter(["name"]):
            n = p.info.get("name")
            if n:
                names.add(n.lower())
        self._running = [a["id"] for a in self.apps if a["exe"] and a["exe"].lower() in names]
        self._running_t = time.time()
        return self._running

    def launch(self, aid):
        for a in self.apps:
            if a["id"] == aid:
                os.startfile(a["path"])
                return a["label"]
        return None

    def public(self):
        return [{"id": a["id"], "label": a["label"], "icon": a["icon"]} for a in self.apps]
