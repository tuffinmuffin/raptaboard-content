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

A pack's files may also come from another repository's GitHub release
([[source]]: `repo`, `tag` and the `files` it takes): each is downloaded
(kept in `--cache`), checked against that release's `SHA256SUMS`, checked
like a file of the pack's own, and listed with its URL there. A tag with a
`-` (`v3-pre.1`) builds a pre-release catalog, which may use pre-release
sources (`v0.1.0-pre.2`); a release catalog (`v3`) may not.

A pack holds sections, mixed as needed: [[sound]] (name and file; a
built-in sound's name replaces it in raptaboard), [[image]], [[field]],
[[plugin]] and [[layout]] (file, optional name). `kind` is an optional label.

A [[plugin]]'s file is its WebAssembly component (`alerts.wasm`); its
manifest, raptaboard's plugin.toml, sits beside it named for it
(`alerts.toml`). The catalog gives each plugin its manifest's name and the
permissions it asks for, which raptaboard shows before installing and holds
the plugin to.

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
import urllib.request
from collections.abc import Callable
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
# What a plugin's manifest may ask for (raptaboard's plugin.toml [permissions]).
PERMISSIONS = ["publish", "sound", "background", "storage"]
# Another repository's release a pack takes files from.
SOURCE_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SOURCE_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# Where downloaded source files are kept between runs.
CACHE = ROOT / ".cache"
# The largest file downloaded (raptaboard's own limit for a pack file).
DOWNLOAD_LIMIT = 200 << 20

# Reads a URL's bytes: the network in the scripts, a stand-in in tests.
Fetch = Callable[[str], bytes]


class PackError(Exception):
    """A pack that's wrong, with what's wrong."""


def http_get(url: str) -> bytes:
    """`url`'s bytes, at most DOWNLOAD_LIMIT."""
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read(DOWNLOAD_LIMIT + 1)
    if len(data) > DOWNLOAD_LIMIT:
        raise PackError(f"{url}: over {DOWNLOAD_LIMIT >> 20} MB")
    return data


def is_prerelease(tag: str) -> bool:
    """Whether `tag` names a pre-release: it has a `-` (`v0.1.0-pre.2`)."""
    return "-" in tag


def release_url(repo: str, tag: str, name: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{name}"


def sums(text: str) -> dict[str, str]:
    """A `SHA256SUMS` file (`sha256sum`'s output): each file's checksum."""
    out = {}
    for line in text.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            out[parts[1].lstrip("*").strip()] = parts[0].lower()
    return out


def fetch_source(source: dict, where: str, fetch: Fetch, cache: Path) -> dict[str, tuple[Path, str]]:
    """A [[source]]'s files, downloaded (or found in `cache`) and checked
    against its release's SHA256SUMS: each file's name, where it is now and
    its URL."""
    repo, tag, files = source.get("repo"), source.get("tag"), source.get("files")
    if not isinstance(repo, str) or not SOURCE_REPO.match(repo):
        raise PackError(f"{where}: a [[source]]'s repo is owner/name")
    if not isinstance(tag, str) or not SOURCE_TAG.match(tag):
        raise PackError(f"{where}: a [[source]]'s tag is a release tag, like v1.0.0")
    if not isinstance(files, list) or not files or not all(isinstance(f, str) for f in files):
        raise PackError(f"{where}: a [[source]] lists the files it takes, as text")
    try:
        listed = sums(fetch(release_url(repo, tag, "SHA256SUMS")).decode("utf-8"))
    except PackError:
        raise
    except Exception as e:
        raise PackError(f"{where}: {repo} {tag}: no SHA256SUMS ({e})") from e
    out = {}
    for name in files:
        if not FILE.match(name):
            raise PackError(f"{where}: {name!r}: file names are letters, digits, . _ -")
        want = listed.get(name)
        if want is None:
            raise PackError(f"{where}: {repo} {tag} has no {name} in its SHA256SUMS")
        path = cache / repo.replace("/", "_") / tag / name
        if not (path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == want):
            try:
                data = fetch(release_url(repo, tag, name))
            except PackError:
                raise
            except Exception as e:
                raise PackError(f"{where}: {repo} {tag}: couldn't download {name} ({e})") from e
            if hashlib.sha256(data).hexdigest() != want:
                raise PackError(f"{where}: {repo} {tag}: {name} doesn't match its SHA256SUMS")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        out[name] = (path, release_url(repo, tag, name))
    return out


def plugin_manifest(
    paths: dict[str, Path], folder: Path, file: str, where: str
) -> tuple[str, str, list[str]]:
    """The manifest beside a pack's plugin `file` (`alerts.wasm` →
    `alerts.toml`), from the pack's files (`paths`, by name): its file name,
    the plugin's name and the permissions it asks for."""
    manifest = Path(file).with_suffix(".toml").name
    path = paths.get(manifest)
    if path is None:
        raise PackError(f"{where}: plugin {file} needs its manifest beside it, {manifest}")
    try:
        m = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise PackError(f"{folder.name}/{manifest}: {e}") from e
    name = m.get("name")
    if not isinstance(name, str) or not ID.match(name):
        raise PackError(f"{folder.name}/{manifest}: needs name, lowercase letters, digits and dashes")
    if not isinstance(m.get("api"), str):
        raise PackError(f"{folder.name}/{manifest}: needs api, the plugin interface version")
    asked = m.get("permissions", {})
    if not isinstance(asked, dict):
        raise PackError(f"{folder.name}/{manifest}: [permissions] is a table")
    for key, value in asked.items():
        if key not in PERMISSIONS or not isinstance(value, bool):
            raise PackError(
                f"{folder.name}/{manifest}: permissions are {PERMISSIONS}, each true or false"
            )
    return manifest, name, [p for p in PERMISSIONS if asked.get(p)]


def load_pack(folder: Path, fetch: Fetch = http_get, cache: Path = CACHE) -> dict:
    """The pack in `folder` (its pack.toml), checked, with its files' sizes
    and checksums under "files" (and the URL of each from a [[source]])."""
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
    present = sorted(p.name for p in folder.iterdir() if p.name != "pack.toml")
    for name in present:
        if not (folder / name).is_file():
            raise PackError(f"{folder.name}/{name}: packs hold files only, no folders")
    # Every file the pack has, by name: its own, then its sources'.
    paths = {name: folder / name for name in present}
    urls: dict[str, str] = {}
    sources = pack.get("source", [])
    if not isinstance(sources, list):
        raise PackError(f"{where}: sources are [[source]] tables")
    for source in sources:
        if not isinstance(source, dict):
            raise PackError(f"{where}: sources are [[source]] tables")
        for name, (path, url) in fetch_source(source, where, fetch, cache).items():
            if name in paths:
                raise PackError(f"{where}: {name} is both the pack's own and a source's")
            paths[name] = path
            urls[name] = url
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
            if section == "plugin":
                if Path(file).suffix.lower() not in types:
                    raise PackError(f"{where}: {file} isn't a {section} file ({sorted(types)})")
                manifest, plugin_name, permissions = plugin_manifest(paths, folder, file, where)
                if name is not None and name != plugin_name:
                    raise PackError(f"{where}: plugin {file} is named {plugin_name!r} in {manifest}")
                name = item["name"] = plugin_name
                item["permissions"] = permissions
                used.add(manifest)
            label = name or file
            if label in names:
                raise PackError(f"{where}: two {section}s are named {label!r}")
            names.add(label)
            if Path(file).suffix.lower() not in types:
                raise PackError(f"{where}: {file} isn't a {section} file ({sorted(types)})")
            used.add(file)

    listed = sorted(used | set(pack.get("files", [])))
    if missing := sorted(set(listed) - set(paths)):
        raise PackError(f"{where}: lists files that aren't there: {missing}")
    if extra := sorted(set(paths) - set(listed)):
        raise PackError(f"{where}: has files it doesn't list (add them to files): {extra}")
    for name in listed:
        if not FILE.match(name):
            raise PackError(f"{where}: {name!r}: file names are letters, digits, . _ -")

    pack["files"] = [
        {
            "path": name,
            "size": paths[name].stat().st_size,
            "sha256": hashlib.sha256(paths[name].read_bytes()).hexdigest(),
            **({"url": urls[name]} if name in urls else {}),
        }
        for name in listed
    ]
    pack["source"] = sources
    return pack


def load_packs(packs: Path, fetch: Fetch = http_get, cache: Path = CACHE) -> list[dict]:
    """Every pack under `packs`, checked, in id order. Two packs may give a
    sound the same name (or a built-in one's): raptaboard layers them, the
    newest install winning."""
    folders = sorted(p for p in packs.iterdir() if p.is_dir()) if packs.is_dir() else []
    return [load_pack(f, fetch, cache) for f in folders]


def check_channel(packs: list[dict], tag: str) -> None:
    """A release catalog (`tag` without a `-`) takes nothing from a
    pre-release: every [[source]]'s tag must be a release's too."""
    if is_prerelease(tag):
        return
    for pack in packs:
        for source in pack.get("source", []):
            if is_prerelease(source["tag"]):
                raise PackError(
                    f"{pack['id']}: {source['repo']} {source['tag']} is a pre-release; "
                    f"release catalog {tag} takes only releases (tag {tag}-pre.N to publish it early)"
                )


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
                {k: item[k] for k in ("name", "file", "permissions") if k in item}
                for item in pack.get(section, [])
            ]
            if items:
                entry[key] = items
        entry["files"] = [
            {**f, "url": f.get("url") or f"{base}/{asset_name(pack, f['path'])}"}
            for f in pack["files"]
        ]
        out.append(entry)
    return {"format": FORMAT, "release": tag, "packs": out}


def build(
    packs_dir: Path,
    out: Path,
    tag: str,
    repo: str = REPO,
    fetch: Fetch = http_get,
    cache: Path = CACHE,
) -> dict:
    """Write `out`: each pack's own files as release assets, and
    catalog.json (a source's files stay in their own releases)."""
    packs = load_packs(packs_dir, fetch, cache)
    check_channel(packs, tag)
    out.mkdir(parents=True, exist_ok=True)
    for pack in packs:
        for f in pack["files"]:
            if "url" not in f:
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
    parser.add_argument("--cache", type=Path, default=CACHE, help="where source files are kept")
    args = parser.parse_args()
    try:
        if args.check:
            packs = load_packs(ROOT / "packs", cache=args.cache)
            print(f"{len(packs)} packs are fine: {', '.join(p['id'] for p in packs)}")
            return 0
        if not args.tag:
            parser.error("--tag is needed unless --check")
        cat = build(ROOT / "packs", args.out, args.tag, args.repo, cache=args.cache)
        print(f"catalog {args.tag}: {len(cat['packs'])} packs into {args.out}")
        return 0
    except PackError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
