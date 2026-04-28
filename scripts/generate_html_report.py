"""Generate an HTML QA report from qa_generated_tests_report.json.

Usage:
  python scripts/generate_qa_report.py
  python scripts/generate_html_report.py
"""

from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _escape(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, indent=2)
    return html.escape(str(value))


def _pretty_json(value: Any) -> str:
    return _escape(json.dumps(value, indent=2))


def _status_badge(passed: bool | None) -> str:
    if passed is True:
        return '<span class="badge pass">PASS</span>'
    if passed is False:
        return '<span class="badge fail">FAIL</span>'
    return '<span class="badge not-run">NOT RUN</span>'


def _flatten_suite_report(report: dict[str, Any]) -> dict[str, Any]:
    if "reports" not in report:
        return report
    flattened_tests = []
    flattened_results = []
    for child in report.get("reports", []):
        ticket = child.get("ticket", {})
        for test in child.get("api_test_cases", []):
            enriched = dict(test)
            enriched["ticket_key"] = ticket.get("key")
            enriched["ticket_summary"] = ticket.get("summary")
            flattened_tests.append(enriched)
        for result in child.get("api_test_results", {}).get("results", []):
            enriched_result = dict(result)
            enriched_result["ticket_key"] = ticket.get("key")
            enriched_result["ticket_summary"] = ticket.get("summary")
            flattened_results.append(enriched_result)
    execution = report.get("api_test_results", {})
    return {
        "ticket": {"key": report.get("suite_name", "API test suite"), "summary": report.get("base_url", ""), "status": "Executed", "issue_type": "Suite", "acceptance_criteria": "Combined report across generated Jira-ticket-driven API tests."},
        "generation_mode": report.get("generation_mode"),
        "model": report.get("model"),
        "api_test_cases": flattened_tests,
        "api_test_results": {"total": execution.get("total", len(flattened_tests)), "passed": execution.get("passed", 0), "failed": execution.get("failed", 0), "results": flattened_results},
    }



def _result_test_data(result: dict[str, Any]) -> dict[str, Any]:
    """Collect execution data worth showing to QA: resolved URL parts, extracted IDs/tokens, setup/follow-up data."""
    data: dict[str, Any] = {}
    if result.get("executed_endpoint"):
        data["resolved_endpoint"] = result.get("executed_endpoint")
    if result.get("variables"):
        data["variables"] = result.get("variables")

    setup_data = []
    for step in result.get("setup_results", []) or []:
        item: dict[str, Any] = {
            "name": step.get("name"),
            "status": step.get("actual_status"),
            "passed": step.get("passed"),
        }
        if step.get("extracted_variables"):
            item["extracted_variables"] = step.get("extracted_variables")
        sample = step.get("response_sample")
        if isinstance(sample, dict):
            compact = {k: sample.get(k) for k in ("bookingid", "token") if k in sample}
            if compact:
                item["response_ids"] = compact
        setup_data.append(item)
    if setup_data:
        data["setup_data"] = setup_data

    follow_up_data = []
    for step in result.get("follow_up_results", []) or []:
        follow_up_data.append({
            "name": step.get("name"),
            "status": step.get("actual_status"),
            "expected_status": step.get("expected_status"),
            "passed": step.get("passed"),
            "extracted_variables": step.get("extracted_variables", {}),
        })
    if follow_up_data:
        data["follow_up_data"] = follow_up_data

    return data

def _request_test_data(test: dict[str, Any]) -> dict[str, Any]:
    """Show the generated request data sent by the test."""
    return {
        "method": test.get("method"),
        "endpoint_template": test.get("endpoint"),
        "headers": test.get("headers", {}),
        "body": test.get("body", {}),
        "setup_steps": test.get("setup_steps", []),
        "follow_up_steps": test.get("follow_up_steps", []),
    }


