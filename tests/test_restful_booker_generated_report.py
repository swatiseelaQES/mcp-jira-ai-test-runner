"""QA-facing tests for Restful Booker Jira tickets and workflow-style API execution."""

import os

import responses

os.environ["MCP_DISABLE_IMPORT"] = "1"
os.environ["JIRA_MODE"] = "mock"
os.environ["TEST_GENERATION_MODE"] = "rule"
os.environ["APP_BASE_URL"] = "https://restful-booker.herokuapp.com"

from src import server  # noqa: E402


class TestRestfulBookerJiraDrivenLiveTests:
    def test_mock_jira_contains_restful_booker_tickets_for_real_api_endpoints(self):
        tickets = {ticket["key"]: ticket for ticket in server.list_mock_jira_tickets()}

        assert tickets["RB-1"]["summary"] == "Restful Booker - create booking"
        assert tickets["RB-2"]["summary"] == "Restful Booker - retrieve booking"
        assert tickets["RB-3"]["summary"] == "Restful Booker - update booking requires auth"
        assert tickets["RB-4"]["summary"] == "Restful Booker - partial update booking"
        assert tickets["RB-5"]["summary"] == "Restful Booker - delete booking requires auth"

    def test_restful_booker_ticket_generates_real_endpoint_tests_with_setup_steps(self):
        ticket = server.fetch_jira_ticket("RB-3")
        generated_tests = server.generate_api_test_cases(ticket)

        assert [test["name"] for test in generated_tests] == [
            "Update booking succeeds with valid auth token",
            "Update booking without auth is rejected",
        ]
        assert generated_tests[0]["setup_steps"][0]["endpoint"] == "/auth"
        assert generated_tests[0]["setup_steps"][1]["endpoint"] == "/booking"
        assert generated_tests[0]["endpoint"] == "/booking/${bookingid}"
        assert generated_tests[0]["headers"]["Cookie"] == "token=${token}"

    @responses.activate
    def test_restful_booker_workflow_executes_setup_extracts_bookingid_and_validates_contract(self):
        responses.post(
            "https://restful-booker.herokuapp.com/booking",
            json={"bookingid": 42, "booking": server.BOOKING_PAYLOAD},
            status=200,
        )
        responses.get(
            "https://restful-booker.herokuapp.com/booking/42",
            json=server.BOOKING_PAYLOAD,
            status=200,
        )
        responses.get(
            "https://restful-booker.herokuapp.com/booking/999999999",
            body="Not Found",
            status=404,
        )

        ticket = server.fetch_jira_ticket("RB-2")
        report = server.run_api_tests(server.generate_api_test_cases(ticket))

        assert report["total"] == 2
        assert report["passed"] == 2
        assert report["failed"] == 0
        assert report["results"][0]["variables"]["bookingid"] == "42"
        assert report["results"][0]["executed_endpoint"] == "/booking/42"

    @responses.activate
    def test_restful_booker_delete_ticket_executes_follow_up_check(self):
        responses.post(
            "https://restful-booker.herokuapp.com/auth",
            json={"token": "abc123"},
            status=200,
        )
        responses.post(
            "https://restful-booker.herokuapp.com/booking",
            json={"bookingid": 77, "booking": server.BOOKING_PAYLOAD},
            status=200,
        )
        responses.delete("https://restful-booker.herokuapp.com/booking/77", body="Created", status=201)
        responses.get("https://restful-booker.herokuapp.com/booking/77", body="Not Found", status=404)

        ticket = server.fetch_jira_ticket("RB-5")
        report = server.run_api_tests(server.generate_api_test_cases(ticket))

        assert report["passed"] == 1
        assert report["results"][0]["follow_up_results"][0]["passed"] is True
