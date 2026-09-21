const crypto = require('crypto');

const ORGANIZATION = Object.freeze({
  name: 'Castle & Crown Collective',
  shortName: 'C&C Collective',
  mediaDivision: 'RT Football Media',
  slogan: 'REAL CLUBS. REAL STORIES. ALL FOOTBALL THAT MATTERS.',
  timezone: 'America/New_York',
});

const REPORTERS = Object.freeze({
  birmingham: {
    name: 'Raine',
    outlet: 'Raine at St. Andrew’s',
    voice: 'Polished, observant and grounded, with occasional understated dry football humor.',
  },
  crownfc: {
    name: 'Teagan',
    outlet: 'Teagan Behind the Crown',
    voice: 'Energetic, playful and confident, with occasional cheeky but professional football humor.',
  },
});

const SPOTLIGHT_QUESTIONS = Object.freeze([
  'How are you enjoying life at the club so far?',
  'What do you think about the direction the club is taking?',
  'What is your main personal goal for this season?',
  'Which role or playing style brings out your best football?',
  'Which teammate do you feel you have built the strongest chemistry with?',
  'What has been your favorite club moment so far?',
  'What part of your game are you working hardest to improve?',
  'What are your expectations for the rest of the season?',
  'Who has been your toughest teammate or opponent to face?',
  'How would you describe the locker-room culture?',
  'What makes this squad different from others you have played with?',
  'What would you like teammates and supporters to know about you?',
  'Which teammate would you trust to take a last-minute penalty, and why?',
  'If your playing style had a headline, what would it say?',
]);

const AWARD_DEFINITIONS = Object.freeze([
  { key: 'player_of_the_season', label: 'Player of the Season', metric: s => s.goals * 4 + s.assists * 3 + s.motm * 5 + s.appearances },
  { key: 'golden_boot', label: 'Golden Boot', metric: s => s.goals },
  { key: 'playmaker', label: 'Playmaker', metric: s => s.assists * 3 + s.goals },
  { key: 'goalkeeper', label: 'Goalkeeper of the Season', metric: s => s.saves + s.cleanSheets * 8 - s.goalsConceded * 0.25, eligible: s => s.saves > 0 || s.cleanSheets > 0 },
  { key: 'big_game_player', label: 'Big Game Player', metric: s => s.motm * 5 + s.goals * 2 + s.assists * 2 },
]);

function stableId(prefix, values) {
  return prefix + '-' + crypto.createHash('sha256').update(values.join('|')).digest('hex').slice(0, 16);
}

