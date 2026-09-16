import json
import unittest
from unittest import mock

import support
from fresh_tube import cli
from fresh_tube.errors import NETWORK, FreshTubeError


class CliTest(unittest.TestCase):
    def setUp(self):
        self.box = support.Sandbox()
        self.addCleanup(self.box.cleanup)

    def ok(self, *args, **kw):
        result = self.box.run(*args, **kw)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def json(self, *args, **kw):
        return json.loads(self.ok(*args, **kw))

    def fails(self, code, *args, **kw):
        result = self.box.run(*args, **kw)
        self.assertEqual(result.returncode, code, (result.stdout, result.stderr))
        if code != 2:
            self.assertTrue(result.stderr.startswith("fresh-tube: "), result.stderr)
        return result.stderr


class Usage(CliTest):
    def test_help_and_usage_errors(self):
        self.assertIn("fresh-tube", self.ok("-h"))
        self.fails(2, "nope")
        self.fails(2)


LTT = "UCXuqSBlHAE6Xw-yeJA0Tunw"


class Channels(CliTest):
    def setUp(self):
        super().setUp()
        self.box.apply()

    def add(self, text, page="channel_page.html"):
        with mock.patch("fresh_tube.resolve.fetch_url", return_value=support.fixture(page)), \
             mock.patch("fresh_tube.feed.fetch_url", return_value=support.fixture("feed.xml")), \
             mock.patch("fresh_tube.resolve.ytdlp_channel_id", return_value=None), \
             support.captured() as (out, err):
            code = cli.main(["add", "--", text])
        return code, out.getvalue(), err.getvalue()

    def test_add_prints_the_channel_and_caches_its_feed(self):
        code, out, err = self.add("@LinusTechTips")
        self.assertEqual(code, 0, err)
        channel = json.loads(out)
        self.assertEqual(channel["id"], LTT)
        self.assertEqual(channel["name"], "Example Channel")
        self.assertEqual(channel["lastError"], "")
        state = self.box.read_json(self.box.state_file)
        self.assertEqual(state["feeds"][LTT]["latest"]["videoId"], "newest22222")
        listed = self.json("channels", "--json")["channels"]
        self.assertEqual([c["id"] for c in listed], [LTT])
        self.assertIn("Example Channel", self.ok("channels"))

    def test_add_errors(self):
        self.assertEqual(self.add("https://vimeo.com/x")[0], 2)
        self.assertEqual(self.add("@Nobody", page="no_id_page.html")[0], 3)
        self.assertEqual(self.add("@LinusTechTips")[0], 0)
        code, out, err = self.add("https://www.youtube.com/channel/" + LTT)
        self.assertEqual(code, 4)
        self.assertEqual(err.strip(), "fresh-tube: Already added")
        self.assertEqual(len(self.json("channels", "--json")["channels"]), 1)

    def test_add_reports_a_feed_that_cannot_be_fetched(self):
        with mock.patch("fresh_tube.resolve.fetch_url", return_value=support.fixture("channel_page.html")), \
             mock.patch("fresh_tube.feed.fetch_url", side_effect=FreshTubeError("HTTP 404 from feed", NETWORK)), \
             support.captured() as (out, err):
            self.assertEqual(cli.main(["add", "@LinusTechTips"]), 3)
        self.assertIn("HTTP 404", err.getvalue())
        self.assertEqual(self.json("channels", "--json"), {"channels": []})

    def test_remove(self):
        self.add("@LinusTechTips")
        self.assertEqual(self.json("remove", LTT), {"removed": LTT})
        self.assertEqual(self.json("channels", "--json"), {"channels": []})
        self.assertNotIn(LTT, self.box.read_json(self.box.state_file)["feeds"])
        self.assertIn("No such channel", self.fails(5, "remove", LTT))
