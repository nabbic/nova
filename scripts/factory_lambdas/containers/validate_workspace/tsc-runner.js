const { execSync } = require("child_process");
const dir = process.argv[2];
try {
  execSync("/opt/bin/tsc --noEmit --project tsconfig.json", { cwd: dir, stdio: "inherit" });
} catch (e) {
  process.exit(1);
}
