const assert = require('node:assert/strict');
const test = require('node:test');
const { CLUBS, TAGS, archivedName, categoryMatches, normalizedName } = require('../matchCenterSetup');

test('normalizes decorated Discord channel names safely', () => {
  assert.equal(normalizedName('📅・MLPC Match Center'), 'mlpc-match-center');
  assert.equal(normalizedName('𓊆  𓊇 CLUB ARCHIVE'), 'club-archive');
});

test('finds both club category naming variants', () => {
  assert.equal(categoryMatches({ name: 'CrownFC • MLPC' }, CLUBS.crownfc), true);
  assert.equal(categoryMatches({ name: 'Birmingham City • MPL' }, CLUBS.birmingham), true);
  assert.equal(categoryMatches({ name: 'Birmingham City • ML1' }, CLUBS.birmingham), true);
  assert.equal(categoryMatches({ name: 'RT Football Media' }, CLUBS.birmingham), false);
});

test('archives Match Center channels without renaming result channels', () => {
  assert.equal(archivedName('mlpc-match-center'), 'mlpc-match-center-old');
  assert.equal(archivedName('mpl-match-center'), 'mpl-match-center-old');
  assert.equal(archivedName('ml1-match-center'), 'ml1-match-center-old');
  assert.equal(archivedName('mpl-match-results'), 'mpl-match-results');
});

test('uses the seven approved forum tags', () => {
  assert.deepEqual(TAGS, ['Upcoming', 'Home', 'Away', 'Completed', 'Win', 'Loss', 'Draw']);
});
