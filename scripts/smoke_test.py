#!/usr/bin/env python3
"""Deployment smoke test: prove a running deployment actually works.

    python scripts/smoke_test.py                                  # local, default ports
    python scripts/smoke_test.py --api https://api.example.com    # deployed backend
    python scripts/smoke_test.py --api https://api.example.com \
                                --origin https://app.vercel.app   # + CORS from that origin
    python scripts/smoke_test.py --bundle apps/web/dist           # + scan the built bundle

Exits non-zero on the first failure. Stdlib only, so it runs anywhere Python does
— including from a CI step that has nothing installed.

What it checks:
  * health and readiness, and that readiness names every adapter;
  * the demo project exists and is seeded (idempotent auto-seed on an empty store);
  * both workflows reach their expected decision states;
  * re-running an analysis is idempotent (no gap inflation, stale set unchanged);
  * the impact graph is served for an analysed change;
  * CORS answers the real frontend origin and refuses an unknown one;
  * no secret, localhost URL, Windows path or CORS wildcard is in the bundle.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

TIMEOUT = 60
failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global checks
    checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(f"{name}{(': ' + detail) if detail else ''}")
    return ok


def request(url: str, method: str = "GET", body: dict | None = None, headers: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            raw = response.read().decode("utf-8", "replace")
            return response.status, dict(response.headers), (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, dict(exc.headers), json.loads(raw)
        except ValueError:
            return exc.code, dict(exc.headers), raw
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, {}, str(exc)


# ---------------------------------------------------------------------------


def smoke_api(api: str, origin: str | None, allow_live: bool = False) -> None:
    print(f"\nAPI {api}")

    status, _, body = request(f"{api}/api/health")
    if not check("health returns 200", status == 200, f"got {status} {body}"):
        return  # nothing else can pass
    check("health reports ok", isinstance(body, dict) and body.get("status") == "ok")

    status, _, ready = request(f"{api}/api/ready")
    check("readiness returns 200", status == 200, f"got {status}")
    if isinstance(ready, dict):
        check("readiness is true", ready.get("ready") is True, json.dumps(ready.get("checks", {})))
        adapters = ready.get("checks", {})
        for name in ("store", "mireye", "graph", "vector", "seeded"):
            check(f"readiness names '{name}'", name in adapters, str(adapters.get(name, "")))
        check("store is seeded", adapters.get("seeded") == "yes", str(adapters.get("seeded")))

    status, _, meta = request(f"{api}/api/meta")
    check("meta returns 200", status == 200)
    mireye_mode = "unknown"
    if isinstance(meta, dict):
        check("meta reports 34 Mireye fields", meta.get("mireye_field_count") == 34)
        check("safety disclaimer present", "not professional engineering approval" in meta.get("disclaimer", ""))
        mireye_mode = meta.get("services", {}).get("mireye", "unknown")
        print(f"        services: {json.dumps(meta.get('services', {}))}  demo_mode={meta.get('demo_mode')}")

    # Everything below sweeps every candidate site and analyses every change.
    # Against a live backend that is a per-field, per-location bill, so refuse to
    # start rather than discover the cost afterwards.
    if mireye_mode != "mock" and not allow_live:
        print(
            f"\n  ABORTED before any site analysis: the backend reports mireye='{mireye_mode}',"
            "\n  and this suite sweeps every site. Point it at a mock-mode backend, or pass"
            "\n  --i-understand-this-spends-credits to override."
        )
        check("backend is in mock mode before sweeping sites", False, f"mireye={mireye_mode}")
        return

    status, _, projects = request(f"{api}/api/projects")
    if not check("a demo project is present", status == 200 and bool(projects), f"got {status}"):
        return
    pid = projects[0]["id"]

    status, _, changes = request(f"{api}/api/projects/{pid}/changes")
    check("three change cases", status == 200 and len(changes or []) == 3, f"got {len(changes or [])}")
    by_tag = {c["equipment_tag"]: c["id"] for c in (changes or [])}

    expected = {
        "CH-01": "ENGINEER REVIEW",
        "CH-02": "FIRST-PASS CHECKS CLOSED",
        "PDU-3": "NEEDS INFORMATION",
    }
    for tag, want in expected.items():
        if tag not in by_tag:
            check(f"{tag} present", False)
            continue
        status, _, inv = request(f"{api}/api/projects/{pid}/changes/{by_tag[tag]}/analyze", "POST", {})
        got = inv.get("decision_state") if isinstance(inv, dict) else None
        check(f"{tag} reaches {want}", status == 200 and got == want, f"got {got}")

    # Idempotency: the whole point of the audited fixes.
    if "CH-01" in by_tag:
        _, _, gaps_before = request(f"{api}/api/projects/{pid}/gaps")
        _, _, first = request(f"{api}/api/projects/{pid}/changes/{by_tag['CH-01']}/analyze", "POST", {})
        _, _, second = request(f"{api}/api/projects/{pid}/changes/{by_tag['CH-01']}/analyze", "POST", {})
        _, _, gaps_after = request(f"{api}/api/projects/{pid}/gaps")
        check(
            "re-analysis keeps the stale-assumption set",
            isinstance(second, dict) and second.get("stale_assumption_ids") and
            sorted(second["stale_assumption_ids"]) == sorted(first.get("stale_assumption_ids", [])),
            f"{len(second.get('stale_assumption_ids', []) if isinstance(second, dict) else [])} stale",
        )
        check(
            "re-analysis does not multiply gaps",
            len(gaps_after or []) == len(gaps_before or []),
            f"{len(gaps_before or [])} -> {len(gaps_after or [])}",
        )
        status, _, graph = request(f"{api}/api/impact/{by_tag['CH-01']}")
        check(
            "impact graph served for an analysed change",
            status == 200 and isinstance(graph, dict) and len(graph.get("nodes", [])) > 1,
            f"{len(graph.get('nodes', [])) if isinstance(graph, dict) else 0} nodes",
        )

    status, _, _ = request(f"{api}/api/impact/chg_never_analysed")
    check("unanalysed change still 404s", status == 404, f"got {status}")

    status, _, _ = request(f"{api}/api/projects/prj_does_not_exist")
    check("unknown project 404s", status == 404, f"got {status}")

    # Site workflow, end to end.
    status, _, inv = request(f"{api}/api/projects/{pid}/investigations/site", "POST", {})
    ranking = inv.get("ranking") if isinstance(inv, dict) else None
    check("site investigation completes", status == 200 and isinstance(inv, dict) and inv.get("status") == "completed")
    check(
        "five candidates ranked with a leader",
        bool(ranking) and len(ranking.get("scores", [])) == 5 and ranking["scores"][0].get("rank") == 1,
    )
    if ranking:
        top = ranking["scores"][0]
        print(f"        leader: {top['site_name']} {top['overall_score']} ({top['risk_level']})")

    # CORS: the frontend origin must be allowed, an unknown one must not be.
    if origin:
        _, headers, _ = request(f"{api}/api/health", headers={"Origin": origin})
        allowed = headers.get("access-control-allow-origin") or headers.get("Access-Control-Allow-Origin")
        check(f"CORS allows {origin}", allowed == origin, f"got {allowed!r}")
        check("CORS is not a wildcard", allowed != "*", f"got {allowed!r}")
        rogue = "https://not-our-frontend.example"
        _, headers, _ = request(f"{api}/api/health", headers={"Origin": rogue})
        rogue_allowed = headers.get("access-control-allow-origin") or headers.get("Access-Control-Allow-Origin")
        check("CORS refuses an unknown origin", rogue_allowed in (None, ""), f"got {rogue_allowed!r}")


# ---------------------------------------------------------------------------

#: Things that must never reach a shipped bundle.
FORBIDDEN = [
    (r"https?://localhost", "localhost URL"),
    (r"https?://127\.0\.0\.1", "loopback URL"),
    (r"[A-Za-z]:\\\\[A-Za-z]", "Windows filesystem path"),
    (r"sk-[A-Za-z0-9]{16,}", "OpenAI-style secret"),
    (r"sk-ant-[A-Za-z0-9\-]{16,}", "Anthropic secret"),
    (r"postgres(?:ql)?://[^\s\"']*:[^\s\"'@]+@", "database URL with credentials"),
    (r"neo4j\+?s?://[^\s\"']*:[^\s\"'@]+@", "Neo4j URL with credentials"),
    (r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}", "JWT / service key"),
    (r"MIREYE_API_KEY", "Mireye key name"),
    (r"NEO4J_PASSWORD", "Neo4j password name"),
    (r"SUPABASE_SERVICE_KEY", "Supabase service key name"),
    (r"Access-Control-Allow-Origin\s*[:=]\s*[\"']\*", "CORS wildcard"),
]


def smoke_bundle(bundle: Path, expect_base: str | None) -> None:
    print(f"\nBundle {bundle}")
    if not check("bundle directory exists", bundle.is_dir(), str(bundle)):
        return
    files = [p for p in bundle.rglob("*") if p.suffix in (".js", ".css", ".html", ".map")]
    check("bundle contains build output", bool(files), f"{len(files)} files")
    text = "\n".join(p.read_text("utf-8", "replace") for p in files)

    for pattern, label in FORBIDDEN:
        hits = re.findall(pattern, text)
        check(f"no {label} in the bundle", not hits, f"{len(hits)} hit(s): {hits[:2]}")

    if expect_base:
        check(f"bundle targets {expect_base}", expect_base.rstrip("/") in text)
        host = urlparse(expect_base).hostname or ""
        check("bundle API origin is not local", host not in ("localhost", "127.0.0.1", "0.0.0.0"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="API origin to test")
    parser.add_argument("--origin", default=None, help="frontend origin to test CORS with")
    parser.add_argument("--bundle", default=None, help="path to the built frontend (e.g. apps/web/dist)")
    parser.add_argument(
        "--expect-base",
        default=None,
        help="API origin the bundle must have been built against (defaults to --api when it is not local)",
    )
    parser.add_argument("--skip-api", action="store_true")
    parser.add_argument(
        "--i-understand-this-spends-credits",
        dest="allow_live",
        action="store_true",
        help="permit the site sweep against a non-mock backend (bills provider credits)",
    )
    args = parser.parse_args()

    print("Deployment smoke test")
    if not args.skip_api:
        smoke_api(args.api.rstrip("/"), args.origin, args.allow_live)
    if args.bundle:
        expected = args.expect_base
        if expected is None and (urlparse(args.api).hostname or "") not in ("localhost", "127.0.0.1"):
            expected = args.api
        smoke_bundle(Path(args.bundle), expected)

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("Smoke test passed.")


if __name__ == "__main__":
    main()
