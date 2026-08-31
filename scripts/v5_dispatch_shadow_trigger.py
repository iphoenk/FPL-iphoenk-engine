from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def request_json(url: str, *, token: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def dispatch(repo: str, branch: str, token: str, reasons: list[str]) -> dict:
    path = "config/v5_shadow_trigger.json"
    encoded_path = urllib.parse.quote(path, safe="/")
    base = f"https://api.github.com/repos/{repo}/contents/{encoded_path}"
    for attempt in range(1, 4):
        current = request_json(f"{base}?ref={urllib.parse.quote(branch, safe='')}", token=token)
        content = json.loads(base64.b64decode(current["content"]).decode("utf-8"))
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        run_id = os.environ.get("GITHUB_RUN_ID", "local")
        content["requested_cycle"] = f"scheduler-{run_id}-{int(time.time())}"
        content["requested_at"] = now
        content["scheduler_reasons"] = reasons
        content["scheduler_source"] = "default-branch-thin-dispatcher"
        payload = {
            "message": f"chore(v5): dispatch governed shadow evidence [{','.join(reasons) or 'manual'}]",
            "content": base64.b64encode((json.dumps(content, indent=2, ensure_ascii=False) + "\n").encode("utf-8")).decode("ascii"),
            "sha": current["sha"],
            "branch": branch,
        }
        try:
            return request_json(base, token=token, method="PUT", payload=payload)
        except urllib.error.HTTPError as exc:
            if exc.code not in {409, 422} or attempt >= 3:
                raise
            time.sleep(attempt)
    raise RuntimeError("unable to dispatch V5 shadow trigger")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reasons", default="")
    parser.add_argument("--branch", default=os.environ.get("V5_CODE_BRANCH", "v5-unified-engine"))
    args = parser.parse_args()
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    reasons = [row for row in args.reasons.split(",") if row]
    result = dispatch(repo, args.branch, token, reasons)
    print(json.dumps({"commit": (result.get("commit") or {}).get("sha"), "branch": args.branch, "reasons": reasons}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
