# Backend Test Architecture & Guide

This directory houses the backend test suite, test runners, and pre-flight verification scripts for **Disha**.

---

## Directory Organization

```text
packages/backend/tests/
├── unit/                         # Unit & functional test runner
│   └── run-unit-tests.js         # Cross-platform runner for pytest suite
├── smoke/                        # Pre-flight smoke tests for packaged/frozen binaries
│   └── smoke-test-backend.js     # Tests PyInstaller binary boot & /health endpoint
├── test_*.py                     # Backend pytest unit & functional tests
└── README.md                     # Test architecture documentation
```

### Component Test Suites

- **Backend Unit & MCP Tests**: Located in [`packages/backend/tests/`](./) (`pytest`).
- **Frontend UI Component Tests**: Located in [`apps/desktop/src/__tests__/`](../../../apps/desktop/src/) (`vitest`).

---

## Test CLI Commands (Run from Repository Root)

| Command | Action | Description |
| :--- | :--- | :--- |
| **`pnpm test`** | Full Test Suite | Runs unit tests (`test:unit`) and pre-flight binary smoke tests (`test:smoke`). |
| **`pnpm run test:unit`** | Unit & Functional | Executes backend pytest functional suite. |
| **`pnpm run test:smoke`** | Pre-flight Smoke Test | Boots frozen PyInstaller Python executable standalone on port `8766` and asserts `/health` readiness. |

---

## Running the Backend Tests Directly

From `packages/backend`:

```bash
# Using the project virtualenv (recommended)
.buildenv\Scripts\python.exe -m pytest tests/ -v   # Windows
.buildenv/bin/python -m pytest tests/ -v           # macOS / Linux

# Using system Python
python -m pytest tests/ -v