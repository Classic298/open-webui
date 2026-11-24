import equal from 'fast-deep-equal';
import { get, writable } from 'svelte/store';
import { getChatById } from '$lib/apis/chats';
import { user } from '$lib/stores';

const MAX_CACHED_CHATS = 20;

/** The user's own chats opened before, oldest first; each shows at once when opened again. */
export const cachedChats = new Map<string, any>();

export const cacheChat = (chat: any) => {
	cachedChats.delete(chat.id);
	if (chat.user_id !== get(user)?.id) return;
	cachedChats.set(chat.id, chat);
	if (cachedChats.size > MAX_CACHED_CHATS) cachedChats.delete(cachedChats.keys().next().value!);
};

/** A chat requested before the component that shows it is ready. */
export const pendingChatRequest = writable<{
	id: string;
	promise: ReturnType<typeof getChatById>;
} | null>(null);

export const requestChat = (id: string) => {
	const promise = getChatById(localStorage.token, id);
	promise.catch(() => {});
	pendingChatRequest.set({ id, promise });
	return promise;
};

export const getCachedChat = (id: string) => {
	const chat = cachedChats.get(id);
	const history = chat?.chat?.history;
	const messages: any[] = Object.values(history?.messages ?? {});
	const current = history?.messages?.[chat.current_message_id ?? history?.currentId];
	// A reply that was still running continues from the server's copy.
	const replying =
		messages.some((message) => message.role === 'assistant' && message.done === false) ||
		(current?.role === 'assistant' && !current.done);
	return replying ? undefined : chat;
};

/** Each chat's messages as last loaded or saved; a save sends only the ones changed since. */
const savedMessages = new Map<string, Record<string, any>>();

export const markMessagesSaved = (chatId: string, messages: Record<string, any>) => {
	const saved = { ...savedMessages.get(chatId), ...messages };
	savedMessages.delete(chatId);
	savedMessages.set(chatId, saved);
	if (savedMessages.size > MAX_CACHED_CHATS)
		savedMessages.delete(savedMessages.keys().next().value!);
};

export const getUnsavedMessages = (chatId: string, messages: Record<string, any>) => {
	const saved = savedMessages.get(chatId) ?? {};
	return structuredClone(
		Object.fromEntries(
			Object.entries(messages).filter(
				([id, message]) =>
					!saved[id] ||
					!equal({ ...message, childrenIds: null }, { ...saved[id], childrenIds: null })
			)
		)
	);
};
