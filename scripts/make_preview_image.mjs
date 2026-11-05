// Make the picture a link to the site shows when it's pasted into a chat or a post (player/images/
// preview.png, named by the og:image tag in player/index.html): the title screen at 1200 × 630, on its
// dark side, with only the emblem, the name, and the tagline (no settings button,
// song count, Listen button, or profile links, which don't belong in a picture or would go stale).
// Run it again after the title screen changes (a new tagline, say), with the local preview running:
//   cd ~/OsloHaggadone && python3 serve.py        (in another terminal)
//   "/mnt/c/Program Files/nodejs/node.exe" Synopsist/scripts/make_preview_image.mjs
// It drives Chrome through its debugging port (CHROME names another one), and takes another address
// as its first argument (the live site's, say).
import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const PAGE = process.argv[2] ?? "http://localhost:8080/Synopsist/";
const OUT = fileURLToPath(new URL("../player/images/preview.png", import.meta.url));
const CHROME = process.env.CHROME ?? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const HIDE = ".landing-settings, #landing-stats, #listen, .also-on, .landing-more, .topbar, .status-band { display: none !important; }";

const port = 9300 + Math.floor(Math.random() * 500);
const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--hide-scrollbars", `--remote-debugging-port=${port}`,
  `--user-data-dir=${process.env.TEMP ?? "/tmp"}/synopsist-preview-${process.pid}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let pages = [];
for (let i = 0; i < 60 && !pages.some((p) => p.type === "page"); i++) {
  try { pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); } catch {}
  await sleep(250);
}
const ws = new WebSocket(pages.find((p) => p.type === "page").webSocketDebuggerUrl);
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
const run = async (expression) => (await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result?.value;

try {
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1200, height: 630, deviceScaleFactor: 1, mobile: false });
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "dark" }] });
  await send("Page.navigate", { url: PAGE });
  await sleep(3000);
  await run(`(async () => {
    document.head.append(Object.assign(document.createElement("style"), { textContent: ${JSON.stringify(HIDE)} }));
    await document.fonts.ready;
    // the pictures on the screen (the emblem's), not the ones further down, which load only when
    // scrolled to; and never more than 5 s
    const shown = [...document.images].filter((img) => img.getBoundingClientRect().top < innerHeight);
    await Promise.race([Promise.all(shown.map((img) => img.decode().catch(() => {}))), new Promise((r) => setTimeout(r, 5000))]);
  })()`);
  await sleep(2500); // the emblem's rings turn slowly: held still, they'd sit square around it
  const { data } = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(OUT, Buffer.from(data, "base64"));
  console.log(`Saved ${OUT}`);
} finally {
  chrome.kill();
  ws.close();
}
