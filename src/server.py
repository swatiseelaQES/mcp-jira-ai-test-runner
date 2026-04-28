"""
MCP Jira AI Test Runner

QA-focused MCP workflow:
1. Fetch a Jira ticket from mock data or real Jira.
2. Generate functional scenarios and API test cases.
3. Optionally call OpenAI to generate API test definitions from the Jira ticket.
4. Execute generated API tests against a configured test environment.
5. Return JSON and HTML QA reports.

This version includes live Restful Booker demo tickets and workflow-style API tests.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx
import requests


class _NoOpMcp:
    """Tiny fallback used by unit tests when MCP import is disabled."""

    def __init__(self, name: str):
        self.name = name

    def tool(self):
        def decorator(func):
            return func

        return decorator

    def run(self) -> None:
        raise RuntimeError("MCP import is disabled. Unset MCP_DISABLE_IMPORT to run the server.")


if os.getenv("MCP_DISABLE_IMPORT") == "1":
    mcp = _NoOpMcp("jira-ai-test-runner")
else:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("jira-ai-test-runner")


RESTFUL_BOOKER_BASE_URL = "https://restful-booker.herokuapp.com"
BOOKING_PAYLOAD = {
    "firstname": "Jim",
    "lastname": "Brown",
    "totalprice": 111,
    "depositpaid": True,
    "bookingdates": {"checkin": "2026-05-01", "checkout": "2026-05-05"},
    "additionalneeds": "Breakfast",
}
UPDATED_BOOKING_PAYLOAD = {
    "firstname": "James",
    "lastname": "Brown",
    "totalprice": 222,
    "depositpaid": False,
    "bookingdates": {"checkin": "2026-06-01", "checkout": "2026-06-05"},
    "additionalneeds": "Dinner",
}

MOCK_JIRA_TICKETS: dict[str, dict[str, Any]] = {
    "QA-DEMO-1": {
        "key": "QA-DEMO-1",
        "summary": "Create order API",
        "description": "As a customer, I want to create an order so that I can purchase items in my cart.",
        "status": "Ready for QA",
        "issue_type": "Story",
        "acceptance_criteria": (
            "Given a customer has a valid cart, when they submit an order, then an order is created. "
            "Missing itemId returns 400. Requests without a token return 401."
        ),
    },
    "QA-DEMO-2": {
        "key": "QA-DEMO-2",
        "summary": "Prevent duplicate order submission",
        "description": "As a customer, I should not be charged twice if I submit the same order more than once.",
        "status": "In Progress",
        "issue_type": "Bug",
        "acceptance_criteria": (
            "Duplicate requests with the same idempotency key should return the original order response. "
            "Duplicate requests must not create a second payment or second order."
        ),
    },
    "RB-1": {
        "key": "RB-1",
        "summary": "Restful Booker - create booking",
        "description": "As an API consumer, I want to create a hotel booking using POST /booking.",
        "status": "Ready for QA",
        "issue_type": "Story",
        "acceptance_criteria": (
            "POST /booking with a valid JSON payload returns 200 and includes bookingid and booking. "
            "The returned booking should preserve firstname, lastname, price, dates, and additional needs."
        ),
        "api_under_test": "restful-booker",
    },
    "RB-2": {
        "key": "RB-2",
        "summary": "Restful Booker - retrieve booking",
        "description": "As an API consumer, I want to retrieve a booking by id using GET /booking/{id}.",
        "status": "Ready for QA",
        "issue_type": "Story",
        "acceptance_criteria": (
            "After a booking is created, GET /booking/{id} returns 200 and the booking details. "
            "A missing booking id should return 404."
        ),
        "api_under_test": "restful-booker",
    },
    "RB-3": {
        "key": "RB-3",
        "summary": "Restful Booker - update booking requires auth",
        "description": "As an authenticated API consumer, I want to update an existing booking using PUT /booking/{id}.",
        "status": "Ready for QA",
        "issue_type": "Story",
        "acceptance_criteria": (
            "POST /auth returns a token. PUT /booking/{id} with Cookie token updates the booking and returns 200. "
            "PUT /booking/{id} without authorization returns 403."
        ),
        "api_under_test": "restful-booker",
    },
    "RB-4": {
        "key": "RB-4",
        "summary": "Restful Booker - partial update booking",
        "description": "As an authenticated API consumer, I want to partially update a booking using PATCH /booking/{id}.",
        "status": "Ready for QA",
        "issue_type": "Story",
        "acceptance_criteria": (
            "PATCH /booking/{id} with Cookie token updates selected fields and returns 200. "
            "Unchanged fields should remain available in the response."
        ),
        "api_under_test": "restful-booker",
    },
    "RB-5": {
        "key": "RB-5",
        "summary": "Restful Booker - delete booking requires auth",
        "description": "As an authenticated API consumer, I want to delete an existing booking using DELETE /booking/{id}.",
        "status": "Ready for QA",
        "issue_type": "Story",
        "acceptance_criteria": (
            "DELETE /booking/{id} with Cookie token returns 201. A subsequent GET /booking/{id} returns 404. "
            "DELETE without authorization returns 403."
        ),
        "api_under_test": "restful-booker",
    },
}


@dataclass(frozen=True)
class Settings:
    jira_mode: str = os.getenv("JIRA_MODE", "mock").lower()
    jira_base_url: str | None = os.getenv("JIRA_BASE_URL")
    jira_email: str | None = os.getenv("JIRA_EMAIL")
    jira_api_token: str | None = os.getenv("JIRA_API_TOKEN")
    jira_acceptance_criteria_field: str = os.getenv("JIRA_ACCEPTANCE_CRITERIA_FIELD", "customfield_12345")
    app_base_url: str | None = os.getenv("APP_BASE_URL")
    app_api_token: str | None = os.getenv("APP_API_TOKEN")
    test_generation_mode: str = os.getenv("TEST_GENERATION_MODE", "rule").lower()
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.2")
    verify_ssl: bool = os.getenv("VERIFY_SSL", "true").strip().lower() not in {"0", "false", "no", "off"}


settings = Settings()


def _require(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _extract_jira_text(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text_parts: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("type") == "text" and "text" in node:
                    text_parts.append(node["text"])
                for child in node.get("content", []):
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(value)
        return " ".join(text_parts)
    return str(value)


@mcp.tool()
def list_mock_jira_tickets() -> list[dict[str, str]]:
    """List available mock Jira tickets for demos and local testing."""
    return [
        {"key": t["key"], "summary": t["summary"], "status": t["status"], "issue_type": t["issue_type"]}
        for t in MOCK_JIRA_TICKETS.values()
    ]


def _fetch_mock_jira_ticket(ticket_key: str) -> dict[str, Any]:
    try:
        return MOCK_JIRA_TICKETS[ticket_key]
    except KeyError as error:
        available = ", ".join(MOCK_JIRA_TICKETS)
        raise ValueError(f"Unknown mock ticket '{ticket_key}'. Available tickets: {available}") from error


def _fetch_real_jira_ticket(ticket_key: str) -> dict[str, Any]:
    jira_base_url = _require(settings.jira_base_url, "JIRA_BASE_URL")
    jira_email = _require(settings.jira_email, "JIRA_EMAIL")
    jira_api_token = _require(settings.jira_api_token, "JIRA_API_TOKEN")
    url = f"{jira_base_url.rstrip('/')}/rest/api/3/issue/{ticket_key}"
    response = requests.get(url, auth=(jira_email, jira_api_token), headers={"Accept": "application/json"}, timeout=10)
    response.raise_for_status()
    issue = response.json()
    fields = issue.get("fields", {})
    return {
        "key": issue.get("key"),
        "summary": fields.get("summary"),
        "description": _extract_jira_text(fields.get("description")),
        "status": fields.get("status", {}).get("name"),
        "issue_type": fields.get("issuetype", {}).get("name"),
        "acceptance_criteria": _extract_jira_text(fields.get(settings.jira_acceptance_criteria_field)),
    }


@mcp.tool()
def fetch_jira_ticket(ticket_key: str) -> dict[str, Any]:
    """Fetch a Jira ticket by key. Defaults to mock mode."""
    if settings.jira_mode == "mock":
        return _fetch_mock_jira_ticket(ticket_key)
    if settings.jira_mode == "real":
        return _fetch_real_jira_ticket(ticket_key)
    raise ValueError("JIRA_MODE must be either 'mock' or 'real'")


@mcp.tool()
def generate_functional_scenarios(ticket: dict[str, Any]) -> list[dict[str, str]]:
    """Generate functional test scenarios from a Jira ticket."""
    summary = ticket.get("summary") or "Unknown feature"
    acceptance = ticket.get("acceptance_criteria") or ""
    return [
        {
            "scenario": f"Happy path validation for: {summary}",
            "given": "The API consumer sends valid request data.",
            "when": "The API endpoint is called.",
            "then": "The API returns the expected success status and contract fields.",
            "traceability": acceptance,
        },
        {
            "scenario": f"Negative or authorization validation for: {summary}",
            "given": "The API consumer sends missing, invalid, or unauthorized input.",
            "when": "The API endpoint is called.",
            "then": "The API rejects the request with the expected error status and no sensitive leakage.",
            "traceability": acceptance,
        },
    ]


def _normalize_path(path: str) -> str:
    """Normalize simple JSONPath-style paths into dot paths.

    The OpenAI-generated tests may use paths like "$.bookingid" while
    the runner internally expects paths like "bookingid". This keeps the
    generated test format and the execution engine compatible.
    """
    path = str(path)
    if path.startswith("$."):
        return path[2:]
    if path.startswith("$"):
        return path[1:]
    return path


def _get_by_path(data: Any, path: str) -> Any:
    path = _normalize_path(path)
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current

def _extract_variable(data: Any, path: str) -> Any:
    return _get_by_path(data, path)


def _replace_placeholders(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            return str(variables.get(name, match.group(0)))

        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, value)
    if isinstance(value, dict):
        return {k: _replace_placeholders(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_placeholders(v, variables) for v in value]
    return value


def _normalize_test(test: dict[str, Any], source: str = "openai") -> dict[str, Any]:
    expected_fields = test.get("expected_fields", [])
    expected_field_paths = test.get("expected_field_paths", expected_fields)
    return {
        "name": str(test["name"]),
        "method": str(test["method"]).upper(),
        "endpoint": str(test["endpoint"]),
        "headers": test.get("headers") or {},
        "body": test.get("body") or {},
        "expected_status": int(test["expected_status"]),
        "expected_fields": [str(field) for field in expected_fields],
        "expected_field_paths": [str(field) for field in expected_field_paths],
        "setup_steps": test.get("setup_steps", []),
        "follow_up_steps": test.get("follow_up_steps", []),
        "source": test.get("source", source),
        "traceability": test.get("traceability", "Generated from Jira ticket content."),
    }


def _validate_api_test_cases(test_cases: Any) -> list[dict[str, Any]]:
    if not isinstance(test_cases, list) or not test_cases:
        raise ValueError("OpenAI must return a non-empty JSON array of API test cases.")
    required_fields = {"name", "method", "endpoint", "headers", "body", "expected_status", "expected_fields"}
    validated: list[dict[str, Any]] = []
    for index, test in enumerate(test_cases, start=1):
        if not isinstance(test, dict):
            raise ValueError(f"Test case {index} must be a JSON object.")
        missing = sorted(required_fields - set(test))
        if missing:
            raise ValueError(f"Test case {index} is missing required fields: {missing}")
        if not str(test["endpoint"]).startswith("/"):
            raise ValueError(f"Test case {index} endpoint must start with '/'.")
        validated.append(_normalize_test(test))
    return validated


def _restful_booker_test_cases(ticket: dict[str, Any]) -> list[dict[str, Any]]:
    key = ticket.get("key")
    if key == "RB-1":
        return [_normalize_test({
            "name": "Create booking returns booking id and booking contract",
            "method": "POST", "endpoint": "/booking", "headers": {"Content-Type": "application/json", "Accept": "application/json"},
            "body": BOOKING_PAYLOAD, "expected_status": 200, "expected_fields": ["bookingid", "booking"],
            "expected_field_paths": ["bookingid", "booking.firstname", "booking.lastname", "booking.bookingdates.checkin"],
            "traceability": ticket["acceptance_criteria"], "source": "rule_restful_booker",
        }, source="rule_restful_booker")]
    if key == "RB-2":
        return [
            _normalize_test({
                "name": "Get booking returns details for a newly created booking",
                "setup_steps": [{"name": "Create booking fixture", "method": "POST", "endpoint": "/booking", "headers": {"Content-Type": "application/json", "Accept": "application/json"}, "body": BOOKING_PAYLOAD, "extract": {"bookingid": "bookingid"}}],
                "method": "GET", "endpoint": "/booking/${bookingid}", "headers": {"Accept": "application/json"}, "body": {},
                "expected_status": 200, "expected_fields": ["firstname", "lastname", "bookingdates"],
                "expected_field_paths": ["firstname", "lastname", "bookingdates.checkin", "bookingdates.checkout"],
                "traceability": "After a booking is created, GET /booking/{id} returns 200 and booking details.", "source": "rule_restful_booker",
            }, source="rule_restful_booker"),
            _normalize_test({
                "name": "Get booking returns 404 for a missing booking id",
                "method": "GET", "endpoint": "/booking/999999999", "headers": {"Accept": "application/json"}, "body": {},
                "expected_status": 404, "expected_fields": [], "expected_field_paths": [],
                "traceability": "A missing booking id should return 404.", "source": "rule_restful_booker",
            }, source="rule_restful_booker"),
        ]
    if key == "RB-3":
        setup = [
            {"name": "Create auth token", "method": "POST", "endpoint": "/auth", "headers": {"Content-Type": "application/json"}, "body": {"username": "admin", "password": "password123"}, "extract": {"token": "token"}},
            {"name": "Create booking fixture", "method": "POST", "endpoint": "/booking", "headers": {"Content-Type": "application/json", "Accept": "application/json"}, "body": BOOKING_PAYLOAD, "extract": {"bookingid": "bookingid"}},
        ]
        return [
            _normalize_test({"name": "Update booking succeeds with valid auth token", "setup_steps": setup, "method": "PUT", "endpoint": "/booking/${bookingid}", "headers": {"Content-Type": "application/json", "Accept": "application/json", "Cookie": "token=${token}"}, "body": UPDATED_BOOKING_PAYLOAD, "expected_status": 200, "expected_fields": ["firstname", "lastname", "totalprice"], "expected_field_paths": ["firstname", "lastname", "totalprice", "bookingdates.checkin"], "traceability": "PUT with Cookie token updates the booking and returns 200.", "source": "rule_restful_booker"}, source="rule_restful_booker"),
            _normalize_test({"name": "Update booking without auth is rejected", "setup_steps": [setup[1]], "method": "PUT", "endpoint": "/booking/${bookingid}", "headers": {"Content-Type": "application/json", "Accept": "application/json"}, "body": UPDATED_BOOKING_PAYLOAD, "expected_status": 403, "expected_fields": [], "expected_field_paths": [], "traceability": "PUT without authorization returns 403.", "source": "rule_restful_booker"}, source="rule_restful_booker"),
        ]
    if key == "RB-4":
        return [_normalize_test({"name": "Partial update changes selected booking fields", "setup_steps": [{"name": "Create auth token", "method": "POST", "endpoint": "/auth", "headers": {"Content-Type": "application/json"}, "body": {"username": "admin", "password": "password123"}, "extract": {"token": "token"}}, {"name": "Create booking fixture", "method": "POST", "endpoint": "/booking", "headers": {"Content-Type": "application/json", "Accept": "application/json"}, "body": BOOKING_PAYLOAD, "extract": {"bookingid": "bookingid"}}], "method": "PATCH", "endpoint": "/booking/${bookingid}", "headers": {"Content-Type": "application/json", "Accept": "application/json", "Cookie": "token=${token}"}, "body": {"firstname": "Jane", "totalprice": 333}, "expected_status": 200, "expected_fields": ["firstname", "lastname", "totalprice"], "expected_field_paths": ["firstname", "lastname", "totalprice", "bookingdates.checkin"], "traceability": ticket["acceptance_criteria"], "source": "rule_restful_booker"}, source="rule_restful_booker")]
    if key == "RB-5":
        return [_normalize_test({"name": "Delete booking removes created booking", "setup_steps": [{"name": "Create auth token", "method": "POST", "endpoint": "/auth", "headers": {"Content-Type": "application/json"}, "body": {"username": "admin", "password": "password123"}, "extract": {"token": "token"}}, {"name": "Create booking fixture", "method": "POST", "endpoint": "/booking", "headers": {"Content-Type": "application/json", "Accept": "application/json"}, "body": BOOKING_PAYLOAD, "extract": {"bookingid": "bookingid"}}], "method": "DELETE", "endpoint": "/booking/${bookingid}", "headers": {"Cookie": "token=${token}"}, "body": {}, "expected_status": 201, "expected_fields": [], "expected_field_paths": [], "follow_up_steps": [{"name": "Confirm deleted booking is not retrievable", "method": "GET", "endpoint": "/booking/${bookingid}", "headers": {"Accept": "application/json"}, "body": {}, "expected_status": 404}], "traceability": ticket["acceptance_criteria"], "source": "rule_restful_booker"}, source="rule_restful_booker")]
    return []


def _fallback_api_test_cases(ticket: dict[str, Any]) -> list[dict[str, Any]]:
    restful_booker = _restful_booker_test_cases(ticket)
    if restful_booker:
        return restful_booker
    summary = ticket.get("summary") or "Unknown feature"
    return [
        _normalize_test({"name": f"API happy path - {summary}", "method": "POST", "endpoint": "/api/orders", "headers": {"Authorization": "Bearer ${APP_API_TOKEN}"}, "body": {"customerId": "12345", "itemId": "SKU-100", "quantity": 1}, "expected_status": 201, "expected_fields": ["orderId", "status", "createdAt"], "traceability": "Valid order is created.", "source": "rule_fallback"}, source="rule_fallback"),
        _normalize_test({"name": f"API validation failure - {summary}", "method": "POST", "endpoint": "/api/orders", "headers": {"Authorization": "Bearer ${APP_API_TOKEN}"}, "body": {"customerId": "12345", "quantity": 1}, "expected_status": 400, "expected_fields": ["error", "message"], "traceability": "Missing itemId returns 400.", "source": "rule_fallback"}, source="rule_fallback"),
        _normalize_test({"name": f"API unauthorized request - {summary}", "method": "POST", "endpoint": "/api/orders", "headers": {}, "body": {"customerId": "12345", "itemId": "SKU-100", "quantity": 1}, "expected_status": 401, "expected_fields": ["error"], "traceability": "Requests without a token return 401.", "source": "rule_fallback"}, source="rule_fallback"),
    ]


def _call_openai_for_api_tests(ticket: dict[str, Any]) -> str:
    if not settings.openai_api_key:
        raise ValueError("Missing OPENAI_API_KEY. Set TEST_GENERATION_MODE=rule for local fallback.")
    from openai import OpenAI

    http_client = httpx.Client(
        verify=False,
        timeout=httpx.Timeout(20.0, connect=10.0),
    )

    client = OpenAI(api_key=settings.openai_api_key, http_client=http_client)
    instructions = """
