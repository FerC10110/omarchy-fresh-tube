import json
import unittest

import support


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
