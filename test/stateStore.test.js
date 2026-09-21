const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { StateStore } = require('../stateStore');

test('persists stories and duplicate-message status across restarts', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'rt-media-'));
  const file = path.join(directory, 'state.json');
  const first = new StateStore(file);
  first.putStory({ id: 'story-1', state: 'waiting_for_quote', playerName: 'Test Player' });
  first.markProcessed('message-1', 'pending');

  const second = new StateStore(file);
  assert.equal(second.getStory('story-1').playerName, 'Test Player');
  assert.equal(second.isProcessed('message-1'), true);
});

test('patches and deletes a story', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'rt-media-'));
  const store = new StateStore(path.join(directory, 'state.json'));
  store.putStory({ id: 'story-2', state: 'selecting' });
  store.patchStory('story-2', { state: 'draft_ready' });
  assert.equal(store.getStory('story-2').state, 'draft_ready');
  store.deleteStory('story-2');
  assert.equal(store.getStory('story-2'), null);
});

test('persists club-specific squad number assignments', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'rt-media-'));
  const file = path.join(directory, 'state.json');
  const first = new StateStore(file);
  first.assignSquadNumber('birmingham', '22', { playerName: 'Tru', storyId: 'signing-1' });

  const second = new StateStore(file);
  assert.equal(second.getSquadNumber('birmingham', '22').playerName, 'Tru');
  assert.equal(second.getSquadNumber('crownfc', '22'), null);
  assert.equal(second.listSquadNumbers('birmingham').length, 1);
  assert.deepEqual(second.releaseSquadNumbersForPlayer('birmingham', 'tru'), ['22']);
  assert.equal(second.getSquadNumber('birmingham', '22'), null);
});

test('persists one-time audit metadata', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'rt-media-'));
  const file = path.join(directory, 'state.json');
  const first = new StateStore(file);
  assert.equal(first.getMetadata('audit'), undefined);
  first.setMetadata('audit', { version: 'v2' });
  assert.equal(new StateStore(file).getMetadata('audit').version, 'v2');
});
