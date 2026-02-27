---
name: review-citation-guide
description: Citation requirements for specialist reviewers. Referenced by the /review skill. Not intended for direct invocation.
user-invocable: false
---

# Citation Requirements for Reviewers

For any finding that references a best practice, standard, library API usage, or asserts that something "should be documented" — you MUST verify it and cite the source inline in your COMMENT text. Do not assert from memory.

Acceptable sources (in priority order):
1. Local docs: read the repository's docs/, README.md, and CLAUDE.md files if the repository is checked out locally — see the Full Repository Access section in your specialist prompt
2. Context7 MCP: use `mcp__context7__resolve-library-id` then `mcp__context7__query-docs` to look up library/framework documentation (if unavailable, skip to step 3)
3. Official online documentation: WebFetch the authoritative source URL

Embed the citation naturally in your COMMENT:

> COMMENT: This approach can expose users to SQL injection (OWASP A03:2021 Injection — https://owasp.org/Top10/A03_2021-Injection/). Parameterized queries are the standard fix.

Findings that are purely observational (e.g., "this variable is shadowed") do not require citation.
