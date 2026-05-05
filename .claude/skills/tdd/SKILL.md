---
name: tdd
description: >
  Red/green/refactor TDD workflow triggered via the /tdd slash command.
  When invoked, Claude writes a failing test first, confirms it fails,
  then writes the minimal implementation to make it pass, then refactors.
  Automatically includes security test templates when API routes or
  endpoints are detected. Use this skill any time the user runs /tdd,
  or asks to "do TDD", "test-drive", "write tests first", or
  "red green refactor" for any feature.
---

# Test-Driven Development Skill

This skill enforces a disciplined red/green/refactor cycle. Every piece of
functionality is built test-first. The goal is smaller, more confident commits
and code that's tested by design rather than as an afterthought.

## Slash command

`/tdd <description of the feature or change>`

## The cycle

Follow these steps strictly and in order. Do not skip ahead.

### 1. RED — Write a failing test

Based on the user's feature description, write one or more test cases that
describe the desired behaviour. These tests should:

- Be specific and assertion-based (not just "does it run")
- Cover the happy path first
- Use the project's existing test framework if one is present (detect from
  package.json, pytest config, etc.) — otherwise ask the user what they prefer
- Be runnable immediately

Run the test(s) and confirm they fail. Show the user the failure output.
If a test passes unexpectedly, flag this — either the test isn't testing
anything new or the feature already exists.

### 2. GREEN — Write the minimal implementation

Write the smallest amount of production code needed to make the failing
test(s) pass. Resist the urge to write more than what the test demands.
This keeps the feedback loop tight and avoids untested code paths.

Run the test(s) again and confirm they pass. Show the user the green output.

### 3. REFACTOR — Clean up with confidence

With passing tests as a safety net, improve the code:

- Remove duplication
- Improve naming and readability
- Extract functions or modules if warranted
- Simplify logic

Run the tests again after refactoring to confirm nothing broke.

### 4. REPEAT

Ask the user: "Tests are green. Want to add another case, or move on?"

If the feature needs more coverage (edge cases, error handling, boundary
conditions), loop back to step 1 with the next test case.

## API route detection — automatic security tests

When the feature description or the code being written involves any of the
following, automatically include security-focused test cases in the RED phase:

- HTTP route handlers (Express, Fastify, Next.js API routes, Flask, Django, etc.)
- REST or GraphQL endpoints
- Middleware or auth handlers
- Webhook receivers

### Security test template

Include these test categories alongside the functional tests. Not every
category will apply to every endpoint — use judgement, but err on the side
of including them.

**Authentication & authorisation**
- Request without auth token/session returns 401
- Request with expired/invalid token returns 401
- Request with valid token but insufficient permissions returns 403
- If role-based: test each role gets only what it should

**Input validation**
- Reject oversized payloads (if relevant)
- Reject unexpected content types
- Reject missing required fields with 400, not 500
- SQL/NoSQL injection strings in input fields don't cause errors or data leaks
- XSS payloads in string fields are sanitised or rejected
- Path traversal attempts in file-related params are blocked

**Rate limiting & abuse**
- If rate limiting is configured, verify it triggers correctly
- If not configured, flag this to the user as a recommendation

**Data exposure**
- Response bodies don't leak sensitive fields (passwords, tokens, internal IDs
  that shouldn't be public)
- Error responses don't expose stack traces, DB details, or internal paths
- Verify CORS headers are set correctly if endpoint is browser-facing

**Example test (Express + Jest style)**

```javascript
describe('POST /api/widgets', () => {
  // Functional (normal TDD)
  it('creates a widget and returns 201', async () => {
    const res = await request(app)
      .post('/api/widgets')
      .set('Authorization', `Bearer ${validToken}`)
      .send({ name: 'Test Widget' });
    expect(res.status).toBe(201);
    expect(res.body.name).toBe('Test Widget');
  });

  // Security: auth
  it('returns 401 without auth token', async () => {
    const res = await request(app).post('/api/widgets').send({ name: 'Test' });
    expect(res.status).toBe(401);
  });

  // Security: input validation
  it('returns 400 for missing required fields', async () => {
    const res = await request(app)
      .post('/api/widgets')
      .set('Authorization', `Bearer ${validToken}`)
      .send({});
    expect(res.status).toBe(400);
  });

  // Security: data exposure
  it('does not expose internal fields in response', async () => {
    const res = await request(app)
      .post('/api/widgets')
      .set('Authorization', `Bearer ${validToken}`)
      .send({ name: 'Test Widget' });
    expect(res.body).not.toHaveProperty('_id');
    expect(res.body).not.toHaveProperty('__v');
  });
});
```

Adapt the style and framework to match the project. The example above is
illustrative — use pytest, Vitest, Supertest, or whatever the project uses.

## Behaviour notes

- If the user provides a feature description that's too vague to write a
  meaningful test, ask a clarifying question before writing anything.
- If existing tests in the project are broken before you start, flag this
  to the user and offer to fix them first.
- Keep test names descriptive — they serve as living documentation.
- Prefer one assertion per test where practical, but don't be dogmatic about
  it. A test that checks status code and response body together is fine.
- When refactoring, don't change test names or assertions unless the
  behaviour itself is changing (that would be a new red/green cycle).