You are a senior QA automation engineer. Generate executable API test definitions from a Jira ticket.
Return ONLY a valid JSON array. Do not wrap it in markdown.
Each item must include: name, method, endpoint, headers, body, expected_status, expected_fields, traceability.
You may also include expected_field_paths, setup_steps, follow_up_steps.
For Restful Booker tickets, use these endpoints: POST /auth, GET /booking, POST /booking, GET /booking/{id}, PUT /booking/{id}, PATCH /booking/{id}, DELETE /booking/{id}.
Use setup_steps to create prerequisite bookings and extract variables like bookingid or token.
Use relative endpoints only and placeholders like ${bookingid} when needed.
Create 1 to 3 focused tests for the ticket. Avoid destructive production actions; assume this is a public practice test API.
""".strip()
    response = client.responses.create(model=settings.openai_model, instructions=instructions, input=json.dumps(ticket, indent=2))
    return response.output_text


@mcp.tool()
def generate_api_test_cases(ticket: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate API test definitions from a Jira ticket."""
    if settings.test_generation_mode == "openai":
        raw_json = _call_openai_for_api_tests(ticket)
        try:
            generated = json.loads(raw_json)
        except json.JSONDecodeError as error:
            raise ValueError(f"OpenAI did not return valid JSON: {raw_json}") from error
        return _validate_api_test_cases(generated)
    if settings.test_generation_mode == "rule":
        return _fallback_api_test_cases(ticket)
    raise ValueError("TEST_GENERATION_MODE must be either 'openai' or 'rule'")


