# Code Review Principles

Source links:

- Google Engineering Practices: https://google.github.io/eng-practices/review/
- Google reviewer guide: https://google.github.io/eng-practices/review/reviewer/

AirReview guidance:

- Code review should improve the long-term health of the codebase, not only catch syntax or style issues.
- Prefer concrete comments that point to behavior, maintainability, security, readability, testability, or operational risk.
- Do not block a change for perfection when the change improves the codebase and remaining concerns are low-risk preferences.
- Respect local project conventions, but do not treat objectively unsafe legacy patterns as good practice.
- Prefer small, actionable comments over large generic lists.
- Review the final branch state against the target branch, not a single isolated commit.
- Distinguish new or aggravated problems from pre-existing legacy debt.
- If multiple approaches are valid, prefer the author's approach unless there is a clear project, reliability, security, performance, or maintainability reason to object.
- Comment on missing tests only when the branch changes behavior, risk, data flow, authorization, security, or integration boundaries.

