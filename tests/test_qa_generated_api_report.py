"""QA-facing tests for OpenAI-generated API test evidence.

These tests focus on what a QA reviewer cares about:
- Did OpenAI generate concrete executable API checks from the Jira ticket?
- Did the runner execute those generated checks?
- Did the runner catch a contract failure when the API response drifted?
- Did the full workflow run from mock Jira -> OpenAI-generated tests -> executed report?

The OpenAI call is mocked in pytest so the test suite is deterministic and does not spend tokens.
To run against the real OpenAI API, set TEST_GENERATION_MODE=openai and OPENAI_API_KEY, then run
scripts/generate_qa_report.py.
"""

import json
import os

import responses

# Set env vars before importing the server module.
os.environ["MCP_DISABLE_IMPORT"] = "1"
os.environ["JIRA_MODE"] = "mock"
os.environ["TEST_GENERATION_MODE"] = "openai"
os.environ["OPENAI_API_KEY"] = "fake-openai-key-for-pytest"
os.environ["APP_BASE_URL"] = "https://api.example.test"
os.environ["APP_API_TOKEN"] = "fake-app-token"

from src import server  # noqa: E402


OPENAI_GENERATED_TESTS = [
    {
        "name": "Create order succeeds with a valid cart",
        "method": "POST",
        "endpoint": "/api/orders",
        "headers": {"Authorization": "Bearer ${APP_API_TOKEN}"},
        "body": {"customerId": "12345", "itemId": "SKU-100", "quantity": 1},
        "expected_status": 201,
        "expected_fields": ["orderId", "status", "createdAt"],
        "traceability": "Covers: valid cart submission creates an order.",
    },
    {
        "name": "Create order rejects missing itemId",
        "method": "POST",
        "endpoint": "/api/orders",
        "headers": {"Authorization": "Bearer ${APP_API_TOKEN}"},
        "body": {"customerId": "12345", "quantity": 1},
        "expected_status": 400,
        "expected_fields": ["error", "message"],
        "traceability": "Covers: Missing itemId returns 400.",
    },
    {
        "name": "Create order rejects request without token",
        "method": "POST",
        "endpoint": "/api/orders",
        "headers": {},
        "body": {"customerId": "12345", "itemId": "SKU-100", "quantity": 1},
        "expected_status": 401,
        "expected_fields": ["error"],
        "traceability": "Covers: Requests without a token return 401.",
    },
]


class TestOpenAIGeneratedApiExecutionReport:
    """QA-facing evidence for OpenAI-generated API tests and execution results."""

    def test_openai_generates_executable_api_tests_from_mock_jira_ticket(self, monkeypatch):
        """Shows the exact API tests generated from Jira ticket content."""
        monkeypatch.setattr(
            server,
            "_call_openai_for_api_tests",
            lambda ticket: json.dumps(OPENAI_GENERATED_TESTS),
        )

        ticket = server.fetch_jira_ticket("QA-DEMO-1")
        generated_tests = server.generate_api_test_cases(ticket)

        assert [test["name"] for test in generated_tests] == [
            "Create order succeeds with a valid cart",
            "Create order rejects missing itemId",
            "Create order rejects request without token",
        ]
        assert all(test["source"] == "openai" for test in generated_tests)
        assert generated_tests[0]["method"] == "POST"
        assert generated_tests[0]["endpoint"] == "/api/orders"
        assert generated_tests[0]["expected_status"] == 201
        assert generated_tests[0]["expected_fields"] == ["orderId", "status", "createdAt"]

    @responses.activate
    def test_openai_generated_api_tests_pass_when_api_matches_expected_contract(self, monkeypatch):
        """Executes the OpenAI-generated tests and verifies all checks pass."""
        monkeypatch.setattr(
            server,
            "_call_openai_for_api_tests",
            lambda ticket: json.dumps(OPENAI_GENERATED_TESTS),
        )
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

        ticket = server.fetch_jira_ticket("QA-DEMO-1")
        generated_tests = server.generate_api_test_cases(ticket)
        report = server.run_api_tests(generated_tests)

        assert report["total"] == 3
        assert report["passed"] == 3
        assert report["failed"] == 0
        assert [result["passed"] for result in report["results"]] == [True, True, True]

    @responses.activate
    def test_openai_generated_api_test_fails_when_expected_response_field_is_missing(self):
        """Proves the API runner catches schema/contract drift in a generated check."""
        responses.post(
            "https://api.example.test/api/orders",
            json={"orderId": "ORD-1", "status": "CREATED"},
            status=201,
        )

        report = server.run_api_tests([OPENAI_GENERATED_TESTS[0]])

        assert report["total"] == 1
        assert report["passed"] == 0
        assert report["failed"] == 1
        assert report["results"][0]["missing_fields"] == ["createdAt"]

    @responses.activate
    def test_full_workflow_uses_openai_generated_tests_from_mock_jira_ticket(self, monkeypatch):
        """Runs mock Jira -> OpenAI-generated API tests -> executed QA report."""
        monkeypatch.setattr(
            server,
            "_call_openai_for_api_tests",
            lambda ticket: json.dumps(OPENAI_GENERATED_TESTS),
        )
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
        assert report["ticket"]["summary"] == "Create order API"
        assert len(report["api_test_cases"]) == 3
        assert all(test["source"] == "openai" for test in report["api_test_cases"])
        assert report["api_test_results"]["passed"] == 3
        assert report["api_test_results"]["failed"] == 0
