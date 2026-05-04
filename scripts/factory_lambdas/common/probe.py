"""HTTP probe parser. Extracts {method, path, expected_status, auth} tuples
from human-written acceptance-criteria strings.

The parser is intentionally conservative: it only emits a probe when it can
identify the verb, the path, and the status code in the same criterion. If a
criterion lacks any of these, it is skipped (not all criteria translate to
HTTP probes — e.g., 'docs/openapi.json includes the endpoint').
"""

from __future__ import annotations

import re

# Match: VERB /path/with/{tokens} ... returns NNN ...
_PATTERN = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE)\b\s+(/[^\s)]*)\s+(?:returns|→|->|yields)\s+(\d{3})",
    re.IGNORECASE,
)


def extract_probes(criteria: list[str]) -> list[dict]:
    out: list[dict] = []
    for c in criteria:
        m = _PATTERN.search(c)
        if not m:
            continue
        method = m.group(1).upper()
        path = m.group(2).rstrip(",;.).")
        status = int(m.group(3))
        # Heuristic: if the criterion mentions auth/owner/buyer_org/tenant or
        # mentions a 403, it's an authenticated endpoint.
        ctext = c.lower()
        needs_auth = any(k in ctext for k in ("authenticat", "auth ", "owner", "buyer_org", "tenant", "403"))
        out.append({
            "method": method,
            "path": path,
            "expected_status": status,
            "auth": needs_auth,
        })
    return out
