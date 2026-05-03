#!/usr/bin/env python3
"""
Adds structured properties to the Notion Features DB and backfills the four
Platform Foundation feature pages.

Run: PYTHONPATH=scripts /c/Python314/python scripts/setup_notion_fields.py
"""
import os
import requests

NOTION_VERSION = "2022-06-28"
BASE_URL = "https://api.notion.com/v1"
FEATURES_DB = os.environ["NOTION_FEATURES_DB_ID"]


def headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['NOTION_API_KEY']}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def add_db_properties():
    """Add missing properties to the Features database."""
    resp = requests.patch(
        f"{BASE_URL}/databases/{FEATURES_DB}",
        headers=headers(),
        json={
            "properties": {
                "Description": {"rich_text": {}},
                "Acceptance Criteria": {"rich_text": {}},
                "Out of Scope": {"rich_text": {}},
                "Affected Roles": {
                    "multi_select": {
                        "options": [
                            {"name": "backend",           "color": "blue"},
                            {"name": "frontend",          "color": "green"},
                            {"name": "database",          "color": "purple"},
                            {"name": "infrastructure",    "color": "orange"},
                            {"name": "test",              "color": "yellow"},
                            {"name": "security-reviewer", "color": "red"},
                        ]
                    }
                },
                "Design URL": {"url": {}},
                "Feature Flag": {"rich_text": {}},
            }
        },
    )
    resp.raise_for_status()
    print("Database properties added.")


CHUNK = 1900


def rich_blocks(text: str) -> list:
    blocks = []
    while text:
        blocks.append({"type": "text", "text": {"content": text[:CHUNK]}})
        text = text[CHUNK:]
    return blocks or [{"type": "text", "text": {"content": ""}}]


def update_page(page_id: str, properties: dict):
    resp = requests.patch(
        f"{BASE_URL}/pages/{page_id}",
        headers=headers(),
        json={"properties": properties},
    )
    resp.raise_for_status()
    return resp.json()


# Page IDs created by create_foundation_features.py
PAGES = {
    "Foundation: Core Backend Setup": "3550930a-bc71-81c8-93b7-f9c69f1d6b03",
    "Foundation: Org, Engagement & Invitation API": "3550930a-bc71-815b-b92f-f225afdcc3cb",
    "Foundation: Terraform — Cognito & RDS": "3550930a-bc71-8127-8698-f609f2bae1d0",
    "Foundation: React Frontend Scaffold": "3550930a-bc71-811c-8d50-dd3bd62f0713",
}

