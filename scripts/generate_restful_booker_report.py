"""Generate live QA reports for Restful Booker mock Jira tickets.

PowerShell-friendly examples:
  python scripts/generate_restful_booker_report.py
  python scripts/generate_restful_booker_report.py --generation-mode openai --openai-api-key "sk-..."
  python scripts/generate_restful_booker_report.py --base-url http://restful-booker.herokuapp.com
  python scripts/generate_restful_booker_report.py --no-verify-ssl

The --base-url http://... option is useful on corporate networks that intercept HTTPS traffic.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_dotenv(path: Path) -> None:
    """Tiny .env loader so this script does not require python-dotenv."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and execute Restful Booker QA tests from mock Jira tickets.")
    parser.add_argument("--ticket-keys", default=os.getenv("TICKET_KEYS", "RB-1,RB-2,RB-3,RB-4,RB-5"), help="Comma-separated mock Jira ticket keys.")
    parser.add_argument("--generation-mode", choices=["rule", "openai"], default=os.getenv("TEST_GENERATION_MODE", "rule"), help="Use deterministic fallback rules or OpenAI-generated tests.")
    parser.add_argument("--openai-api-key", default=os.getenv("OPENAI_API_KEY"), help="OpenAI API key. You can also set OPENAI_API_KEY.")
    parser.add_argument("--openai-model", default=os.getenv("OPENAI_MODEL", "gpt-5.2"), help="OpenAI model name.")
    parser.add_argument("--base-url", default=os.getenv("APP_BASE_URL", "http://restful-booker.herokuapp.com"), help="API base URL. Default uses http to avoid local SSL/proxy issues.")
    parser.add_argument("--output", default=os.getenv("QA_REPORT_PATH", "qa_restful_booker_live_report.json"), help="JSON report output path.")
    parser.add_argument("--no-verify-ssl", action="store_true", help="Disable TLS certificate verification for HTTPS calls. Demo/local only.")
    return parser.parse_args()


def main() -> None:
    load_dotenv(ROOT / ".env")
    args = parse_args()

    # Set env BEFORE importing src.server because server.Settings is created at import time.
    os.environ.setdefault("MCP_DISABLE_IMPORT", "1")
    os.environ["JIRA_MODE"] = "mock"
    os.environ["TEST_GENERATION_MODE"] = args.generation_mode
    os.environ["APP_BASE_URL"] = args.base_url.rstrip("/")
    os.environ["OPENAI_MODEL"] = args.openai_model
    if args.openai_api_key:
        os.environ["OPENAI_API_KEY"] = args.openai_api_key
    if args.no_verify_ssl:
        os.environ["VERIFY_SSL"] = "false"
    else:
        os.environ.setdefault("VERIFY_SSL", "true")

    from src import server  # noqa: E402

    ticket_keys = [key.strip() for key in args.ticket_keys.split(",") if key.strip()]
    reports = []
    for ticket_key in ticket_keys:
        print(f"Running live Restful Booker QA workflow for {ticket_key}...")
        reports.append(server.generate_and_run_tests_from_jira(ticket_key))

    combined = {
        "suite_name": "Restful Booker live API tests from mock Jira tickets",
        "base_url": server.settings.app_base_url or server.RESTFUL_BOOKER_BASE_URL,
        "generation_mode": server.settings.test_generation_mode,
        "verify_ssl": server.settings.verify_ssl,
        "model": server.settings.openai_model if server.settings.test_generation_mode == "openai" else None,
        "reports": reports,
        "api_test_cases": [test for report in reports for test in report["api_test_cases"]],
        "api_test_results": {
            "total": sum(report["api_test_results"]["total"] for report in reports),
            "passed": sum(report["api_test_results"]["passed"] for report in reports),
            "failed": sum(report["api_test_results"]["failed"] for report in reports),
            "results": [result for report in reports for result in report["api_test_results"]["results"]],
        },
    }

    output_path = Path(args.output)
    output_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    print(json.dumps(combined["api_test_results"], indent=2))
    print(f"\nSaved live QA report to: {output_path}")


if __name__ == "__main__":
    main()
