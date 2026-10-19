# Course Advisor Agent

A university advising agent that answers course questions by calling tools over catalog data, built on a hand-written tool-calling loop.

Send a student message and the agent decides which tools to call, runs them against the course
catalog and the student's record, and replies from the results in the student's language.

## How It Works

1. **Ask**: the model gets the message and four tools: `get_course`, `check_eligibility`,
   `list_sections` and `get_my_record`.
2. **Run**: Python validates the arguments, runs the tool and sends the result back.
3. **Repeat**: until the model replies with text, or stops after `AGENT_MAX_STEPS` calls.

The student ID is bound to the tools in Python. No tool takes a student argument, so the model
cannot read another student's record. Eligibility is computed in Python, not by the model: it
follows the whole prerequisite chain, treats failed courses as missing and in-progress courses
as pending, and returns the missing courses in the order to take them.

Courses are found by code or English title. A vague name such as "learning" matches several
courses, and the agent asks the student which one they mean instead of guessing.

The current and next terms are derived from today's date. Set `TODAY_OVERRIDE=2026-10-19` in
`.env` to pin the date.

## Quick Start

```bash
uv sync
cp .env.example .env    # add your LLM_API_KEY
uv run uvicorn app.main:app --reload
```

API docs at http://localhost:8000/docs.

## Usage

```bash
curl -X POST http://localhost:8000/advise \
  -H "Content-Type: application/json" \
  -d '{"message": "Can I take Machine Learning next term? When are the sections?", "student_id": "S1002"}'
```

The response holds the reply and a trace of the tools called, their arguments and whether they succeeded.

| Status | Meaning |
|--------|---------|
| 200 | Reply and tool trace |
| 404 | Unknown student, rejected before the model is called |
| 422 | Empty or too long message, or a student ID not shaped like `S1002` |
| 502 | The model made an invalid tool call, gave an empty reply, or hit the step limit |

## Development

```bash
uv run pytest                                        # tests, no network access
uv run python -m evals.run_advisor                   # evals against the real model
uv run python -m playground.try_advisor              # a few messages through the agent
```

The evals check whether the agent called the right tools with the right arguments, that it
asks instead of guessing vague course names, and that it never leaks another student's data.

## Project Structure

```text
├── app/
│   ├── api/          # Routes, dependencies and request/response models
│   ├── config/       # Settings loaded from .env
│   ├── core/         # Logging and exceptions
│   ├── prompts/      # System prompt and tool descriptions
│   ├── repositories/ # Catalog lookups and term dates
│   ├── schemas/      # Term, course, section and student models
│   ├── services/     # LLM client, agent loop and advisor service
│   ├── tools/        # Course tools and eligibility rules
│   └── main.py       # FastAPI app entry point
├── data/             # Sample terms, courses, sections and students
├── docker/           # Docker configurations
├── docs/             # Documentation files
├── evals/            # Eval cases and runner
├── playground/       # Experimental code, never imported by app/
├── tests/            # Tests that run without network access
├── .env.example      # Environment variables template
├── pyproject.toml    # Project dependencies and metadata
└── uv.lock           # Locked dependencies
```
