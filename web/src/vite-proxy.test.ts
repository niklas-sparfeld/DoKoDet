import { createServer as createHttpServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { createServer as createViteServer, type ViteDevServer } from "vite";

const servers: Array<{ backend: Server; vite: ViteDevServer }> = [];

describe("Vite development proxy", () => {
  afterEach(async () => {
    await Promise.all(
      servers.splice(0).map(async ({ backend, vite }) => {
        await vite.close();
        await new Promise<void>((resolve, reject) => {
          backend.close((error) => (error ? reject(error) : resolve()));
        });
      }),
    );
    delete process.env.VITE_API_PROXY_TARGET;
  });

  it("forwards v1 requests to the configured backend target", async () => {
    const backend = createHttpServer((request, response) => {
      if (request.url !== "/v1/proxy-check") {
        response.writeHead(404).end();
        return;
      }
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ status: "proxied" }));
    });
    await listen(backend);
    const backendAddress = addressOf(backend);
    process.env.VITE_API_PROXY_TARGET = `http://127.0.0.1:${backendAddress.port}`;

    const vite = await createViteServer({
      configFile: resolve(process.cwd(), "vite.config.ts"),
      server: {
        host: "127.0.0.1",
        port: 0,
      },
    });
    await vite.listen();
    servers.push({ backend, vite });
    const viteAddress = addressOf(vite.httpServer!);

    const response = await fetch(
      `http://127.0.0.1:${viteAddress.port}/v1/proxy-check`,
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "proxied" });
  });
});

function listen(server: Server): Promise<void> {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
}

function addressOf(server: {
  address(): ReturnType<Server["address"]>;
}): AddressInfo {
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Expected a local TCP address.");
  }
  return address;
}
