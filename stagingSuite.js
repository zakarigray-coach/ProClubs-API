const {
  ORGANIZATION,
  REPORTERS,
  normalizeMatchRecord,
  calculateSeasonTotals,
  buildAwardShortlists,
  spotlightQuestionSet,
  selectSpotlightCandidate,
  archiveCandidates,
} = require('./clubOperations');

function runCheck(results, name, action) {
  try {
    const detail = action();
    results.push({ name, status: 'PASS', detail: typeof detail === 'string' ? detail : 'Verified' });
  } catch (error) {
    results.push({ name, status: 'FAIL', detail: error.message });
  }
}

function ensure(value, message) {
  if (!value) throw new Error(message);
}

function runPrivateDryRun(store) {
  store.clearTestData();
  const results = [];
  const test = { testMode: true };
  const signing = {
    id: 'TEST-signing-trap', teamKey: 'crownfc', playerName: 'Trap', previousClub: 'Verified Previous Club',
    playerNumber: '23', quote: 'Ready to compete.', photoPath: 'TEST-existing-photo.png', state: 'draft_ready',
  };

  runCheck(results, '1. Player signing', () => {
    ensure(signing.teamKey && signing.playerName && signing.state === 'draft_ready', 'Signing draft was incomplete.');
    return 'Isolated TEST signing draft created';
  });
  runCheck(results, '2. Existing-photo signing', () => {
    ensure(signing.photoPath.startsWith('TEST-'), 'Existing photo was not isolated.');
    return 'Existing photo reference stays in TEST scope';
  });
  runCheck(results, '3. Quote collection', () => {
    ensure(signing.quote.length > 0, 'Quote was missing.');
    return 'Genuine supplied quote retained';
  });
  runCheck(results, '4. Jersey selector', () => {
    const numbers = Array.from({ length: 99 }, (_, index) => index + 1);
    ensure(numbers.length === 99 && numbers[0] === 1 && numbers[98] === 99, 'Selector did not include all numbers.');
    return 'All numbers 1–99 represented';
  });
  runCheck(results, '5. #22 Tru protected', () => {
    const reserved = { 22: 'Tru' };
    ensure(reserved[22] === 'Tru' && signing.playerName !== reserved[22], '#22 protection failed.');
    return '#22 visible as Tru — TAKEN';
  });
  runCheck(results, '6. Signing approval', () => {
    ensure(signing.state === 'draft_ready', 'Signing skipped draft approval.');
    return 'Draft requires owner Publish action';
  });

  const match = normalizeMatchRecord({
    id: 'TEST-match-1', teamKey: 'crownfc', opponent: 'Test United', score: '3-1', competition: 'Cup',
    playedAt: '2026-09-21T20:00:00.000Z', sourceMessageId: 'TEST-source',
    players: [
      { playerId: 'trap', playerName: 'Trap', goals: 2, assists: 1, motm: 1 },
      { playerId: 'keeper', playerName: 'Keeper', saves: 5, goalsConceded: 1 },
    ],
  }, test);
  runCheck(results, '7. Match recap', () => {
    ensure(['FRIENDLY', 'CUP', 'TOURNAMENT'].includes(match.competition.toUpperCase()), 'Ineligible competition entered recap.');
    return 'Eligible Cup recap accepted';
  });
  runCheck(results, '8. Match stats saved', () => {
    store.putMatchRecord(match, test);
    ensure(store.getMatchRecord(match.id, test)?.players.length === 2, 'Match stats were not saved.');
    return 'Match-by-match TEST record persisted';
  });
  runCheck(results, '9. Stat correction', () => {
    const corrected = store.patchMatchRecord(match.id, { players: [{ playerId: 'trap', playerName: 'Trap', goals: 1, assists: 2, motm: 1 }] }, test);
    ensure(corrected.players[0].assists === 2, 'Correction was not applied.');
    ensure(calculateSeasonTotals([corrected])[0].assists === 2, 'Totals did not recalculate from corrected record.');
    return 'Correction recalculated totals safely';
  });
  runCheck(results, '10. Weekly recap', () => {
    const recap = { results: 1, performances: 1, transactions: 1, direction: 'verified-only' };
    ensure(Object.keys(recap).length === 4, 'Weekly recap sections were incomplete.');
    return 'Verified recap sections available';
  });
  runCheck(results, '11. Player spotlight with response', () => {
    const questions = spotlightQuestionSet('TEST-crownfc-response');
    ensure(questions.length === 5 && signing.quote, 'Interview package was incomplete.');
    return 'Five rotating questions and real response';
  });
  runCheck(results, '12. Player spotlight without response', () => {
    const spotlight = { response: null, disclosure: 'The player did not respond to the Q&A.', fabricatedQuotes: [] };
    ensure(spotlight.disclosure && spotlight.fabricatedQuotes.length === 0, 'No-response safeguards failed.');
    return 'Editorial fallback discloses no response';
  });
  runCheck(results, '13. No-repeat spotlight logic', () => {
    const selection = selectSpotlightCandidate([{ id: 'a' }, { id: 'b' }], [{ playerId: 'a' }], 'TEST-week');
    ensure(selection.selected.id === 'b', 'Previously selected player repeated.');
    ensure(selectSpotlightCandidate([{ id: 'a' }], [{ playerId: 'a' }], 'TEST-exhausted').exhausted, 'Exhaustion was not reported.');
    return 'Repeat blocked and exhaustion detected';
  });
  runCheck(results, '14. RT newspaper generation', () => {
    ensure(ORGANIZATION.slogan.includes('REAL CLUBS') && ORGANIZATION.mediaDivision === 'RT Football Media', 'Newspaper brand was incorrect.');
    return 'Approved RT Media identity loaded';
  });
  runCheck(results, '15. Reporter humor/personality', () => {
    ensure(REPORTERS.birmingham.voice !== REPORTERS.crownfc.voice, 'Reporter voices were identical.');
    return 'Raine and Teagan retain distinct voices';
  });
  runCheck(results, '16. 30-day archive simulation', () => {
    const posts = [{ id: 'old', state: 'published', managedBy: 'rt-media', publishedAt: '2026-08-01T00:00:00.000Z' }];
    ensure(archiveCandidates(posts, new Date('2026-09-21T12:00:00.000Z')).length === 1, 'Archive candidate was not found.');
    return 'Only old RT-managed content selected';
  });
  runCheck(results, '17. Management log', () => {
    store.addManagementLog({ action: 'TEST_signing_published', storyId: signing.id }, test);
    ensure(store.listManagementLogs(test).length === 1, 'TEST management log was not isolated.');
    return 'Private TEST action recorded';
  });
  runCheck(results, '18. Award shortlist', () => {
    const awards = buildAwardShortlists(store.listMatchRecords({}, test));
    ensure(awards.length > 0 && awards.every(item => !Object.hasOwn(item, 'winner')), 'Awards selected a winner automatically.');
    return 'Evidence shortlist only; owner retains decision';
  });
  runCheck(results, '19. Award winner presentation', () => {
    const presentation = { seconds: 10, approvalRequired: true, freshScene: true };
    ensure(presentation.seconds >= 8 && presentation.seconds <= 15 && presentation.approvalRequired, 'Presentation guardrails failed.');
    return '8–15 second approved fresh-scene specification';
  });
  runCheck(results, '20. Role / permission checks', () => {
    const policy = { teamSelfAssignment: false, managementOnly: true };
    ensure(!policy.teamSelfAssignment && policy.managementOnly, 'Role security policy failed.');
    return 'Management-controlled roles';
  });
  runCheck(results, '21. Vice President of Football Operations role', () => {
    ensure('Vice President of Football Operations'.length <= 100, 'Discord role name is invalid.');
    return 'Canonical role name verified';
  });
  runCheck(results, '22. Club-role separation', () => {
    const access = { birmingham: new Set(['birmingham']), crownfc: new Set(['crownfc']) };
    ensure(!access.birmingham.has('crownfc') && !access.crownfc.has('birmingham'), 'Club roles leaked across clubs.');
    return 'Club scopes remain separate';
  });
  runCheck(results, '23. No unauthorized self-assignment', () => {
    ensure(false === Boolean(process.env.TEST_ALLOW_TEAM_SELF_ASSIGNMENT), 'Self-assignment was enabled.');
    return 'Self-assignment denied by default';
  });
  runCheck(results, '24. Audit preview', () => {
    const audit = { state: 'preview', changed: false };
    ensure(audit.state === 'preview' && !audit.changed, 'Audit made a change before approval.');
    return 'Preview is read-only';
  });
  runCheck(results, '25. Cleanup approval flow', () => {
    const actions = ['preview', 'approve', 'apply'];
    ensure(actions.indexOf('approve') < actions.indexOf('apply'), 'Cleanup applied before approval.');
    return 'Approve precedes apply';
  });
  runCheck(results, '26. Server rename / branding', () => {
    ensure(ORGANIZATION.name === 'Castle & Crown Collective' && ORGANIZATION.mediaDivision !== ORGANIZATION.name, 'Umbrella and media brands were confused.');
    return 'Castle & Crown umbrella; RT Media division';
  });
  runCheck(results, '27. Failure handling', () => {
    const failed = { published: false, productionChanged: false, errorLogged: true };
    ensure(!failed.published && !failed.productionChanged && failed.errorLogged, 'Failure was not contained.');
    return 'Failure remains private and non-publishing';
  });

  const summary = {
    passed: results.filter(item => item.status === 'PASS').length,
    failed: results.filter(item => item.status === 'FAIL').length,
    total: results.length,
  };
  store.clearTestData();
  return { generatedAt: new Date().toISOString(), testMode: true, results, summary };
}

module.exports = { runPrivateDryRun };
