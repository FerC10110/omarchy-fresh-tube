import json
import os
import unittest
from unittest import mock

import support
from fresh_tube import cli, play, store
from fresh_tube.errors import USAGE, FreshTubeError

VID = "4_fM3Nv8BB0"
URL = "https://www.youtube.com/watch?v=" + VID
MONITORS = [{"id": 0, "name": "HDMI-A-1", "x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1,
             "reserved": [0, 26, 0, 0], "focused": True},
            {"id": 1, "name": "DP-1", "x": 1920, "y": 0, "width": 2560, "height": 1440, "scale": 2,
             "reserved": [0, 0, 0, 40], "focused": False}]


def client(pid, floating=True, monitor=0):
    return {"address": "0x55aa", "pid": pid, "class": "mpv", "floating": floating, "monitor": monitor}


class Argv(unittest.TestCase):
    def test_mpv_gets_the_companion_flags(self):
        argv = play.build_argv("mpv", VID, (860, 484))
        self.assertEqual(argv[0], "mpv")
        self.assertEqual(argv[-1], URL)
        self.assertIn("--save-position-on-quit", argv)
        self.assertIn("--force-window=immediate", argv)
        self.assertIn("--geometry=860x484", argv)
        self.assertIn("--script=" + play.SCRIPT_PATH, argv)
        self.assertIn(f"--script-opt=fresh_tube-id={VID}", argv)
        self.assertIn(f"--script-opt=fresh_tube-bin={play.BIN_PATH}", argv)
        self.assertFalse(any(a.startswith("--script-opts=") for a in argv))
        self.assertTrue(play.SCRIPT_PATH.endswith(os.path.join("mpv", "fresh-tube.lua")))
        self.assertTrue(os.path.isabs(play.BIN_PATH))

    def test_mpv_with_options_and_a_path_still_counts_as_mpv(self):
        argv = play.build_argv("/usr/bin/mpv --profile=big", VID, (860, 484))
        self.assertEqual(argv[:2], ["/usr/bin/mpv", "--profile=big"])
        self.assertIn("--save-position-on-quit", argv)

    def test_other_players_get_only_the_url(self):
        self.assertEqual(play.build_argv("vlc --fullscreen", VID, (860, 484)), ["vlc", "--fullscreen", URL])

    def test_empty_command_means_mpv(self):
        self.assertEqual(play.build_argv("", VID, (860, 484))[0], "mpv")

    def test_unbalanced_quotes_are_a_usage_error(self):
        with self.assertRaises(FreshTubeError) as caught:
            play.build_argv('mpv "oops', VID, (860, 484))
        self.assertTrue(str(caught.exception).startswith("Could not start the player"))
        self.assertEqual(caught.exception.code, USAGE)


class DefaultSize(unittest.TestCase):
    def test_quarter_of_the_focused_monitor_logical_width(self):
        self.assertEqual(play.default_size(MONITORS), (480, 270))

    def test_physical_width_is_used_and_first_monitor_is_the_fallback(self):
        self.assertEqual(play.default_size([dict(MONITORS[1], focused=True)]), (640, 360))
        self.assertEqual(play.default_size([dict(MONITORS[0], focused=False)]), (480, 270))

    def test_no_or_bad_monitors(self):
        self.assertEqual(play.default_size(None), play.DEFAULT_SIZE)
        self.assertEqual(play.default_size([]), play.DEFAULT_SIZE)
        self.assertEqual(play.default_size([{"width": "x"}]), play.DEFAULT_SIZE)


class Placement(unittest.TestCase):
    def setUp(self):
        self.dispatches = []
        self.addCleanup(mock.patch.stopall)
        mock.patch("fresh_tube.play.dispatch", side_effect=lambda *a: self.dispatches.append(a)).start()
        mock.patch("fresh_tube.play.sleep").start()
        mock.patch("fresh_tube.play.pid_alive", return_value=True).start()

    def test_ignores_a_window_before_it_is_mapped(self):
        with mock.patch("fresh_tube.play.hyprctl",
                         side_effect=[[dict(client(7), mapped=False)], [dict(client(7), mapped=True)]]) as hyprctl:
            self.assertEqual(play.find_window(7), dict(client(7), mapped=True))
        self.assertEqual(hyprctl.call_count, 2)

    def test_moves_below_the_bar_of_its_monitor(self):
        with mock.patch("fresh_tube.play.hyprctl", side_effect=lambda what: {"clients": [client(7)], "monitors": MONITORS}[what]):
            play.place_window(play.find_window(7))
        self.assertEqual(self.dispatches, [("movewindowpixel", "exact 0 26,address:0x55aa")])

    def test_floats_first_when_tiled_and_uses_the_monitor_origin(self):
        with mock.patch("fresh_tube.play.hyprctl", side_effect=lambda what: {"clients": [client(7, floating=False, monitor=1)], "monitors": MONITORS}[what]):
            play.place_window(play.find_window(7))
        self.assertEqual(self.dispatches, [("setfloating", "address:0x55aa"),
                                           ("movewindowpixel", "exact 1920 0,address:0x55aa")])

    def test_waits_for_the_window_then_gives_up(self):
        clocks = iter([0.0, 0.0, 5.0, 11.0])
        with mock.patch("fresh_tube.play.hyprctl", return_value=[client(8)]) as hyprctl, \
             mock.patch("fresh_tube.play.monotonic", side_effect=lambda: next(clocks)):
            self.assertIsNone(play.find_window(7))
        self.assertGreaterEqual(hyprctl.call_count, 2)
        self.assertEqual(self.dispatches, [])

    def test_stops_when_the_player_died(self):
        with mock.patch("fresh_tube.play.hyprctl", return_value=[]) as hyprctl, \
             mock.patch("fresh_tube.play.pid_alive", return_value=False):
            self.assertIsNone(play.find_window(7))
        self.assertEqual(hyprctl.call_count, 1)

    def test_no_hyprland_means_no_wait(self):
        with mock.patch("fresh_tube.play.hyprctl", return_value=None) as hyprctl, \
             mock.patch("fresh_tube.play.sleep") as sleep:
            self.assertIsNone(play.find_window(7))
        self.assertEqual(hyprctl.call_count, 1)
        sleep.assert_not_called()

    def test_hyprctl_wrapper_parses_json_and_swallows_failures(self):
        done = mock.Mock(returncode=0, stdout=json.dumps(MONITORS), stderr="")
        with mock.patch("fresh_tube.play.subprocess.run", return_value=done) as run:
            self.assertEqual(play.hyprctl("monitors"), MONITORS)
        self.assertEqual(run.call_args.args[0], ["hyprctl", "monitors", "-j"])
        with mock.patch("fresh_tube.play.subprocess.run", side_effect=FileNotFoundError):
            self.assertIsNone(play.hyprctl("monitors"))
        with mock.patch("fresh_tube.play.subprocess.run", return_value=mock.Mock(returncode=1, stdout="")):
            self.assertIsNone(play.hyprctl("monitors"))
        with mock.patch("fresh_tube.play.subprocess.run", return_value=mock.Mock(returncode=0, stdout="nope")):
            self.assertIsNone(play.hyprctl("monitors"))


