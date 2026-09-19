import { describe, expect, it } from "vitest";
import {
  bookDisplayName,
  makeWorkspace,
  updateConversationInWorkspace,
} from "../workspaceState";
import type { BookWorkspace } from "../types";

const workspace: BookWorkspace = {
  bookId: "book-1",
  activeConversationId: "conversation-1",
  conversations: [
    {
      id: "conversation-1",
      title: "对话一",
      messages: [],
      draft: "对话一的草稿",
      error: "",
    },
    {
      id: "conversation-2",
      title: "对话二",
      messages: [],
      draft: "对话二的草稿",
      error: "原有错误",
    },
  ],
};

describe("book workspace state", () => {
  it("uses the book id when an older API response has no display names", () => {
    expect(bookDisplayName("book-1", undefined)).toBe("book-1");
    expect(bookDisplayName("book-1", { "book-1": "第一本书" })).toBe("第一本书");
  });

  it("updates only the requested conversation", () => {
    const updated = updateConversationInWorkspace(
      workspace,
      "book-1",
      "conversation-1",
      (conversation) => ({ ...conversation, draft: "修改后的草稿", error: "请求失败" }),
    );

    expect(updated?.conversations[0]).toMatchObject({
      draft: "修改后的草稿",
      error: "请求失败",
    });
    expect(updated?.conversations[1]).toBe(workspace.conversations[1]);
  });

  it("ignores a stale update belonging to another book", () => {
    const updated = updateConversationInWorkspace(
      workspace,
      "book-2",
      "conversation-1",
      (conversation) => ({ ...conversation, draft: "不应写入" }),
    );

    expect(updated).toBe(workspace);
  });

  it("creates an empty local conversation when a book has no history", () => {
    const created = makeWorkspace("book-empty", []);

    expect(created.conversations).toHaveLength(1);
    expect(created.activeConversationId).toBe(created.conversations[0].id);
    expect(created.conversations[0]).toMatchObject({
      title: "新对话",
      messages: [],
      draft: "",
      error: "",
    });
  });
});
