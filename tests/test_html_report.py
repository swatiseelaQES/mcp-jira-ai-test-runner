"""Tests for the HTML QA report renderer."""

from scripts.generate_html_report import render_html_report


def test_html_report_includes_generated_api_tests_and_execution_results():
    report = {
        "ticket": {
            "key": "QA-DEMO-1",
            "summary": "Create order API",
            "status": "Ready for QA",
            "issue_type": "Story",
            "acceptance_criteria": "Valid order is created. Missing itemId returns 400.",
        },
        "generation_mode": "openai",
        "model": "gpt-5.2",
        "api_test_cases": [
            {
                "name": "Create order succeeds with a valid cart",
                "method": "POST",
                "endpoint": "/api/orders",
                "headers": {"Authorization": "Bearer ${APP_API_TOKEN}"},
                "body": {"customerId": "12345", "itemId": "SKU-100", "quantity": 1},
                "expected_status": 201,
                "expected_fields": ["orderId", "status", "createdAt"],
                "source": "openai",
                "traceability": "Covers valid cart submission.",
            }
        ],
        "api_test_results": {
            "total": 1,
            "passed": 1,
            "failed": 0,
            "results": [
                {
                    "test_name": "Create order succeeds with a valid cart",
                    "passed": True,
                    "expected_status": 201,
                    "actual_status": 201,
                    "missing_fields": [],
                    "response_sample": {"orderId": "ORD-1", "status": "CREATED", "createdAt": "2026-04-28T12:00:00Z"},
                }
            ],
        },
    }

    html = render_html_report(report)

    assert "QA Generated API Tests Report" in html
    assert "QA-DEMO-1" in html
    assert "Create order succeeds with a valid cart" in html
    assert "/api/orders" in html
    assert "PASS" in html
    assert "orderId" in html
