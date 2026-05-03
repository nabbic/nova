# Technical Due Diligence Platform — Design Spec

**Date:** 2026-05-01
**Project:** Nova
**Status:** Approved
**Working title:** [Product Name TBD]

---

## Overview

A SaaS platform that automates technical due diligence for PE M&A transactions. It sits as a neutral third party between the buyer (PE firm) and seller (target company), automatically gathering data from the seller's tech estate, synthesising findings with AI, and delivering a structured diligence report to the buyer. A human advisor layer validates AI-generated findings before the buyer sees the final report.

**The core value proposition:**
- For the **seller**: zero manual disclosure work — connect your tools and we handle the rest. You control scope and see exactly what is shared.
- For the **buyer**: a comprehensive, advisor-validated technical report in days rather than weeks. *(Timeline dependent on seller completing the connection wizard — the platform's processing time is hours, not days.)*
- For **advisors**: raw scan data and full technical depth to validate findings and add commentary.

---

## 1. Users, Roles & Tenancy

### 1.1 Buyer organisation model

PE firms are provisioned as **Buyer Organisations** in the platform. This is a one-time setup. All users at a PE firm belong to the same organisation and are never re-provisioned per deal. An organisation can have many active deal engagements running simultaneously, and users can move between them freely.

The organisation dashboard shows all active and historical engagements. Users are assigned to specific engagements within their organisation — they see only the deals they are assigned to unless they are an org admin.

**Historical engagement retention:** Buyer orgs retain access to all historical engagement reports within their portal. This supports re-review of past targets, benchmarking across deals, and future monitoring or re-evaluation features. The report and curated findings are retained; raw seller scan data is subject to the deal outcome data policy (see Section 1.5).

### 1.2 Role definitions

| Role | Who | Access level |
|---|---|---|
| **Org Admin** | PE firm IT / operations | Manages users, billing, org-level settings. Assigns users to engagements. |
| **Buyer** | PE firm deal partners, internal tech team | Curated, presented findings — exec summary through category drilldown. Cannot see raw scan data. |
| **External Advisor** | PE firm's retained tech DD consultant, or internal tech team where IP agreement permits | Raw scan data + full technical detail + all findings. Elevated access is deal-specific, requires a two-step approval workflow (see 1.4). |
| **Seller** | Target company's engineering / ops lead | Own portal only — scoped to a specific engagement. Connects tools, sees what is being scanned, uploads supplemental data, responds to clarification requests. |

Seller accounts are provisioned per engagement, not per organisation. A seller's access exists only for the duration of the engagement it was created for, and is linked to the buyer organisation that initiated it.

### 1.3 Annotations & comments

Both Buyer and External Advisor can annotate individual findings with comments. Annotations are visible to all users on the same side of the deal. Annotations are appended to the final report as a permanent record and are displayed as a distinct layer from AI-generated content — they never modify the underlying finding.

### 1.4 IP protection principle

Raw scan data (source code metrics, infrastructure topology, cost data, dependency graphs) is never surfaced to Buyer by default. Buyer sees curated synthesis only. Elevation to External Advisor access requires explicit opt-in by the seller and is enforced via a two-step approval workflow:

1. Org Admin sends an elevation request to the seller, specifying which user and which data categories will be exposed.
2. Seller receives a notification with a plain-English description of exactly what the elevated user will see, and must explicitly approve via a signed confirmation step.
3. Platform grants the elevated role only after seller confirmation is recorded. The approval is time-stamped and immutable.

This workflow is technically enforced — there is no admin override path that bypasses seller confirmation.

### 1.5 Deal outcome data policy

When an engagement is closed, the buyer must record the outcome. This triggers a data handling workflow with no exceptions:

**Deal closed (acquisition completed):**
- Seller loses all portal access immediately
- Buyer retains the curated report and findings within their org portal for ongoing reference
- Raw scan data (connector outputs, uploaded documents, agent artefacts) is deleted from S3 and the findings store within 30 days of close
- Buyer retains only the synthesised, curated report — not the underlying raw data

**Deal abandoned / fell through:**

The seller enters a structured **offboarding period** before access is revoked. Immediately cutting access would leave the seller unable to clean up the connector footprint they were asked to create, which is both a practical and trust problem.

Offboarding workflow:
1. Either party marks the deal as abandoned. The engagement status changes to **Offboarding**.
2. Seller receives an offboarding checklist in their portal — a step-by-step guide to revoking each OAuth connection they authorised, uninstalling the OS agent (if deployed), and rotating any credentials they shared. The platform highlights exactly what was connected and what needs to be cleaned up.
3. Platform suspends all buyer access to findings immediately — buyer cannot view or export any data from this point.
4. Seller has a defined offboarding window (default: 7 days) to work through the checklist. They can request an extension if needed.
5. Once the seller confirms offboarding is complete (or the window expires), the platform initiates full data deletion: raw scan data, uploaded documents, synthesised findings, the report, and all annotations.
6. A deletion receipt is issued to both parties. Deletion is permanent, auditable, and enforced at the infrastructure level (S3 lifecycle rules, database hard delete — no soft-delete fallback).

Buyer does not retain access to any findings or the report after a deal is abandoned. Retention of any seller data outside the platform is prohibited under platform terms.

This policy must be reflected in the platform's data processing agreements.

---

## 2. Architecture

```
── BUYER ORG (PE Firm) ───────────────────── SELLER (Target Company) ──

  Org Dashboard                              Seller Portal
  (all deals · users · settings)            (connect tools · scope · Q&A · uploads)

  Engagement View                            Engagement View
  (curated findings · exec report)          (this engagement only)

          ──────────── SaaS Web Frontend (role-based) ────────────

                        Engagement Engine
             (deal rooms · invitations · scope negotiation ·
              permissions · IP access controls · status tracking)

                              ↓

               Job Queue (SQS) + Async Workers (ECS)
               (scan jobs dispatched per engagement ·
                progress events streamed to frontend)

                              ↓

                  Agent API (LangGraph + AgentCore)
          ← cloud connectors push data here (outbound to seller SaaS APIs)
          ← OS agent calls this API outbound from seller infrastructure
               No inbound connections to seller networks. Ever.

                              ↓ runs

  ┌─────────────┬──────────────┬──────────────┬─────────────┐
  │ Code Agent  │ Infra Agent  │ Security     │ Process     │
  │             │              │ Agent        │ Agent       │
  ├─────────────┼──────────────┼──────────────┼─────────────┤
  │ Deps Agent  │ Compliance   │ Docs Agent   │ IT Ops      │
  │             │ Agent        │              │ Agent       │
  └─────────────┴──────────────┴──────────────┴─────────────┘

  ┌──────────────────────────┬─────────────────────────────────┐
  │  Cloud Connectors        │  OS-Level Agent (optional)      │
  │  GitHub · GitLab · AWS   │  Installed on seller VMs /      │
  │  GCP · Azure · Jira      │  servers · outbound only ·      │
  │  M365 · Google Workspace │  no inbound ports               │
  │  PagerDuty · Snyk · ...  │                                 │
  └──────────────────────────┴─────────────────────────────────┘

  ┌──────────────────────────┬─────────────────────────────────┐
  │  Manual Upload (S3)      │  Questionnaire Engine           │
  │  PDFs · spreadsheets ·   │  Structured interview for       │
  │  policy docs · runbooks  │  low-connectivity orgs          │
  └──────────────────────────┴─────────────────────────────────┘

                              ↓ all inputs

  ┌───────────────────────┬────────────────────────────────────┐
  │  Findings Store       │  AI Layer (Bedrock AgentCore)      │
  │  Structured · versioned│  LangGraph orchestration ·       │
  │  per scan · queryable │  LiteLLM gateway · Guardrails     │
  │  OpenSearch (vectors) │  AgentCore Memory · S3 artefacts  │
  └───────────────────────┴────────────────────────────────────┘
```

---

## 3. Engagement Lifecycle

A full engagement runs in 9 steps:

1. **PE firm creates a deal room** — names the target, sets timeline, selects diligence scope (all 7 modules default, configurable). Invites seller via secure link. Assigns users from the org to the engagement as Buyer or External Advisor.

2. **Seller accepts and reviews scope** — receives plain-English breakdown of what will be scanned. Can flag modules for discussion before proceeding. Reviews and approves IP access level (standard Buyer view vs External Advisor raw access).

3. **Seller connects systems** — guided wizard for each connector category: source code, cloud infrastructure, productivity tools, observability, etc. Each connector shows exactly what read-only access is requested. For on-prem components, OS-level agent download with install guide. Sellers can upload documents manually for anything not covered by a connector. Estimated connection time: 20–45 minutes depending on number of integrations.

4. **Agents run autonomously** — all 8 agents execute in parallel where possible. Jobs are queued via SQS and processed by async workers. Both sides see live progress per category. No human input required. Estimated processing time: 2–6 hours depending on codebase and infrastructure size.

5. **AI synthesises findings** — synthesis layer reads all structured findings, generates impact narrative per finding, produces executive summary with overall risk score, flags critical issues, and compiles the full report draft.

6. **Advisor reviews** — External Advisor drills into raw findings, adds annotations and commentary. Buyer-side users can also annotate at this stage. Report is marked advisor-reviewed when complete.

7. **Buyer reviews report and raises clarifications** — buyer receives notification. Live dashboard with exec summary and category drilldown. Can export PDF. Can raise structured clarification requests to seller. AI chat grounded in findings is available for ad-hoc questions.

8. **Seller responds to clarifications** — structured Q&A within the platform. All responses appended to the final report.

9. **Engagement closed** — report locked and archived. Seller system access revoked. Deal room retained as permanent record. Typical platform processing time once seller connections are complete: 1 business day.

---

## 4. Data Collection Layer

### 4.1 Cloud & SaaS connectors

OAuth or read-only API token integrations. Each connector requests the minimum scope required and the seller sees a plain-English description of what will be accessed before authorising.

Integrations are the core of the product and the connector library will grow continuously. The v1 set is:

| Category | Connectors |
|---|---|
| Source code | GitHub, GitLab, Bitbucket |
| Cloud infrastructure | AWS (read-only IAM role), GCP (viewer role), Azure (reader role) |
| Code quality | SonarQube (cloud + self-hosted), Snyk |
| Engineering process | Jira, Linear, GitHub Actions, GitLab CI, Azure DevOps |
| Incident management | PagerDuty, OpsGenie |
| Observability | Datadog, New Relic (read-only) |
| Productivity & comms | Microsoft 365 (SharePoint, Teams — document and process signals only), Google Workspace (Drive, Docs — document and process signals only) |
| Security scanning | Semgrep, Trivy, Checkmarx |

M365 and Google Workspace connectors are scoped to metadata and document access only — email and personal communications are explicitly excluded. These connectors are particularly valuable for assessing documentation maturity, knowledge management practices, and operational process signals (runbooks, incident records, architecture docs in shared drives).

Post-v1 connector priorities: Confluence, Notion, Salesforce (contract signals), Slack (process signals), Okta, CrowdStrike.

### 4.2 OS-level agent (buyer-requested escalation)

Cloud connectors cover the majority of modern SaaS-native targets. The OS-level agent is an optional escalation tier — not part of the default engagement flow — available when the buyer determines deeper infrastructure visibility is warranted.

**When it is requested:** After cloud connector scanning completes, the buyer (or External Advisor) can review the findings and request OS-level scanning if: findings indicate significant on-prem infrastructure, cloud scans surface gaps that suggest unmanaged server workloads, or the deal warrants deeper scrutiny of the IT estate.

**Escalation workflow:**
1. Buyer raises an OS scan request from the engagement view, specifying which categories of OS-level data they want
2. Seller receives a plain-English explanation of what the agent will collect, and must explicitly accept before the agent download is made available
3. Seller installs the agent on the relevant hosts
4. Agent runs and reports back; findings are appended to the existing report

**Agent characteristics:**
- **Outbound only** — calls out to the platform, no inbound ports
- **Read-only** — no write access to any system
- **Manifest-declared** — seller sees a manifest of every data type the agent can collect before accepting
- **Scoped** — seller configures which hosts and services the agent is permitted to reach
- Collects: OS version and patch level, installed software inventory, open ports and services, self-hosted tool versions (SonarQube, Jenkins, private Git servers), database presence (schema only — no data), network topology signals

This model keeps the default engagement friction low while preserving depth for deals that need it.

### 4.3 Manual upload

Sellers can upload documents for anything not covered by a connector: policy documents, architecture diagrams, runbooks, incident post-mortems, compliance certifications, vendor contracts. Uploads are stored in S3, associated with the engagement, and made available to the Docs Agent and Compliance Agent for AI assessment.

Accepted formats: PDF, Word, Markdown, Excel, PowerPoint, images.

### 4.4 Low-connectivity assessment path

Not all target companies have a mature SaaS tooling footprint — smaller, bootstrapped, or legacy-software companies may not use GitHub, AWS, Snyk, or any of the standard connectors. Good engineering practices can exist without these tools, and the platform must still provide value to the buyer in these cases.

For low-connectivity engagements, the platform provides two complementary inputs:

**Structured questionnaire:** Covers each of the 8 categories with targeted questions designed to surface practices, processes, and evidence regardless of tooling:

- Code quality: "How is code review conducted? What is the branching strategy? Is there a test suite — what percentage of critical paths does it cover?"
- Security: "When was a penetration test last conducted? Who manages dependency updates? How are access credentials managed?"
- Infrastructure: "What is the deployment process? Where is the system hosted? What is the disaster recovery plan?"
- Process: "How are incidents handled? What is the on-call rotation? How are deployments tracked?"
- IT Operations: "How are devices managed? Is MFA enforced across all systems? What is the identity provider? Is there a formal ITSM process?"
- Documentation: "Where does technical documentation live? Who maintains it? Is there a runbook for common failure scenarios?"

**Evidence uploads:** For each questionnaire question, the seller can upload supporting evidence — screenshots, exported reports, policy documents, audit results, test output, architecture diagrams. The AI synthesis layer scans all uploaded evidence alongside the questionnaire response, treating it as a data source in the same way as connector data. Evidence is not taken at face value; the AI assesses whether it corroborates the questionnaire response.

Both inputs are ingested by the AI synthesis layer alongside any available connector data. The report clearly indicates which findings are based on automated scan data, self-reported questionnaire responses, or uploaded evidence. Buyers can weight this distinction when interpreting scores.

The scoring model applies a **coverage penalty** when the engagement relies heavily on self-reported data — the overall confidence band is widened and flagged explicitly in the exec summary.

---

## 5. Agent Architecture

Eight specialist agents, orchestrated by a central orchestrator.

### 5.1 Orchestrator

Reads the deal scope and available data sources, determines which agents are relevant and can run, sequences execution (parallel where possible), handles agent failures gracefully (partial data is better than no data), and writes the final status to the engagement record.

### 5.2 Specialist agents

| Agent | What it assesses | Key data sources |
|---|---|---|
| **Code Agent** | Complexity, duplication, test coverage, dead code, code churn, language breakdown | GitHub/GitLab, SonarQube |
| **Security Agent** | CVEs in dependencies, secrets in git history, SAST findings, exposed endpoints, IAM over-privilege | Snyk, Semgrep, Trivy, AWS IAM, git history scan |
| **Infrastructure Agent** | Cloud architecture, IaC coverage, redundancy, scalability ceiling, monthly cost, single points of failure | AWS/GCP/Azure APIs, Terraform state, OS agent (v1.1) |
| **Process Agent** | Deployment frequency, lead time, MTTR, PR review patterns, CI/CD health, DORA metrics | GitHub Actions, Jira, PagerDuty, questionnaire |
| **Dependencies Agent** | Open-source license risk, EOL packages, vendor lock-in, third-party API dependencies, SBOM generation | Package manifests (npm, pip, Maven, Go modules, NuGet) |
| **Compliance Agent** | SOC 2 / GDPR / HIPAA / ISO 27001 indicators, audit log presence, data residency, policy-as-code coverage, uploaded certifications | Cloud config scanners, IAM policies, logging config, uploaded docs |
| **Docs Agent** | Documentation quality and coverage across all available sources (see 5.4) | Git repos, M365/Google Workspace, Confluence/Notion, uploaded docs, questionnaire |
| **IT Operations Agent** | Identity and access management maturity, endpoint/device management, ITSM processes, backup and DR, network controls, shadow IT exposure | M365/Google Workspace (identity signals), questionnaire, uploaded policies, OS agent (v1.1) |

### 5.3 IT Operations scope

The IT Operations category covers the operational technology estate alongside the software product — critical for understanding post-acquisition integration cost and security posture:

- **Identity & access management**: SSO adoption, MFA enforcement, privileged access controls, Active Directory / Entra ID / Okta health
- **Endpoint and device management**: MDM coverage, patch levels, BYOD policy, endpoint security tooling
- **IT service management**: Ticketing system maturity, change management process, asset inventory, SLA adherence
- **Business continuity and DR**: Backup frequency and testing, RTO/RPO definitions, DR plan existence and last test date
- **Network controls**: Firewall rules, VPN usage, network segmentation, guest network controls
- **Shadow IT and SaaS sprawl**: Unmanaged SaaS subscriptions, tools outside IT oversight

This category has a lower default weight than Security and Compliance but can be material in deals where the acquirer will integrate the target's IT estate into their own.

### 5.4 How the Docs Agent works

Documentation is inherently multi-source and unstructured. The Docs Agent operates as follows:

1. **Discovery**: Identifies all available documentation sources across connected tools — README files, wiki pages (Confluence, Notion, SharePoint), architecture docs in shared drives (Google Drive, SharePoint), API documentation (OpenAPI specs, Postman collections), uploaded files.

2. **AI assessment**: Reads each document and scores it against a rubric covering: accuracy (does it match observed system behaviour), completeness (does it cover the expected scope), freshness (last updated date vs system change frequency), and accessibility (is it findable and navigable).

3. **Gap detection**: Identifies documentation that should exist but doesn't — e.g., no runbook for the primary service, no incident playbooks, no onboarding guide.

4. **Bus factor signals**: Cross-references commit history, document authorship, and questionnaire responses to identify single-person knowledge dependencies.

Findings include specific document assessments ("Architecture overview last updated 18 months ago, describes a legacy monolith but the codebase has been migrated to microservices") as well as gap findings ("No runbook exists for database failover despite this being identified as a critical dependency").

---

## 6. AI Synthesis Layer

After all agents complete, the synthesis layer:

1. Reads all structured findings from the findings store
2. Generates a **per-finding narrative** using the standard finding format (see Section 7)
3. Produces a **category-level summary** for each of the 8 categories (Code, Security, Infrastructure, Process, Dependencies, Compliance, Docs, IT Operations)
4. Generates the **executive summary** — plain-English overview of the overall tech estate, key strengths, primary risks, and deal implications
5. Computes **risk scores** per category and overall using the active scoring configuration (see Section 8)
6. Flags **critical findings** that require immediate attention or deal-level discussion
7. Classifies each finding as **pre-close** (must resolve before transaction) or **post-close** (budget into integration programme)
8. Produces a **remediation cost summary** — aggregate estimated cost and time to address all findings, broken down by pre-close vs post-close

The synthesis layer uses Claude as the underlying model. All narratives are grounded strictly in scan data and questionnaire responses — no hallucinated findings. Where data is absent (connector not connected, questionnaire question unanswered), findings note the gap explicitly rather than inferring.

---

## 7. Finding Format

Every finding is presented in a consistent structured format:

```
FINDING TITLE
Source badge: [AUTOMATED SCAN | QUESTIONNAIRE | UPLOADED DOCUMENT | ADVISOR ANNOTATION]
Risk level: [CRITICAL | HIGH | MEDIUM | LOW]
Effort: [DAYS | WEEKS | MONTHS | YEARS]
Timing: [PRE-CLOSE REQUIRED | POST-CLOSE PROGRAMME | BACKLOG]

What this is
  Plain-English description of what was found, with reference to
  the specific evidence (e.g. "SonarQube scan of 4 repositories
  found 847 instances of cyclomatic complexity > 15").

Why this matters for the deal
  Business-context explanation: financial risk, customer impact,
  valuation implication, or post-close cost. Written for a
  non-technical deal partner.

Estimated remediation
  Time range + cost range (where estimable). Basis for estimate noted.

Recommended actions
  Numbered, concrete steps. Tool recommendations where relevant.

Evidence [External Advisor only]
  Link to raw scan data / source document.
```

Advisor annotations appear below the AI-generated finding as a distinct visual layer, attributed to the advisor by name and timestamp.

---

## 8. Scoring Model

### 8.1 Configurability

All scoring parameters — axis weights, category weights, score band thresholds, and rubric definitions — are stored in a `scoring_config` table in the database, not hardcoded. Each config is versioned. When a report is generated it records the config version used, so historical reports remain reproducible even as the rubric evolves. Platform admins can edit the active config at any time. Individual engagements can override category weights without affecting the global config.

### 8.2 Per-finding score

Each finding is scored on two independent axes:

**Financial Risk (default weight: 60%)**
- Critical — could block deal close or trigger MAC clause
- High — likely valuation impact or material post-close cost
- Medium — operational cost, slows velocity
- Low — hygiene, no material financial impact

**Remediation Effort (default weight: 25%)**
- Days — single engineer, no external dependency
- Weeks — sprint-scale, small team
- Months — programme, external consultants or vendors required
- Years — structural, fundamental re-architecture

**Finding count density (10%) + Data coverage completeness (5%)** round out the category score. Coverage completeness penalises categories where limited connectors were available.

### 8.3 Category weights (defaults)

| Category | Default Weight | Rationale |
|---|---|---|
| Security | 23% | Breaches, active exploits, and compliance failures are the most common deal blockers |
| Compliance | 18% | SOC 2 / GDPR gaps block enterprise customer contracts and regulatory approvals |
| Infrastructure | 13% | Scalability ceiling and architecture risk directly affect growth story |
| Code Quality | 13% | Affects developer velocity, hiring, and future feature delivery cost |
| Engineering Process | 11% | DORA metrics predict reliability and incident risk post-acquisition |
| IT Operations | 10% | Identity, device, ITSM, and DR maturity — integration cost and security posture |
| Dependencies | 7% | License risk and EOL packages compound security and maintenance cost |
| Documentation | 5% | Knowledge risk and bus factor; rarely deal-defining but affects integration cost |

All weights are configurable per engagement. A PE firm acquiring a heavily regulated fintech may increase Compliance weighting; a deal where IT estate integration is the primary concern may increase IT Operations weighting.

### 8.4 Overall risk score

Weighted average of category scores (0–100). Default bands:

- **0–39**: High Risk — significant issues requiring immediate deal-level attention
- **40–59**: Medium-High Risk — material findings, valuation adjustment likely warranted
- **60–74**: Medium Risk — manageable post-close programme required
- **75–89**: Low-Medium Risk — minor issues, normal integration backlog
- **90–100**: Low Risk — strong tech estate

Bands are also stored in `scoring_config` and are configurable.

---

## 9. Portals

### 9.1 Buyer org dashboard

The top-level view for users at a PE firm. Shows all active and historical engagements, their status, and the overall risk score for completed ones. Users see only engagements they are assigned to; org admins see all. User management and role assignment live here.

### 9.2 Buyer engagement view

- Overall score, category heatmap, critical flags, exec summary
- Category drilldown — curated findings in standard format
- Remediation cost summary — total estimated spend to resolve all findings
- AI chat — ask questions grounded in the report findings
- Clarification requests — raise structured questions to the seller in-platform
- Annotation layer — add comments to findings, visible to all buyer-side users on this engagement
- PDF export for investment committee

### 9.3 External Advisor view

All Buyer engagement view capabilities plus:
- Raw scan data — the underlying structured output from each agent
- Full finding detail including agent-level evidence
- Annotations from both buyer and advisor users

### 9.4 Seller portal

The seller's portal is scoped to a single engagement (sellers do not have an org-level view).

- Guided connector wizard — step-by-step, one connector at a time, with plain-English scope per connector
- Document upload — upload policy docs, runbooks, architecture diagrams, certifications, and other supplemental materials
- Questionnaire — structured questions for categories where connectors are unavailable
- Scope review — see exactly what categories are being assessed and what data types are collected
- IP controls — approve or restrict External Advisor raw data access; approve/deny any elevation requests via the workflow in Section 1.4
- Live scan progress — real-time view of agent status and what has been collected
- Clarification inbox — respond to buyer questions in-platform; responses are appended to the report
- Access revocation — can disconnect any connector at any time; all access automatically revoked on engagement close

---

## 10. Tech Stack

The Nova baseline (ECS Fargate, RDS PostgreSQL, Cognito, Cloudflare, FastAPI, Terraform) remains the right foundation for the web application layer. The AI and agent architecture uses a more specialised stack suited to multi-model agent orchestration at scale.

### 10.1 Web application layer

| Component | Choice | Notes |
|---|---|---|
| Compute | ECS Fargate | Web app + async scan workers both run on Fargate |
| Database | RDS PostgreSQL | Application data, engagement records, findings store, scoring config |
| Auth | AWS Cognito | Separate user pools for buyer org users and seller engagement users |
| Frontend auth SDK | amazon-cognito-identity-js | Native AWS Cognito library for React; handles both buyer and seller pools independently without Amplify framework overhead |
| Edge | Cloudflare (CDN, WAF) | |
| Frontend | React 18 + TypeScript, Vite, React Router | SPA; built with Vite, client routing via react-router-dom |
| Backend | FastAPI (Python) | Strong fit: async support, Pydantic for structured agent outputs |
| Async job queue | SQS + ECS workers | Scan jobs dispatched via SQS, consumed by async ECS worker tasks. Parallel agent execution, decoupled from web request latency. |
| File storage | S3 | Uploaded seller documents, scan artefacts, generated PDFs, AI artefacts |
| Caching | ElastiCache (Redis) | Session state, job status polling, connector credential caching |
| IaC | Terraform | |

### 10.2 AI and agent layer

The AI architecture is built around Amazon Bedrock AgentCore and LangGraph, with LiteLLM as a multi-model gateway.

**Connectivity principle — no network access into seller environments, ever.** All data collection happens via two strictly outbound mechanisms:
- **Cloud connectors**: our platform calls seller SaaS APIs (GitHub, AWS, Jira, etc.) using seller-provided OAuth tokens. Data is collected and pushed to the agent API.
- **OS-level agent**: a binary installed on seller infrastructure that calls our platform's agent API outbound. We never initiate any connection into the seller's network.

All communication is over HTTPS/TLS. No VPN tunnels, no VPC peering, no PrivateLink into seller environments. The agents expose an API that receives data — they do not reach out to collect it.

| Component | Choice | Notes |
|---|---|---|
| Agent runtime | Amazon Bedrock AgentCore | Managed runtime for agent execution; exposes the agent API that connectors and the OS agent push data to |
| Agent framework | LangGraph | Graph-based orchestration for multi-step agent workflows, conditional routing, and parallel execution across the 8 specialist agents |
| Agent memory | AgentCore Memory | Persistent memory across steps within an engagement run |
| AI gateway | LiteLLM | Unified API across model providers — Anthropic (Claude), OpenAI, Gemini, Bedrock-hosted models. Model switching without agent code changes. |
| Safety / guardrails | Amazon Bedrock Guardrails | Content filtering and output safety on all AI-generated findings narratives |
| Vector / semantic search | OpenSearch (3-AZ) | Semantic search over findings for the AI chat feature. Used in preference to pgvector, which is not available on RDS PostgreSQL. |
| AI artefact storage | S3 | Intermediate agent outputs, synthesis artefacts |
| Network (internal) | VPC Private Subnets + VPC Endpoints | Bedrock, Secrets Manager, and other AWS services accessed via VPC endpoints — no internet transit for internal AI traffic |
| Egress | NAT Gateway (3-AZ) | Controlled outbound for connector calls to external SaaS APIs |
| AI observability | Langfuse or Arize | LLM tracing, token usage, latency, and output quality monitoring. Evaluation between the two pending; both provide the required visibility into agent behaviour. |

**On model selection:** LiteLLM allows the platform to use the best model per task without provider lock-in. Claude is the primary model for synthesis and narrative generation. Other models may be used for specific subtasks as the agent library matures.

### 10.3 On-prem / OS agent (v1.1)

| Component | Choice | Notes |
|---|---|---|
| On-prem / OS agent | Go binary | Go produces a small, single static binary with no runtime dependency — significantly easier to distribute and install on arbitrary seller infrastructure than a Python binary. The only component not in Python. |

---

## 11. Out of Scope for v1

- Financial system connectors (payroll, ERP, revenue data) — strong future addition
- Portfolio monitoring (continuous post-acquisition monitoring) — natural v2 product
- Multi-region deployment
- Seller-initiated "pre-sale readiness" self-assessment
- Marketplace of advisors
- Automated valuation adjustment modelling
- Integration with VDR (virtual data room) platforms
- Slack, Okta, CrowdStrike connectors — post-v1 priority

---

## Key Constraints

- **Seller IP protection is non-negotiable** — raw data access requires explicit seller consent per engagement, enforced by a two-step approval workflow with no admin override
- **All findings are immutable** — scan data and AI output are the authoritative record; advisors annotate, never edit
- **Findings must be explainable** — every AI-generated narrative must be grounded in scan data with traceable evidence; absence of data is noted explicitly, never inferred
- **Nothing is collected that wasn't declared** — the connector scope descriptions and agent manifests must be accurate and complete
- **Scoring is always reproducible** — all scoring parameters are versioned; a report generated today must produce the same score if regenerated on the same data
