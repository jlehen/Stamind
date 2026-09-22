// Serves `miniapp/` over HTTP so a browser can open the page, for the screenshots and for the
// browser test. The page is static, so `python3 -m http.server` is the whole server.
import { spawn } from "node:child_process";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const PAGE_DIR = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

export function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.on("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

export async function servePage(port) {
  const server = spawn("python3",
    ["-m", "http.server", String(port), "--bind", "127.0.0.1", "--directory", PAGE_DIR],
    { stdio: "ignore" });
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      const answer = await fetch(`http://127.0.0.1:${port}/index.html`);
      if (answer.ok) {
        return server;
      }
    } catch (problem) {
      // The server is still starting up.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  server.kill();
  throw new Error("the page server did not start");
}
