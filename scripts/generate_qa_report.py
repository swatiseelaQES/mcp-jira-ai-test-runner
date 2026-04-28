"""Generate a QA-facing report from mock Jira using the configured test generator.

Usage:
  TEST_GENERATION_MODE=openai OPENAI_API_KEY=... APP_BASE_URL=https://restful-booker.herokuapp.com \
    python scripts/generate_qa_report.py

This script prints generated API test definitions. It does not execute them unless RUN_API_TESTS=1.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Keep this script runnable without starting the MCP transport.
os.environ.setdefault("MCP_DISABLE_IMPORT", "1")
os.environ.setdefault("JIRA_MODE", "mock")
os.environ.setdefault("APP_BASE_URL", "https://restful-booker.herokuapp.com")
os.environ.setdefault("APP_API_TOKEN", "fake-app-token")

from src import server  # noqa: E402


def main() -> None:
    ticket_key = os.getenv("TICKET_KEY", "RB-1")
    ticket = server.fetch_jira_ticket(ticket_key)
    api_tests = server.generate_api_test_cases(ticket)

    report = {
        "ticket": ticket,
        "generation_mode": server.settings.test_generation_mode,
        "model": server.settings.openai_model if server.settings.test_generation_mode == "openai" else None,
        "api_test_cases": api_tests,
    }

    if os.getenv("RUN_API_TESTS") == "1":
        report["api_test_results"] = server.run_api_tests(api_tests)

    output_path = Path(os.getenv("QA_REPORT_PATH", "qa_generated_tests_report.json"))
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    print(f"\nSaved report to: {output_path}")


if __name__ == "__main__":
    main()
