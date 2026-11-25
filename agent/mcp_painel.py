#!/usr/bin/env python3
"""
Servidor MCP "painel": as "maos" do Jarvis no PC.

O Claude Code o inicia (stdio, JSON-RPC 2.0, uma mensagem por linha). Ele nao executa nada
sozinho: cada ferramenta e repassada ao agente do painel (painel_agent.py) por
http://127.0.0.1:<porta>/jarvis/tool, autenticada com o token que o agente grava em data\\agent_token.

Usa so a biblioteca padrao, importada ANTES de ler o stdin: no Windows, carregar DLLs nativas
enquanto uma leitura do stdin esta pendente pode travar o processo.
"""
import http.client  # noqa: F401  (carrega tudo agora; ver docstring)
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")

TOOLS = [
    {"name": "status_pc", "description": "Uso atual de CPU, GPU, RAM e disco do PC.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "processos", "description": "Programas que mais usam o PC agora (como o Gerenciador de Tarefas).",
     "inputSchema": {"type": "object", "properties": {
         "quantidade": {"type": "integer", "description": "quantos listar (1 a 10)", "default": 5},
         "ordenar_por": {"type": "string", "enum": ["cpu", "memoria"], "default": "cpu"}}}},
    {"name": "lista_apps", "description": "Apps fixados na barra de tarefas do Windows e se estão abertos.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "abrir_app", "description": "Abre um app pelo nome (os da barra de tarefas, ou calculadora, "
                                         "bloco de notas, explorador, paint, terminal, configurações).",
     "inputSchema": {"type": "object", "required": ["nome"], "properties": {
         "nome": {"type": "string", "description": "nome do app, ex.: Discord, Chrome, VS Code, calculadora"}}}},
    {"name": "fechar_app", "description": "Fecha um app aberto (como clicar no X). Pede confirmação no tablet.",
     "inputSchema": {"type": "object", "required": ["nome"], "properties": {"nome": {"type": "string"}}}},
    {"name": "midia", "description": "Controla a música/vídeo tocando no PC ou diz o que está tocando.",
     "inputSchema": {"type": "object", "required": ["acao"], "properties": {
         "acao": {"type": "string", "enum": ["play_pause", "proxima", "anterior", "estado"]}}}},
    {"name": "volume", "description": "Volume do PC: aumentar, diminuir, alternar mudo ou ver o nível atual.",
     "inputSchema": {"type": "object", "required": ["acao"], "properties": {
         "acao": {"type": "string", "enum": ["aumentar", "diminuir", "mudo", "estado"]},
         "passos": {"type": "integer", "description": "cada passo = 2% (padrão 3)", "default": 3}}}},
    {"name": "recorte_tela", "description": "Abre a ferramenta de recorte de tela do Windows (Win+Shift+S).",
     "inputSchema": {"type": "object", "properties": {}}},
]


def agent_port():
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8-sig") as f:
            return int(json.load(f).get("http_port", 8765))
    except (OSError, ValueError):
        return 8765


def call_agent(tool, args):
    try:
        with open(os.path.join(DATA, "agent_token"), encoding="ascii") as f:
            token = f.read().strip()
    except OSError:
        return False, "O agente do painel não está rodando."
    req = urllib.request.Request("http://127.0.0.1:%d/jarvis/tool" % agent_port(),
                                 data=json.dumps({"tool": tool, "args": args}).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "X-Painel-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.load(r)
        return bool(res.get("ok")), res.get("text") or ""
    except Exception as e:  # noqa: BLE001
        return False, "Não consegui falar com o agente do painel (%s)." % type(e).__name__


def reply(id_, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    names = {t["name"] for t in TOOLS}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method, id_ = msg.get("method"), msg.get("id")
        if id_ is None:
            continue  # notificacoes (ex.: notifications/initialized) nao tem resposta
        if method == "initialize":
            reply(id_, {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2025-06-18"),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "painel", "version": "1.0"}})
        elif method == "tools/list":
            reply(id_, {"tools": TOOLS})
        elif method == "tools/call":
            p = msg.get("params") or {}
            if p.get("name") not in names:
                reply(id_, error={"code": -32602, "message": "ferramenta desconhecida"})
                continue
            ok, text = call_agent(p["name"], p.get("arguments") or {})
            reply(id_, {"content": [{"type": "text", "text": text}], "isError": not ok})
        elif method == "ping":
            reply(id_, {})
        else:
            reply(id_, error={"code": -32601, "message": "método não suportado"})


if __name__ == "__main__":
    main()
