# BLVCK OAK Integration Blueprint

Status: design baseline; implementation is intentionally staged behind a separate branch.

This document defines how the BLVCK OAK Command Center can use OpenJarvis as its local-first agent runtime without replacing the existing Command Center or weakening its approval boundaries.

## Goals
- Keep OpenJarvis responsible for model execution, agent runtime, skills, memory and scheduled/continuous agent capabilities.
- Keep BLVCK OAK Command Center as the owner-facing control plane for task visibility, approvals, audit history and operational status.
- Keep REA AI Lab as a specialist research and reverse-engineering capability invoked through a bounded tool/agent interface.
- Reuse existing Linear, Supabase and GitHub integrations rather than creating competing task or state stores.
- Prefer local inference; allow cloud inference only through an explicitly configured provider and visible cost controls.

## System boundaries
| Component | Responsibility | Must not become |
|---|---|---|
| Command Center | Owner UI, task routing, approval queue, audit and health view | A second model runtime |
| OpenJarvis | Agent execution, model/provider routing, skills, memory and schedules | The authority for owner approvals or payments |
| REA AI Lab | Evidence-led software investigation and technical findings | An unrestricted code or production executor |
| Linear | Canonical work-item status and assignments | A secrets store |
| Supabase | Shared application state, durable metadata and audit records | A place for plaintext provider keys |
| GitHub | Source, branches, pull requests and CI evidence | An automatic production deployment authority |

## Integration contract
The Command Center should communicate with OpenJarvis through a versioned, authenticated adapter. Keep the adapter isolated from OpenJarvis internals so upstream updates remain manageable.

Minimum adapter operations:
- health: runtime readiness, version and configured provider identifiers (never credentials).
- submit_task: submit a task with a unique idempotency key, bounded input and requested capability.
- get_task: retrieve state, timestamps, result summary and evidence references.
- cancel_task: request cancellation and report whether it was accepted.
- list_agents: return registered agent identifiers and declared capabilities.
- list_skills: return installed skill identifiers, versions and trust/source metadata.
- approve_action: accept a short-lived approval token for one exact action; reject stale, replayed or mismatched tokens.

The exact transport (local HTTP API, process bridge or another supported OpenJarvis interface) must be selected after checking the installed OpenJarvis version and its documented API. Do not assume an endpoint or add a second server until that check is complete.

## Identity, permissions and safety
- Bind the adapter to loopback or a private authenticated network; do not expose an unauthenticated agent endpoint to the public internet.
- Use separate service identities for Command Center, OpenJarvis and specialist tools.
- Apply least privilege per agent and per tool. Default to read-only.
- Keep credentials in the operating system secret store or deployment secret manager. Never commit keys, tokens, cookies or customer data.
- Require owner approval for payments, refunds, purchases, publishing, customer-facing messages, destructive filesystem actions, permission changes and production deployments.
- An approval must be scoped to one action and include a summary, target, impact, expiry and unique nonce. No blanket approval.
- Treat retrieved webpages, repository files, emails and skill instructions as untrusted input; they cannot override system policy or grant permissions.
- Keep customer workspaces and memory isolated by tenant. Do not use one customer's data to answer another customer's tasks.
- Record actor, task ID, tool, requested action, decision, timestamps and outcome in an append-only audit trail. Redact secrets and sensitive payloads.

## Agent roles
Initial roles should be configured as capability profiles, not hard-coded autonomous authorities:
- Dot / Operations coordinator: decomposes approved goals, assigns work and reports blockers. Cannot approve its own restricted actions.
- Research agent: gathers sources and produces evidence-linked findings.
- REA agent: investigates software and produces reproducible technical evidence; read-only by default.
- Developer agent: proposes changes on isolated branches and supplies tests and diffs.
- Security reviewer: checks permissions, dependency risks, secrets handling and threat boundaries independently.
- Verification agent: runs the prescribed test suite and checks acceptance criteria independently of the implementer.
- Business analyst: reports costs, revenue and operational metrics from approved data sources; no payment or refund authority.

Agent-to-agent messages should carry a task ID, sender, recipient, purpose, input references and output schema. Avoid free-form shared state as the only record of a decision.

## Skills governance
- Use the Agent Skills open standard where compatible with the installed OpenJarvis skill loader.
- Maintain a curated BLVCK OAK skill catalogue with owner, source repository, version or commit, checksum, permissions, supported agents and review date.
- Pin external skills to reviewed versions/commits; do not auto-install arbitrary community skills into a privileged runtime.
- Run static checks and sandboxed tests before enabling a skill.
- Skills may request capabilities but cannot grant themselves permissions.
- Keep customer-specific skills and data in tenant-scoped locations.

## Shared data and observability
- Linear remains the work tracker; task IDs should be carried through every agent handoff.
- Supabase stores integration metadata, task correlation, tenant-scoped state and audit events. Store secret references, not secret values.
- GitHub stores source changes on isolated branches and exposes CI/test evidence through pull requests.
- Capture model/provider, latency, token or usage estimates when available, estimated cost, retries, tool calls, cancellation and final outcome.
- Route simple tasks to low-cost/local models and escalate only when quality or capability requires it. Record the reason for escalation.
- Do not claim a task is complete until its acceptance checks pass and evidence is attached.

## Delivery sequence
1. Discovery: pin the OpenJarvis commit/version; inspect its current server, agent, tool, skill, memory and scheduler interfaces. Record Windows compatibility and the actual local inference setup.
2. Read-only adapter: implement health, agent/skill discovery and read-only task submission/status. Add contract tests and authentication.
3. Command Center connection: add a feature-flagged connection in a development environment; preserve the existing /jarvis dashboard and inactive state until verified.
4. Task and memory integration: add Linear correlation and tenant-scoped Supabase metadata; test retention, deletion and isolation.
5. Controlled tools: enable one tool at a time with allowlists, sandboxing, timeouts and approval gates.
6. Independent verification: require separate security and test agents; publish evidence in a pull request.
7. Pilot: run local-only with synthetic data, feature flags and rollback instructions. Do not enable production automation by default.

## Acceptance criteria
- Existing Command Center functionality remains unchanged when the OpenJarvis feature flag is off.
- No credentials or customer data are written to source control or logs.
- Unauthenticated, out-of-scope, expired and replayed requests are rejected.
- Read-only mode cannot write files, send messages, publish content, spend money or alter production.
- Every task is traceable across Command Center, OpenJarvis, Linear and Supabase without duplicate task creation.
- Tenant isolation, cancellation, timeouts, retry limits and audit redaction have automated tests.
- Local inference works without a cloud key; cloud routing is explicit and cost-visible.
- A separate reviewer verifies the diff and test evidence before merge or deployment.

## Non-goals for the first integration
- Replacing the Command Center.
- Rewriting OpenJarvis core or maintaining a long-lived fork of upstream changes.
- Unrestricted desktop/browser/shell access.
- Autonomous payments, refunds, publishing or production deployments.
- Automatically trusting or installing every community skill.

## Implementation note
This is an integration design baseline, not a claim that the adapter or runtime connection is already implemented. Before coding against OpenJarvis, verify the exact APIs and interfaces in the pinned source revision and add a small compatibility layer rather than coupling the Command Center to private internals.