# MCP Jira AI Test Runner

A small QA-focused MCP demo that turns Jira-style tickets into API test definitions, runs them, and generates JSON/HTML reports.

The repo includes **Restful Booker** mock Jira tickets so you can run real API tests against a public practice API.

## What this demonstrates

- Mock Jira tickets for real API behavior
- OpenAI-generated or deterministic fallback API test definitions
- Stateful API workflow execution with setup steps
- Runtime variable extraction, such as `bookingid` and auth `token`
- Status code, response field, and follow-up validation
- JSON and HTML QA reports with traceability and test data used

## Setup

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
```

### Mac/Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

## Run the QA-facing pytest suite

```bash
pytest -vv
```

The terminal summary prints the generated Restful Booker API tests and the Jira ticket each one came from.

## Mock Jira tickets included

| Ticket | Purpose | Endpoint focus |
|---|---|---|
| `RB-1` | Create booking | `POST /booking` |
| `RB-2` | Retrieve booking | `POST /booking`, `GET /booking/{id}` |
| `RB-3` | Update booking with auth | `POST /auth`, `PUT /booking/{id}` |
| `RB-4` | Partial update booking | `POST /auth`, `PATCH /booking/{id}` |
| `RB-5` | Delete booking with auth | `POST /auth`, `DELETE /booking/{id}`, follow-up `GET /booking/{id}` |

## Generate and run a live Restful Booker report

### Deterministic fallback mode

```powershell
python scripts/generate_restful_booker_report.py --base-url http://restful-booker.herokuapp.com
```

This writes:

```text
qa_restful_booker_live_report.json
```

## Run only one ticket

### Windows PowerShell

```powershell
$env:TICKET_KEYS="RB-2"
python scripts/generate_restful_booker_report.py --base-url http://restful-booker.herokuapp.com
```

### Mac/Linux

```bash
TICKET_KEYS=RB-2 python scripts/generate_restful_booker_report.py --base-url http://restful-booker.herokuapp.com
```

## Run OpenAI-generated tests

### Recommended PowerShell command

```powershell
python scripts/generate_restful_booker_report.py --generation-mode openai --openai-api-key "YOUR_KEY" --base-url http://restful-booker.herokuapp.com
```

### Mac/Linux equivalent

```bash
TEST_GENERATION_MODE=openai OPENAI_API_KEY=your_key python scripts/generate_restful_booker_report.py --base-url http://restful-booker.herokuapp.com
```

## Generate HTML report

```powershell
python scripts/generate_html_report.py --input qa_restful_booker_live_report.json --output qa_restful_booker_live_report.html
```

Open this file in a browser:

```text
qa_restful_booker_live_report.html
```

The HTML report shows:

- Jira traceability
- Generated API test definition
- Request headers and body
- Resolved endpoint, including runtime values such as `bookingid`
- Test data sent
- Test data used during execution
- Response sample
- Pass/fail result and missing fields

## Important workflow note

If you change `src/server.py`, regenerate the JSON report before regenerating HTML.

Correct order:

```powershell
python scripts/generate_restful_booker_report.py --generation-mode openai --openai-api-key "YOUR_KEY" --base-url http://restful-booker.herokuapp.com
python scripts/generate_html_report.py --input qa_restful_booker_live_report.json --output qa_restful_booker_live_report.html
```

If you only regenerate the HTML from an old JSON file, the report may still show old failures.

## Run the MCP server

```bash
python -m src.server
```

## Notes

Restful Booker is a public practice API. It resets periodically and contains intentional quirks, so a live report may occasionally reveal behavior differences. That is useful for this demo because it shows why generated API checks still need deterministic execution and clear evidence.

For local demos, `http://restful-booker.herokuapp.com` is often simpler than HTTPS because some Windows or corporate-network environments can produce SSL certificate verification errors.
