---
name: security-review
description: >
  Security vulnerability review for code and APIs, triggered via the
  /security-review slash command. Analyses code for common vulnerability
  patterns including injection, auth issues, data exposure, dependency
  risks, and API-specific concerns like CORS, rate limiting, and input
  validation. Use this skill when the user runs /security-review, asks
  to "check for vulnerabilities", "review security", "audit this code",
  "is this secure", or any request to find security issues in code,
  endpoints, or API designs.
---

# Security Review Skill

This skill performs a structured security review of code and APIs. It's
designed to catch common vulnerabilities before they ship, not to replace
a full penetration test — but it covers the issues that most often slip
through in day-to-day development.

## Slash command

`/security-review [file, directory, or description of what to review]`

If no target is specified, review all changed files in the current git diff.
If there's no git context, ask the user what to review.

## Review process

### 1. Identify what you're looking at

Before diving in, understand the context:

- What framework/language is this?
- Is this a public-facing API, internal service, or library?
- What auth mechanism is in use (if any)?
- What data does this code handle? (PII, financial, health, etc.)

This context shapes which checks matter most. A public API handling user
data needs much more scrutiny than an internal CLI tool.

### 2. Run the checks

Work through each category below. Skip categories that genuinely don't
apply (e.g., don't check for CORS issues in a CLI tool), but err on the
side of checking rather than skipping.

## Check categories

### A. Injection vulnerabilities

Look for places where user input flows into:

- SQL queries — is it parameterised or string-concatenated?
- NoSQL queries — are operators like `$gt`, `$where` possible via input?
- Shell commands — is `exec`, `spawn`, `system` called with user input?
- Template rendering — is user input rendered without escaping?
- LDAP, XPath, or other query languages

Flag any string interpolation or concatenation involving user input in
these contexts. Even if an ORM is in use, check for raw query escape hatches.

### B. Authentication & authorisation

- Are there endpoints or routes missing auth middleware?
- Is auth checked at the route level or only at a gateway — and could it
  be bypassed?
- Are JWTs validated properly (signature, expiry, issuer, audience)?
- Is token storage secure (httpOnly cookies vs localStorage)?
- Are API keys or secrets hardcoded or committed?
- Is there role/permission checking, or just "is authenticated"?
- Are password hashing algorithms appropriate (bcrypt/argon2, not MD5/SHA)?

### C. Input validation & sanitisation

- Are request bodies validated against a schema?
- Are file uploads checked for type, size, and content?
- Are URL parameters and query strings validated?
- Is there protection against oversized payloads?
- Are content-type headers enforced?

### D. Data exposure

- Do API responses include fields that shouldn't be public?
  (database IDs, internal flags, timestamps that leak info, password hashes)
- Do error responses expose stack traces, SQL errors, or file paths?
- Are logs capturing sensitive data (passwords, tokens, PII)?
- Is sensitive data encrypted at rest?

### E. API-specific concerns

- **CORS**: Is the origin whitelist appropriate, or is it wide open (`*`)?
- **Rate limiting**: Is there any? If not, flag it. If so, is it per-user
  or per-IP, and are the limits reasonable?
- **HTTPS**: Is TLS enforced? Are there redirect loops or mixed content?
- **Headers**: Are security headers set? (Strict-Transport-Security,
  Content-Security-Policy, X-Content-Type-Options, X-Frame-Options)
- **Versioning**: Are deprecated endpoints still accessible?
- **HTTP methods**: Are only intended methods allowed per route?

### F. Dependency & supply chain

- Are there known vulnerabilities in dependencies? (Check for `npm audit`,
  `pip audit`, `cargo audit` results if available)
- Are dependency versions pinned or floating?
- Are there unnecessary dependencies that increase attack surface?

### G. Secrets & configuration

- Are secrets in environment variables, not code?
- Are `.env` files in `.gitignore`?
- Are there any hardcoded credentials, API keys, or tokens?
- Is there a secrets management approach, or are prod secrets ad hoc?
- Check for accidental commits: does git history contain secrets?

### H. Business logic

- Can users access or modify resources belonging to other users? (IDOR)
- Can pricing, quantities, or permissions be manipulated client-side?
- Are there race conditions in critical operations (payments, inventory)?
- Is idempotency handled for operations that shouldn't repeat?

## Output format

Present findings grouped by severity:

**Critical** — Exploitable now, would cause real damage.
Examples: SQL injection, hardcoded production secrets, missing auth on
sensitive endpoints, unauthenticated admin routes.

**High** — Significant risk, should fix before shipping.
Examples: Weak password hashing, overly permissive CORS, no rate limiting
on auth endpoints, PII in logs.

**Medium** — Should address, but not an emergency.
Examples: Missing security headers, verbose error messages in production,
floating dependency versions.

**Low / Informational** — Good practice, worth noting.
Examples: Could add CSP headers, consider adding request ID tracing,
might want to pin dependency versions.

For each finding, include:

1. **What**: One-line description of the issue
2. **Where**: File and line number (or route/endpoint)
3. **Why it matters**: Brief explanation of the risk
4. **Fix**: Concrete suggestion, ideally with a code snippet

## Behaviour notes

- Don't cry wolf. Only flag things that are genuinely concerning in context.
  A prototype with no auth is worth mentioning, but it's not "critical" if
  it's clearly a local dev tool.
- When you're not sure if something is a problem, say so. "This might be
  intentional, but worth confirming: ..." is better than a false alarm or
  a missed issue.
- If the codebase is large, focus on the highest-risk areas first:
  auth flows, payment handling, data access layers, and public endpoints.
- If you spot something that the /tdd skill's security test template would
  catch, mention that too — the two skills complement each other.
- If you find no significant issues, say so clearly. Don't invent problems
  to look thorough.
