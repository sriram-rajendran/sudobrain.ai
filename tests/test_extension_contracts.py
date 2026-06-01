import unittest

from backend.actions.sample_workflow_action import DraftNotificationAction
from backend.ai.providers import configured_providers
from backend.connectors.local_markdown import LocalMarkdownConnector
from backend.extensions.runtime import keyword_risk_preview, workflow_action_preview
from backend.intelligence.sample_module import KeywordRiskModule
from backend.sdk import SourceDocument


class ExtensionContractTests(unittest.TestCase):
    def test_provider_config_is_safe(self):
        config = configured_providers()
        self.assertIn("providers", config)
        text = str(config)
        self.assertNotIn("API_KEY=", text)

    def test_markdown_connector_health_for_missing_folder(self):
        connector = LocalMarkdownConnector("/tmp/sudobrain-missing-folder")
        health = connector.health()
        self.assertFalse(health["ok"])

    def test_sample_module_emits_risk_signal(self):
        module = KeywordRiskModule()
        docs = [SourceDocument(source="test", external_id="1", title="Plan", text="Launch delay risk")]
        items = list(module.analyze(docs))
        self.assertEqual(items[0].kind, "risk_signal")

    def test_sample_action_requires_approval(self):
        action = DraftNotificationAction()
        result = action.run({"title": "Review", "body": "Check risk"}, dry_run=True)
        self.assertTrue(result.requires_approval)
        self.assertEqual(result.status, "preview")

    def test_extension_runtime_previews_are_dry_run(self):
        risk = keyword_risk_preview([
            {"source": "test", "external_id": "1", "title": "Plan", "text": "Launch delay risk"}
        ])
        self.assertEqual(risk["items"][0]["kind"], "risk_signal")

        action = workflow_action_preview({"title": "Review", "body": "Check risk"})
        self.assertTrue(action["dry_run"])
        self.assertTrue(action["requires_approval"])


if __name__ == "__main__":
    unittest.main()
