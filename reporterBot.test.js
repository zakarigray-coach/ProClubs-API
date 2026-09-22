const assert = require('node:assert/strict');
const test = require('node:test');
const sharp = require('sharp');
const { publicationDate, safePublicText, normalizeStory, normalizeSquadNumber, newspaperGraphic, playerRegistrationModal } = require('../reporterBot');
const { headlineLayout, limitWords, storyParagraphs, sidebarRows } = require('../rtNewspaperRenderer');

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

test('squad numbers are normalized and limited to 1 through 99', () => {
  assert.equal(normalizeSquadNumber('#22'), '22');
  assert.equal(normalizeSquadNumber('07'), '7');
  assert.equal(normalizeSquadNumber(''), '');
  assert.equal(normalizeSquadNumber('0'), null);
  assert.equal(normalizeSquadNumber('100'), null);
  assert.equal(normalizeSquadNumber('keeper'), null);
});

test('player registration modal collects five fields without exposing club role selection', () => {
  const modal = playerRegistrationModal().toJSON();
  assert.equal(modal.components.length, 5);
  const ids = modal.components.map(row => row.components[0].custom_id);
  assert.deepEqual(ids, ['ea_id', 'position', 'availability', 'verification', 'notes']);
  assert.equal(ids.includes('club'), false);
});

test('approved RT Media renderer creates a Discord-readable vertical front page', async () => {
  const team = { label: 'CrownFC', league: 'MLPC', reporter: 'Teagan', outlet: 'Teagan Behind the Crown', color: 0x7bafd4 };
  const story = normalizeStory(team, 'signing', {
    headline: 'THE CROWN ADDS A NEW VOICE',
    subheadline: 'Verified club news receives a proper front page',
    article: 'A concise verified story designed to remain readable on a Discord mobile screen.',
    body: 'CrownFC confirms a verified club update ahead of the MLPC campaign.',
    reporterNote: 'Teagan has the verified details behind the Crown.',
  }, { player: 'Test Player' });
  const buffer = await newspaperGraphic(team, 'signing', story, null, { publishedAt: '2026-09-21T18:00:00.000Z', issueNumber: 27 });
  const metadata = await sharp(buffer).metadata();
  assert.equal(metadata.width, 1024);
  assert.equal(metadata.height, 1536);
  assert.equal(metadata.format, 'png');
});

test('newspaper typography keeps full headlines and limits print copy', () => {
  const headline = 'A NEW MIDFIELD STANDARD AT ST. ANDREW’S FOR THE NEW MPL SEASON';
  const layout = headlineLayout(headline);
  assert.equal(layout.wrapped.join(' '), headline);
  assert.equal(layout.wrapped.join(' ').includes('…'), false);
  const longCopy = Array.from({ length: 100 }, (_, index) => `word${index}`).join(' ');
  assert.equal(limitWords(longCopy, 52).split(' ').length, 52);
  assert.equal(limitWords(longCopy, 52).includes('…'), false);
});

test('signing front page uses distinct complete copy without repeated sidebar summaries', () => {
  const team = { label: 'Birmingham City', league: 'Masters Premier League • League 1', reporter: 'Raine at St. Andrew’s' };
  const story = {
    playerName: 'Tru', playerNumber: '22', position: 'CDM', previousClub: '',
    article: 'This deliberately long article should not be copied into every panel.',
  };
  const paragraphs = storyParagraphs(team, 'signing', story);
  assert.equal(paragraphs.every(value => /[.!?]$/.test(value)), true);
  assert.equal(paragraphs.some(value => value.includes('…') || value.includes('...')), false);
  const rows = sidebarRows(team, 'signing', story);
  assert.deepEqual(rows.map(row => row[0]), ['OFFICIAL MOVE', 'SQUAD FILE', 'PLAYER’S WORD', 'LEAGUE DESK']);
  assert.equal(rows.filter(row => row[1].includes('Tru')).length, 0);
});
