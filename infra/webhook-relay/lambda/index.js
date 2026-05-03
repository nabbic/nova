const https = require("https");

const GITHUB_OWNER = process.env.GITHUB_OWNER;
const GITHUB_REPO = process.env.GITHUB_REPO;
const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
const NOTION_API_KEY = process.env.NOTION_API_KEY;
const TARGET_STATUS = "Ready to Build";

exports.handler = async (event) => {
  try {
    const body = JSON.parse(event.body || "{}");

    // Always log incoming event type for observability
    console.log("Received:", JSON.stringify({ type: body.type, entityId: body.entity?.id }));

    // Notion webhook verification challenge
    if (body.verification_token) {
      console.log("Verification challenge — echoing token");
      return {
        statusCode: 200,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verification_token: body.verification_token }),
      };
    }

    // Accept both property-update and generic page-update events
    const HANDLED_TYPES = ["page.properties_updated", "page.updated"];
    if (!HANDLED_TYPES.includes(body.type)) {
      console.log("Skipping unhandled event type:", body.type);
      return { statusCode: 200, body: JSON.stringify({ skipped: true, reason: "unhandled type", type: body.type }) };
    }

    const featureId = body?.entity?.id;
    if (!featureId) {
      console.log("No entity ID in payload");
      return { statusCode: 400, body: JSON.stringify({ error: "No page ID in webhook payload" }) };
    }

    // Fetch the page to confirm Status is still "Ready to Build"
    // (user may have changed it again before we processed the event)
    const status = await getPageStatus(featureId);
    console.log(`Page ${featureId} status: "${status}"`);

    if (status !== TARGET_STATUS) {
      return { statusCode: 200, body: JSON.stringify({ skipped: true, reason: `status is "${status}"` }) };
    }

    await triggerGitHubActions(featureId);
    console.log(`Factory triggered for feature ${featureId}`);
    return { statusCode: 200, body: JSON.stringify({ triggered: true, featureId }) };

  } catch (err) {
    console.error("Relay error:", err.message, err.stack);
    return { statusCode: 500, body: JSON.stringify({ error: err.message }) };
  }
};

function getPageStatus(pageId) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: "api.notion.com",
      path: `/v1/pages/${pageId}`,
      method: "GET",
      headers: {
        Authorization: `Bearer ${NOTION_API_KEY}`,
        "Notion-Version": "2022-06-28",
      },
    };

    const req = https.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => { data += chunk; });
      res.on("end", () => {
        try {
          const page = JSON.parse(data);
          // Notion "Status" properties are type "status", not "select"
          // Support both in case the DB was set up either way
          const status =
            page?.properties?.Status?.status?.name ||
            page?.properties?.Status?.select?.name ||
            null;
          resolve(status);
        } catch (e) {
          reject(new Error(`Failed to parse Notion response: ${e.message}`));
        }
      });
    });

    req.on("error", reject);
    req.end();
  });
}

function triggerGitHubActions(featureId) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify({
      event_type: "factory-trigger",
      client_payload: { feature_id: featureId },
    });

    const options = {
      hostname: "api.github.com",
      path: `/repos/${GITHUB_OWNER}/${GITHUB_REPO}/dispatches`,
      method: "POST",
      headers: {
        "User-Agent": "nova-webhook-relay",
        Authorization: `Bearer ${GITHUB_TOKEN}`,
        Accept: "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(payload),
      },
    };

    const req = https.request(options, (res) => {
      if (res.statusCode === 204) {
        resolve();
      } else {
        let data = "";
        res.on("data", (chunk) => { data += chunk; });
        res.on("end", () => {
          reject(new Error(`GitHub API returned ${res.statusCode}: ${data}`));
        });
      }
    });

    req.on("error", reject);
    req.write(payload);
    req.end();
  });
}