def render_html_report(report: dict[str, Any]) -> str:
    report = _flatten_suite_report(report)
    ticket = report.get("ticket", {})
    test_cases = report.get("api_test_cases", [])
    execution = report.get("api_test_results")
    results = execution.get("results", []) if execution else []
    results_by_name = {r.get("test_name", ""): r for r in results}

    total = execution.get("total", len(test_cases)) if execution else len(test_cases)
    passed = execution.get("passed", 0) if execution else 0
    failed = execution.get("failed", 0) if execution else 0
    not_run = 0 if execution else len(test_cases)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    generation_mode = report.get("generation_mode", "unknown")
    model = report.get("model") or "N/A"

    rows = []
    cards = []
    for index, test in enumerate(test_cases, start=1):
        result = results_by_name.get(test.get("name", ""), {})
        passed_value = result.get("passed") if execution else None
        actual_status = result.get("actual_status", "Not run")
        expected_status = test.get("expected_status")
        missing_fields = result.get("missing_fields", [])

        rows.append(f"""
        <tr>
          <td>{index}</td>
          <td>{_escape(test.get('name'))}</td>
          <td>{_escape(test.get('method'))}</td>
          <td><code>{_escape(result.get('executed_endpoint') or test.get('endpoint'))}</code></td>
          <td>{_escape(expected_status)}</td>
          <td>{_escape(actual_status)}</td>
          <td>{_status_badge(passed_value)}</td>
        </tr>
        """)

        failure_block = ""
        if missing_fields:
            failure_block += f'<div class="failure"><strong>Missing expected fields:</strong> {_escape(", ".join(missing_fields))}</div>'
        if result.get("error"):
            failure_block += f'<div class="failure"><strong>Error:</strong> {_escape(result.get("error"))}</div>'

        response_sample = result.get("response_sample", "Not executed") if execution else "Not executed"
        cards.append(f"""
        <section class="card">
          <div class="card-header"><h3>{index}. {_escape(test.get('name'))}</h3>{_status_badge(passed_value)}</div>
          <p><strong>Traceability:</strong> {_escape(test.get('traceability'))}</p>
          <div class="grid two">
            <div>
              <h4>Generated API Test</h4>
              <dl>
                <dt>Method</dt><dd>{_escape(test.get('method'))}</dd>
                <dt>Endpoint</dt><dd><code>{_escape(test.get('endpoint'))}</code></dd>
                <dt>Expected status</dt><dd>{_escape(expected_status)}</dd>
                <dt>Expected fields</dt><dd>{_escape(', '.join(test.get('expected_fields', [])))}</dd>
              </dl>
            </div>
            <div>
              <h4>Execution Result</h4>
              <dl>
                <dt>Actual status</dt><dd>{_escape(actual_status)}</dd>
                <dt>Resolved endpoint</dt><dd><code>{_escape(result.get('executed_endpoint') or test.get('endpoint'))}</code></dd>
                <dt>Generated by</dt><dd>{_escape(test.get('source', generation_mode))}</dd>
              </dl>
              {failure_block}
            </div>
          </div>
          <div class="grid two">
            <div><h4>Request headers</h4><pre>{_pretty_json(test.get('headers', {}))}</pre></div>
            <div><h4>Request body</h4><pre>{_pretty_json(test.get('body', {}))}</pre></div>
          </div>
          <div class="grid two">
            <div><h4>Test data sent</h4><pre>{_pretty_json(_request_test_data(test))}</pre></div>
            <div><h4>Test data used during execution</h4><pre>{_pretty_json(_result_test_data(result))}</pre></div>
          </div>
          <h4>Response sample</h4><pre>{_pretty_json(response_sample)}</pre>
        </section>
        """)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>QA Generated API Tests Report</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; background: #f6f7f9; color: #1f2937; }}
    header {{ background: #111827; color: white; padding: 32px; }}
    header h1 {{ margin: 0 0 8px; font-size: 28px; }}
    header p {{ margin: 0; color: #d1d5db; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    .summary {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-bottom: 24px; }}
    .metric, .card {{ background: white; border: 1px solid #e5e7eb; border-radius: 14px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }}
    .metric {{ padding: 18px; }} .metric .label {{ color: #6b7280; font-size: 13px; }} .metric .value {{ font-size: 28px; font-weight: 700; margin-top: 6px; }}
    .card {{ padding: 20px; margin-bottom: 18px; }} .card-header {{ display: flex; justify-content: space-between; gap: 12px; align-items: start; }}
    h2 {{ margin: 26px 0 12px; }} h3 {{ margin: 0 0 12px; }} h4 {{ margin: 14px 0 8px; }}
    .grid.two {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #e5e7eb; border-radius: 14px; overflow: hidden; }}
    th, td {{ padding: 12px; border-bottom: 1px solid #e5e7eb; text-align: left; vertical-align: top; }} th {{ background: #f3f4f6; font-size: 13px; color: #374151; }} tr:last-child td {{ border-bottom: none; }}
    code {{ background: #f3f4f6; padding: 2px 5px; border-radius: 6px; }} pre {{ background: #0b1020; color: #e5e7eb; padding: 14px; border-radius: 10px; overflow-x: auto; font-size: 13px; line-height: 1.4; }}
    dl {{ display: grid; grid-template-columns: 150px 1fr; gap: 8px 12px; margin: 0; }} dt {{ color: #6b7280; }} dd {{ margin: 0; }}
    .badge {{ display: inline-block; border-radius: 999px; padding: 5px 10px; font-weight: 700; font-size: 12px; white-space: nowrap; }} .pass {{ background: #dcfce7; color: #166534; }} .fail {{ background: #fee2e2; color: #991b1b; }} .not-run {{ background: #e5e7eb; color: #374151; }}
    .failure {{ margin-top: 10px; padding: 10px; border-radius: 10px; background: #fee2e2; color: #991b1b; }}
    @media (max-width: 800px) {{ .summary, .grid.two {{ grid-template-columns: 1fr; }} main {{ padding: 16px; }} header {{ padding: 24px 16px; }} dl {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header><h1>QA Generated API Tests Report</h1><p>Generated tests from Jira ticket content, with optional deterministic execution results.</p></header>
  <main>
    <section class="card">
      <h2>Source</h2>
      <dl>
        <dt>Ticket</dt><dd>{_escape(ticket.get('key'))} — {_escape(ticket.get('summary'))}</dd>
        <dt>Status</dt><dd>{_escape(ticket.get('status'))}</dd>
        <dt>Issue type</dt><dd>{_escape(ticket.get('issue_type'))}</dd>
        <dt>Generation mode</dt><dd>{_escape(generation_mode)}</dd>
        <dt>Model</dt><dd>{_escape(model)}</dd>
        <dt>Generated at</dt><dd>{_escape(generated_at)}</dd>
      </dl>
      <h4>Acceptance criteria</h4><p>{_escape(ticket.get('acceptance_criteria'))}</p>
    </section>
    <section class="summary">
      <div class="metric"><div class="label">Total tests</div><div class="value">{total}</div></div>
      <div class="metric"><div class="label">Passed</div><div class="value">{passed}</div></div>
      <div class="metric"><div class="label">Failed</div><div class="value">{failed}</div></div>
      <div class="metric"><div class="label">Not run</div><div class="value">{not_run}</div></div>
    </section>
    <h2>Execution Summary</h2>
    <table><thead><tr><th>#</th><th>Generated test</th><th>Method</th><th>Endpoint</th><th>Expected</th><th>Actual</th><th>Status</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
    <h2>Generated API Test Details</h2>
    {''.join(cards)}
  </main>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an HTML QA report from a JSON report.")
    parser.add_argument("--input", default=os.getenv("QA_REPORT_PATH", "qa_generated_tests_report.json"), help="Input JSON report path.")
    parser.add_argument("--output", default=os.getenv("HTML_REPORT_PATH", "qa_generated_tests_report.html"), help="Output HTML report path.")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        raise SystemExit(f"Could not find {input_path}. Run the JSON report first, or pass --input.")
    report = json.loads(input_path.read_text(encoding="utf-8"))
    output_path.write_text(render_html_report(report), encoding="utf-8")
    print(f"Saved HTML report to: {output_path}")


if __name__ == "__main__":
    main()
