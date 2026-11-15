"""Probe: xAI X Search through OpenRouter (native web plugin + x_search). Key from env, never printed."""
import json, os, sys, urllib.request

prompt = sys.argv[1]
out = sys.argv[2]
from_date = sys.argv[3] if len(sys.argv) > 3 else "2026-01-01"
body = {
    "model": "x-ai/grok-4.3",
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": 3000,
    "plugins": [{"id": "web", "engine": "native", "max_results": 10,
                 "x_search": {"from_date": from_date}}],
}
req = urllib.request.Request(
    "https://openrouter.ai/api/v1/chat/completions",
    data=json.dumps(body).encode(),
    headers={"Authorization": "Bearer " + os.environ["RESEARCH_LLM_API_KEY"], "Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=300) as r:
    data = json.load(r)
json.dump(data, open(out, "w"), ensure_ascii=False, indent=1)
msg = data["choices"][0]["message"]
anns = msg.get("annotations") or []
print("model:", data.get("model"), "| usage:", json.dumps(data.get("usage"))[:400])
print("citations:", len(anns), "| x.com:", sum("x.com" in a.get("url_citation", {}).get("url", "") for a in anns))
print(msg.get("content", "")[:6000])
