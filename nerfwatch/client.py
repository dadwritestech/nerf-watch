"""Minimal OpenAI-compatible chat client (stdlib only)."""
import json
import time
import urllib.error
import urllib.request


class ChatError(RuntimeError):
    pass


def chat(base_url, model, prompt, api_key=None, max_tokens=256, temperature=0.0, seed=1234,
         system_prompt=None, extra_body=None, timeout=300, retries=2):
    msgs = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    msgs.append({"role": "user", "content": prompt})
    body = {"model": model, "messages": msgs, "max_tokens": max_tokens,
            "temperature": temperature, "seed": seed}
    body.update(extra_body or {})
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = base_url.rstrip("/") + "/chat/completions"
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            latency = time.perf_counter() - t0
            choice = data["choices"][0]
            usage = data.get("usage") or {}
            return {"text": choice["message"].get("content") or "",
                    "finish_reason": choice.get("finish_reason"),
                    "latency_s": round(latency, 3),
                    "completion_tokens": usage.get("completion_tokens"),
                    "prompt_tokens": usage.get("prompt_tokens")}
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
            last = e
            if isinstance(e, urllib.error.HTTPError) and e.code in (400, 401, 403, 404):
                break
            time.sleep(2 * (attempt + 1))
    raise ChatError(f"{url} model={model}: {last}")
