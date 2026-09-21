const assert = require('node:assert/strict');
const test = require('node:test');
const {
  ORGANIZATION,
  normalizeMatchRecord,
  calculateSeasonTotals,
  calculateTeamTotals,
  buildAwardShortlists,
  spotlightQuestionSet,
  selectSpotlightCandidate,
  archiveCandidates,
  dueRecurringJobs,
} = require('../clubOperations');

test('uses Castle & Crown Collective as the umbrella identity', () => {
  assert.equal(ORGANIZATION.name, 'Castle & Crown Collective');
  assert.equal(ORGANIZATION.shortName, 'C&C Collective');
  assert.equal(ORGANIZATION.mediaDivision, 'RT Football Media');
});

test('calculates a public team record from verified match-by-match data', () => {
  const records = [
    normalizeMatchRecord({ teamKey: 'birmingham', opponent: 'One', score: '3-1', result: 'W', competition: 'Friendly' }),
    normalizeMatchRecord({ teamKey: 'birmingham', opponent: 'Two', score: '0-0', result: 'D', competition: 'Cup' }),
    normalizeMatchRecord({ teamKey: 'birmingham', opponent: 'Three', score: '1-2', result: 'L', competition: 'Tournament' }),
  ];
  assert.deepEqual(calculateTeamTotals(records), {
    played: 3, wins: 1, draws: 1, losses: 1, goalsFor: 4, goalsAgainst: 3,
    goalDifference: 1, cleanSheets: 1, form: ['W', 'D', 'L'],
  });
});

test('normalizes match-by-match records and totals corrected data safely', () => {
  const match = normalizeMatchRecord({
    teamKey: 'birmingham', opponent: 'Rivals FC', score: '3-1', competition: 'Friendly',
    playedAt: '2026-09-22T02:00:00.000Z', sourceMessageId: 'source-1',
    players: [{ playerId: 'tru', playerName: 'Tru', goals: 1, assists: 2 }],
  });
  assert.equal(match.season, 'FC27');
  const corrected = { ...match, players: [{ playerId: 'tru', playerName: 'Tru', goals: 2, assists: 1 }] };
  assert.deepEqual(calculateSeasonTotals([corrected])[0], {
    playerId: 'tru', playerName: 'Tru', appearances: 1, goals: 2, assists: 1,
    saves: 0, goalsConceded: 0, cleanSheets: 0, yellowCards: 0, redCards: 0, motm: 0,
  });
});

test('award shortlists use actual accumulated statistics and leave final choice to owner', () => {
  const records = [normalizeMatchRecord({
    teamKey: 'crownfc', opponent: 'City', score: '2-1', competition: 'Cup',
    players: [
      { playerId: 'a', playerName: 'Alpha', goals: 2, assists: 0, motm: 1 },
      { playerId: 'b', playerName: 'Bravo', goals: 0, assists: 2 },
    ],
  })];
  const awards = buildAwardShortlists(records);
  assert.equal(awards.find(item => item.awardKey === 'golden_boot').candidates[0].playerName, 'Alpha');
  assert.equal(awards.some(item => Object.hasOwn(item, 'winner')), false);
});

test('spotlight selection never repeats and reports pool exhaustion', () => {
  const candidates = [{ id: '1', playerName: 'One' }, { id: '2', playerName: 'Two' }];
  const first = selectSpotlightCandidate(candidates, [{ playerId: '1' }], 'week-one');
  assert.equal(first.selected.id, '2');
  const exhausted = selectSpotlightCandidate(candidates, [{ playerId: '1' }, { playerId: '2' }], 'week-two');
  assert.equal(exhausted.exhausted, true);
  assert.equal(exhausted.selected, null);
});

test('spotlight questions rotate without duplicates and keep four to five questions', () => {
  const a = spotlightQuestionSet('2026-09-24:birmingham');
  const b = spotlightQuestionSet('2026-10-01:birmingham');
  assert.equal(a.length, 5);
  assert.equal(new Set(a).size, 5);
  assert.notDeepEqual(a, b);
});

test('archive planner only selects verified RT-managed posts older than 30 days', () => {
  const selected = archiveCandidates([
    { id: 'old', managedBy: 'rt-media', state: 'published', publishedAt: '2026-08-01T00:00:00.000Z' },
    { id: 'chat', managedBy: 'member', state: 'published', publishedAt: '2026-08-01T00:00:00.000Z' },
    { id: 'new', managedBy: 'rt-media', state: 'published', publishedAt: '2026-09-15T00:00:00.000Z' },
  ], new Date('2026-09-21T12:00:00.000Z'));
  assert.deepEqual(selected.map(item => item.id), ['old']);
});

test('recurring jobs are evaluated in Eastern Time with stable idempotency keys', () => {
  const saturday = dueRecurringJobs(new Date('2026-09-26T14:05:00.000Z'));
  assert.equal(saturday.some(job => job.name === 'spotlight-publish-draft'), true);
  assert.equal(saturday.every(job => job.key.startsWith('2026-09-26:')), true);
});
