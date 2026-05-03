#!/usr/bin/env python3
"""
Updates the 'Foundation: React Frontend Scaffold' Notion feature page to replace
AWS Amplify references with amazon-cognito-identity-js.

Run: PYTHONPATH=scripts /c/Python314/python scripts/update_frontend_feature.py
"""
import os
import requests

NOTION_VERSION = "2022-06-28"
BASE_URL = "https://api.notion.com/v1"
CHUNK = 1900

FRONTEND_PAGE_ID = "3550930a-bc71-811c-8d50-dd3bd62f0713"


def headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['NOTION_API_KEY']}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def rich_blocks(text: str) -> list:
    blocks = []
    while text:
        blocks.append({"type": "text", "text": {"content": text[:CHUNK]}})
        text = text[CHUNK:]
    return blocks or [{"type": "text", "text": {"content": ""}}]


def update_page(page_id: str, properties: dict) -> dict:
    resp = requests.patch(
        f"{BASE_URL}/pages/{page_id}",
        headers=headers(),
        json={"properties": properties},
    )
    resp.raise_for_status()
    return resp.json()


DESCRIPTION = (
    "React 18 + TypeScript SPA scaffold. amazon-cognito-identity-js handles Cognito "
    "auth for both buyer and seller pools independently (no Amplify framework), axios "
    "API client with automatic Bearer token injection, AuthProvider context with "
    "useAuth hook, RoleGuard for protected routes, org dashboard showing the "
    "engagement list, and seller invitation acceptance flow (signUp in seller pool "
    "then POST /accept). Functional shell that later features build UI into."
)

TECH_NOTES = (
    "Vite + React 18 + TypeScript.\n"
    "Packages: amazon-cognito-identity-js, @types/amazon-cognito-identity-js, "
    "axios, react-router-dom.\n\n"
    "Env vars (VITE_ prefix):\n"
    "  VITE_API_BASE_URL                  — backend base URL\n"
    "  VITE_COGNITO_BUYER_USER_POOL_ID    — Terraform output buyer_user_pool_id\n"
    "  VITE_COGNITO_BUYER_CLIENT_ID       — Terraform output buyer_client_id\n"
    "  VITE_COGNITO_SELLER_USER_POOL_ID   — Terraform output seller_user_pool_id\n"
    "  VITE_COGNITO_SELLER_CLIENT_ID      — Terraform output seller_client_id\n"
    "  VITE_ORG_ID                        — placeholder; comes from auth claims later\n\n"
    "Key files:\n"
    "  frontend/src/auth/cognito.ts          — buyerPool + sellerPool instances; "
    "signIn, signUp, getIdToken, signOut helpers\n"
    "  frontend/src/auth/AuthContext.tsx     — React context: session, loading, useAuth hook\n"
    "  frontend/src/App.tsx                  — BrowserRouter + AuthProvider "
    "(no Amplify.configure needed)\n"
    "  frontend/src/api/client.ts            — axios + getIdToken(buyerPool) interceptor\n"
    "  frontend/src/api/engagements.ts       — listEngagements, createEngagement\n"
    "  frontend/src/types/index.ts           — BuyerOrg, Engagement, Invitation\n"
    "  frontend/src/components/RoleGuard.tsx — redirects to /login if no active session\n"
    "  frontend/src/pages/Login.tsx          — custom sign-in form using buyer pool\n"
    "  frontend/src/pages/OrgDashboard.tsx\n"
    "  frontend/src/pages/AcceptInvitation.tsx — signUp in seller pool + POST /accept\n\n"
    "Routes: /login, /dashboard, /invite/:token, * → /login.\n\n"
    "Full component code: "
    "docs/superpowers/plans/2026-05-01-platform-foundation.md Task 13."
)

ACCEPTANCE_CRITERIA = (
    "1. npm run build exits 0 with no TypeScript errors\n"
    "2. Login renders a custom sign-in form; submit calls signIn(email, password, buyerPool) "
    "from amazon-cognito-identity-js and navigates to /dashboard on success\n"
    "3. OrgDashboard calls GET /orgs/{orgId}/engagements and renders each as "
    "'name — target_company_name (status)'\n"
    "4. AcceptInvitation calls GET /invitations/{token} on mount (no auth header); "
    "shows error message on 404\n"
    "5. Submitting AcceptInvitation form: signUp in seller pool, then signIn, then "
    "POST /invitations/{token}/accept with {token, cognito_sub}\n"
    "6. All axios requests include Authorization: Bearer {idToken} via "
    "getIdToken(buyerPool) interceptor\n"
    "7. Unauthenticated user at /dashboard redirected to /login via RoleGuard + useAuth"
)

OUT_OF_SCOPE = (
    "Seller portal UI (Sub-project 2). Report/findings UI (Sub-project 3). "
    "Design system/styling. NavBar wiring beyond scaffold."
)


if __name__ == "__main__":
    props = {
        "Description": {"rich_text": rich_blocks(DESCRIPTION)},
        "Tech Notes": {"rich_text": rich_blocks(TECH_NOTES)},
        "Acceptance Criteria": {"rich_text": rich_blocks(ACCEPTANCE_CRITERIA)},
        "Out of Scope": {"rich_text": rich_blocks(OUT_OF_SCOPE)},
    }
    update_page(FRONTEND_PAGE_ID, props)
    print("Updated: Foundation: React Frontend Scaffold")
    print("  Replaced AWS Amplify references with amazon-cognito-identity-js.")
