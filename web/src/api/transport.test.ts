import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, jsonHeaders, requestJson } from "./transport";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("API transport", () => {
  it("decodes JSON and supplies the Accept header", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response('{"ready":true}', {
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(
      requestJson(fetchImplementation, "/ready", {
        headers: { "X-Trace": "abc" },
      }),
    ).resolves.toEqual({ ready: true });
    const headers = new Headers(
      fetchImplementation.mock.calls[0]?.[1]?.headers,
    );
    expect(headers.get("Accept")).toBe("application/json");
    expect(headers.get("X-Trace")).toBe("abc");
  });

  it.each([
    ["text response", "upstream unavailable", "upstream unavailable"],
    ["empty response", "", null],
    ["JSON response", '{"code":"missing"}', { code: "missing" }],
  ])("retains %s error bodies", async (_label, body, expected) => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(new Response(body, { status: 503 })),
    );

    await expect(requestJson(fetchImplementation, "/failure")).rejects.toEqual(
      expect.objectContaining({
        name: "ApiError",
        status: 503,
        body: expected,
      }),
    );
  });

  it("converts the configured timeout into an API timeout error and clears its timer", async () => {
    vi.useFakeTimers();
    const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout");
    const fetchImplementation = vi.fn<typeof fetch>(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(init.signal?.reason),
            { once: true },
          );
        }),
    );

    const request = requestJson(fetchImplementation, "/slow", {}, 25);
    const rejection = expect(request).rejects.toMatchObject({
      name: "ApiError",
      status: 408,
      body: { message: "The request timed out after 25 ms." },
    });
    await vi.advanceTimersByTimeAsync(25);
    await rejection;
    expect(clearTimeoutSpy).toHaveBeenCalledOnce();
  });

  it("forwards caller abort reasons and removes the abort listener", async () => {
    const controller = new AbortController();
    const addListener = vi.spyOn(controller.signal, "addEventListener");
    const removeListener = vi.spyOn(controller.signal, "removeEventListener");
    const reason = new Error("caller stopped request");
    const fetchImplementation = vi.fn<typeof fetch>(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(init.signal?.reason),
            { once: true },
          );
        }),
    );

    const request = requestJson(
      fetchImplementation,
      "/slow",
      { signal: controller.signal },
      500,
    );
    const rejection = expect(request).rejects.toBe(reason);
    controller.abort(reason);
    await rejection;

    const abortCallback = addListener.mock.calls.find(
      ([type]) => type === "abort",
    )?.[1];
    expect(abortCallback).toBeTypeOf("function");
    expect(removeListener).toHaveBeenCalledWith("abort", abortCallback);
    expect(fetchImplementation.mock.calls[0]?.[1]?.signal).not.toBe(
      controller.signal,
    );
  });

  it("clears the timeout timer after a successful response", async () => {
    vi.useFakeTimers();
    const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout");
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(new Response('{"ok":true}')),
    );

    await expect(
      requestJson(fetchImplementation, "/fast", {}, 500),
    ).resolves.toEqual({ ok: true });
    expect(clearTimeoutSpy).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("sets JSON request headers", () => {
    const headers = jsonHeaders({ "X-Trace": "abc" });
    expect(headers.get("Accept")).toBe("application/json");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("X-Trace")).toBe("abc");
  });

  it("exposes the HTTP error fields", () => {
    const error = new ApiError(502, "bad gateway");
    expect(error).toMatchObject({
      name: "ApiError",
      status: 502,
      body: "bad gateway",
    });
  });
});
