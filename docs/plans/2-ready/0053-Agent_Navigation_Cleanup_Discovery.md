# Agent navigation cleanup discovery

## Plan status

- **Summary:** Use one repository-wide Sol review to find and rank cleanup work that reduces the
  context agents need to navigate, understand, and change the repository.
- **Status:** Ready
- **Depends on:** None
- **Readiness:** The review is read-only. It can start from the tracked repository, current active
  plans, tests, build configuration, and generated or runtime boundaries.
- **Outcome:** Publish a concise repository navigation map and create a small set of evidence-based
  follow-up epics for separate Terra specification. Do not implement cleanup in this epic.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — one Sol agent maps navigation costs, ranks low-risk cleanup candidates, and
  creates the justified follow-up epics.

## 1. Problem and priority

The repository has accumulated features, documentation, directories, and component internals over
many development cycles. Agents now spend too much context on finding the active contract, relevant
entry point, owning component, and correct verification command.

Optimize for agent navigation. Prefer changes that let an agent identify the correct files and
constraints with less reading. Treat smaller file counts, shorter documentation, fewer commands,
and tidier folders as possible methods. They are not outcomes by themselves.

Human developers rarely use detailed development interfaces directly. Agents perform most
development work. Operators use the product UIs for normal work. Review command-line interfaces and
human-oriented documentation under that operating model, but do not assume that they are obsolete.
An agent, test, automation, deployment path, or recovery workflow can still need a command-line
interface.

## 2. Planning structure and agent roles

Use three model tiers and two planning levels:

1. One `gpt-5.6-sol` agent completes M0 of this discovery epic. It must not delegate repository
   areas to other agents. The purpose is one consistent repository-wide judgment with a bounded
   context budget.
2. The Sol agent creates one follow-up epic for each justified work area. Each follow-up starts in
   `To Specify` and assigns its first specification milestone to one `gpt-5.6-terra` agent. One
   Terra agent owns one work area and gathers the detailed evidence for that area.
3. The Terra milestone replaces the high-level outline with small delivery milestones. Each
   delivery milestone must fit one `gpt-5.6-luna` phase. Move the epic to `Ready` only when those
   milestones have concrete boundaries and acceptance checks.

Do not create a third level of smaller implementation epics by default. The existing milestone
unit already provides the Luna-sized delivery boundary. Create another epic only when work has an
independent outcome, dependency, or closure decision that cannot remain clear inside its work-area
epic.

## 3. Discovery method

Keep the Sol pass broad and shallow. Do not read every source file or design the cleanup. Start with
cheap repository evidence and inspect more only when it can change the ranking:

- tracked path and file-size inventories;
- root and component instructions, active architecture documents, and README files;
- build, test, lint, format, type, generation, and runtime entry points;
- command definitions and their references from agents, tests, automation, and documentation;
- source-to-test layout, public imports, dependency direction, and clear responsibility hotspots;
- duplicate, stale, conflicting, or orphaned current guidance; and
- generated, cached, model, fixture, source-data, and runtime boundaries that affect search results.

Exclude dependency trees, build products, caches, local runtime data, accepted source assets, and
closed epic history from cleanup counts unless their placement or search visibility directly harms
agent navigation. Closed epics are immutable historical records. Do not treat their old terminology
or commands as current guidance unless an active document points to them as current authority.

For every candidate, record:

- the navigation problem and a concrete example;
- affected paths and current owner;
- evidence that the surface is unused, duplicated, misleading, oversized, or poorly placed;
- expected context reduction or decision simplification;
- implementation risk and likely verification boundary;
- confidence and the missing evidence that Terra must collect; and
- the active epic, if one already owns the work.

Use `high`, `medium`, or `low` ratings. Do not invent precise token savings without a repeatable
measurement. Rank high-confidence, high-navigation-benefit, low-risk work first. Stop after the
small set of candidates that can support a useful cleanup session. This is not an exhaustive
repository review.

## 4. Required review themes

### Development interfaces

Classify command-line interfaces and scripts by consumer: agent development, test or automation,
runtime or operations, recovery, or direct human convenience. Candidate removal requires repository
evidence that no necessary consumer remains and that the UI or a smaller direct interface covers
the supported workflow. Prefer removal over compatibility layers when removal is justified.

### Documentation

Identify the smallest authoritative path from root instructions to component contract and local
verification. Distinguish durable product or architecture documentation from agent execution
instructions where that distinction removes duplication or conflict. Do not create parallel human
and agent versions of the same facts. Shared facts need one authority; audience-specific documents
should link to it.

### Repository structure

Default to keeping top-level component boundaries. A move is a candidate only when it fixes a
demonstrated ownership or discovery problem for several common tasks and its import, build, test,
fixture, and documentation churn is proportionate. Cosmetic folder uniformity is insufficient.

### Component-local architecture

Find only clear hotspots where file size, mixed responsibilities, dependency direction, duplicated
contracts, or distant tests force agents to load unrelated context. Leave detailed module design to
the owning Terra follow-up. Do not propose broad rewrites from line counts alone.

## 5. M0 deliverables

The Sol agent must produce one concise report under `docs/reports/` with:

- a first-hop repository navigation map;
- the evidence and rating for each retained candidate;
- rejected ideas and the reason for rejection, including any rejected top-level moves;
- the recommended order of follow-up work; and
- baseline measures that later work can repeat where practical.

Create no more than six follow-up epics. Prefer fewer. Combine closely related low-risk removals
when they share one verification boundary. Do not create an epic for an observation without a clear
navigation benefit.

Each follow-up epic must contain only enough detail for its Terra specification pass:

- a high-level problem and outcome;
- the Sol evidence and candidate paths;
- explicit exclusions and known overlap with active work;
- one `M0` specification milestone assigned to `gpt-5.6-terra`;
- the questions M0 must answer before implementation;
- a requirement for Luna-sized delivery milestones and focused verification; and
- `To Specify` status with this epic as its dependency.

M0 completes when the report, board changes, and all justified follow-up epic outlines are committed
to `main`, local Markdown links pass, and unrelated tracked and untracked files remain unchanged.

## 6. Guardrails

- Do not implement, delete, move, or rewrite cleanup candidates in this epic.
- Do not modify active feature behavior to make cleanup easier.
- Do not duplicate work already owned by an active epic. Record the navigation concern on the
  earliest active owner or create a dependency when separation is necessary.
- Do not preserve obsolete development interfaces merely for backward compatibility.
- Do preserve source assets, reviewed data, reproducible fixtures, model evidence, and runtime
  recovery paths unless a follow-up proves that another canonical boundary replaces them.
- Keep every follow-up independently closable when detailed evidence does not support the original
  candidate.
