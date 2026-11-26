"""Tests for build_catalog.py: python3 -m unittest discover scripts

Tests written by Claude.
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_catalog as bc  # noqa: E402

GOOD = """
id = "beeps"
name = "Beeps"
version = "1.2.0"
kind = "sounds"
min_app = "0.3.0"
summary = "Beeps."
license = "CC0"
credits = "Made by us."

[[sound]]
name = "beep"
file = "beep.mp3"
"""


DOOM = """
name = "doom"
version = "0.1.0"
api = "0.2"

[permissions]
sound = true
publish = false
"""

PLUGIN = GOOD + '\n[[plugin]]\nfile = "doom.wasm"\n'


class Packs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.packs = Path(self.tmp.name) / "packs"
        self.packs.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def pack(self, toml=GOOD, folder="beeps", files=("beep.mp3",), texts=None):
        d = self.packs / folder
        d.mkdir()
        (d / "pack.toml").write_text(toml)
        for f in files:
            (d / f).write_bytes(b"sound:" + f.encode())
        for f, text in (texts or {}).items():
            (d / f).write_text(text)
        return d

    def fails(self, message, **kw):
        self.pack(**kw)
        with self.assertRaises(bc.PackError) as e:
            bc.load_packs(self.packs)
        self.assertIn(message, str(e.exception))

    def test_the_real_packs_are_fine(self):
        packs = bc.load_packs(bc.ROOT / "packs")
        self.assertIn("fan-clips", [p["id"] for p in packs])

    def test_a_good_pack_has_its_files_sizes_and_checksums(self):
        self.pack()
        [pack] = bc.load_packs(self.packs)
        [f] = pack["files"]
        self.assertEqual(f["path"], "beep.mp3")
        self.assertEqual(f["size"], len(b"sound:beep.mp3"))
        self.assertEqual(f["sha256"], hashlib.sha256(b"sound:beep.mp3").hexdigest())

    def test_the_id_must_match_the_folder(self):
        self.fails("must match its folder", folder="boops")

    def test_every_required_key_is_needed(self):
        self.fails("needs license", toml=GOOD.replace('license = "CC0"', ""))

    def test_a_pack_needs_a_section(self):
        no_sections = GOOD.split("[[sound]]")[0]
        self.fails("needs at least one of", toml=no_sections, files=())

    def test_sections_mix_and_reach_the_catalog(self):
        toml = GOOD + """
[[image]]
name = "raptor"
file = "raptor.svg"

[[plugin]]
file = "doom.wasm"

