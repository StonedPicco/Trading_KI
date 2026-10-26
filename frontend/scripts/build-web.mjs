// Builds the dashboard as a static site and copies it to ../web, which the backend serves
// for the one-click start (Start.bat / start.sh). Commit ../web after frontend changes.
import { execSync } from "node:child_process";
import { cpSync, existsSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const target = resolve(root, "..", "web");

execSync("npx next build", {
  cwd: root,
  stdio: "inherit",
  env: { ...process.env, NEXT_OUTPUT: "export", NEXT_PUBLIC_API_URL: "", NEXT_TELEMETRY_DISABLED: "1" },
});
if (!existsSync(resolve(root, "out", "index.html"))) throw new Error("static export failed: out/index.html missing");
rmSync(target, { recursive: true, force: true });
cpSync(resolve(root, "out"), target, { recursive: true });
console.log(`static dashboard written to ${target}`);
