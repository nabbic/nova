const https = require("https");

const GITHUB_OWNER = process.env.GITHUB_OWNER;
const GITHUB_REPO = process.env.GITHUB_REPO;
const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
const TARGET_STATUS = "Ready to Build";

exports.handler = async (event) => {
  try {
    const body = JSON.parse(event.body || "{}");

    if (!isReadyToBuild(body)) {
      return { statusCode: 200, body: JSON.stringify({ skipped: true }) };
    }

    const featureId = extractFeatureId(body);
    if (!featureId) {
      return { statusCode: 400, body: JSON.stringify({ error: "No feature ID" }) };
    }

    await triggerGitHubActions(featureId);

    return {
      statusCode: 200,
      body: JSON.stringify({ triggered: true, featureId }),
    };
  } catch (err) {
    console.error("Relay error:", err);
    return { statusCode: 500, body: JSON.stringify({ error: err.message }) };
  }
};

function isReadyToBuild(body) {
  const updates = body?.data?.properties || {};
  const statusUpdate = updates["Status"];
  if (!statusUpdate) return false;
  const newValue = statusUpdate?.select?.name;
  return newValue === TARGET_STATUS;
}

function extractFeatureId(body) {
  return body?.data?.id || null;
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
