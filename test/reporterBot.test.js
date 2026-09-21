const assert = require('node:assert/strict');
const test = require('node:test');
const { publicationDate, safePublicText, normalizeStory } = require('../reporterBot');

test('newspaper date follows Eastern Time instead of UTC', () => {
  assert.equal(publicationDate('2026-09-21T02:30:00.000Z'), 'SEP 20, 2026');
  assert.equal(publicationDate('2026-09-21T18:00:00.000Z'), 'SEP 21, 2026');
});

test('public copy neutralizes mass and role mentions', () => {
  const cleaned = safePublicText('@everyone signed <@&1234567890>', 200);
  assert.equal(cleaned.includes('@everyone'), false);
  assert.equal(cleaned.includes('<@&1234567890>'), false);
});

test('missing quotes are disclosed instead of simulated', () => {
  const team = { label: 'CrownFC', league: 'MLPC' };
  const story = normalizeStory(team, 'signing', { body: 'Verified signing story.' }, { player: 'Player One' });
  assert.equal(story.playerQuote, '');
  assert.equal(story.leadershipQuote, 'No separate club leadership comment was supplied.');
});