function number(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function normalizePlayerStat(value = {}) {
  return {
    playerId: String(value.playerId || value.userId || value.playerName || '').trim(),
    playerName: String(value.playerName || value.name || 'Unknown Player').trim(),
    appearance: value.appearance === false ? 0 : number(value.appearances || value.appearance || 1),
    goals: number(value.goals),
    assists: number(value.assists),
    saves: number(value.saves),
    goalsConceded: number(value.goalsConceded),
    cleanSheets: number(value.cleanSheets),
    yellowCards: number(value.yellowCards),
    redCards: number(value.redCards),
    motm: number(value.motm || value.playerOfTheMatch),
  };
}

function normalizeMatchRecord(value, options = {}) {
  const teamKey = String(value.teamKey || '').trim();
  if (!['birmingham', 'crownfc'].includes(teamKey)) throw new Error('Match record team must be Birmingham City or CrownFC.');
  const playedAt = new Date(value.playedAt || value.matchDate || Date.now()).toISOString();
  const opponent = String(value.opponent || '').trim();
  const score = String(value.score || '').trim();
  const competition = String(value.competition || value.competitionType || '').trim();
  if (!opponent || !score || !competition) throw new Error('Match records require opponent, score and competition.');
  const sourceMessageId = String(value.sourceMessageId || '').trim();
  return {
    ...value,
    id: value.id || stableId('match', [teamKey, playedAt, opponent, score, sourceMessageId]),
    teamKey,
    season: String(value.season || options.season || 'FC27').trim(),
    playedAt,
    opponent,
    score,
    competition,
    players: (value.players || []).map(normalizePlayerStat),
    sourceMessageId,
    verified: value.verified !== false,
    testMode: Boolean(options.testMode),
  };
}

function calculateSeasonTotals(records) {
  const players = new Map();
  for (const record of records.filter(item => item.verified !== false)) {
    for (const stat of record.players || []) {
      const normalized = normalizePlayerStat(stat);
      const key = normalized.playerId || normalized.playerName.toLowerCase();
      const current = players.get(key) || {
        playerId: normalized.playerId,
        playerName: normalized.playerName,
        appearances: 0,
        goals: 0,
        assists: 0,
        saves: 0,
        goalsConceded: 0,
        cleanSheets: 0,
        yellowCards: 0,
        redCards: 0,
        motm: 0,
      };
      current.appearances += normalized.appearance;
      for (const field of ['goals', 'assists', 'saves', 'goalsConceded', 'cleanSheets', 'yellowCards', 'redCards', 'motm']) {
        current[field] += normalized[field];
      }
      players.set(key, current);
    }
  }
  return [...players.values()].sort((a, b) =>
    b.goals - a.goals || b.assists - a.assists || b.motm - a.motm || a.playerName.localeCompare(b.playerName)
  );
}

function parseScore(score) {
  const values = String(score || '').match(/\d+/g);
  if (!values || values.length < 2) return null;
  return { goalsFor: Number(values[0]), goalsAgainst: Number(values[1]) };
}

function calculateTeamTotals(records) {
  const totals = { played: 0, wins: 0, draws: 0, losses: 0, goalsFor: 0, goalsAgainst: 0, goalDifference: 0, cleanSheets: 0, form: [] };
  for (const record of records.filter(item => item.verified !== false)) {
    const parsed = parseScore(record.score);
    const suppliedResult = String(record.result || '').trim().toUpperCase();
    const result = ['W', 'D', 'L'].includes(suppliedResult)
      ? suppliedResult
      : parsed ? (parsed.goalsFor > parsed.goalsAgainst ? 'W' : parsed.goalsFor < parsed.goalsAgainst ? 'L' : 'D') : '';
    totals.played += 1;
    if (result === 'W') totals.wins += 1;
    if (result === 'D') totals.draws += 1;
    if (result === 'L') totals.losses += 1;
    if (parsed) {
      totals.goalsFor += parsed.goalsFor;
      totals.goalsAgainst += parsed.goalsAgainst;
      if (parsed.goalsAgainst === 0) totals.cleanSheets += 1;
    }
    totals.form.push(result || '?');
  }
  totals.goalDifference = totals.goalsFor - totals.goalsAgainst;
  totals.form = totals.form.slice(-5);
  return totals;
}

function buildAwardShortlists(records, limit = 3) {
  const totals = calculateSeasonTotals(records);
  return AWARD_DEFINITIONS.map(definition => {
    const candidates = totals
      .filter(player => !definition.eligible || definition.eligible(player))
      .map(player => ({ ...player, evidenceScore: definition.metric(player) }))
      .sort((a, b) => b.evidenceScore - a.evidenceScore || a.playerName.localeCompare(b.playerName))
      .slice(0, limit)
      .map(player => ({
        playerId: player.playerId,
        playerName: player.playerName,
        evidence: {
          appearances: player.appearances,
          goals: player.goals,
          assists: player.assists,
          saves: player.saves,
          cleanSheets: player.cleanSheets,
          motm: player.motm,
        },
      }));
    return { awardKey: definition.key, award: definition.label, candidates };
  });
}

function seededShuffle(items, seed) {
  const values = [...items];
  let state = crypto.createHash('sha256').update(String(seed)).digest().readUInt32BE(0);
  for (let index = values.length - 1; index > 0; index -= 1) {
    state = (state * 1664525 + 1013904223) >>> 0;
    const swap = state % (index + 1);
    [values[index], values[swap]] = [values[swap], values[index]];
  }
  return values;
}

function spotlightQuestionSet(seed, count = 5) {
  return seededShuffle(SPOTLIGHT_QUESTIONS, seed).slice(0, Math.max(4, Math.min(5, count)));
}

function selectSpotlightCandidate(candidates, previousSelections, seed) {
  const used = new Set(previousSelections.map(item => String(item.playerId || item.userId || '').trim()).filter(Boolean));
  const eligible = candidates.filter(item => !item.bot && !used.has(String(item.playerId || item.userId || item.id)));
  if (!eligible.length) return { exhausted: true, selected: null };
  return { exhausted: false, selected: seededShuffle(eligible, seed)[0] };
}

function archiveCandidates(posts, now = new Date(), ageDays = 30) {
  const cutoff = now.getTime() - ageDays * 24 * 60 * 60 * 1000;
  return posts.filter(post =>
    post.managedBy === 'rt-media' &&
    post.state === 'published' &&
    !post.archivedAt &&
    new Date(post.publishedAt).getTime() <= cutoff
  );
}

function easternDateParts(value = new Date(), timezone = ORGANIZATION.timezone) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    weekday: 'short',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(value).reduce((result, item) => ({ ...result, [item.type]: item.value }), {});
  return {
    weekday: parts.weekday,
    dateKey: `${parts.year}-${parts.month}-${parts.day}`,
    hour: Number(parts.hour),
    minute: Number(parts.minute),
  };
}

function dueRecurringJobs(value = new Date(), timezone = ORGANIZATION.timezone) {
  const time = easternDateParts(value, timezone);
  const jobs = [];
  if (time.weekday === 'Thu' && time.hour >= 12) jobs.push({ name: 'spotlight-selection', key: `${time.dateKey}:spotlight-selection` });
  if (time.weekday === 'Fri' && time.hour >= 18) jobs.push({ name: 'weekly-recap-draft', key: `${time.dateKey}:weekly-recap-draft` });
  if (time.weekday === 'Sat' && time.hour >= 10) jobs.push({ name: 'spotlight-publish-draft', key: `${time.dateKey}:spotlight-publish-draft` });
  jobs.push({ name: 'media-archive-check', key: `${time.dateKey}:media-archive-check` });
  return jobs;
}

module.exports = {
  ORGANIZATION,
  REPORTERS,
  SPOTLIGHT_QUESTIONS,
  normalizeMatchRecord,
  calculateSeasonTotals,
  calculateTeamTotals,
  buildAwardShortlists,
  spotlightQuestionSet,
  selectSpotlightCandidate,
  archiveCandidates,
  easternDateParts,
  dueRecurringJobs,
  stableId,
};