def _request(base_url: str, step: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    endpoint = _replace_placeholders(step["endpoint"], variables)
    headers = _replace_placeholders(step.get("headers", {}), variables)
    headers = {k: str(v).replace("${APP_API_TOKEN}", settings.app_api_token or "") for k, v in headers.items()}
    body = _replace_placeholders(step.get("body", {}), variables)
    response = requests.request(
        method=step["method"],
        url=f"{base_url}{endpoint}",
        headers=headers,
        json=body if body != {} else None,
        timeout=15,
        verify=settings.verify_ssl,
    )
    try:
        response_json = response.json() if response.content else {}
    except ValueError:
        response_json = {"raw_response": response.text}
    return {"status_code": response.status_code, "json": response_json, "endpoint": endpoint, "headers": headers, "body": body}


def _run_steps(base_url: str, steps: list[dict[str, Any]], variables: dict[str, Any]) -> list[dict[str, Any]]:
    executed: list[dict[str, Any]] = []

    for step in steps:
        # Some generated tests define variables directly instead of making
        # an HTTP request. Example: {"set_variables": {"missing_bookingid": 99999999}}.
        # Treat these as successful setup steps and continue.
        if "endpoint" not in step and "method" not in step:
            executed.append({
                "name": step.get("name", "Skipped invalid step"),
                "passed": True,
                "skipped": True,
                "reason": "Missing endpoint/method",
            })
            continue

        if "set_variables" in step:
            variables.update(step["set_variables"])
            executed.append({
                "name": step.get("name", "Set variables"),
                "passed": True,
                "set_variables": step["set_variables"],
                "extracted_variables": {k: str(v) for k, v in variables.items()},
            })
            continue

        result = _request(base_url, step, variables)

        for var_name, path in step.get("extract", {}).items():
            extracted = _extract_variable(result["json"], path)
            if extracted is not None:
                variables[var_name] = extracted

        expected_status = step.get("expected_status")
        passed = expected_status is None or result["status_code"] == expected_status

        executed.append({
            "name": step.get("name", step.get("endpoint")),
            "actual_status": result["status_code"],
            "expected_status": expected_status,
            "passed": passed,
            "response_sample": result["json"],
            "extracted_variables": {k: str(v) for k, v in variables.items()},
        })

    return executed


@mcp.tool()
def run_api_tests(test_cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute generated API test cases and return a structured result report."""
    app_base_url = (settings.app_base_url or RESTFUL_BOOKER_BASE_URL).rstrip("/")
    results: list[dict[str, Any]] = []
    for test in test_cases:
        variables: dict[str, Any] = {}
        try:
            setup_results = _run_steps(app_base_url, test.get("setup_steps", []), variables)
            result = _request(app_base_url, test, variables)
            response_json = result["json"]
            expected_status = test["expected_status"]
            status_passed = result["status_code"] == expected_status
            field_paths = test.get("expected_field_paths") or test.get("expected_fields", [])
            missing_fields = [path for path in field_paths if _get_by_path(response_json, path) is None]
            follow_up_results = _run_steps(app_base_url, test.get("follow_up_steps", []), variables)
            follow_up_passed = all(step.get("passed") for step in follow_up_results)
            passed = status_passed and not missing_fields and follow_up_passed
            results.append({
                "test_name": test["name"], "passed": passed, "expected_status": expected_status, "actual_status": result["status_code"],
                "missing_fields": missing_fields, "response_sample": response_json, "source": test.get("source", "unknown"),
                "traceability": test.get("traceability", ""), "executed_endpoint": result["endpoint"], "setup_results": setup_results,
                "follow_up_results": follow_up_results, "variables": {k: str(v) for k, v in variables.items()},
            })
        except Exception as error:  # noqa: BLE001 - demo reporting should show failures clearly
            results.append({"test_name": test.get("name", "Unnamed test"), "passed": False, "error": str(error), "source": test.get("source", "unknown")})
    return {"total": len(results), "passed": sum(1 for r in results if r.get("passed")), "failed": sum(1 for r in results if not r.get("passed")), "results": results}


@mcp.tool()
def generate_and_run_tests_from_jira(ticket_key: str) -> dict[str, Any]:
    """Fetch a Jira ticket, generate scenarios/API tests, run API tests, and return a QA report."""
    ticket = fetch_jira_ticket(ticket_key)
    functional_scenarios = generate_functional_scenarios(ticket)
    api_test_cases = generate_api_test_cases(ticket)
    api_test_results = run_api_tests(api_test_cases)
    return {"ticket": ticket, "functional_scenarios": functional_scenarios, "api_test_cases": api_test_cases, "api_test_results": api_test_results}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
