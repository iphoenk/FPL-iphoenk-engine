from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


REQ_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)(?P<extras>\[[^]]+\])?==(?P<version>[^\s;]+)(?P<rest>.*)$"
)
HASH_RE = re.compile(r"--hash=sha256:(?P<digest>[0-9a-f]{64})(?:\s|$)")


@dataclass(frozen=True)
class LockedRequirement:
    name: str
    version: str
    hashes: tuple[str, ...]
    source: str


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def validate_lock(path: Path, seen: set[Path] | None = None) -> list[LockedRequirement]:
    seen = seen or set()
    resolved = path.resolve()
    if resolved in seen:
        return []
    seen.add(resolved)

    requirements: list[LockedRequirement] = []
    require_hashes = False
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "--require-hashes":
            require_hashes = True
            continue
        if line.startswith("-r ") or line.startswith("--requirement "):
            child = path.parent / line.split(maxsplit=1)[1]
            if not child.is_file():
                raise RuntimeError(f"missing nested lockfile: {path}:{line_no}:{child}")
            requirements.extend(validate_lock(child, seen))
            continue
        if line.startswith("-"):
            raise RuntimeError(f"unsupported dependency option: {path}:{line_no}:{line}")
        if ";" in line or " @ " in line or "://" in line or line.startswith(("git+", "hg+", "svn+", "bzr+")):
            raise RuntimeError(f"non-deterministic dependency source forbidden: {path}:{line_no}:{line}")
        match = REQ_RE.match(line)
        if not match:
            raise RuntimeError(f"dependency must use exact == pin: {path}:{line_no}:{line}")
        rest = match.group("rest") or ""
        hashes = tuple(sorted(set(HASH_RE.findall(rest))))
        cleaned = HASH_RE.sub("", rest).strip()
        if cleaned:
            raise RuntimeError(f"unsupported trailing requirement tokens: {path}:{line_no}:{cleaned}")
        if not hashes:
            raise RuntimeError(f"dependency hash missing: {path}:{line_no}:{line}")
        requirements.append(
            LockedRequirement(
                name=_normalize(match.group("name")),
                version=match.group("version"),
                hashes=hashes,
                source=f"{path}:{line_no}",
            )
        )

    if not require_hashes:
        raise RuntimeError(f"lockfile must enable --require-hashes: {path}")
    return requirements


def validate_lock_set(paths: list[Path]) -> dict[str, object]:
    rows: list[LockedRequirement] = []
    for path in paths:
        rows.extend(validate_lock(path, set()))

    canonical: dict[str, LockedRequirement] = {}
    for row in rows:
        previous = canonical.get(row.name)
        if previous is not None and (previous.version != row.version or previous.hashes != row.hashes):
            raise RuntimeError(
                f"dependency lock conflict for {row.name}: "
                f"{previous.version}/{previous.hashes} vs {row.version}/{row.hashes}"
            )
        canonical[row.name] = row

    if not canonical:
        raise RuntimeError("dependency lock set is empty")
    return {
        "status": "PASS",
        "lockfiles": [str(path) for path in paths],
        "unique_requirements": len(canonical),
        "all_exact_pins": True,
        "all_sha256_hashed": True,
        "require_hashes_enabled": True,
        "direct_url_or_vcs_sources": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("lockfiles", nargs="+", type=Path)
    args = parser.parse_args()
    print(validate_lock_set(args.lockfiles))


if __name__ == "__main__":
    main()
