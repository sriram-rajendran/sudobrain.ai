import unittest

from scripts.sudobrain_mcp_server import handle


class MCPContractTests(unittest.TestCase):
    def test_tools_list_includes_core_knowledge_tools(self):
        response = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertIn("sudobrain_search", names)
        self.assertIn("sudobrain_people", names)
        self.assertIn("sudobrain_reports", names)


if __name__ == "__main__":
    unittest.main()
