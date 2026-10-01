# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The household that hosts the instance: a small group of people sharing the
same bank accounts, with different access levels (`admin` / `editor` /
`viewer` roles in the database). The main use is quick categorization of
transactions from a smartphone or tablet, on the go or in short sessions
("goal: handle 30 transactions in under 3 minutes").

## Product Purpose

Twiga is a personal finance steering tool, not accounting software. It exists
to make the chore of categorizing manually imported bank transactions
bearable, and to give a clear view of the budget and savings, without ever
connecting the household to a third-party cloud service.

## Positioning

100% local and self-hosted (Docker Compose, PostgreSQL): no automatic bank
connection (no Plaid/SimpleFIN/Open Banking), no AI assistant, no outgoing
network call, no telemetry, no library loaded from a CDN. A SaaS competitor
cannot honestly reproduce this promise of privacy and offline operation.

## Operating Context

- Deployed with Docker Compose on a server at home (e.g. NAS, Raspberry Pi,
  Proxmox VM), reachable on the local network (and possibly exposed behind a
  password when accessed remotely).
- Manual import of bank statements: QIF (initial import, HomeBank history),
  CSV and OFX (regular imports), with duplicate detection.
- Daily/weekly two-step workflow: "La Savane" (card-by-card categorization,
  mobile-first) when transactions are waiting, then "Panorama" (dashboard)
  once the inbox is empty.
- Installable PWA (Android, iOS, desktop) for a native-app feel.

## Capabilities and Constraints

- All amounts are `NUMERIC(15, 2)` in the database and `decimal.Decimal` in
  Python, never `Float`/`Double` for money (non-negotiable constraint for a
  financial project).
- No React/Vue/Node on the frontend: Jinja2 + HTMX + Alpine.js + TailwindCSS
  only. All JS/CSS libraries are vendored locally in
  `frontend/static/vendor/`.
- User roles: `viewer` (read-only), `editor` (categorization, budgets,
  projects), `admin` (full access: import, deletion, users, settings).
- No stock/crypto/investment tracking, no double-entry accounting.
- Product terminology: three French brand names are kept as is in every
  language and explained in the English guided tour: **La Savane**
  (categorization inbox), **Panorama** (dashboard) and **Le Cap** (the monthly
  budget ritual, inspired by the Japanese kakeibo method). The other screens
  (Transactions, Reports, Projects, Settings) are translated.

## Brand Commitments

- Name: **Twiga** 🦒 ("giraffe" in Swahili), tagline *"Voir loin. Voir juste."*
  ("See far. See true.")
- Visual identity already in place (see
  `frontend/static/css/design-system.css`): giraffe-spot pattern as the
  background (`giraffe-pattern.svg` / dark variant), amber `#D4A96A` as the
  accent color, `twiga-logo.svg` logo. These existing choices are
  authoritative: document and refine them, do not replace them unless
  explicitly asked to.

## Evidence on Hand

- Existing code, templates and design tokens in the repository (main source
  of truth).
- No testimonials, benchmarks or marketing data to invent: a self-hosted
  tool with no product storytelling to build.

## Product Principles

1. Privacy and 100% offline operation come before any convenience that would
   require an external service.
2. Touch speed of the categorization workflow ("La Savane") is the most
   concrete measure of the app's success; every friction added to that flow
   has a real cost.
3. Financial accuracy (rounding, balances) is non-negotiable; never a design
   or technical compromise that would weaken it.
4. The simplicity of a tool for a small household: no multi-tenant
   complexity, no collaborative features beyond the roles already in place.
5. Consistency with the established Twiga identity (giraffe, amber, French)
   rather than a visual reinvention at every iteration.

## Accessibility & Inclusion

No specific requirement beyond the usual web standards already met in the
original specification (contrast, touch targets ≥ 50 px, no horizontal scroll
on a 390 px viewport).
