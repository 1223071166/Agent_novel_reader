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
      .mockResolvedValueOnce(new Response(
        '{"tool_round_limit":100,"show_usage":true,"model_provider":"siliconflow","siliconflow":{"base_url":"https://api.siliconflow.cn/v1","model_name":"deepseek-ai/DeepSeek-V4-Flash","has_api_key":true},"custom":{"base_url":"","model_name":"","has_api_key":false}}',
        { status: 200 },
      ))
      .mockResolvedValueOnce(new Response(
        '{"tool_round_limit":6,"show_usage":false,"model_provider":"custom","siliconflow":{"base_url":"https://api.siliconflow.cn/v1","model_name":"deepseek-ai/DeepSeek-V4-Flash","has_api_key":true},"custom":{"base_url":"https://example.com/v1","model_name":"test-model","has_api_key":true}}',
        { status: 200 },
      ));
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadAppSettings()).resolves.toEqual({
      tool_round_limit: 100,
      show_usage: true,
      model_provider: "siliconflow",
      siliconflow: {
        base_url: "https://api.siliconflow.cn/v1",
        model_name: "deepseek-ai/DeepSeek-V4-Flash",
        has_api_key: true,
      },
      custom: { base_url: "", model_name: "", has_api_key: false },
    });
    await expect(saveAppSettings({
      toolRoundLimit: 6,
      showUsage: false,
      modelProvider: "custom",
      siliconflowApiKey: null,
      customBaseUrl: "https://example.com/v1",
      customModelName: "test-model",
      customApiKey: "custom-key",
    })).resolves.toEqual({
      tool_round_limit: 6,
      show_usage: false,
      model_provider: "custom",
      siliconflow: {
        base_url: "https://api.siliconflow.cn/v1",
        model_name: "deepseek-ai/DeepSeek-V4-Flash",
        has_api_key: true,
      },
      custom: {
        base_url: "https://example.com/v1",
        model_name: "test-model",
        has_api_key: true,
      },
    });

    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://127.0.0.1:8000/api/settings",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          tool_round_limit: 6,
          show_usage: false,
          model_provider: "custom",
          siliconflow_api_key: null,
          custom_base_url: "https://example.com/v1",
          custom_model_name: "test-model",
          custom_api_key: "custom-key",
        }),
      }),
    );
  });
});
