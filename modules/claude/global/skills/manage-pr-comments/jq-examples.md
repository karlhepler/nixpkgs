# Manage PR Comments — Examples with jq Parsing

Three worked `jq` patterns for parsing `prc list`'s JSON output: extracting thread IDs for scripting, building a human-readable summary report, and counting comments by author. Read this file from `SKILL.md` when composing a `jq` query against `prc list` output and you want a concrete pattern to start from rather than reasoning from the JSON schema alone.

### Extract Thread IDs for Scripting

Get all unresolved thread IDs:
```bash
prc list | jq -r '.[] | select(.isResolved == false) | .id'
```

### Create Summary Report

Generate human-readable comment summary:
```bash
prc list --bots-only | jq -r '.[] | "[\(.author.login)] \(.path // "PR"):\(.line // "N/A") - \(.body[:80])..."'
```

Output example:
```
[dependabot[bot]] package.json:5 - Bumps lodash from 4.17.19 to 4.17.21...
[github-actions[bot]] PR:N/A - Workflow failed: build step...
```

### Count Comments by Author

```bash
prc list | jq -r '.[] | .author.login' | sort | uniq -c | sort -rn
```

Output example:
```
  5 dependabot[bot]
  3 octocat
  2 reviewer-name
```
