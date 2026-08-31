from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path


REQ_RE = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)(?P<extras>\[[^]]+\])?==(?P<version>[^\s;]+)")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirements(path: Path, seen: set[Path] | None = None) -> list[tuple[str, str, str]]:
    seen = seen or set()
    resolved = path.resolve()
    if resolved in seen:
        return []
    seen.add(resolved)
    rows: list[tuple[str, str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r ") or line.startswith("--requirement "):
            child = line.split(maxsplit=1)[1]
            rows.extend(_requirements(path.parent / child, seen))
            continue
        match = REQ_RE.match(line)
        if not match:
            raise RuntimeError(f"unsupported locked requirement line: {path}:{raw}")
        rows.append((match.group("name"), match.group("version"), line.split(" --hash=", 1)[0]))
    dedup: dict[tuple[str, str], str] = {}
    for name, version, spec in rows:
        dedup[(_normalize(name), version)] = spec
    return [(name, version, dedup[(name, version)]) for name, version in sorted(dedup)]


def _wheel_identity(path: Path) -> tuple[str, str]:
    parts = path.name.split("-")
    if len(parts) < 2 or path.suffix != ".whl":
        raise RuntimeError(f"expected wheel file, got: {path.name}")
    return _normalize(parts[0]), parts[1]


def emit(lockfiles: list[Path]) -> str:
    requirements: dict[tuple[str, str], str] = {}
    for lockfile in lockfiles:
        for name, version, spec in _requirements(lockfile):
            requirements[(name, version)] = spec

    with tempfile.TemporaryDirectory(prefix="v3-lock-hashes-") as tmp:
        target = Path(tmp)
        for _, _, spec in requirements.values() if False else []:
            pass
        specs = list(requirements.values())
        cmd = [sys.executable, "-m", "pip", "download", "--disable-pip-version-check", "--no-deps", "--only-binary=:all:", "--dest", str(target), *specs]
        subprocess.run(cmd, check=True)

        wheel_hashes: dict[tuple[str, str], str] = {}
        for wheel in sorted(target.glob("*.whl")):
            identity = _wheel_identity(wheel)
            digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
            if identity in wheel_hashes and wheel_hashes[identity] != digest:
                raise RuntimeError(f"multiple wheel hashes resolved for {identity}")
            wheel_hashes[identity] = digest

    missing = sorted(set(requirements) - set(wheel_hashes))
    extra = sorted(set(wheel_hashes) - set(requirements))
    if missing or extra:
        raise RuntimeError(f"wheel/lock mismatch: missing={missing} extra={extra}")

    lines = []
    for identity in sorted(requirements):
        spec = requirements[identity]
        lines.append(f"{spec} --hash=sha256:{wheel_hashes[identity]}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("lockfiles", nargs="+", type=Path)
    args = parser.parse_args()
    print(emit(args.lockfiles), end="")


if __name__ == "__main__":
    main()
