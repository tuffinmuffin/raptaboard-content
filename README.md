# raptaboard-content

Extra content for [raptaboard](https://github.com/tuffinmuffin/raptaboard), the FRC driver
dashboard: sound packs, and later widget plugins and their data. raptaboard offers these packs
when it first starts and in ⚙ Settings → Content, and downloads one only when you choose it.

Each pack carries its own license and credits, which raptaboard shows before you install it.
Not every pack is open source: some hold short clips that aren't ours, kept for non-commercial,
educational use and removed at once if their owner asks.

The code in this repository (scripts and workflows) is MIT-licensed; see [LICENSE](LICENSE).

## Packs

Each folder in [packs/](packs/) is a pack: a `pack.toml` and its files (no subfolders).
[packs/fan-clips/pack.toml](packs/fan-clips/pack.toml) is an example with every key explained.

- `id` matches the folder name; `version` and `min_app` (the oldest raptaboard it works
  with) are versions like `1.0.0`. Raise `version` whenever a file changes, so raptaboard
  offers the update.
- `kind` is `sounds` or `plugin`. A sounds pack lists each `[[sound]]` with the `name`
  raptaboard shows and its `file`. Sound names are unique across every pack.
- `license` is one line; `credits` is the full text raptaboard shows before installing.
- `suggested = true` ticks the pack in the list raptaboard offers when it first starts.

Check them with `python3 scripts/build_catalog.py --check` and
`python3 -m unittest discover scripts` (CI runs both on every pull request).

## Releases

Push a tag `vN` (`v1`, `v2`, ...) on `main` to publish. The Release workflow publishes every
pack file as a release asset named `<pack id>.<file>`, with `catalog.json` listing each
pack's files, sizes and SHA-256 checksums. It also publishes `catalog.json.sig`, an Ed25519
signature of `catalog.json` made with the `CONTENT_SIGNING_KEY` secret. raptaboard downloads
`releases/latest/download/catalog.json` and its signature, and checks them against the public
key it's built with, [catalog-key.pub](catalog-key.pub) (raw 32 bytes, base64). It checks each
file against its checksum before using it.
