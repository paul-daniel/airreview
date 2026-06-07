# Testing Review Guidance

AirReview guidance:

- Ask for tests when a branch changes externally visible behavior, permissions, state transitions, data validation, error handling, or integration boundaries.
- Prefer one focused regression test over generic "add more tests" comments.
- A good test recommendation names the scenario, input/state, expected output, and failure mode being protected.
- If a branch weakens or deletes an assertion, review whether it hides a real behavior regression.
- For UI work, prefer tests for user-visible behavior and accessibility-relevant interactions over snapshot-only assertions.
- For security-sensitive changes, include negative tests for denied roles, invalid input, high-risk states, or missing credentials.
- Do not request tests for trivial copy, purely mechanical formatting, or dead code removal unless risk is clear.

