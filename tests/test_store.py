import os
import unittest

import support
from fresh_tube import store
from fresh_tube.errors import DUPLICATE, UNKNOWN, USAGE, FreshTubeError

LTT = "UCXuqSBlHAE6Xw-yeJA0Tunw"


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.box = support.Sandbox()
        self.box.apply()
        self.addCleanup(self.box.cleanup)


class Paths(StoreTest):
    def test_paths_follow_xdg(self):
        self.assertEqual(store.channels_path(), self.box.channels_file)
        self.assertEqual(store.state_path(), self.box.state_file)

    def test_paths_fall_back_to_home(self):
        os.environ["XDG_CONFIG_HOME"] = ""
        os.environ["XDG_STATE_HOME"] = ""
        self.assertEqual(store.channels_path(),
                         os.path.join(self.box.home, ".config", "fresh-tube", "channels.json"))
        self.assertEqual(store.state_path(),
                         os.path.join(self.box.home, ".local", "state", "fresh-tube", "state.json"))

    def test_now_iso_is_utc_with_offset(self):
        self.assertRegex(store.now_iso(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")


class Channels(StoreTest):
    def test_missing_file_is_empty(self):
        self.assertEqual(store.load_channels(), [])

    def test_add_save_and_reload(self):
        channels = []
        added = store.add_channel(channels, LTT, "Linus Tech Tips")
        self.assertEqual(added["id"], LTT)
        self.assertEqual(added["name"], "Linus Tech Tips")
        self.assertEqual(added["url"], "https://www.youtube.com/channel/" + LTT)
        self.assertRegex(added["addedAt"], r"^\d{4}-\d\d-\d\dT")
        store.save_channels(channels)
        self.assertEqual(store.load_channels(), [added])
        self.assertEqual(self.box.read_json(self.box.channels_file)["version"], 1)
        self.assertEqual(store.find_channel(channels, LTT), added)
        self.assertIsNone(store.find_channel(channels, "UCnothere0000000000000xx"))

    def test_duplicate_is_refused(self):
        channels = [store.add_channel([], LTT, "LTT")]
        with self.assertRaises(FreshTubeError) as caught:
            store.add_channel(channels, LTT, "Again")
        self.assertEqual(caught.exception.code, DUPLICATE)
        self.assertEqual(len(channels), 1)

    def test_remove(self):
        channels = [store.add_channel([], LTT, "LTT")]
        self.assertEqual(store.remove_channel(channels, LTT), [])
        with self.assertRaises(FreshTubeError) as caught:
            store.remove_channel(channels, LTT)
        self.assertEqual(caught.exception.code, UNKNOWN)

    def test_corrupt_file_is_reported_not_overwritten(self):
        os.makedirs(os.path.dirname(self.box.channels_file))
        with open(self.box.channels_file, "w") as f:
            f.write("{not json")
        with self.assertRaises(FreshTubeError) as caught:
            store.load_channels()
        self.assertIn("channels.json", str(caught.exception))
        with open(self.box.channels_file) as f:
            self.assertEqual(f.read(), "{not json")

    def test_write_is_atomic_and_leaves_no_temp_files(self):
        store.save_channels([])
        folder = os.path.dirname(self.box.channels_file)
        self.assertEqual(os.listdir(folder), ["channels.json"])
