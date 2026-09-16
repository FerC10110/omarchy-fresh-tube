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


PARSED = {"name": "Example",
          "latest": {"videoId": "new", "title": "New", "published": "2026-09-15T17:00:03+00:00",
                     "thumbnail": "https://i/new.jpg"},
          "recent": ["new", "old"]}


class State(StoreTest):
    def test_missing_state_has_defaults(self):
        self.assertEqual(store.load_state(), {"version": 1, "seen": [], "feeds": {}, "fetchedAt": "",
                                              "prefs": {"width": 420, "height": 520, "pinned": False}})

    def test_save_and_reload(self):
        state = store.load_state()
        store.mark_seen(state, "abc")
        store.save_state(state)
        self.assertEqual(store.load_state()["seen"], ["abc"])

    def test_mark_seen_is_idempotent(self):
        state = store.load_state()
        store.mark_seen(state, "abc")
        store.mark_seen(state, "abc")
        self.assertEqual(state["seen"], ["abc"])

    def test_prefs_validation(self):
        state = store.load_state()
        self.assertEqual(store.set_pref(state, "width", "500")["width"], 500)
        self.assertEqual(store.set_pref(state, "height", "300")["height"], 300)
        self.assertIs(store.set_pref(state, "pinned", "true")["pinned"], True)
        self.assertIs(store.set_pref(state, "pinned", "False")["pinned"], False)
        for key, value in (("width", "10"), ("width", "abc"), ("height", "99999"),
                           ("pinned", "maybe"), ("color", "red")):
            with self.assertRaises(FreshTubeError, msg=(key, value)) as caught:
                store.set_pref(state, key, value)
            self.assertEqual(caught.exception.code, USAGE)

    def test_partial_prefs_are_completed(self):
        self.box.write_json(self.box.state_file, {"version": 1, "prefs": {"width": 600}})
        self.assertEqual(store.load_state()["prefs"], {"width": 600, "height": 520, "pinned": False})


class Feeds(StoreTest):
    def test_update_feed_and_error_keep_cache(self):
        state = store.load_state()
        store.update_feed(state, "UC1", PARSED, "2026-09-16T10:00:00+00:00")
        self.assertEqual(state["feeds"]["UC1"], {"fetchedAt": "2026-09-16T10:00:00+00:00", "lastError": "",
                                                 "latest": PARSED["latest"], "recent": ["new", "old"]})
        store.set_feed_error(state, "UC1", "timed out")
        self.assertEqual(state["feeds"]["UC1"]["lastError"], "timed out")
        self.assertEqual(state["feeds"]["UC1"]["latest"], PARSED["latest"])
        store.set_feed_error(state, "UC2", "timed out")
        self.assertEqual(state["feeds"]["UC2"], {"fetchedAt": "", "lastError": "timed out",
                                                 "latest": None, "recent": []})
        store.drop_feed(state, "UC1")
        self.assertNotIn("UC1", state["feeds"])

    def test_prune_keeps_only_ids_still_in_a_feed(self):
        state = store.load_state()
        store.update_feed(state, "UC1", PARSED, "2026-09-16T10:00:00+00:00")
        state["seen"] = ["new", "gone", "old"]
        store.prune_seen(state)
        self.assertEqual(state["seen"], ["new", "old"])

    def test_unseen_videos_one_per_channel_newest_first(self):
        state = store.load_state()
        channels = [{"id": "UC1", "name": "One"}, {"id": "UC2", "name": "Two"}, {"id": "UC3", "name": "Three"}]
        store.update_feed(state, "UC1", PARSED, "2026-09-16T10:00:00+00:00")
        later = dict(PARSED, latest=dict(PARSED["latest"], videoId="later", published="2026-09-16T09:00:00+00:00"))
        store.update_feed(state, "UC2", later, "2026-09-16T10:00:00+00:00")
        # UC3 has no cache yet and must simply be absent.
        videos = store.unseen_videos(state, channels)
        self.assertEqual([v["videoId"] for v in videos], ["later", "new"])
        self.assertEqual(videos[0]["channel"], "Two")
        self.assertEqual(videos[0]["channelId"], "UC2")
        self.assertEqual(videos[0]["url"], "https://www.youtube.com/watch?v=later")
        self.assertEqual(videos[1]["thumbnail"], "https://i/new.jpg")
        store.mark_seen(state, "later")
        self.assertEqual([v["videoId"] for v in store.unseen_videos(state, channels)], ["new"])
