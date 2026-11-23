#!/usr/bin/env python3
"""Check the packs in packs/ and build the catalog raptaboard downloads.

    python3 scripts/build_catalog.py --check
    python3 scripts/build_catalog.py --tag v1 --out dist

`--check` only checks the packs (CI on every pull request). With `--tag`, it
also writes into `--out` every pack file as a release asset named
`<pack id>.<file>` and `catalog.json`, which lists each pack with its files'
download URLs (the release of that tag), sizes and SHA-256 checksums. The
release workflow then signs `catalog.json` (`catalog.json.sig`) and
publishes the lot as a GitHub release.

The catalog format (`format` 1) is read by raptaboard
(crates/app/src/content.rs there); change both together.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORMAT = 1
REPO = "tuffinmuffin/raptaboard-content"
KINDS = {"sounds", "plugin"}
REQUIRED = ["id", "name", "version", "kind", "min_app", "summary", "license", "credits"]
ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
SOUND_TYPES = {".mp3", ".wav", ".ogg", ".flac"}


class PackError(Exception):
    """A pack that's wrong, with what's wrong."""


def load_pack(folder: Path) -> dict:
    """The pack in `folder` (its pack.toml), checked, with its files' sizes
    and checksums under "files"."""
    toml = folder / "pack.toml"
    if not toml.is_file():
        raise PackError(f"{folder.name}: no pack.toml")
    try:
        pack = tomllib.loads(toml.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise PackError(f"{folder.name}/pack.toml: {e}") from e
    where = f"{folder.name}/pack.toml"
    for key in REQUIRED:
        if not isinstance(pack.get(key), str) or not pack[key].strip():
            raise PackError(f"{where}: needs {key}, a non-empty string")
    if pack["id"] != folder.name:
        raise PackError(f"{where}: id {pack['id']!r} must match its folder name")
    if not ID.match(pack["id"]):
        raise PackError(f"{where}: id must be lowercase letters, digits and dashes")
    if pack["kind"] not in KINDS:
        raise PackError(f"{where}: kind must be one of {sorted(KINDS)}")
    for key in ["version", "min_app"]:
        if not VERSION.match(pack[key]):
            raise PackError(f"{where}: {key} must be a version like 1.0.0")
    if not isinstance(pack.get("suggested", False), bool):
        raise PackError(f"{where}: suggested must be true or false")

    sounds = pack.get("sound", [])
    if pack["kind"] == "sounds" and not sounds:
        raise PackError(f"{where}: a sounds pack needs at least one [[sound]]")
    names: set[str] = set()
    for sound in sounds:
        name, file = sound.get("name"), sound.get("file")
        if not isinstance(name, str) or not name.strip() or not isinstance(file, str):
            raise PackError(f"{where}: each [[sound]] needs a name and a file")
        if name in names:
            raise PackError(f"{where}: two sounds are named {name!r}")
        names.add(name)
        if Path(file).suffix.lower() not in SOUND_TYPES:
            raise PackError(f"{where}: {file} isn't a sound file ({sorted(SOUND_TYPES)})")

    present = sorted(p.name for p in folder.iterdir() if p.name != "pack.toml")
    listed = sorted({s["file"] for s in sounds} | set(pack.get("files", [])))
    for name in present:
        if not (folder / name).is_file():
            raise PackError(f"{folder.name}/{name}: packs hold files only, no folders")
    if missing := sorted(set(listed) - set(present)):
        raise PackError(f"{where}: lists files that aren't there: {missing}")
    if extra := sorted(set(present) - set(listed)):
        raise PackError(f"{where}: has files it doesn't list (add them to files): {extra}")
    for name in listed:
        if not FILE.match(name):
            raise PackError(f"{where}: {name!r}: file names are letters, digits, . _ -")

    pack["files"] = [
        {
            "path": name,
            "size": (folder / name).stat().st_size,
            "sha256": hashlib.sha256((folder / name).read_bytes()).hexdigest(),
        }
        for name in listed
    ]
    return pack


def load_packs(packs: Path) -> list[dict]:
    """Every pack under `packs`, checked, in id order. Sound names must be
    unique across packs, since raptaboard lists them together."""
    folders = sorted(p for p in packs.iterdir() if p.is_dir()) if packs.is_dir() else []
    loaded = [load_pack(f) for f in folders]
    seen: dict[str, str] = {}
    for pack in loaded:
        for sound in pack.get("sound", []):
            if sound["name"] in seen:
                raise PackError(
                    f"sound {sound['name']!r} is in both {seen[sound['name']]} and {pack['id']}"
                )
            seen[sound["name"]] = pack["id"]
    return loaded


def asset_name(pack: dict, path: str) -> str:
    """The release asset a pack file is published as: `fan-clips.fire1.mp3`."""
    return f"{pack['id']}.{path}"


def catalog(packs: list[dict], tag: str, repo: str = REPO) -> dict:
    """The catalog for `packs` published as release `tag` of `repo`."""
    base = f"https://github.com/{repo}/releases/download/{tag}"
    out = []
    for pack in packs:
        entry = {key: pack[key] for key in REQUIRED}
        entry["suggested"] = pack.get("suggested", False)
        if pack.get("sound"):
            entry["sounds"] = [{"name": s["name"], "file": s["file"]} for s in pack["sound"]]
        entry["files"] = [
            {**f, "url": f"{base}/{asset_name(pack, f['path'])}"} for f in pack["files"]
        ]
        out.append(entry)
    return {"format": FORMAT, "release": tag, "packs": out}


def build(packs_dir: Path, out: Path, tag: str, repo: str = REPO) -> dict:
    """Write `out`: each pack file as its release asset, and catalog.json."""
    packs = load_packs(packs_dir)
    out.mkdir(parents=True, exist_ok=True)
    for pack in packs:
        for f in pack["files"]:
            shutil.copyfile(packs_dir / pack["id"] / f["path"], out / asset_name(pack, f["path"]))
    cat = catalog(packs, tag, repo)
    (out / "catalog.json").write_text(json.dumps(cat, indent=2) + "\n", encoding="utf-8")
    return cat


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only check the packs")
    parser.add_argument("--tag", help="the release tag the catalog points at, like v1")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument("--repo", default=REPO)
    args = parser.parse_args()
    try:
        if args.check:
            packs = load_packs(ROOT / "packs")
            print(f"{len(packs)} packs are fine: {', '.join(p['id'] for p in packs)}")
            return 0
        if not args.tag:
            parser.error("--tag is needed unless --check")
        cat = build(ROOT / "packs", args.out, args.tag, args.repo)
        print(f"catalog {args.tag}: {len(cat['packs'])} packs into {args.out}")
        return 0
    except PackError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
