---
name: review-citation-guide
description: Citation requirements for specialist reviewers. Referenced by the /pr-review skill. Not intended for direct invocation.
user-invocable: false
---

# Citation Requirements for Reviewers

For any finding that references a best practice, standard, library API usage, or asserts that something "should be documented" — you MUST verify it and cite the source inline in your COMMENT text. Do not assert from memory.

Acceptable sources (in priority order — this list restates the authoritative order in global `CLAUDE.md` § Research Priority Order; if that section changes, update this list too):
1. CLAUDE.md files: read the repository's global and project-specific CLAUDE.md files if checked out locally — most authoritative for "how we do things here"
2. Local docs/ folder: read the repository's docs/, README.md, and other documentation files if checked out locally — see the Full Repository Access section in your specialist prompt
3. Context7 MCP: as a specialist sub-agent, you cannot query Context7 MCP directly — no sub-agent can reach any MCP server. Use whatever Context7 documentation (fetched via `mcp__context7__resolve-library-id` then `mcp__context7__query-docs`) is supplied by the coordinator, inline in the card or via `.scratchpad/` files (if none was supplied, skip to step 4)
4. Web search / official online documentation: WebFetch the authoritative source URL, only when the above sources don't have what you need

Embed the citation naturally in your COMMENT:

> COMMENT: This approach can expose users to SQL injection (OWASP A03:2021 Injection — https://owasp.org/Top10/A03_2021-Injection/). Parameterized queries are the standard fix.

Findings that are purely observational (e.g., "this variable is shadowed") do not require citation.
