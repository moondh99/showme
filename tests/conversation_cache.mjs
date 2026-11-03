import {test} from 'node:test';
import assert from 'node:assert/strict';
import {conversationCache} from '../web/conversation-cache.js';

function useStorage(t) {
  const entries = new Map();
  t.mock.method(Date, 'now', () => 1000);
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: {
      getItem: key => entries.get(key) ?? null,
      setItem: (key, value) => entries.set(key, value),
      removeItem: key => entries.delete(key)
    }
  });
  t.after(() => delete globalThis.sessionStorage);
  return entries;
}

test('restore only recent settled turns and keep a pending question as a draft', t => {
  useStorage(t);
  const items = Array.from({length: 10}, (_, id) => ({response: {id}}));
  items.push({response: null});
  const selection = {id: 'selection'};
  const cache = conversationCache('approved-revision');
  cache.write('step', {items, draft: '작성 중', selection, parent: 'parent', busy: true});

  const saved = conversationCache('approved-revision').read('step');
  assert.deepEqual(saved.items.map(item => item.response.id), [2, 3, 4, 5, 6, 7, 8, 9]);
  assert.deepEqual(saved.selection, selection);
  assert.equal(saved.parent, 'parent');
  assert.equal(saved.draft, '작성 중');
  assert.equal(saved.interrupted, true);
  assert.equal(saved.busy, undefined);
  assert.equal(conversationCache('another-revision').read('step'), null);
  assert.equal(cache.read('another-step'), null);
});

test('editing does not move the cutoff and clearing affects only the current step', t => {
  const entries = useStorage(t);
  const cache = conversationCache('approved-revision');
  const state = {items: [], draft: '처음'};
  cache.write('step', state);
  cache.write('other-step', {items: [], draft: '다른 질문'});
  t.mock.method(Date, 'now', () => state.expiresAt - 1);
  state.draft = '수정';
  cache.write('step', state);
  assert.equal(cache.read('step').draft, '수정');

  cache.clear('other-step');
  assert.equal(cache.read('other-step'), null);
  assert.equal(entries.size, 1);
  t.mock.method(Date, 'now', () => state.expiresAt);
  assert.equal(cache.read('step'), null);
  assert.equal(entries.size, 0);
});

test('unreadable or unavailable storage leaves the live conversation usable', t => {
  const entries = useStorage(t);
  const cache = conversationCache('revision');
  cache.write('step', {items: [], draft: '질문'});
  const [key] = entries.keys();
  entries.set(key, '{');
  assert.equal(cache.read('step'), null);
  assert.equal(entries.size, 0);

  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    get() { throw new Error('storage blocked'); }
  });
  assert.doesNotThrow(() => cache.write('step', {items: [], draft: '질문'}));
  assert.equal(cache.read('step'), null);
});
