import { afterEach, describe, expect, it, vi } from "vitest";

import { loadAppSettings, saveAppSettings, streamChat } from "../api";


afterEach(() => {
  vi.unstubAllGlobals();
});

describe("chat stream", () => {
  it("rejects a stream that closes without a terminal event", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      'event: token\ndata: {"content":"半截回答"}\n\n',
      { status: 200 },
    )));

    await expect(streamChat("book-1", "conversation-1", "继续", () => {}))
      .rejects.toThrow("聊天连接意外中断");
  });

  it("accepts a stream that ends with done", async () => {
    const events: string[] = [];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      'event: done\ndata: {"conversation_id":"conversation-1"}\n\n',
      { status: 200 },
    )));

    await streamChat("book-1", "conversation-1", "继续", ({ event }) => {
      events.push(event);
    });

    expect(events).toEqual(["done"]);
  });
});

describe("app settings", () => {
  it("loads and saves the tool round limit", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('{"tool_round_limit":100}', { status: 200 }))
      .mockResolvedValueOnce(new Response('{"tool_round_limit":6}', { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadAppSettings()).resolves.toEqual({ tool_round_limit: 100 });
    await expect(saveAppSettings(6)).resolves.toEqual({ tool_round_limit: 6 });

    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://127.0.0.1:8000/api/settings",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ tool_round_limit: 6 }),
      }),
    );
  });
});
