const lifetime = 24 * 60 * 60 * 1000;
export const recentQuestionCount = 8;

export function hasConversation({items, draft, selection}) {
  return items.length > 0 || draft !== '' || Boolean(selection);
}

export function conversationCache(shareId) {
  const key = stepId => `showme:conversation:v1:${encodeURIComponent(shareId)}:${encodeURIComponent(stepId)}`;
  return {
    read(stepId) {
      try {
        const raw = sessionStorage.getItem(key(stepId));
        if (raw === null) return null;
        const saved = JSON.parse(raw);
        if (Number.isFinite(saved?.expiresAt) && saved.expiresAt > Date.now() &&
            Array.isArray(saved.items) && typeof saved.draft === 'string') return saved;
      } catch {
        // Storage can be blocked or contain an unreadable copy.
      }
      this.clear(stepId);
      return null;
    },
    write(stepId, state) {
      // Keep the cutoff fixed so editing a draft cannot extend the lifetime of
      // server-side selection IDs or earlier turns in a clarification chain.
      state.expiresAt ??= Date.now() + lifetime;
      if (state.expiresAt <= Date.now() || !hasConversation(state)) {
        this.clear(stepId);
        return;
      }
      const {expiresAt, draft, parent, selection} = state;
      const items = state.items.filter(item => item.response).slice(-recentQuestionCount);
      try {
        sessionStorage.setItem(key(stepId), JSON.stringify({
          expiresAt, items, draft, parent, selection, interrupted: state.busy || state.interrupted
        }));
      } catch {
        // Prefer live state over reviving an older draft or selection.
        this.clear(stepId);
      }
    },
    clear(stepId) {
      try { sessionStorage.removeItem(key(stepId)); } catch {}
    }
  };
}
