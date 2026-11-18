// The replay heatmaps' pictures: each page scripts/make_heatmaps.py wrote (data/heatmaps/*.html),
// photographed at 1080 x 1080 as a PNG beside it, through Chrome's debugging port (CHROME names
// another Chrome). Run from WSL with Windows' Node, giving the folder as a Windows path:
//   "/mnt/c/Program Files/nodejs/node.exe" scripts/render_heatmaps.mjs "$(wslpath -w data/heatmaps)"
import { spawn } from "node:child_process";
import { readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const folder = process.argv[2];
if (!folder) {
  console.error("Give the folder of pages (a Windows path): scripts/render_heatmaps.mjs \"$(wslpath -w data/heatmaps)\"");
  process.exit(1);
}
const pages = readdirSync(folder).filter((name) => name.endsWith(".html"));
const CHROME = process.env.CHROME ?? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const port = 9300 + Math.floor(Math.random() * 500);
const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--hide-scrollbars", `--remote-debugging-port=${port}`,
  `--user-data-dir=${process.env.TEMP ?? "/tmp"}/synopsist-heatmaps-${process.pid}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let targets = [];
for (let i = 0; i < 60 && !targets.some((t) => t.type === "page"); i++) {
  try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); } catch {}
  await sleep(250);
}
const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((resolve) => ws.addEventListener("open", resolve));
let id = 0;
const waiting = new Map();
ws.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (waiting.has(message.id)) { waiting.get(message.id)(message); waiting.delete(message.id); }
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const n = ++id;
  waiting.set(n, (m) => (m.error ? reject(new Error(`${method}: ${m.error.message}`)) : resolve(m.result)));
  ws.send(JSON.stringify({ id: n, method, params }));
});

try {
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1080, height: 1080, deviceScaleFactor: 1, mobile: false });
  for (const name of pages) {
    await send("Page.navigate", { url: pathToFileURL(join(folder, name)).href });
    await sleep(1200);
    await send("Runtime.evaluate", { expression: "document.fonts.ready.then(() => true)", awaitPromise: true });
    const { data } = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(folder, name.replace(/\.html$/, ".png")), Buffer.from(data, "base64"));
    console.log(`Saved ${name.replace(/\.html$/, ".png")}`);
  }
} finally {
  chrome.kill();
  ws.close();
}
