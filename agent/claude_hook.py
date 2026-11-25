#!/usr/bin/env python3
"""
Hook "PermissionRequest" do Claude Code -> Painel PC.

Mostra o pedido de permissao no tablet e devolve Permitir/Negar.
Se o agente nao estiver rodando, o tablet estiver desconectado ou ninguem
responder a tempo, o hook nao decide nada e o Claude Code mostra o pedido
normal no computador.
"""
import json
import sys
import urllib.request

URL = "http://127.0.0.1:8765/approval"


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    payload = {k: data.get(k) for k in ("tool_name", "tool_input", "cwd", "session_id")}
    payload["agent"] = "Claude Code"
    try:
        req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            decision = json.load(r).get("decision")
    except Exception:  # agente fora do ar: segue o fluxo normal
        return 0
    if decision == "allow":
        out = {"behavior": "allow"}
    elif decision == "deny":
        out = {"behavior": "deny", "message": "Negado pelo Painel PC (tablet)."}
    else:
        return 0
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": out}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
