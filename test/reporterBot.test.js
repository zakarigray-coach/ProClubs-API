const assert = require('node:assert/strict');
const test = require('node:test');
const sharp = require('sharp');
const { publicationDate, safePublicText, normalizeStory, normalizeSquadNumber, newspaperGraphic, spotlightGraphic, playerRegistrationModal } = require('../reporterBot');
const { headlineLayout, limitWords, storyParagraphs, sidebarRows, palette, featureNameSize } = require('../rtNewspaperRenderer');
const { selectSpotlightLayout, interviewExcerpts, exactExcerpt } = require('../rtSpotlightRenderer');
const { batchComposition, validateBatchSigningData, renderBatchSigningPoster } = require('../rtBatchSigningRenderer');

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

test('locked newspaper themes keep Birmingham light and CrownFC dark', () => {
  const birmingham = palette('birmingham');
  const crown = palette('crownfc');
  assert.equal(birmingham.paper, '#EEE8DB');
  assert.equal(birmingham.ink, '#101216');
  assert.equal(crown.paper, '#050A11');
  assert.equal(crown.ink, '#F5F2E9');
  assert.notEqual(birmingham.featurePanel, crown.featurePanel);
  assert.ok(featureNameSize('A VERY LONG PLAYER DISPLAY NAME') < featureNameSize('TRU'));
});

test('Player Spotlight uses its own magazine renderer and genuine complete excerpts', async () => {
  const team = { label: 'CrownFC', league: 'MLPC', reporter: 'Teagan Behind the Crown' };
  const story = {
    playerName: 'Tru', playerNumber: '22', position: 'CDM', spotlightHeadline: 'THE GENERAL',
    playerQuote: 'because I’m a baller',
    interviewExcerpts: ['because I’m a baller', 'I try to lead by example and set the standard every game.'],
  };
  assert.equal(selectSpotlightLayout(story), 'profile');
  assert.deepEqual(interviewExcerpts(story), story.interviewExcerpts);
  assert.equal(exactExcerpt('A complete statement.', 10), 'A complete statement.');
  assert.equal(exactExcerpt('one two three four five six seven eight nine ten eleven twelve', 5), '');
  const hero = await sharp({ create: { width: 1024, height: 1536, channels: 3, background: '#123A68' } }).png().toBuffer();
  const buffer = await spotlightGraphic(team, story, null, { heroBuffer: hero });
  const metadata = await sharp(buffer).metadata();
  assert.equal(metadata.width, 1024);
  assert.equal(metadata.height, 1536);
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
    playerQuote: 'because I’m a baller', article: 'This deliberately long article should not be copied into every panel.',
  };
  const paragraphs = storyParagraphs(team, 'signing', story);
  assert.equal(paragraphs.every(value => /[.!?]$/.test(value)), true);
  assert.equal(paragraphs.some(value => value.includes('…') || value.includes('...')), false);
  const rows = sidebarRows(team, 'signing', story);
  assert.deepEqual(rows.map(row => row[0]), ['ROSTER UPDATE', 'SQUAD FILE', 'LEAGUE WATCH', 'PLAYER’S WORD']);
  assert.equal(rows[3][1], '“because I’m a baller” — Tru');
  assert.ok(rows[3][1].length < 50);
  assert.equal(new Set(rows.map(row => row[1])).size, 4);
  assert.equal(rows.every(row => !row[1].includes('…') && !row[1].includes('...')), true);
});

test('multiple signing contract supports two through five players and explicit marquee only', async () => {
  const players = Array.from({ length: 5 }, (_, index) => ({ id: `player-${index + 1}`, name: `Player ${index + 1}`, position: index ? 'CM' : 'GK', number: String(index + 1) }));
  assert.equal(validateBatchSigningData('birmingham', players, 'player-3'), true);
  assert.throws(() => validateBatchSigningData('birmingham', players.slice(0, 1)), /2–5/);
  assert.throws(() => validateBatchSigningData('crownfc', players, 'not-selected'), /must be one/);
  assert.match(batchComposition(2, 'a'), /^duo-/);
  assert.match(batchComposition(3, 'b'), /^trio-/);
  assert.match(batchComposition(4, 'c'), /^four-/);
  assert.match(batchComposition(5, 'd'), /^class-/);
  const art = await sharp({ create: { width: 1024, height: 1536, channels: 3, background: '#10243A' } }).png().toBuffer();
  const poster = await renderBatchSigningPoster({ teamKey: 'birmingham', players, artBuffer: art, season: '2026/27', composition: 'class-lineup', marqueePlayerId: 'player-3' });
  const metadata = await sharp(poster).metadata();
  assert.equal(metadata.width, 1080);
  assert.equal(metadata.height, 1350);
});
