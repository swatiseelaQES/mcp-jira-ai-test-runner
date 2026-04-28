import importlib
import os

import pytest
import responses

# Set env vars before importing the server module.
os.environ["MCP_DISABLE_IMPORT"] = "1"
os.environ["JIRA_MODE"] = "mock"
os.environ["APP_BASE_URL"] = "https://api.example.test"
os.environ["APP_API_TOKEN"] = "fake-app-token"

from src import server  # noqa: E402


class TestMockJiraSource:
    """Tests that prove the demo can run without a real Jira instance."""

    def test_mock_jira_lists_available_demo_tickets(self):
        """Verifies that the fake Jira source exposes seeded demo tickets."""
        tickets = server.list_mock_jira_tickets()

        assert len(tickets) >= 2
        assert tickets[0]["key"].startswith("QA-DEMO-")
        assert "summary" in tickets[0]

    def test_mock_jira_fetches_known_ticket_with_requirements_fields(self):
        """Verifies that QA-DEMO-1 returns story details used for test generation."""
        ticket = server.fetch_jira_ticket("QA-DEMO-1")

        assert ticket["key"] == "QA-DEMO-1"
        assert ticket["summary"] == "Create order API"
        assert ticket["status"] == "Ready for QA"
        assert "Missing itemId returns 400" in ticket["acceptance_criteria"]

    def test_mock_jira_rejects_unknown_ticket_key(self):
        """Verifies that invalid ticket keys fail clearly instead of returning fake data."""
        with pytest.raises(ValueError, match="Unknown mock ticket"):
            server.fetch_jira_ticket("QA-DEMO-999")


class TestGeneratedTestDesign:
    """Tests that prove the AI-assist workflow creates traceable test intent."""

    def test_jira_story_generates_three_functional_scenarios(self):
        """Verifies happy path, validation, and permission scenarios are generated."""
        ticket = server.fetch_jira_ticket("QA-DEMO-1")

        scenarios = server.generate_functional_scenarios(ticket)

        assert len(scenarios) == 3
        assert "Happy path" in scenarios[0]["scenario"]
        assert scenarios[0]["given"]
        assert scenarios[0]["when"]
        assert scenarios[0]["then"]
        assert scenarios[0]["traceability"] == "QA-DEMO-1"

    def test_jira_story_generates_three_api_test_cases(self):
        """Verifies API checks are generated for success, validation, and auth failure."""
        ticket = server.fetch_jira_ticket("QA-DEMO-1")

        tests = server.generate_api_test_cases(ticket)

        assert len(tests) == 3
        assert tests[0]["name"] == "API happy path - Create order API"
        assert tests[0]["method"] == "POST"
        assert tests[0]["endpoint"] == "/api/orders"
        assert tests[0]["expected_status"] == 201
        assert tests[1]["expected_status"] == 400
        assert tests[2]["expected_status"] == 401


class TestRealJiraIntegrationContract:
    """Tests that prove real Jira mode can parse Jira Cloud responses."""

    @responses.activate
    def test_real_jira_mode_fetches_ticket_from_jira_cloud_api(self, monkeypatch):
        """Verifies the Jira REST API integration without calling a real Atlassian site."""
        monkeypatch.setenv("JIRA_MODE", "real")
        monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "tester@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "fake-jira-token")
        monkeypatch.setenv("JIRA_ACCEPTANCE_CRITERIA_FIELD", "customfield_12345")

        importlib.reload(server)

        responses.get(
            "https://example.atlassian.net/rest/api/3/issue/PROJ-123",
            json={
                "key": "PROJ-123",
                "fields": {
                    "summary": "Create order API",
                    "description": "As a customer, I want to create an order.",
                    "status": {"name": "Ready for QA"},
                    "issuetype": {"name": "Story"},
                    "customfield_12345": "Order is created successfully.",
                },
            },
            status=200,
        )

        ticket = server.fetch_jira_ticket("PROJ-123")

        assert ticket["key"] == "PROJ-123"
        assert ticket["summary"] == "Create order API"
        assert ticket["status"] == "Ready for QA"
        assert ticket["acceptance_criteria"] == "Order is created successfully."

        monkeypatch.setenv("JIRA_MODE", "mock")
        importlib.reload(server)


class TestApiExecutionEngine:
    """Tests that prove generated API checks are actually executed and evaluated."""

    @responses.activate
    def test_api_runner_reports_all_generated_tests_as_passed(self):
        """Verifies status-code and response-field checks pass for three mocked API calls."""
        responses.post(
            "https://api.example.test/api/orders",
            json={"orderId": "ORD-1", "status": "CREATED", "createdAt": "2026-04-28T12:00:00Z"},
            status=201,
        )
        responses.post(
            "https://api.example.test/api/orders",
            json={"error": "Bad Request", "message": "itemId is required"},
            status=400,
        )
        responses.post(
            "https://api.example.test/api/orders",
            json={"error": "Unauthorized"},
            status=401,
        )

        test_cases = server.generate_api_test_cases({"summary": "Create order API"})
        report = server.run_api_tests(test_cases)

        assert report["total"] == 3
        assert report["passed"] == 3
        assert report["failed"] == 0
        assert [result["passed"] for result in report["results"]] == [True, True, True]

    @responses.activate
    def test_api_runner_fails_when_expected_response_field_is_missing(self):
        """Verifies the runner catches schema/contract drift in an API response."""
        responses.post(
            "https://api.example.test/api/orders",
            json={"orderId": "ORD-1", "status": "CREATED"},
            status=201,
        )

        report = server.run_api_tests(
            [
                {
                    "name": "Create order happy path",
                    "method": "POST",
                    "endpoint": "/api/orders",
                    "headers": {"Authorization": "Bearer ${APP_API_TOKEN}"},
                    "body": {"customerId": "12345", "itemId": "SKU-100", "quantity": 1},
                    "expected_status": 201,
                    "expected_fields": ["orderId", "status", "createdAt"],
                }
            ]
        )

        assert report["total"] == 1
        assert report["passed"] == 0
        assert report["failed"] == 1
        assert report["results"][0]["missing_fields"] == ["createdAt"]

    @responses.activate
    def test_full_workflow_fetches_mock_jira_generates_and_runs_api_tests(self):
        """Verifies the complete demo path from Jira ticket to executed test report."""
        responses.post(
            "https://api.example.test/api/orders",
            json={"orderId": "ORD-1", "status": "CREATED", "createdAt": "2026-04-28T12:00:00Z"},
            status=201,
        )
        responses.post(
            "https://api.example.test/api/orders",
            json={"error": "Bad Request", "message": "itemId is required"},
            status=400,
        )
        responses.post(
            "https://api.example.test/api/orders",
            json={"error": "Unauthorized"},
            status=401,
        )

        report = server.generate_and_run_tests_from_jira("QA-DEMO-1")

        assert report["ticket"]["key"] == "QA-DEMO-1"
        assert len(report["generated_test_cases"]) == 3
        assert report["test_results"]["passed"] == 3