class PlayCommand(unittest.TestCase):
    def setUp(self):
        self.box = support.Sandbox()
        self.box.apply()
        self.addCleanup(self.box.cleanup)
        self.spawned = []

        def fake_popen(argv, **kw):
            self.spawned.append((argv, kw))
            return mock.Mock(pid=4242)
        self.addCleanup(mock.patch.stopall)
        mock.patch("fresh_tube.play.popen", side_effect=fake_popen).start()
        mock.patch("fresh_tube.play.hyprctl", side_effect=lambda what: {"monitors": MONITORS}.get(what)).start()

    def run_play(self, *args):
        with support.captured() as (out, err):
            code = cli.main(["play", *args])
        return code, out.getvalue(), err.getvalue()

    def test_launches_mpv_with_the_default_size_then_the_placer_and_marks_seen(self):
        code, out, err = self.run_play("--player", "mpv", "--", VID)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {"played": VID})
        player, placer = self.spawned
        self.assertIn("--geometry=480x270", player[0])
        self.assertEqual(player[0][-1], URL)
        self.assertTrue(player[1]["start_new_session"])
        self.assertEqual(placer[0], [play.BIN_PATH, "place-window", "4242"])
        self.assertIn(VID, self.box.read_json(self.box.state_file)["seen"])

    def test_uses_the_remembered_size(self):
        state = store.load_state()
        store.set_prefs(state, [("playerWidth", "1000"), ("playerHeight", "560")])
        store.save_state(state)
        self.run_play("--", VID)
        self.assertIn("--geometry=1000x560", self.spawned[0][0])

    def test_default_player_is_mpv(self):
        self.run_play("--", VID)
        self.assertEqual(self.spawned[0][0][0], "mpv")

    def test_launch_failure_marks_nothing(self):
        mock.patch("fresh_tube.play.popen", side_effect=FileNotFoundError(2, "No such file or directory")).start()
        code, out, err = self.run_play("--player", "mpv", "--", VID)
        self.assertEqual(code, 1)
        self.assertIn("Could not start mpv", err)
        self.assertNotIn(VID, store.load_state()["seen"])

    def test_a_placer_that_cannot_start_does_not_fail_the_play(self):
        calls = {"n": 0}

        def flaky_popen(argv, **kw):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("no fork for you")
            return mock.Mock(pid=4242)
        mock.patch("fresh_tube.play.popen", side_effect=flaky_popen).start()
        code, out, err = self.run_play("--", VID)
        self.assertEqual(code, 0, err)

    def test_rejects_a_bad_id(self):
        code, out, err = self.run_play("--", "not-an-id")
        self.assertEqual(code, 2)
        self.assertIn("That doesn't look like a YouTube video", err)
        self.assertEqual(self.spawned, [])


class PlaceWindowCommand(unittest.TestCase):
    def test_places_the_window_of_the_given_pid(self):
        with mock.patch("fresh_tube.play.find_window", return_value=client(7)) as find, \
             mock.patch("fresh_tube.play.place_window") as place, support.captured() as (out, err):
            self.assertEqual(cli.main(["place-window", "7"]), 0)
        find.assert_called_once_with(7)
        place.assert_called_once_with(client(7))
        with mock.patch("fresh_tube.play.find_window", return_value=None), \
             mock.patch("fresh_tube.play.place_window") as place, support.captured():
            self.assertEqual(cli.main(["place-window", "7"]), 0)
        place.assert_not_called()
        with support.captured() as (out, err):
            self.assertEqual(cli.main(["place-window", "x"]), 2)


if __name__ == "__main__":
    unittest.main()
