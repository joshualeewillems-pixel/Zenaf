from __future__ import annotations

import json
import sys


def main() -> int:
    path = r"C:\Users\philc\.cursor\projects\c-Users-philc-OneDrive-Desktop-Atria\agent-tools\06b3446a-e940-48e9-aa55-5065b66ff524.txt"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    provider_default_models = data.get("provider_default_models") or {}
    providers = ["ollama", "openai", "anthropic", "google", "xai"]

    print("PROVIDER_DEFAULT_MODELS:", provider_default_models)
    print()
    print("RECOMMENDATIONS:", json.dumps(data.get("recommendations") or {}, indent=2))
    print()
    print("CATEGORY_BEST:", json.dumps(data.get("category_best") or {}, indent=2))
    print()

    def _ascii_safe(t: str) -> str:
        # PowerShell defaults to a legacy code page; keep the report readable (no emojis).
        return t.encode("ascii", errors="backslashreplace").decode("ascii")

    def first_n_preview(s: object, n: int = 210) -> str:
        if not s:
            return "(none)"
        t = str(s).replace("\n", "\\n")
        t2 = (t[:n] + "…") if len(t) > n else t
        return _ascii_safe(t2)

    for batch in data.get("prompts") or []:
        pid = batch.get("prompt_id")
        print(f"PROMPT {pid}")
        rows = batch.get("results") or []
        # Sort by total_score desc, latency asc
        def _k(r):
            tot = int(r.get("total_score") or 0)
            lat = r.get("latency_ms")
            if lat is None:
                lat = 1e18
            return (-tot, float(lat))

        rows_sorted = sorted(rows, key=_k)
        for r in rows_sorted:
            prov = r.get("provider")
            model = r.get("model")
            ok = r.get("ok")
            tot = int(r.get("total_score") or 0)
            g = int(r.get("grounding_score") or 0)
            s = int(r.get("structure_score") or 0)
            sp = int(r.get("specificity_score") or 0)
            c = int(r.get("constraint_obedience_score") or 0)
            u = int(r.get("usefulness_score") or 0)
            lat = r.get("latency_ms")
            err = r.get("error")
            preview = first_n_preview(r.get("output_preview"))
            suffix = ""
            if err:
                suffix = f" error='{str(err)[:120]}…'"
            print(
                f"- {prov}/{model}: ok={ok} total={tot} (g={g},s={s},sp={sp},c={c},u={u}) latency_ms={lat} preview='{preview}'{suffix}"
            )
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

