import { cp, mkdir, rm, writeFile } from "node:fs/promises";

await rm("dist", { recursive: true, force: true });
await mkdir("dist/server", { recursive: true });
await cp("../static", "dist/client", { recursive: true });

const worker = `
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const response = await env.ASSETS.fetch(request);
    if (response.status !== 404 || url.pathname.includes('.')) return response;
    return env.ASSETS.fetch(new Request(new URL('/index.html', request.url), request));
  }
};
`;

await writeFile("dist/server/index.js", worker.trimStart(), "utf8");
