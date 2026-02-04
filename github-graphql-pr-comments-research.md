# GitHub GraphQL API Research: PR Comment Management

**Research Date:** 2026-02-04
**Purpose:** Complete investigation of GitHub GraphQL operations for building `prc` tool

---

## Table of Contents

1. [Query Structure](#1-query-structure)
2. [Mutation Catalog](#2-mutation-catalog)
3. [Node ID Handling](#3-node-id-handling)
4. [Pagination](#4-pagination)
5. [Bot Identification](#5-bot-identification)
6. [Permissions](#6-permissions)
7. [Rate Limits](#7-rate-limits)
8. [Working Examples](#8-working-examples)
9. [Limitations & Gaps](#9-limitations--gaps)

---

## 1. Query Structure

### Complete PR Comment Query

Fetch all PR comments (both issue comments and review threads):

```graphql
query($owner: String!, $repo: String!, $pr: Int!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      id
      number
      title

      # Issue-level comments (PR discussion)
      comments(first: 100, after: $cursor) {
        nodes {
          id
          databaseId
          body
          bodyText
          author {
            __typename
            login
            ... on Bot {
              login
            }
            ... on User {
              login
              name
            }
          }
          createdAt
          updatedAt
          isMinimized
          minimizedReason
        }
        pageInfo {
          endCursor
          hasNextPage
        }
      }

      # Review threads (code comments)
      reviewThreads(first: 100, after: $cursor) {
        nodes {
          id
          isResolved
          isCollapsed
          isOutdated
          line
          originalLine
          startLine
          originalStartLine
          path
          comments(first: 50) {
            nodes {
              id
              databaseId
              body
              bodyText
              author {
                __typename
                login
                ... on Bot {
                  login
                }
                ... on User {
                  login
                  name
                }
              }
              createdAt
              updatedAt
              isMinimized
              minimizedReason
              pullRequestReview {
                id
              }
            }
          }
        }
        pageInfo {
          endCursor
          hasNextPage
        }
      }
    }
  }
}
```

### Key Fields Available

**Comment Fields:**
- `id` - GraphQL global node ID (base64 encoded)
- `databaseId` - Integer database ID (for REST API compatibility)
- `body` - Full markdown body
- `bodyText` - Plain text version
- `author` - Actor interface (User, Bot, or Organization)
- `createdAt` / `updatedAt` - Timestamps
- `isMinimized` - Boolean visibility flag
- `minimizedReason` - Classifier if minimized

**Review Thread Fields:**
- `id` - Thread node ID
- `isResolved` - Boolean resolution status
- `isCollapsed` - Boolean collapsed state
- `isOutdated` - Boolean if code changed
- `line` / `originalLine` - Line numbers
- `startLine` / `originalStartLine` - Multi-line comment start
- `path` - File path

---

## 2. Mutation Catalog

### Comment Creation

#### addComment
**Purpose:** Add comment to issue or pull request (PR-level discussion)

```graphql
mutation CreatePRComment($prId: ID!, $body: String!) {
  addComment(input: { subjectId: $prId, body: $body }) {
    commentEdge {
      node {
        id
        body
      }
    }
  }
}
```

**Parameters:**
- `subjectId` (required): Pull request node ID
- `body` (required): Comment text (markdown supported)
- `clientMutationId` (optional): Unique identifier

**Permissions:** Pull request write access

---

#### addPullRequestReviewThread
**Purpose:** Create new review thread on specific code lines

```graphql
mutation CreateReviewThread($input: AddPullRequestReviewThreadInput!) {
  addPullRequestReviewThread(input: $input) {
    thread {
      id
      comments(first: 1) {
        nodes {
          id
          body
        }
      }
    }
  }
}
```

**Parameters:**
- `pullRequestId` or `pullRequestReviewId` (required)
- `path` (required): File path
- `line` (required): Line number
- `body` (required): Comment text
- `startLine` (optional): For multi-line comments
- `startSide` (optional): LEFT or RIGHT (for diffs)

**Limitations:**
- No `commitOID` argument - always creates comments on PR HEAD
- Both `commit` and `originalCommit` fields point to HEAD

**Permissions:** Pull request write access

---

#### addPullRequestReviewThreadReply
**Purpose:** Reply to existing review thread

```graphql
mutation ReplyToThread($threadId: ID!, $body: String!) {
  addPullRequestReviewThreadReply(input: {
    pullRequestReviewThreadId: $threadId
    body: $body
  }) {
    comment {
      id
      body
      author {
        login
      }
    }
  }
}
```

**Parameters:**
- `pullRequestReviewThreadId` (required): Thread node ID
- `body` (required): Reply text

**Status:** ✅ Available (as of August 2023)
- Was missing during deprecation transition
- Now fully functional and documented

**Permissions:** Pull request write access

---

### Comment Modification

#### updateIssueComment
**Purpose:** Modify existing issue/PR comment

```graphql
mutation UpdateComment($commentId: ID!, $body: String!) {
  updateIssueComment(input: { id: $commentId, body: $body }) {
    issueComment {
      id
      body
    }
  }
}
```

**Parameters:**
- `id` (required): Comment node ID
- `body` (required): New comment text

---

#### updatePullRequestReviewComment
**Purpose:** Modify review comment

```graphql
mutation UpdateReviewComment($commentId: ID!, $body: String!) {
  updatePullRequestReviewComment(input: {
    pullRequestReviewCommentId: $commentId
    body: $body
  }) {
    pullRequestReviewComment {
      id
      body
    }
  }
}
```

---

### Comment Deletion

#### deleteIssueComment
**Purpose:** Delete issue/PR comment

```graphql
mutation DeleteComment($id: ID!) {
  deleteIssueComment(input: { id: $id }) {
    clientMutationId
  }
}
```

---

#### deletePullRequestReviewComment
**Purpose:** Delete review comment

```graphql
mutation DeleteReviewComment($id: ID!) {
  deletePullRequestReviewComment(input: { id: $id }) {
    pullRequestReview {
      id
    }
  }
}
```

---

### Thread Management

#### resolveReviewThread
**Purpose:** Mark review thread as resolved

```graphql
mutation ResolveThread($threadId: ID!) {
  resolveReviewThread(input: { threadId: $threadId }) {
    thread {
      isResolved
    }
  }
}
```

**Parameters:**
- `threadId` (required): Review thread node ID

**Permissions:** Repository Contents: Read and Write
- Counterintuitive - not Pull Requests permission
- Discovered through experimentation

---

#### unresolveReviewThread
**Purpose:** Reopen resolved thread

```graphql
mutation UnresolveThread($threadId: ID!) {
  unresolveReviewThread(input: { threadId: $threadId }) {
    thread {
      isResolved
    }
  }
}
```

**Permissions:** Repository Contents: Read and Write

---

### Comment Visibility

#### minimizeComment
**Purpose:** Hide/collapse comment

```graphql
mutation MinimizeComment($id: ID!, $classifier: ReportedContentClassifiers!) {
  minimizeComment(input: { subjectId: $id, classifier: $classifier }) {
    minimizedComment {
      isMinimized
      minimizedReason
      viewerCanMinimize
    }
  }
}
```

**Parameters:**
- `subjectId` (required): Comment node ID
- `classifier` (required): Reason enum
  - `SPAM`
  - `ABUSE`
  - `OFF_TOPIC`
  - `OUTDATED`
  - `DUPLICATE`
  - `RESOLVED`

**Known Issue:** Classifier enum is lowercased internally, causing fallback message "This comment has been minimized" instead of specific reason.

---

#### unminimizeComment
**Purpose:** Restore hidden comment visibility

```graphql
mutation UnminimizeComment($id: ID!) {
  unminimizeComment(input: { subjectId: $id }) {
    unminimizedComment {
      isMinimized
    }
  }
}
```

---

## 3. Node ID Handling

### Node ID vs Database ID

- **Node ID**: Base64-encoded global identifier used in GraphQL
  - Format when decoded: `{type_id}:{type_name}{resource_id}`
  - Example: `MDQ6VXNlcjU4MzIzMQ==` decodes to `010:User5832231`
- **Database ID**: Integer identifier used in REST API
  - Same resource, different format
  - Available via `databaseId` field in GraphQL

### Obtaining Node IDs

**From REST API:**
```json
{
  "node_id": "MDQ6VXNlcjU4MzIzMQ==",
  "id": 5832231
}
```

**From GraphQL:**
```graphql
query {
  repository(owner: "owner", name: "repo") {
    pullRequest(number: 123) {
      id          # Node ID
      databaseId  # Integer ID
    }
  }
}
```

### Using Node IDs in Queries

**Direct node lookup:**
```graphql
query {
  node(id: "MDQ6VXNlcjU4MzIzMQ==") {
    __typename
    ... on User {
      login
      name
    }
  }
}
```

### Best Practices

1. **Persist node IDs** - They remain stable across API versions
2. **Query both IDs** - Store `databaseId` for REST API interop
3. **Use node() for lookups** - Efficient single-node retrieval
4. **No database ID lookup** - GraphQL has no direct database ID query

---

## 4. Pagination

### Cursor-Based Pagination

GitHub GraphQL uses cursor-based pagination for all connections.

**Required:**
- Must specify `first` (1-100) or `last` (1-100)
- Maximum 100 items per page

### PageInfo Fields

```graphql
pageInfo {
  endCursor       # Position of last item
  startCursor     # Position of first item
  hasNextPage     # More results forward
  hasPreviousPage # More results backward
}
```

### Forward Pagination Pattern

```graphql
# First page
query {
  repository(owner: "owner", name: "repo") {
    pullRequest(number: 123) {
      comments(first: 100) {
        nodes { id }
        pageInfo {
          endCursor
          hasNextPage
        }
      }
    }
  }
}

# Next page (if hasNextPage == true)
query {
  repository(owner: "owner", name: "repo") {
    pullRequest(number: 123) {
      comments(first: 100, after: "Y3Vyc29yOnYyOpHOUH8B7g==") {
        nodes { id }
        pageInfo {
          endCursor
          hasNextPage
        }
      }
    }
  }
}
```

### Backward Pagination Pattern

```graphql
query {
  repository(owner: "owner", name: "repo") {
    pullRequest(number: 123) {
      comments(last: 100, before: "R3Vyc29yOnYyOpHOHcfoOg==") {
        nodes { id }
        pageInfo {
          startCursor
          hasPreviousPage
        }
      }
    }
  }
}
```

### Implementation Tools

**Octokit SDK with pagination plugin:**
```javascript
import { Octokit } from "@octokit/core";
import { paginateGraphql } from "@octokit/plugin-paginate-graphql";

const MyOctokit = Octokit.plugin(paginateGraphql);
const octokit = new MyOctokit({ auth: "token" });

const { repository } = await octokit.graphql.paginate(query, variables);
```

---

## 5. Bot Identification

### Author Type Detection

Comments have an `author` field of type `Actor` (interface).

**Actor Types:**
- `User` - Human accounts
- `Bot` - GitHub App accounts
- `Organization` - Org accounts

### Query Pattern

```graphql
author {
  __typename
  login
  ... on User {
    login
    name
  }
  ... on Bot {
    login
  }
}
```

### Bot Characteristics

- Created by GitHub Apps
- Limited capabilities (cannot create/delete repos)
- Username typically contains `[bot]` suffix
- Type distinction available via `__typename`

### Filtering Bot Comments

```javascript
// Filter by type
const botComments = comments.filter(c => c.author.__typename === "Bot");

// Filter by username pattern (less reliable)
const botComments = comments.filter(c => c.author.login.includes("[bot]"));
```

---

## 6. Permissions

### Mutation Permission Requirements

**Discovered through experimentation** - Not well documented by GitHub.

#### resolveReviewThread / unresolveReviewThread
- **Required:** Repository Permissions > Contents: Read and Write
- **Counterintuitive:** Pull Requests permission is NOT sufficient
- Source: Community discussion experimentation

#### addComment / addPullRequestReviewThreadReply
- **Required:** Pull Requests: Write access
- **Typical:** Contents: Write also needed

#### General Pattern
- Test permissions iteratively
- GitHub returns 401 for insufficient permissions
- Error message sometimes indicates required scopes

### GitHub App Permissions

For GitHub Apps, configure:
- **Contents:** Read and Write (for resolve/unresolve)
- **Pull Requests:** Write (for comments)

### Personal Access Token Scopes

Minimum scopes for PR comment operations:
- `repo` (full repo access)
- Or more granular: `public_repo`, `repo:status`, `repo_deployment`

---

## 7. Rate Limits

### Primary Rate Limits

**Point System:**
- 5,000 points/hour for authenticated users
- 10,000 points/hour for GitHub Enterprise Cloud orgs
- Each query costs points based on complexity

**Calculation:**
- Use `rateLimit` query to check cost
- Test queries in GraphQL Explorer first

```graphql
query {
  rateLimit {
    cost         # Cost of this query
    remaining    # Points remaining
    resetAt      # Reset timestamp
    limit        # Total limit
  }
}
```

### Secondary Rate Limits

**Per-Minute Caps:**
- Max 2,000 points/minute for GraphQL
- Max 100 concurrent requests (REST + GraphQL combined)
- Max 90 seconds CPU time per 60 seconds real time
- Max 60 seconds CPU time for GraphQL

**Content Creation:**
- Max 80 content-generating requests/minute
- Max 500 content-generating requests/hour

### Mutation Spacing

**Best Practice:** Pause at least 1 second between mutations

### Query Optimization

1. **Limit object counts** - Use smaller `first`/`last` values
2. **Reduce depth** - Avoid deeply nested queries
3. **Filter results** - Use arguments to narrow data
4. **Break down queries** - Paginate instead of large single query
5. **Cache results** - Avoid repeated heavy calls

### Node Limits

- Max 500,000 total nodes per query
- `first`/`last` values must be 1-100

### Monitoring

```graphql
query {
  viewer {
    login
  }
  rateLimit {
    limit
    remaining
    cost
    resetAt
  }
}
```

### Best Practices

- **Prefer GraphQL over REST** - More points/minute, efficient batching
- **Use webhooks** - Avoid polling
- **Throttle requests** - Spread out over time
- **Exponential backoff** - When hitting limits
- **Rotate tokens** - Multiple OAuth tokens for high volume

---

## 8. Working Examples

### Complete PR Comment Bot

```javascript
const { Octokit } = require("@octokit/core");
const octokit = new Octokit({ auth: process.env.GITHUB_TOKEN });

// Fetch all review threads
const query = `
  query($owner: String!, $repo: String!, $pr: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $pr) {
        id
        reviewThreads(first: 100) {
          nodes {
            id
            isResolved
            comments(first: 10) {
              nodes {
                id
                body
                author {
                  __typename
                  login
                }
              }
            }
          }
        }
      }
    }
  }
`;

const variables = { owner: "org", repo: "repo", pr: 123 };
const result = await octokit.graphql(query, variables);

// Reply to thread
const replyMutation = `
  mutation($threadId: ID!, $body: String!) {
    addPullRequestReviewThreadReply(input: {
      pullRequestReviewThreadId: $threadId
      body: $body
    }) {
      comment {
        id
      }
    }
  }
`;

await octokit.graphql(replyMutation, {
  threadId: result.repository.pullRequest.reviewThreads.nodes[0].id,
  body: "Fixed in latest commit!"
});

// Resolve thread
const resolveMutation = `
  mutation($threadId: ID!) {
    resolveReviewThread(input: { threadId: $threadId }) {
      thread { isResolved }
    }
  }
`;

await octokit.graphql(resolveMutation, {
  threadId: result.repository.pullRequest.reviewThreads.nodes[0].id
});
```

### Bulk Resolve All Threads

```bash
#!/bin/bash

# Fetch threads
THREADS=$(gh api graphql -f query='
  query($owner: String!, $repo: String!, $pr: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $pr) {
        reviewThreads(first: 100) {
          nodes {
            id
            isResolved
          }
        }
      }
    }
  }
' -F owner="$OWNER" -F repo="$REPO" -F pr="$PR")

# Resolve each unresolved thread
echo "$THREADS" | jq -r '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false) | .id' | while read THREAD_ID; do
  gh api graphql -f query='
    mutation($threadId: ID!) {
      resolveReviewThread(input: { threadId: $threadId }) {
        thread { isResolved }
      }
    }
  ' -F threadId="$THREAD_ID"
  sleep 1  # Rate limit spacing
done
```

### Minimize Bot Comments

```python
import os
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport

transport = RequestsHTTPTransport(
    url="https://api.github.com/graphql",
    headers={"Authorization": f"bearer {os.environ['GITHUB_TOKEN']}"}
)
client = Client(transport=transport, fetch_schema_from_transport=True)

# Query bot comments
query = gql("""
  query($owner: String!, $repo: String!, $pr: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $pr) {
        comments(first: 100) {
          nodes {
            id
            author {
              __typename
              login
            }
          }
        }
      }
    }
  }
""")

result = client.execute(query, variable_values={
    "owner": "org",
    "repo": "repo",
    "pr": 123
})

# Minimize bot comments
minimize_mutation = gql("""
  mutation($id: ID!, $classifier: ReportedContentClassifiers!) {
    minimizeComment(input: { subjectId: $id, classifier: $classifier }) {
      minimizedComment {
        isMinimized
      }
    }
  }
""")

for comment in result["repository"]["pullRequest"]["comments"]["nodes"]:
    if comment["author"]["__typename"] == "Bot":
        client.execute(minimize_mutation, variable_values={
            "id": comment["id"],
            "classifier": "OUTDATED"
        })
```

---

## 9. Limitations & Gaps

### What GraphQL CAN Do

✅ Query all PR comments (issue + review)
✅ Query review threads with resolution status
✅ Reply to review threads
✅ Resolve/unresolve threads
✅ Minimize/unminimize comments
✅ Add comments to PRs
✅ Update/delete comments
✅ Identify bot comments via type
✅ Paginate through large result sets
✅ Batch queries efficiently

### What GraphQL CANNOT Do

❌ **Specify commit for new review threads** - No `commitOID` argument on `addPullRequestReviewThread`
❌ **Query by database ID** - No direct lookup, must use node ID
❌ **Reliable minimize classifiers** - Enum lowercased, causes fallback message
❌ **Exceed rate limits** - Hard caps on points and concurrent requests
❌ **Query without pagination** - Must use `first`/`last` (max 100)

### Known Issues

1. **Minimize Classifier Bug**
   - Classifier enum lowercased after API processing
   - Results in generic "This comment has been minimized" message
   - Specific reasons (SPAM, OUTDATED, etc.) not displayed
   - Issue documented in community discussions

2. **Permission Documentation Gap**
   - No comprehensive mapping of mutations to permissions
   - Requires experimentation (e.g., Contents: Write for resolve)
   - Error messages sometimes vague

3. **Historical API Gaps**
   - `addPullRequestReviewThreadReply` was missing during deprecation
   - Now available, but caused confusion in 2023
   - Check mutation availability before deprecating old APIs

### Workarounds

**For commit-specific comments:**
- Use REST API `POST /repos/{owner}/{repo}/pulls/{pull_number}/comments`
- Convert GraphQL node IDs to database IDs if needed

**For database ID lookups:**
- Query by repo/PR number first, then filter in application code
- Cache node ID to database ID mappings

**For minimize classifier display:**
- Accept generic message or use comment body to explain minimization

---

## Sources

- [GitHub GraphQL API Mutations Documentation](https://docs.github.com/en/graphql/reference/mutations)
- [Using Global Node IDs](https://docs.github.com/en/graphql/guides/using-global-node-ids)
- [Using Pagination in GraphQL API](https://docs.github.com/en/graphql/guides/using-pagination-in-the-graphql-api)
- [Rate Limits and Query Limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)
- [GitHub GraphQL Interfaces Documentation](https://docs.github.com/en/graphql/reference/interfaces)
- [Community Discussion: addPullRequestReviewThreadReply Missing](https://github.com/orgs/community/discussions/59924)
- [Community Discussion: Necessary Permissions for resolveReviewThread](https://github.com/orgs/community/discussions/44650)
- [Community Discussion: minimizeComment Classifier Bug](https://github.com/orgs/community/discussions/19865)
- [Community Discussion: PullRequest Timeline Review Threads](https://github.com/orgs/community/discussions/24850)
- [Community Discussion: Bot Account Types](https://github.com/orgs/community/discussions/65546)
- [Gist: Sample GraphQL Query for PR Comments](https://gist.github.com/tsriram/f65b9fbcf500de35101e49a395707bd0)
- [Gist: Resolve PR Comments Script](https://gist.github.com/kieranklaassen/0c91cfaaf99ab600e79ba898918cea8a)
- [Gist: Translating GitHub Resource IDs](https://gist.github.com/natanlao/afb676b17aa724754ee77099e4291f3f)
- [Lorna Jane: Querying GitHub GraphQL API (2025)](https://lornajane.net/posts/2025/querying-the-github-graphql-api)
- [Ben Limmer: Create or Update PR Comments in GitHub](https://benlimmer.com/blog/2021/12/20/create-or-update-pr-comment/)
- [CloudBees: Introduction to GraphQL via GitHub API](https://www.cloudbees.com/blog/an-introduction-to-graphql-via-the-github-api)

---

## Conclusion

GitHub's GraphQL API provides comprehensive support for PR comment management with the following strengths:

**Strengths:**
- Efficient batching of queries
- Flexible pagination
- Type-safe author identification
- Complete CRUD operations on comments
- Thread resolution management
- Comment visibility control

**Considerations:**
- Rate limits require careful optimization
- Permission requirements need experimentation
- Some edge cases require REST API fallback
- Documentation gaps exist for advanced use cases

**For `prc` Tool:**
The GraphQL API is well-suited for building a PR comment management tool with the following capabilities:
1. Fetch all comments and threads efficiently
2. Filter bot comments reliably
3. Reply to threads programmatically
4. Resolve/unresolve threads in bulk
5. Minimize outdated comments
6. Monitor rate limits and paginate gracefully

**Recommendation:** Build `prc` primarily on GraphQL with REST API fallback only for commit-specific review comments (if needed).
