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

A pack holds sections, mixed as needed: [[sound]] (name and file; a
built-in sound's name replaces it in raptaboard), [[image]], [[field]],
[[plugin]] and [[layout]] (file, optional name). `kind` is an optional label.

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
REQUIRED = ["id", "name", "version", "min_app", "summary", "license", "credits"]
# Each section a pack may have, the catalog key it becomes, and the file
# types it takes. A sound has a name; the others may (else the file's).
SECTIONS = {
    "sound": ("sounds", {".mp3", ".wav", ".ogg", ".flac"}),
    "image": ("images", {".png", ".jpg", ".jpeg", ".svg"}),
    "field": ("fields", {".json"}),
    "plugin": ("plugins", {".wasm"}),
    "layout": ("layouts", {".json"}),
}
ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


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
    if "kind" in pack and not isinstance(pack["kind"], str):
        raise PackError(f"{where}: kind is a word saying what it holds, if given")
    for key in ["version", "min_app"]:
        if not VERSION.match(pack[key]):
            raise PackError(f"{where}: {key} must be a version like 1.0.0")
    if not isinstance(pack.get("suggested", False), bool):
        raise PackError(f"{where}: suggested must be true or false")

    if not any(pack.get(section) for section in SECTIONS):
        raise PackError(f"{where}: needs at least one of " + ", ".join(f"[[{s}]]" for s in SECTIONS))
    used: set[str] = set()
    for section, (_, types) in SECTIONS.items():
        names: set[str] = set()
        for item in pack.get(section, []):
            name, file = item.get("name"), item.get("file")
            if not isinstance(file, str):
                raise PackError(f"{where}: each [[{section}]] needs a file")
            if section == "sound" and (not isinstance(name, str) or not name.strip()):
                raise PackError(f"{where}: each [[sound]] needs a name")
            if name is not None and not isinstance(name, str):
                raise PackError(f"{where}: a [[{section}]]'s name is text")
            label = name or file
            if label in names:
                raise PackError(f"{where}: two {section}s are named {label!r}")
            names.add(label)
            if Path(file).suffix.lower() not in types:
                raise PackError(f"{where}: {file} isn't a {section} file ({sorted(types)})")
            used.add(file)

    present = sorted(p.name for p in folder.iterdir() if p.name != "pack.toml")
    listed = sorted(used | set(pack.get("files", [])))
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
    """Every pack under `packs`, checked, in id order. Two packs may give a
    sound the same name (or a built-in one's): raptaboard layers them, the
    newest install winning."""
    folders = sorted(p for p in packs.iterdir() if p.is_dir()) if packs.is_dir() else []
    return [load_pack(f) for f in folders]


def asset_name(pack: dict, path: str) -> str:
    """The release asset a pack file is published as: `fan-clips.fire1.mp3`."""
    return f"{pack['id']}.{path}"


def catalog(packs: list[dict], tag: str, repo: str = REPO) -> dict:
    """The catalog for `packs` published as release `tag` of `repo`."""
    base = f"https://github.com/{repo}/releases/download/{tag}"
    out = []
    for pack in packs:
        entry = {key: pack[key] for key in REQUIRED}
        if pack.get("kind"):
            entry["kind"] = pack["kind"]
        entry["suggested"] = pack.get("suggested", False)
        for section, (key, _) in SECTIONS.items():
            items = [
                {k: item[k] for k in ("name", "file") if k in item}
                for item in pack.get(section, [])
            ]
            if items:
                entry[key] = items
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
