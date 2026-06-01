import unittest

from backend.mcp_client import list_mcp_tools, preview_tool_call
from scripts.sudobrain_mcp_server import handle


class MCPContractTests(unittest.TestCase):
    def test_tools_list_includes_core_knowledge_tools(self):
        response = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertIn("sudobrain_search", names)
        self.assertIn("sudobrain_people", names)
        self.assertIn("sudobrain_reports", names)

    def test_client_tool_preview_is_dry_run(self):
        tools = list_mcp_tools()
        names = {tool["name"] for tool in tools["builtin"]}
        self.assertIn("sudobrain_search", names)

        preview = preview_tool_call("sudobrain_search", {"query": "Atlas"})
        self.assertEqual(preview["status"], "preview")
        self.assertTrue(preview["dry_run"])
        self.assertFalse(preview["would_execute"])


if __name__ == "__main__":
    unittest.main()