[[layout]]
name = "Match"
file = "match.json"
"""
        self.pack(
            toml=toml,
            files=("beep.mp3", "raptor.svg", "doom.wasm", "match.json"),
            texts={"doom.toml": DOOM},
        )
        [pack] = bc.catalog(bc.load_packs(self.packs), "v1")["packs"]
        self.assertEqual(pack["images"], [{"name": "raptor", "file": "raptor.svg"}])
        self.assertEqual(
            pack["plugins"],
            [{"name": "doom", "file": "doom.wasm", "permissions": ["sound"]}],
        )
        # The manifest is one of its files.
        self.assertIn("doom.toml", [f["path"] for f in pack["files"]])
        self.assertEqual(pack["layouts"], [{"name": "Match", "file": "match.json"}])
        self.assertEqual(pack["kind"], "sounds")

    def test_a_section_takes_its_own_file_types(self):
        toml = GOOD + '\n[[plugin]]\nfile = "doom.mp3"\n'
        self.fails("isn't a plugin file", toml=toml, files=("beep.mp3", "doom.mp3"))

    def test_a_plugin_needs_its_manifest_beside_it(self):
        self.fails("needs its manifest beside it", toml=PLUGIN, files=("beep.mp3", "doom.wasm"))

    def test_a_plugins_manifest_must_be_sound(self):
        wasm = ("beep.mp3", "doom.wasm")
        for manifest, message in [
            (DOOM.replace('api = "0.2"', ""), "needs api"),
            (DOOM.replace('"doom"', '"Doom!"'), "needs name"),
            (DOOM + "\nfly = true\n", "permissions are"),
            ("name = [", "doom.toml"),
        ]:
            with self.subTest(message):
                self.tearDown()
                self.setUp()
                self.fails(message, toml=PLUGIN, files=wasm, texts={"doom.toml": manifest})

    def test_a_plugins_needs_are_in_the_catalog(self):
        # Only what it asks for: a widget plugin's entry has none.
        game = DOOM.replace('api = "0.2"', 'api = "0.2"\ntab = "Doom"\ncapture_mouse = true')
        game += "\n[limits]\nmemory_mb = 192\ncall_ms = 500\n"
        self.pack(toml=PLUGIN, files=("beep.mp3", "doom.wasm"), texts={"doom.toml": game})
        [pack] = bc.catalog(bc.load_packs(self.packs), "v1")["packs"]
        self.assertEqual(
            pack["plugins"][0]["needs"],
            {"tab": "Doom", "capture_mouse": True, "memory_mb": 192, "call_ms": 500},
        )

    def test_a_plugins_needs_must_be_sound(self):
        wasm = ("beep.mp3", "doom.wasm")
        for extra, message in [
            ("\n[limits]\nmemory_mb = 4096\n", "limits are"),
            ("\n[limits]\ncall_ms = 0\n", "limits are"),
            ("\n[limits]\nstorage_kb = true\n", "limits are"),
            ("\n[limits]\ndisk_gb = 1\n", "limits are"),
        ]:
            with self.subTest(extra):
                self.tearDown()
                self.setUp()
                self.fails(message, toml=PLUGIN, files=wasm, texts={"doom.toml": DOOM + extra})
        for top, message in [
            ('tab = ""', "tab is the name"),
            ('capture_mouse = "yes"', "capture_mouse is true"),
            ("limits = 3", "[limits] is a table"),
        ]:
            with self.subTest(top):
                self.tearDown()
                self.setUp()
                self.fails(message, toml=PLUGIN, files=wasm, texts={"doom.toml": top + "\n" + DOOM})

    def test_a_plugins_name_is_its_manifests(self):
        toml = PLUGIN.replace('file = "doom.wasm"', 'name = "quake"\nfile = "doom.wasm"')
        self.fails("is named 'doom'", toml=toml, files=("beep.mp3", "doom.wasm"), texts={"doom.toml": DOOM})

    def test_versions_are_x_y_z(self):
        self.fails("version must be", toml=GOOD.replace('"1.2.0"', '"1.2"'))

    def test_a_listed_file_must_be_there(self):
        self.fails("aren't there", files=())

    def test_every_file_must_be_listed(self):
        self.fails("doesn't list", files=("beep.mp3", "stray.mp3"))

    def test_sounds_need_a_sound_file(self):
        self.fails("isn't a sound", toml=GOOD.replace("beep.mp3", "beep.txt"), files=("beep.txt",))

    def test_packs_may_share_a_sound_name(self):
        # raptaboard layers them: the newest install wins.
        self.pack()
        self.pack(toml=GOOD.replace('"beeps"', '"more"'), folder="more")
        self.assertEqual(len(bc.load_packs(self.packs)), 2)

    def test_the_catalog_points_at_the_release_assets(self):
        self.pack()
        out = Path(self.tmp.name) / "dist"
        cat = bc.build(self.packs, out, "v7", "team/content")
        self.assertEqual(cat["format"], 1)
        self.assertEqual(cat["release"], "v7")
        [pack] = cat["packs"]
        self.assertFalse(pack["suggested"])
        self.assertEqual(pack["sounds"], [{"name": "beep", "file": "beep.mp3"}])
        [f] = pack["files"]
        self.assertEqual(
            f["url"], "https://github.com/team/content/releases/download/v7/beeps.beep.mp3"
        )
        self.assertEqual((out / "beeps.beep.mp3").read_bytes(), b"sound:beep.mp3")
        self.assertEqual(json.loads((out / "catalog.json").read_text()), cat)



# A plugin from another repository's release: its manifest and component.
REMOTE_MANIFEST = DOOM.replace('api = "0.2"', 'api = "0.3"').replace(
    "publish = false", "storage = true"
)
REMOTE = {"doom.wasm": b"\0asm component", "doom.toml": REMOTE_MANIFEST.encode()}
SOURCED = GOOD + """
[[plugin]]
file = "doom.wasm"

