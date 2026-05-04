const https = require("https");
const { SFNClient, StartExecutionCommand } = require("@aws-sdk/client-sfn");
const { SSMClient, GetParameterCommand } = require("@aws-sdk/client-ssm");
const sfn = new SFNClient({ region: process.env.AWS_REGION || "us-east-1" });
const ssm = new SSMClient({ region: process.env.AWS_REGION || "us-east-1" });

const GITHUB_OWNER = process.env.GITHUB_OWNER;
const GITHUB_REPO = process.env.GITHUB_REPO;
const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
const NOTION_API_KEY = process.env.NOTION_API_KEY;
const FACTORY_BACKEND = process.env.FACTORY_BACKEND || "github-actions";
const STATE_MACHINE_ARN = process.env.STATE_MACHINE_ARN || "";
const PAUSED_PARAM = process.env.PAUSED_PARAM || "/nova/factory/paused";
const TARGET_STATUS = "Ready to Build";
const NOTION_VERSION = "2022-06-28";

async function isFactoryPaused() {
  try {
    const out = await ssm.send(new GetParameterCommand({ Name: PAUSED_PARAM }));
    return (out.Parameter?.Value || "false").toLowerCase().trim() === "true";
  } catch (e) {
    if (e.name === "ParameterNotFound") return false;
    console.error("Failed to read pause flag:", e.message);
    return false;  // Fail open — webhook still dispatches if SSM is degraded
  }
}

async function postNotionComment(featureId, content) {
  const payload = JSON.stringify({
    parent: { page_id: featureId },
    rich_text: [{ text: { content: content.slice(0, 2000) } }],
  });
  return new Promise((resolve) => {
    const req = https.request({
      hostname: "api.notion.com",
      path: "/v1/comments",
      method: "POST",
      headers: {
        Authorization: `Bearer ${NOTION_API_KEY}`,
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(payload),
      },
    }, (res) => { res.on("data", () => {}); res.on("end", resolve); });
    req.on("error", () => resolve());
    req.write(payload);
    req.end();
  });
}

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

    // Fetch the full page to confirm status and read dependencies
    const page = await fetchPage(featureId);
    const props = page.properties || {};
    const status = extractStatus(props);
    console.log(`Page ${featureId} status: "${status}"`);

    if (status !== TARGET_STATUS) {
      return { statusCode: 200, body: JSON.stringify({ skipped: true, reason: `status is "${status}"` }) };
    }

    // Pause flag check — if true, drop the dispatch and notify on Notion.
    if (await isFactoryPaused()) {
      console.log(`Factory paused — skipping dispatch for ${featureId}`);
      await postNotionComment(featureId, "🛑 Nova Factory is currently PAUSED — see CloudWatch alarms. This feature was not dispatched. Resume by setting /nova/factory/paused = false after diagnosing.");
      return { statusCode: 200, body: JSON.stringify({ paused: true, skipped: true, featureId }) };
    }

    // Check that all dependencies are Done before dispatching
    const depIds = extractDepIds(props);
    if (depIds.length > 0) {
      const pendingDeps = [];
      for (const depId of depIds) {
        const depPage = await fetchPage(depId);
        const depStatus = extractStatus(depPage.properties || {});
        if (depStatus !== "Done") {
          pendingDeps.push({ id: depId, status: depStatus });
        }
      }

      if (pendingDeps.length > 0) {
        console.log(`Feature ${featureId} has ${pendingDeps.length} unfinished dep(s) — setting Queued`, pendingDeps);
        await setPageStatus(featureId, "Queued");
        return {
          statusCode: 200,
          body: JSON.stringify({ queued: true, featureId, pendingDeps }),
        };
      }
    }

    if (FACTORY_BACKEND === "step-functions" || FACTORY_BACKEND === "step-functions-v2") {
      await startStateMachine(featureId);
      console.log(`Step Functions triggered for feature ${featureId} (${FACTORY_BACKEND})`);
    } else {
      await triggerGitHubActions(featureId);
      console.log(`Factory triggered for feature ${featureId} via GitHub Actions`);
    }
    return { statusCode: 200, body: JSON.stringify({ triggered: true, featureId, backend: FACTORY_BACKEND }) };

  } catch (err) {
    console.error("Relay error:", err.message, err.stack);
    return { statusCode: 500, body: JSON.stringify({ error: err.message }) };
  }
};

function extractStatus(props) {
  return (
    props?.Status?.status?.name ||
    props?.Status?.select?.name ||
    null
  );
}

function extractDepIds(props) {
  return (props?.["Depends On"]?.relation || []).map((r) => r.id);
}

function fetchPage(pageId) {
  return new Promise((resolve, reject) => {
    const req = https.request(
      {
        hostname: "api.notion.com",
        path: `/v1/pages/${pageId}`,
        method: "GET",
        headers: {
          Authorization: `Bearer ${NOTION_API_KEY}`,
          "Notion-Version": NOTION_VERSION,
        },
      },
      (res) => {
        let data = "";
        res.on("data", (chunk) => { data += chunk; });
        res.on("end", () => {
          try {
            resolve(JSON.parse(data));
          } catch (e) {
            reject(new Error(`Failed to parse Notion page response: ${e.message}`));
          }
        });
      }
    );
    req.on("error", reject);
    req.end();
  });
}

function setPageStatus(pageId, statusName) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify({
      properties: {
        Status: { select: { name: statusName } },
      },
    });
    const req = https.request(
      {
        hostname: "api.notion.com",
        path: `/v1/pages/${pageId}`,
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${NOTION_API_KEY}`,
          "Notion-Version": NOTION_VERSION,
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(payload),
        },
      },
      (res) => {
        let data = "";
        res.on("data", (chunk) => { data += chunk; });
        res.on("end", () => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve();
          } else {
            reject(new Error(`Notion PATCH returned ${res.statusCode}: ${data}`));
          }
        });
      }
    );
    req.on("error", reject);
    req.write(payload);
    req.end();
  });
}

async function startStateMachine(featureId) {
  // Strip hyphens from featureId to create a valid execution name (alphanumeric + hyphens + underscores, max 80 chars)
  const safeName = `${featureId.replace(/-/g, "")}-${Date.now()}`.slice(0, 80);
  await sfn.send(new StartExecutionCommand({
    stateMachineArn: STATE_MACHINE_ARN,
    name: safeName,
    input: JSON.stringify({ feature_id: featureId }),
  }));
}

function triggerGitHubActions(featureId) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify({
      event_type: "factory-trigger",
      client_payload: { feature_id: featureId },
    });

    const req = https.request(
      {
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
      },
      (res) => {
        if (res.statusCode === 204) {
          resolve();
        } else {
          let data = "";
          res.on("data", (chunk) => { data += chunk; });
          res.on("end", () => {
            reject(new Error(`GitHub API returned ${res.statusCode}: ${data}`));
          });
        }
      }
    );

    req.on("error", reject);
    req.write(payload);
    req.end();
  });
}
