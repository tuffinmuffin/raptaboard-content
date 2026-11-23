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


class Packs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.packs = Path(self.tmp.name) / "packs"
        self.packs.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def pack(self, toml=GOOD, folder="beeps", files=("beep.mp3",)):
        d = self.packs / folder
        d.mkdir()
        (d / "pack.toml").write_text(toml)
        for f in files:
            (d / f).write_bytes(b"sound:" + f.encode())
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
        self.pack(toml=toml, files=("beep.mp3", "raptor.svg", "doom.wasm", "match.json"))
        [pack] = bc.catalog(bc.load_packs(self.packs), "v1")["packs"]
        self.assertEqual(pack["images"], [{"name": "raptor", "file": "raptor.svg"}])
        self.assertEqual(pack["plugins"], [{"file": "doom.wasm"}])
        self.assertEqual(pack["layouts"], [{"name": "Match", "file": "match.json"}])
        self.assertEqual(pack["kind"], "sounds")

    def test_a_section_takes_its_own_file_types(self):
        toml = GOOD + '\n[[plugin]]\nfile = "doom.mp3"\n'
        self.fails("isn't a plugin file", toml=toml, files=("beep.mp3", "doom.mp3"))

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


if __name__ == "__main__":
    unittest.main()
