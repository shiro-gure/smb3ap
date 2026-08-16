#!/usr/bin/env python3
"""Build the shippable `smb3.apworld` from the tracked `worlds/smb3/` sources.

The `.apworld` is a zip whose single top-level entry is `smb3/`. We ship the world
Python + `data/` (the committed base patches), and STRIP the dev-only bits that never
belong in a release: the `test/` suite, the `patch/` tooling (this script, gen_panels,
make_hub, …), and any `__pycache__`.

The base patches (`data/*.bsdiff4`) are precomputed and committed, so this build needs
NO ROM and NO assembler — it just stages and zips. That's what lets CI produce a release
artifact reproducibly.

Usage:
    python3 worlds/smb3/patch/build_apworld.py [--out DIR]

Prints the path of the built file. Deterministic: files are added in sorted order with a
fixed timestamp so the same sources produce a byte-identical zip.
"""
from __future__ import annotations

import argparse
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD_DIR = os.path.normpath(os.path.join(HERE, ".."))          # worlds/smb3
WORLD_NAME = os.path.basename(WORLD_DIR)                        # "smb3"

# Directory names anywhere in the tree whose entire subtree is excluded from the build.
_EXCLUDE_DIRS = {"test", "patch", "__pycache__"}
# Fixed DOS timestamp (1980-01-01) so the zip is reproducible run-to-run.
_FIXED_DATE = (1980, 1, 1, 0, 0, 0)


def _shipped_files() -> list[str]:
    """Repo-relative-to-WORLD_DIR paths of every file that ships, sorted."""
    out: list[str] = []
    for root, dirs, files in os.walk(WORLD_DIR):
        # prune excluded directories in place
        dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
        for name in files:
            if name.endswith((".pyc", ".pyo")):
                continue
            rel = os.path.relpath(os.path.join(root, name), WORLD_DIR)
            out.append(rel)
    return sorted(out)


def build(out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{WORLD_NAME}.apworld")
    files = _shipped_files()
    if not any(f == "archipelago.json" for f in files):
        raise SystemExit("ERROR: archipelago.json missing — not a valid apworld source")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            # Top-level entry must be "smb3/…" so AP recognizes the world.
            arcname = f"{WORLD_NAME}/{rel}"
            info = zipfile.ZipInfo(arcname, date_time=_FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(os.path.join(WORLD_DIR, rel), "rb") as f:
                zf.writestr(info, f.read())
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "..", "..", "..", "dist"),
                    help="output directory (default: <repo>/dist)")
    args = ap.parse_args()
    path = build(os.path.abspath(args.out))
    size = os.path.getsize(path)
    print(f"built {path} ({size} bytes)")
    # Also print the shipped file list so CI logs show exactly what went in.
    for rel in _shipped_files():
        print(f"  + {WORLD_NAME}/{rel}")


if __name__ == "__main__":
    main()
