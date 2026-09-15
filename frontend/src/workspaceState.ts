import type { ConversationResponse } from "./api";
import { timelineFromConversation } from "./chatTimeline";
import type { TimelineItem } from "./chatTimeline";

export type ConversationState = {
  id: string;
  title: string;
  messages: TimelineItem[];
  draft: string;
  error: string;
};

export type BookWorkspace = {
  bookId: string;
  conversations: ConversationState[];
  activeConversationId: string;
};

export const makeConversation = (): ConversationState => ({
  id: crypto.randomUUID(),
  title: "新对话",
  messages: [],
  draft: "",
  error: "",
});

const conversationFromResponse = (conversation: ConversationResponse): ConversationState => ({
  id: conversation.id,
  title: conversation.title,
  messages: timelineFromConversation(conversation),
  draft: "",
  error: "",
});

export const makeWorkspace = (
  bookId: string,
  conversationResponses: ConversationResponse[],
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
  update: (conversation: ConversationState) => ConversationState,
): BookWorkspace | null {
  if (!workspace || workspace.bookId !== targetBookId) return workspace;
  return {
    ...workspace,
    conversations: workspace.conversations.map((conversation) => (
      conversation.id === conversationId ? update(conversation) : conversation
    )),
  };
}