PAGE_DATA = [
    {
        "page_id": PAGES["Foundation: Core Backend Setup"],
        "description": (
            "Foundational backend layer for the Tech DD Platform. Async FastAPI app, "
            "SQLAlchemy 2.x ORM models for six core entities (buyer_org, user, engagement, "
            "engagement_user, seller_account, invitation), Alembic migrations, Cognito JWT "
            "validation middleware (tries buyer pool then seller pool), Pydantic schemas, "
            "async pytest fixture scaffolding, main.py wiring, and OpenAPI export to "
            "docs/openapi.json on startup. This is the base all other features depend on."
        ),
        "tech_notes": (
            "Python 3.12, FastAPI >=0.100, SQLAlchemy 2.x async (mapped_column style), "
            "asyncpg, Alembic >=1.13, pydantic-settings, python-jose[cryptography], "
            "pytest-asyncio, httpx.\n\n"
            "Two Cognito user pools: nova-buyer-{env} (roles: org_admin, buyer, "
            "external_advisor; custom attributes: custom:role, custom:org_id) and "
            "nova-seller-{env} (per-engagement seller accounts).\n\n"
            "Tenant key is buyer_org_id. Seller tables scoped by engagement_id.\n\n"
            "Engine/session MUST be lazy (created on first use, never at import time).\n\n"
            "TokenClaims dataclass: sub, email, role, pool (buyer|seller), raw.\n"
            "validate_token() tries buyer JWKS then seller JWKS — raises HTTP 401 on failure.\n\n"
            "Enum values:\n"
            "  EngagementStatus: created, seller_invited, seller_accepted, active, "
            "offboarding, closed, abandoned\n"
            "  UserRole: org_admin, buyer, external_advisor\n"
            "  InvitationType: seller, advisor\n"
            "  InvitationStatus: pending, accepted, expired, revoked\n"
            "  SellerAccountStatus: invited, active, offboarding, revoked\n"
            "  EngagementRole: buyer, external_advisor\n\n"
            "Full file map + TDD steps: "
            "docs/superpowers/plans/2026-05-01-platform-foundation.md Tasks 1-7 and 11."
        ),
        "acceptance_criteria": (
            "1. GET /version returns 200\n"
            "2. All six ORM models importable with no live DB connection\n"
            "3. alembic upgrade head creates all six tables with correct FKs and enum types\n"
            "4. validate_token() returns TokenClaims for mocked valid JWT; raises HTTP 401 for "
            "invalid/expired token\n"
            "5. require_role() raises HTTP 403 when caller role not in allowed set\n"
            "6. tests/test_config.py, test_models.py, test_auth.py, test_schemas.py all PASS\n"
            "7. docs/openapi.json committed\n"
            "8. ruff check app/ tests/ — zero violations\n"
            "9. mypy app/ --ignore-missing-imports — zero errors"
        ),
        "out_of_scope": (
            "API routes (next feature). Cloud connectors, agents, scoring (later sub-projects). "
            "Actual email delivery (stub only)."
        ),
        "affected_roles": ["backend", "database", "test"],
        "design_url": "https://github.com/nabbic/nova/blob/main/docs/superpowers/plans/2026-05-01-platform-foundation.md",
    },
    {
        "page_id": PAGES["Foundation: Org, Engagement & Invitation API"],
        "description": (
            "API routes for the engagement lifecycle setup: buyer org CRUD, engagement "
            "creation/listing (filtered by buyer_org_id), invitation flow (send, lookup by "
            "token, accept with engagement status transitions), and engagement user management. "
            "Produces the core data flows connecting PE firms to target companies."
        ),
        "tech_notes": (
            "Depends on 'Foundation: Core Backend Setup' being merged first.\n\n"
            "Routes:\n"
            "  POST   /orgs                                        → 201 BuyerOrgResponse\n"
            "  GET    /orgs/{org_id}                               → 200 BuyerOrgResponse\n"
            "  POST   /orgs/{org_id}/engagements                   → 201 EngagementResponse\n"
            "  GET    /orgs/{org_id}/engagements                   → 200 list\n"
            "  GET    /orgs/{org_id}/engagements/{id}              → 200 EngagementResponse\n"
            "  POST   /orgs/{org_id}/engagements/{id}/invitations  → 201 InvitationResponse\n"
            "  GET    /invitations/{token}                         → 200 (no auth)\n"
            "  POST   /invitations/{token}/accept                  → 200 (no auth)\n"
            "  POST   /orgs/{org_id}/engagements/{id}/users        → 201\n"
            "  GET    /orgs/{org_id}/engagements/{id}/users        → 200 list\n\n"
            "Business rules:\n"
            "- All engagement queries filter by buyer_org_id (cross-org access → 404)\n"
            "- Sending seller invite creates SellerAccount + transitions engagement → seller_invited\n"
            "- Accepting seller invite: sets SellerAccount.cognito_sub, status → active, "
            "engagement → seller_accepted\n"
            "- Expired invite (expires_at < now) → 410\n"
            "- Already-used invite → 409\n"
            "- Duplicate engagement user → 409\n"
            "- Invitation token: secrets.token_urlsafe(48), TTL: settings.invitation_ttl_hours (72h)\n\n"
            "Full file map + TDD steps: "
            "docs/superpowers/plans/2026-05-01-platform-foundation.md Tasks 8-10."
        ),
        "acceptance_criteria": (
            "1. POST /orgs → 201 with {id, name, created_at}; empty name → 422\n"
            "2. POST /orgs/{org_id}/engagements → 201 with status 'created'\n"
            "3. GET /orgs/{org_id}/engagements returns only that org's engagements\n"
            "4. Send seller invite → 201, engagement.status='seller_invited', SellerAccount "
            "created, email stub called once\n"
            "5. GET /invitations/{token} → 200 without auth header\n"
            "6. POST /invitations/{token}/accept → 200, engagement='seller_accepted', "
            "SellerAccount.cognito_sub set\n"
            "7. POST expired invite accept → 410\n"
            "8. POST already-used invite accept → 409\n"
            "9. Add duplicate user to engagement → 409\n"
            "10. test_orgs, test_engagements, test_invitations, test_users all PASS\n"
            "11. docs/openapi.json updated with all new routes\n"
            "12. ruff + mypy clean"
        ),
        "out_of_scope": (
            "Advisor elevation workflow (Sub-project 5). "
            "Data deletion pipeline for abandoned deals (Sub-project 5). "
            "Seller connector wizard (Sub-project 2). "
            "Full buyer report view (Sub-project 3). "
            "Actual email delivery."
        ),
        "affected_roles": ["backend", "test"],
        "design_url": "https://github.com/nabbic/nova/blob/main/docs/superpowers/plans/2026-05-01-platform-foundation.md",
    },
    {
        "page_id": PAGES["Foundation: Terraform — Cognito & RDS"],
        "description": (
            "Infrastructure as code for the platform's auth and database layer. Two Cognito "
            "user pools (buyer org users and per-engagement seller accounts) and a PostgreSQL "
            "db.t3.micro RDS instance. Free-tier eligible for staging."
        ),
        "tech_notes": (
            "Terraform >= 1.6, AWS provider ~> 5.0.\n"
            "S3 backend: nova-terraform-state-577638385116, "
            "key nova/{env}/terraform.tfstate, DynamoDB lock: nova-terraform-locks.\n\n"
            "Module layout:\n"
            "  infra/main.tf, variables.tf, outputs.tf\n"
            "  infra/modules/cognito/main.tf, variables.tf, outputs.tf\n"
            "  infra/modules/rds/main.tf, variables.tf, outputs.tf\n\n"
            "Buyer pool (nova-buyer-{env}): username=email, auto-verify=email, "
            "custom attrs: custom:role+custom:org_id (String), password min 12 all complexity, "
            "client: USER_PASSWORD_AUTH+SRP+REFRESH, access/id 1h, refresh 30d.\n\n"
            "Seller pool (nova-seller-{env}): username=email, no custom attrs, "
            "password min 12 no symbols, client: access/id 8h, refresh 7d.\n\n"
            "RDS: postgres 16, db.t3.micro, 20GB, storage_encrypted=true, "
            "skip_final_snapshot=(env!=production), deletion_protection=(env==production). "
            "SG: port 5432 inbound from app_sg_id only.\n\n"
            "Tags: Project=nova, ManagedBy=terraform, Environment=var.environment.\n"
            "Outputs: buyer_user_pool_id, seller_user_pool_id, buyer_client_id, "
            "seller_client_id, db_endpoint, db_name.\n\n"
            "Full HCL: docs/superpowers/plans/2026-05-01-platform-foundation.md Task 12."
        ),
        "acceptance_criteria": (
            "1. terraform validate — 'Success! The configuration is valid.'\n"
            "2. terraform plan (staging) shows 2 Cognito pools, 2 clients, 1 RDS, "
            "1 subnet group, 1 security group\n"
            "3. Buyer pool has custom:role and custom:org_id schema attributes\n"
            "4. RDS instance_class = 'db.t3.micro'\n"
            "5. RDS storage_encrypted = true\n"
            "6. RDS deletion_protection = true for production only\n"
            "7. All six outputs present: buyer_user_pool_id, seller_user_pool_id, "
            "buyer_client_id, seller_client_id, db_endpoint, db_name\n"
            "8. No hardcoded account IDs, ARNs, or regions — use data sources\n"
            "9. All resources tagged Project=nova, ManagedBy=terraform"
        ),
        "out_of_scope": (
            "VPC, subnets, NAT gateway, ECS cluster (separate infra feature). "
            "ElastiCache, SQS, OpenSearch (later sub-projects). "
            "Cloudflare DNS/WAF. Parameter Store entries."
        ),
        "affected_roles": ["infrastructure"],
        "design_url": "https://github.com/nabbic/nova/blob/main/docs/superpowers/plans/2026-05-01-platform-foundation.md",
    },
    {
        "page_id": PAGES["Foundation: React Frontend Scaffold"],
        "description": (
            "React 18 + TypeScript SPA scaffold. Amplify Cognito auth, axios API client with "
            "automatic Bearer token injection, RoleGuard for protected routes, org dashboard "
            "showing the engagement list, and seller invitation acceptance flow. Functional "
            "shell that later features build UI into."
        ),
        "tech_notes": (
            "Vite + React 18 + TypeScript. "
            "Packages: aws-amplify, @aws-amplify/ui-react, axios, react-router-dom.\n\n"
            "Env vars (VITE_ prefix):\n"
            "  VITE_API_BASE_URL                 — backend base URL\n"
            "  VITE_COGNITO_BUYER_USER_POOL_ID   — Terraform output buyer_user_pool_id\n"
            "  VITE_COGNITO_BUYER_CLIENT_ID      — Terraform output buyer_client_id\n"
            "  VITE_ORG_ID                       — placeholder; will come from auth claims later\n\n"
            "Key files:\n"
            "  frontend/src/App.tsx                  — router + Amplify.configure()\n"
            "  frontend/src/api/client.ts            — axios + fetchAuthSession() interceptor\n"
            "  frontend/src/api/engagements.ts       — listEngagements, createEngagement\n"
            "  frontend/src/types/index.ts           — BuyerOrg, Engagement, Invitation\n"
            "  frontend/src/components/RoleGuard.tsx\n"
            "  frontend/src/pages/Login.tsx          — Amplify Authenticator\n"
            "  frontend/src/pages/OrgDashboard.tsx\n"
            "  frontend/src/pages/AcceptInvitation.tsx\n\n"
            "Routes: /login, /dashboard, /invite/:token, * → /login.\n\n"
            "Full component code: "
            "docs/superpowers/plans/2026-05-01-platform-foundation.md Task 13."
        ),
        "acceptance_criteria": (
            "1. npm run build exits 0 with no TypeScript errors\n"
            "2. Login renders <Authenticator> from @aws-amplify/ui-react\n"
            "3. OrgDashboard calls GET /orgs/{orgId}/engagements and renders each as "
            "'name — target_company_name (status)'\n"
            "4. AcceptInvitation calls GET /invitations/{token} on mount; shows error on 404\n"
            "5. After Amplify signUp completes, calls POST /invitations/{token}/accept "
            "with {token, cognito_sub: user.userId}\n"
            "6. All axios requests include Authorization: Bearer {idToken}\n"
            "7. Unauthenticated user at /dashboard redirected to /login via RoleGuard"
        ),
        "out_of_scope": (
            "Seller portal UI (Sub-project 2). Report/findings UI (Sub-project 3). "
            "Design system/styling. NavBar wiring beyond scaffold."
        ),
        "affected_roles": ["frontend", "test"],
        "design_url": "https://github.com/nabbic/nova/blob/main/docs/superpowers/plans/2026-05-01-platform-foundation.md",
    },
]


if __name__ == "__main__":
    print("Step 1: Adding properties to Features DB...")
    add_db_properties()

    print("\nStep 2: Backfilling feature pages...")
    for page in PAGE_DATA:
        pid = page["page_id"]
        props = {
            "Description": {"rich_text": rich_blocks(page["description"])},
            "Tech Notes": {"rich_text": rich_blocks(page["tech_notes"])},
            "Acceptance Criteria": {"rich_text": rich_blocks(page["acceptance_criteria"])},
            "Out of Scope": {"rich_text": rich_blocks(page["out_of_scope"])},
            "Affected Roles": {"multi_select": [{"name": r} for r in page["affected_roles"]]},
            "Design URL": {"url": page["design_url"]},
        }
        update_page(pid, props)
        # Find title from PAGES dict
        title = next(k for k, v in PAGES.items() if v == pid)
        print(f"  Updated: {title}")

    print("\nDone. All four features now have structured fields in Notion.")
