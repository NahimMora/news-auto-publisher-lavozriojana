"""Gates locales de seguridad para CI: dry-run, artefactos y secretos obvios."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_TRACKED_PREFIXES = ("data/", "logs/", "output/", "FotosLVR/")
SECRET_PATTERNS = {
    "OpenAI key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "Meta token": re.compile(r"\bEAA[A-Za-z0-9]{30,}\b"),
    "AWS/R2 access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def verify_dry_run(path: Path) -> list[str]:
    errors: list[str] = []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "success":
        errors.append(f"dry-run status={payload.get('status')!r}")
    if payload.get("details", {}).get("production_calls") is not False:
        errors.append("dry-run no declaró production_calls=false")
    return errors


def verify_tracked_paths() -> list[str]:
    tracked = _git("ls-files").splitlines()
    errors = [
        f"Artefacto operativo versionado: {name}"
        for name in tracked
        if name == ".env" or name.startswith(FORBIDDEN_TRACKED_PREFIXES)
    ]
    return errors


def verify_secrets(base: str) -> list[str]:
    try:
        names = _git("diff", "--name-only", f"{base}...HEAD").splitlines()
    except subprocess.CalledProcessError:
        names = _git("ls-files").splitlines()
    errors: list[str] = []
    for name in names:
        path = ROOT / name
        if not path.is_file() or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".ico"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"Posible {label} en {name}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run-json", type=Path)
    parser.add_argument("--base", default="origin/main")
    args = parser.parse_args(argv)
    errors = verify_tracked_paths()
    errors.extend(verify_secrets(args.base))
    if args.dry_run_json:
        errors.extend(verify_dry_run(args.dry_run_json))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("CI safety: production_calls=false, sin artefactos operativos ni secretos obvios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
