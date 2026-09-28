import { timelineFromConversation } from "./chatTimeline";
import type {
  BookWorkspace,
  Conversation,
  FrontendConversation,
} from "./types";

export function bookDisplayName(
  bookId: string,
  bookNames?: Record<string, string>,
): string {
  return bookNames?.[bookId] ?? bookId;
}

export const makeConversation = (): FrontendConversation => ({
  id: crypto.randomUUID(),
  title: "新对话",
  messages: [],
  draft: "",
  error: "",
});

const conversationFromResponse = (conversation: Conversation): FrontendConversation => ({
  id: conversation.id,
  title: conversation.title,
  messages: timelineFromConversation(conversation),
  draft: "",
  error: "",
});

export const makeWorkspace = (
  bookId: string,
  conversationResponses: Conversation[],
): BookWorkspace => {
  const conversations = conversationResponses.length > 0
    ? conversationResponses.map(conversationFromResponse)
    : [makeConversation()];
  return {
    bookId,
    conversations,
    activeConversationId: conversations[0].id,
  };
};

export function updateConversationInWorkspace(
  workspace: BookWorkspace | null,
  targetBookId: string,
  conversationId: string,
  update: (conversation: FrontendConversation) => FrontendConversation,
): BookWorkspace | null {
  if (!workspace || workspace.bookId !== targetBookId) return workspace;
  return {
    ...workspace,
    conversations: workspace.conversations.map((conversation) => (
      conversation.id === conversationId ? update(conversation) : conversation
    )),
  };
}
