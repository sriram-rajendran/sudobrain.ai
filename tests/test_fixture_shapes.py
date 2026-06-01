import json
import unittest
from pathlib import Path


FIXTURES = Path(__file__).parent / "fixtures"


class FixtureShapeTests(unittest.TestCase):
    def load(self, name):
        return json.loads((FIXTURES / name).read_text())

    def test_slack_fixture_is_high_signal(self):
        payload = self.load("slack_message.json")
        text = payload["message"]["text"].lower()
        self.assertIn("decision", text)
        self.assertIn("will", text)
        self.assertIn("channel", payload)

    def test_gmail_fixture_is_valid(self):
        payload = self.load("gmail_message.json")
        self.assertIn("@example.test", payload["from"])
        self.assertGreater(len(payload["body"]), 30)
        self.assertEqual(payload["labels"], ["INBOX"])

    def test_fathom_fixture_builds_segments(self):
        payload = self.load("fathom_meeting.json")
        transcript_text = "\n".join(item["text"] for item in payload["transcript"])
        self.assertIn("web companion", transcript_text)
        self.assertEqual(len(payload["transcript"]), 2)

    def test_linear_fixture_has_required_shape(self):
        payload = self.load("linear_issue.json")
        self.assertEqual(payload["project"]["name"], "Open Source Readiness")
        self.assertIn("description", payload)


if __name__ == "__main__":
    unittest.main()
