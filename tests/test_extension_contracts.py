import unittest

from backend.actions.sample_workflow_action import DraftNotificationAction
from backend.ai.providers import configured_providers
from backend.connectors.asana import AsanaConnector
from backend.connectors.catalog import connector_keys, list_source_connectors
from backend.connectors.confluence import ConfluenceConnector
from backend.connectors.google_drive import GoogleDriveConnector
from backend.connectors.github import GitHubConnector
from backend.connectors.jira import JiraConnector
from backend.connectors.local_markdown import LocalMarkdownConnector
from backend.connectors.notion import NotionConnector
from backend.connectors.trello import TrelloConnector
from backend.extensions.runtime import keyword_risk_preview, list_extensions, workflow_action_preview
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

    def test_source_connector_catalog_covers_requested_sources(self):
        expected = {
            "github", "notion", "google_drive", "confluence", "jira", "asana",
            "trello", "clickup", "monday", "microsoft_teams", "zoom",
            "google_meet", "calendar", "outlook", "imap", "hubspot",
            "salesforce", "pipedrive", "intercom", "zendesk", "freshdesk",
            "help_scout", "pagerduty", "opsgenie", "incident_io", "rootly",
            "datadog", "sentry", "grafana", "posthog", "amplitude", "figma",
            "raindrop", "pocket", "browser_history", "bookmarks",
            "local_files", "terminal_activity", "voice_notes", "mobile_capture",
        }
        self.assertTrue(expected.issubset(connector_keys()))
        catalog = list_source_connectors()
        self.assertGreaterEqual(len(catalog), len(expected))
        self.assertTrue(all(item["access"] in {"read_only", "local_read_only", "local_capture"} for item in catalog))

    def test_extensions_include_source_catalog(self):
        extensions = list_extensions()
        catalog = extensions["runtime"]["source_catalog"]
        self.assertIn("github", {item["key"] for item in catalog})
        self.assertIn("github", extensions["runtime"]["connectors"])
        self.assertIn("notion", extensions["runtime"]["connectors"])
        self.assertIn("google_drive", extensions["runtime"]["connectors"])
        self.assertIn("confluence", extensions["runtime"]["connectors"])
        self.assertIn("jira", extensions["runtime"]["connectors"])
        self.assertIn("asana", extensions["runtime"]["connectors"])
        self.assertIn("trello", extensions["runtime"]["connectors"])

    def test_github_connector_normalizes_repository_activity(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeSession:
            def get(self, url, headers=None, params=None, timeout=30):
                if url.endswith("/repos/acme/widgets"):
                    return FakeResponse({"private": False, "default_branch": "main"})
                if url.endswith("/issues"):
                    return FakeResponse([
                        {
                            "number": 7,
                            "title": "Fix onboarding",
                            "body": "Users need a clearer setup path",
                            "state": "open",
                            "user": {"login": "maya"},
                            "labels": [{"name": "bug"}],
                            "html_url": "https://example.invalid/issues/7",
                            "updated_at": "2026-01-01T00:00:00Z",
                        },
                        {
                            "number": 8,
                            "title": "Add capture",
                            "body": "Adds mobile capture",
                            "state": "closed",
                            "user": {"login": "alex"},
                            "pull_request": {},
                            "labels": [],
                            "html_url": "https://example.invalid/pull/8",
                            "updated_at": "2026-01-02T00:00:00Z",
                        },
                    ])
                if url.endswith("/pulls/8/reviews"):
                    return FakeResponse([
                        {
                            "id": 99,
                            "body": "Looks good after the privacy check.",
                            "state": "APPROVED",
                            "user": {"login": "sam"},
                            "html_url": "https://example.invalid/pull/8#review",
                            "submitted_at": "2026-01-02T01:00:00Z",
                        }
                    ])
                if url.endswith("/releases"):
                    return FakeResponse([])
                if url.endswith("/commits"):
                    return FakeResponse([
                        {
                            "sha": "abc123",
                            "html_url": "https://example.invalid/commit/abc123",
                            "commit": {
                                "message": "feat: add setup",
                                "author": {"name": "Maya", "date": "2026-01-03T00:00:00Z"},
                            },
                        }
                    ])
                if url.endswith("/actions/runs"):
                    return FakeResponse({"workflow_runs": [
                        {
                            "id": 123,
                            "name": "Verify",
                            "status": "completed",
                            "conclusion": "failure",
                            "head_branch": "main",
                            "head_sha": "abc123",
                            "actor": {"login": "ci"},
                            "html_url": "https://example.invalid/actions/runs/123",
                            "updated_at": "2026-01-04T00:00:00Z",
                        }
                    ]})
                return FakeResponse({})

            def post(self, url, headers=None, json=None, timeout=30):
                return FakeResponse({"skipped": "no discussions"})

        connector = GitHubConnector("acme/widgets", session=FakeSession())
        self.assertTrue(connector.health()["ok"])
        docs = list(connector.fetch(limit=10))
        kinds = {doc.metadata["kind"] for doc in docs}
        self.assertTrue({"issue", "pull_request", "pull_request_review", "commit", "ci_failure"}.issubset(kinds))

    def test_github_health_redacts_token(self):
        class FailingSession:
            def get(self, *args, **kwargs):
                raise RuntimeError("network unavailable")

        connector = GitHubConnector("acme/widgets", token="secret", session=FailingSession())
        health = connector.health()
        self.assertTrue(health["token_configured"])
        self.assertNotIn("secret", str(health))

    def test_notion_connector_normalizes_search_results(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeSession:
            def get(self, url, headers=None, timeout=30):
                return FakeResponse({"bot": {"workspace_name": "Demo"}})

            def post(self, url, headers=None, json=None, timeout=30):
                return FakeResponse({
                    "results": [
                        {
                            "object": "page",
                            "id": "page-1",
                            "url": "https://example.invalid/notion/page-1",
                            "created_time": "2026-01-01T00:00:00Z",
                            "last_edited_time": "2026-01-02T00:00:00Z",
                            "created_by": {"id": "u1"},
                            "last_edited_by": {"id": "u2"},
                            "properties": {
                                "Name": {
                                    "type": "title",
                                    "title": [{"plain_text": "Launch plan"}],
                                },
                                "Status": {
                                    "type": "select",
                                    "select": {"name": "Ready"},
                                },
                            },
                        }
                    ]
                })

        connector = NotionConnector(token="secret", session=FakeSession())
        self.assertTrue(connector.health()["ok"])
        docs = list(connector.fetch(limit=5))
        self.assertEqual(docs[0].title, "Launch plan")
        self.assertIn("Status: Ready", docs[0].text)
        self.assertNotIn("secret", str(connector.health()))

    def test_google_drive_connector_normalizes_files(self):
        class FakeResponse:
            headers = {"content-type": "application/json"}

            def __init__(self, payload, text=""):
                self.payload = payload
                self.text = text

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class TextResponse(FakeResponse):
            headers = {"content-type": "text/plain"}

            def json(self):
                raise ValueError("not json")

        class FakeSession:
            def get(self, url, headers=None, params=None, timeout=30):
                if url.endswith("/about"):
                    return FakeResponse({"user": {"emailAddress": "demo@example.invalid"}})
                if url.endswith("/files"):
                    return FakeResponse({"files": [
                        {
                            "id": "doc-1",
                            "name": "Launch spec",
                            "mimeType": "application/vnd.google-apps.document",
                            "webViewLink": "https://example.invalid/doc-1",
                            "modifiedTime": "2026-01-03T00:00:00Z",
                            "createdTime": "2026-01-01T00:00:00Z",
                            "owners": [{"displayName": "Maya"}],
                        }
                    ]})
                if url.endswith("/files/doc-1/export"):
                    return TextResponse({}, text="Decision log and launch plan")
                return FakeResponse({})

        connector = GoogleDriveConnector(token="secret", session=FakeSession())
        self.assertTrue(connector.health()["ok"])
        docs = list(connector.fetch(limit=5))
        self.assertEqual(docs[0].title, "Launch spec")
        self.assertIn("Decision log", docs[0].text)
        self.assertEqual(docs[0].metadata["kind"], "doc")
        self.assertNotIn("secret", str(connector.health()))

    def test_confluence_connector_normalizes_pages(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeSession:
            def get(self, url, headers=None, params=None, timeout=30):
                if url.endswith("/api/v2/spaces"):
                    return FakeResponse({"results": [{"id": "space-1"}]})
                if url.endswith("/api/v2/pages"):
                    return FakeResponse({
                        "results": [
                            {
                                "id": "page-1",
                                "title": "Runbook",
                                "spaceId": "space-1",
                                "status": "current",
                                "authorId": "author-1",
                                "createdAt": "2026-01-01T00:00:00Z",
                                "version": {"number": 3, "createdAt": "2026-01-03T00:00:00Z", "authorId": "author-2"},
                                "body": {"storage": {"value": "<p>Restart service after deploy.</p>"}},
                                "_links": {"webui": "/wiki/spaces/ENG/pages/page-1"},
                            }
                        ]
                    })
                return FakeResponse({})

        connector = ConfluenceConnector(
            base_url="https://example.invalid",
            email="demo@example.invalid",
            token="secret",
            session=FakeSession(),
        )
        self.assertTrue(connector.health()["ok"])
        docs = list(connector.fetch(limit=5))
        self.assertEqual(docs[0].title, "Runbook")
        self.assertIn("Restart service", docs[0].text)
        self.assertEqual(docs[0].metadata["kind"], "page")
        self.assertNotIn("secret", str(connector.health()))

    def test_jira_connector_normalizes_issues(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeSession:
            def get(self, url, headers=None, params=None, timeout=30):
                if url.endswith("/rest/api/3/myself"):
                    return FakeResponse({"accountType": "atlassian"})
                if url.endswith("/rest/api/3/search"):
                    return FakeResponse({
                        "issues": [
                            {
                                "id": "10001",
                                "key": "ENG-7",
                                "fields": {
                                    "summary": "Fix sprint blocker",
                                    "description": {"content": [{"content": [{"text": "Database migration is blocked."}]}]},
                                    "status": {"name": "In Progress"},
                                    "assignee": {"displayName": "Maya"},
                                    "reporter": {"displayName": "Alex"},
                                    "project": {"key": "ENG"},
                                    "issuetype": {"name": "Bug"},
                                    "priority": {"name": "High"},
                                    "labels": ["blocker"],
                                    "updated": "2026-01-04T00:00:00Z",
                                    "created": "2026-01-01T00:00:00Z",
                                    "parent": {"key": "ENG-1"},
                                    "customfield_10020": [{"name": "Sprint 12"}],
                                    "comment": {"comments": [
                                        {
                                            "author": {"displayName": "Sam"},
                                            "body": {"content": [{"content": [{"text": "Waiting on deploy window."}]}]},
                                        }
                                    ]},
                                },
                            }
                        ]
                    })
                return FakeResponse({})

        connector = JiraConnector(
            base_url="https://example.invalid",
            email="demo@example.invalid",
            token="secret",
            session=FakeSession(),
        )
        self.assertTrue(connector.health()["ok"])
        docs = list(connector.fetch(limit=5))
        self.assertEqual(docs[0].title, "Fix sprint blocker")
        self.assertIn("Database migration", docs[0].text)
        self.assertIn("Waiting on deploy window", docs[0].text)
        self.assertEqual(docs[0].metadata["key"], "ENG-7")
        self.assertNotIn("secret", str(connector.health()))

    def test_asana_connector_normalizes_tasks(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeSession:
            def get(self, url, headers=None, params=None, timeout=30):
                if url.endswith("/" + "users" + "/me"):
                    return FakeResponse({"data": {"gid": "user-1"}})
                if url.endswith("/tasks"):
                    return FakeResponse({"data": [
                        {
                            "gid": "task-1",
                            "name": "Ship launch checklist",
                            "notes": "Confirm onboarding and docs.",
                            "completed": False,
                            "created_at": "2026-01-01T00:00:00Z",
                            "modified_at": "2026-01-04T00:00:00Z",
                            "due_on": "2026-01-07",
                            "permalink_url": "https://example.invalid/asana/task-1",
                            "assignee": {"gid": "user-1", "name": "Maya"},
                            "projects": [{"gid": "project-1", "name": "Launch"}],
                            "memberships": [{"section": {"name": "Ready"}}],
                        }
                    ]})
                return FakeResponse({})

        connector = AsanaConnector(token="secret", workspace_gid="workspace-1", session=FakeSession())
        self.assertTrue(connector.health()["ok"])
        docs = list(connector.fetch(limit=5))
        self.assertEqual(docs[0].title, "Ship launch checklist")
        self.assertIn("Confirm onboarding", docs[0].text)
        self.assertEqual(docs[0].metadata["projects"], ["Launch"])
        self.assertNotIn("secret", str(connector.health()))

    def test_trello_connector_normalizes_cards(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeSession:
            def get(self, url, params=None, timeout=30):
                if url.endswith("/members/me"):
                    return FakeResponse({"username": "maya"})
                if url.endswith("/boards/board-1/cards"):
                    return FakeResponse([
                        {
                            "id": "card-1",
                            "name": "Review launch board",
                            "desc": "Check blockers before release.",
                            "due": "2026-01-08T00:00:00Z",
                            "dueComplete": False,
                            "dateLastActivity": "2026-01-04T00:00:00Z",
                            "shortUrl": "https://example.invalid/c/card-1",
                            "idBoard": "board-1",
                            "idList": "list-1",
                            "labels": [{"name": "blocker"}],
                            "members": [{"fullName": "Maya"}],
                            "actions": [
                                {
                                    "data": {"text": "Need owner assignment."},
                                    "memberCreator": {"fullName": "Alex"},
                                }
                            ],
                        }
                    ])
                return FakeResponse([])

        connector = TrelloConnector(api_key="key", token="secret", board_id="board-1", session=FakeSession())
        self.assertTrue(connector.health()["ok"])
        docs = list(connector.fetch(limit=5))
        self.assertEqual(docs[0].title, "Review launch board")
        self.assertIn("Need owner assignment", docs[0].text)
        self.assertEqual(docs[0].metadata["labels"], ["blocker"])
        self.assertNotIn("secret", str(connector.health()))


if __name__ == "__main__":
    unittest.main()