[[source]]
repo = "team/doom"
tag = "TAG"
files = ["doom.wasm", "doom.toml"]
"""


class Sources(unittest.TestCase):
    """Files from another repository's release ([[source]])."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.packs, self.cache, self.out = root / "packs", root / "cache", root / "dist"
        self.packs.mkdir()
        self.asked: list[str] = []
        self.served = dict(REMOTE)

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, url: str) -> bytes:
        """The release `team/doom` at any tag, serving self.served and its
        SHA256SUMS; anything else isn't found."""
        self.asked.append(url)
        prefix = "https://github.com/team/doom/releases/download/"
        if not url.startswith(prefix):
            raise OSError("404")
        name = url.rsplit("/", 1)[1]
        if name == "SHA256SUMS":
            return "".join(
                f"{hashlib.sha256(REMOTE[n]).hexdigest()}  {n}\n" for n in REMOTE
            ).encode()
        if name not in self.served:
            raise OSError("404")
        return self.served[name]

    def pack(self, tag="v1.0.0", toml=SOURCED):
        d = self.packs / "beeps"
        d.mkdir(exist_ok=True)
        (d / "pack.toml").write_text(toml.replace("TAG", tag))
        (d / "beep.mp3").write_bytes(b"sound:beep.mp3")

    def load(self):
        return bc.load_packs(self.packs, self.fetch, self.cache)

    def fails(self, message, **kw):
        self.pack(**kw)
        with self.assertRaises(bc.PackError) as e:
            self.load()
        self.assertIn(message, str(e.exception))

    def test_a_sources_files_are_checked_and_listed_with_their_urls(self):
        self.pack()
        [pack] = self.load()
        files = {f["path"]: f for f in pack["files"]}
        wasm = files["doom.wasm"]
        self.assertEqual(wasm["sha256"], hashlib.sha256(REMOTE["doom.wasm"]).hexdigest())
        self.assertEqual(wasm["size"], len(REMOTE["doom.wasm"]))
        self.assertEqual(
            wasm["url"], "https://github.com/team/doom/releases/download/v1.0.0/doom.wasm"
        )
        self.assertNotIn("url", files["beep.mp3"], "its own file: this release's")
        # The plugin's manifest, from the source, names it and its permissions.
        self.assertEqual(pack["plugin"][0]["permissions"], ["sound", "storage"])

    def test_the_catalog_points_at_the_source_and_publishes_only_the_packs_own(self):
        self.pack()
        cat = bc.build(self.packs, self.out, "v7", "team/content", self.fetch, self.cache)
        urls = {f["path"]: f["url"] for f in cat["packs"][0]["files"]}
        self.assertEqual(urls["doom.toml"], "https://github.com/team/doom/releases/download/v1.0.0/doom.toml")
        self.assertEqual(urls["beep.mp3"], "https://github.com/team/content/releases/download/v7/beeps.beep.mp3")
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["beeps.beep.mp3", "catalog.json"])

    def test_downloads_are_kept_and_checked_again(self):
        self.pack()
        self.load()
        downloads = [u for u in self.asked if not u.endswith("SHA256SUMS")]
        self.assertEqual(len(downloads), 2)
        self.asked.clear()
        self.load()
        self.assertEqual([u.rsplit("/", 1)[1] for u in self.asked], ["SHA256SUMS"], "from the cache")
        # A cached file that changed is downloaded again.
        cached = next(self.cache.rglob("doom.wasm"))
        cached.write_bytes(b"tampered")
        self.asked.clear()
        self.load()
        self.assertIn("doom.wasm", [u.rsplit("/", 1)[1] for u in self.asked])
        self.assertEqual(cached.read_bytes(), REMOTE["doom.wasm"])

    def test_a_file_must_match_its_releases_sums(self):
        self.served["doom.wasm"] = b"something else"
        self.fails("doesn't match its SHA256SUMS")

    def test_a_source_lists_only_files_its_release_has(self):
        self.fails("has no quake.wad", toml=SOURCED.replace('"doom.toml"]', '"doom.toml", "quake.wad"]'))

    def test_a_missing_release_says_so(self):
        self.fails("no SHA256SUMS", toml=SOURCED.replace("team/doom", "team/gone"))

    def test_a_sources_file_must_be_used_and_not_clash(self):
        unused = SOURCED.replace('[[plugin]]\nfile = "doom.wasm"\n', "")
        self.fails("doesn't list", toml=unused)
        self.tearDown()
        self.setUp()
        self.pack()
        (self.packs / "beeps" / "doom.wasm").write_bytes(b"local")
        with self.assertRaises(bc.PackError) as e:
            self.load()
        self.assertIn("both the pack's own and a source's", str(e.exception))

    def test_a_source_is_a_repo_a_tag_and_files(self):
        for bad, message in [
            ('repo = "team/doom"', 'repo = "doom"'),
            ('tag = "TAG"', 'tag = ""'),
            ('files = ["doom.wasm", "doom.toml"]', "files = []"),
        ]:
            with self.subTest(message):
                self.tearDown()
                self.setUp()
                self.fails("[[source]]", toml=SOURCED.replace(bad, message))

    def test_a_release_catalog_takes_only_released_sources(self):
        self.pack(tag="v1.0.0-pre.2")
        with self.assertRaises(bc.PackError) as e:
            bc.build(self.packs, self.out, "v7", "team/content", self.fetch, self.cache)
        self.assertIn("is a pre-release", str(e.exception))
        cat = bc.build(self.packs, self.out, "v7-pre.1", "team/content", self.fetch, self.cache)
        self.assertEqual(cat["release"], "v7-pre.1")
        self.assertTrue(bc.is_prerelease("v7-pre.1") and not bc.is_prerelease("v7"))

    def test_sums_reads_sha256sums_output(self):
        self.assertEqual(
            bc.sums("abc  a.wasm\nDEF *b.toml\n\nbad\n"), {"a.wasm": "abc", "b.toml": "def"}
        )


if __name__ == "__main__":
    unittest.main()
