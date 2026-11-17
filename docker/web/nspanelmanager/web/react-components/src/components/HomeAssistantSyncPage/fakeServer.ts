import { vi } from "vitest";

export type Reply = { status: number; body: unknown };
export type Recorded = { method: string; path: string; query: URLSearchParams; body: unknown };
export type Handler = (request: Recorded) => Reply;

export const ok = (body: unknown, status = 200): Reply => ({ status, body });

/**
 * A fake backend for component tests: `routes` maps "METHOD /path" to a handler. Every request is
 * recorded; a request with no route fails the test loudly.
 */
export function fakeServer(routes: Record<string, Handler>) {
  const requests: Recorded[] = [];
  const fetchMock = vi.fn(async (input: Request | string, init?: RequestInit) => {
    const request = typeof input === "string" ? new Request(new URL(input, "http://localhost"), init) : input;
    const text = await request.clone().text();
    const url = new URL(request.url);
    const recorded: Recorded = { method: request.method, path: url.pathname, query: url.searchParams, body: text ? JSON.parse(text) : undefined };
    requests.push(recorded);
    const handler = routes[`${request.method} ${url.pathname}`];
    if (!handler) throw new Error(`Unexpected request: ${request.method} ${url.pathname}`);
    const reply = handler(recorded);
    return new Response(JSON.stringify(reply.body), { status: reply.status, headers: { "Content-Type": "application/json" } });
  });
  return {
    requests,
    fetchMock,
    calls: (method: string, path: string) => requests.filter((request) => request.method === method && request.path === path),
  };
}
