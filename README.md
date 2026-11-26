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
- What it holds is its sections, mixed as needed: `[[sound]]` (the `name` raptaboard shows and
  its `file`), `[[image]]`, `[[field]]`, `[[plugin]]` and `[[layout]]` (a `file`, and a `name`
  if not the file's), and `files` for other data they read. A sound may have a new name or a built-in one's (`fire 1`), which it then replaces;
  where packs share a name, the newest install wins. raptaboard uses sounds and plugins so far;
  the other sections are for what comes next. `kind` is an optional label.
- A `[[plugin]]`'s `file` is its WebAssembly component (`alerts.wasm`); its manifest, raptaboard's
  `plugin.toml`, sits beside it named for it (`alerts.toml`). The catalog gives each plugin its
  manifest's name and the permissions it asks for (sending values, sounds, running while its tab
  is closed, saving values between runs), which raptaboard shows before installing and holds the plugin to. Set `min_app` to
  0.4.0 or later (the first raptaboard that loads plugins from packs).
- A pack's files may come from another repository's GitHub release instead of its folder: a
  `[[source]]` gives the `repo`, the release `tag` and the `files` it takes, which the pack then
  uses like its own. Building the catalog downloads each (kept in `.cache/`), checks it against
  that release's `SHA256SUMS` and checks it as any pack file (a plugin's manifest too); the catalog
  lists its URL in that release, so raptaboard downloads it from there. This is how plugins built
  in their own repos get into packs: [packs/example-widgets](packs/example-widgets/) takes Number
  and Alerts from [raptaboard-examples](https://github.com/tuffinmuffin/raptaboard-examples)'
  releases and [packs/doom](packs/doom/) the game from
  [raptaboard-doom](https://github.com/tuffinmuffin/raptaboard-doom)'s. To update one, change its
  `tag` and raise the pack's `version`.
- `license` is one line; `credits` is the full text raptaboard shows before installing.
- `suggested = true` ticks the pack in the list raptaboard offers when it first starts.

Check them with `python3 scripts/build_catalog.py --check` and
`python3 -m unittest discover scripts` (CI runs both on every pull request).

## Releases

Push a tag `vN` (`v1`, `v2`, ...) on `main` to publish a release, or `vN-pre.M` (`v4-pre.1`) to
publish a pre-release. The Release workflow publishes every
pack file as a release asset named `<pack id>.<file>`, with `catalog.json` listing each
pack's files, sizes and SHA-256 checksums. It also publishes `catalog.json.sig`, an Ed25519
signature of `catalog.json` made with the `CONTENT_SIGNING_KEY` secret. raptaboard downloads
`releases/latest/download/catalog.json` and its signature, and checks them against the public
key it's built with, [catalog-key.pub](catalog-key.pub) (raw 32 bytes, base64). It checks each
file against its checksum before using it.

A pre-release (a tag with a `-`) is published the same way, signed with the same key, as a GitHub
pre-release, so it never becomes `latest` and the released catalog is unchanged. Only a
pre-release catalog may use pre-release sources (a source `tag` with a `-`, like
`v0.1.0-pre.3`): building a release catalog with one fails and says so. So a pack can point at a
plugin's pre-release to try it, and a release follows once the plugin's repo has released it.
