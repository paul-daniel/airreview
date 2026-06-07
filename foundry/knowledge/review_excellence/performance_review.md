# Performance Review Guidance

AirReview guidance:

- Raise performance findings only when the branch introduces a concrete cost: repeated work, avoidable network calls, blocking operations, unbounded loops, N+1 access, large rendering work, or unnecessary re-computation.
- Prefer local, measurable improvements over speculative micro-optimizations.
- In React/UI code, watch for expensive calculations during render, unstable list keys for dynamic lists, missing memoization around large derived data, and effects that re-run unnecessarily.
- In backend code, watch for repeated database/API calls inside loops, broad queries without limits, synchronous work in request paths, and missing pagination.
- A performance finding should explain the likely scale trigger: number of rows, users, requests, items, renders, or payload size.
- If the performance impact is uncertain, lower confidence and suggest measurement instead of a firm warning.

