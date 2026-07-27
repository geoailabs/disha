# Test Architecture & Guide

This directory houses the top-level test suite, test runners, and pre-flight verification scripts for **Disha**.

---

## Directory Organization

```text
tests/
├── unit/                         # Unit & functional test runner
│   └── run-unit-tests.js         # Cross-platform runner for packages/backend/tests
├── smoke/                        # Pre-flight smoke tests for packaged/frozen binaries
│   └── smoke-test-backend.js     # Tests PyInstaller binary boot & /health endpoint
├── e2e/                          # End-to-end Electron desktop UI integration tests
└── README.md                     # Test architecture documentation
```

### Component Test Suites

- **Backend Unit & MCP Tests**: Located in [`packages/backend/tests/`](../packages/backend/tests/) (`pytest`).
- **Frontend UI Component Tests**: Located in [`apps/desktop/src/__tests__/`](../apps/desktop/src/) (`vitest`).

---

## Test CLI Commands (Run from Repository Root)

| Command | Action | Description |
| :--- | :--- | :--- |
| **`pnpm test`** | Full Test Suite | Runs unit tests (`test:unit`) and pre-flight binary smoke tests (`test:smoke`). |
| **`pnpm run test:unit`** | Unit & Functional | Executes backend pytest functional suite. |
| **`pnpm run test:smoke`** | Pre-flight Smoke Test | Boots frozen PyInstaller Python executable standalone on port `8766` and asserts `/health` readiness. |
