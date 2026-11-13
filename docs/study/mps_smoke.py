"""Real briefings on Where MPs Stand's bundled sample data: one JSON line per question (timings, usage, checks)."""
import json
import sys
import time

import anthropic
import duckdb
import fastapi
from hansard.config import load_settings
from hansard.rag.pipeline import AskRequest, Pipeline

questions = sys.argv[1:]
p = Pipeline(load_settings())
print(json.dumps({"anthropic": anthropic.__version__, "duckdb": duckdb.__version__, "fastapi": fastapi.__version__}))
for q in questions:
    t0 = time.monotonic(); first = None; out = {}; n_text = 0
    try:
        for ev in p.run(AskRequest(question=q)):
            if ev["type"] == "text":
                n_text += len(ev["text"])
                first = first or time.monotonic() - t0
            elif ev["type"] in ("plan", "sources", "final", "error"):
                out[ev["type"]] = ev
    except Exception as exc:
        out["raised"] = f"{type(exc).__name__}: {exc}"[:300]
    f = out.get("final") or {}; a = f.get("answer") or {}
    print(json.dumps({
        "question": q, "raised": out.get("raised"), "error": (out.get("error") or {}).get("message"),
        "parser": (out.get("plan") or {}).get("plan", {}).get("parser"), "parse_usage": (out.get("plan") or {}).get("usage"),
        "sources": len((out.get("sources") or {}).get("sources") or []),
        "first_token_s": round(first, 2) if first else None, "total_s": round(time.monotonic() - t0, 2),
        "model": f.get("model"), "stop_reason": f.get("stop_reason"), "usage": f.get("usage"),
        "chars": n_text, "no_records": a.get("no_records"),
        **{k: a.get(k) for k in ("citations_total", "citations_invalid", "grounded_ratio", "unsupported_segments",
                                 "loaded_words", "quotes_total", "quotes_unverified")},
    }))
