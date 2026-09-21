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

test('keeps production and staging operations completely isolated', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'rt-media-'));
  const store = new StateStore(path.join(directory, 'state.json'));
  store.putMatchRecord({ id: 'real-match', teamKey: 'birmingham' });
  store.putMatchRecord({ id: 'test-match', teamKey: 'birmingham' }, { testMode: true });
  store.recordSpotlightSelection({ id: 'test-spotlight', teamKey: 'crownfc', playerId: 'test-player' }, { testMode: true });
  assert.deepEqual(store.listMatchRecords().map(item => item.id), ['real-match']);
  assert.deepEqual(store.listMatchRecords({}, { testMode: true }).map(item => item.id), ['test-match']);
  assert.equal(store.listSpotlightSelections('crownfc').length, 0);
  store.clearTestData();
  assert.equal(store.listMatchRecords({}, { testMode: true }).length, 0);
  assert.equal(store.listMatchRecords().length, 1);
});

test('scheduled operations are idempotent across restarts', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'rt-media-'));
  const file = path.join(directory, 'state.json');
  const first = new StateStore(file);
  assert.equal(first.claimScheduleRun('2026-09-24:spotlight'), true);
  assert.equal(first.claimScheduleRun('2026-09-24:spotlight'), false);
  const second = new StateStore(file);
  assert.equal(second.claimScheduleRun('2026-09-24:spotlight'), false);
});

test('management logs and media archive state persist', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'rt-media-'));
  const file = path.join(directory, 'state.json');
  const first = new StateStore(file);
  first.addManagementLog({ action: 'signing_published', storyId: 'story-1' });
  first.putMediaPost({ id: 'message-1', state: 'published', managedBy: 'rt-media' });
  first.patchMediaPost('message-1', { archivedAt: '2026-10-21T12:00:00.000Z' });
  const second = new StateStore(file);
  assert.equal(second.listManagementLogs()[0].action, 'signing_published');
  assert.equal(second.listMediaPosts()[0].archivedAt, '2026-10-21T12:00:00.000Z');
});
