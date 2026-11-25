#!/usr/bin/env python3
"""
Status line do Claude Code que tambem guarda os limites de uso (rate_limits)
para o Painel PC. O Claude Code envia esse JSON so para assinantes Pro/Max,
depois da primeira resposta da sessao.
"""
import json
import os
import sys
import time

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "claude_rate_limits.json")


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    rl = data.get("rate_limits") or {}
    if rl:
        try:
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            tmp = CACHE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"saved": time.time(), "rate_limits": rl}, f)
            os.replace(tmp, CACHE)
        except OSError:
            pass
    model = ((data.get("model") or {}).get("display_name")) or ""
    parts = [model] if model else []
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        w = rl.get(key) or {}
        if w.get("used_percentage") is not None:
            parts.append("%s %d%%" % (label, round(w["used_percentage"])))
    print(" · ".join(parts))


if __name__ == "__main__":
    main()
