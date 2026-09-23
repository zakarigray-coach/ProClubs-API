const fs = require('fs');
const path = require('path');

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

class StateStore {
  constructor(filePath) {
    this.filePath = filePath;
    this.state = this.emptyState();
    this.load();
  }

  emptyState() {
    return {
      schemaVersion: 2,
      stories: {},
      processedMessages: {},
      squadNumbers: {},
      metadata: {},
      operations: {
        production: this.emptyOperationsScope(),
        test: this.emptyOperationsScope(),
      },
    };
  }

  emptyOperationsScope() {
    return {
      matchRecords: {},
      spotlightSelections: [],
      managementLogs: [],
      scheduleRuns: {},
      mediaPosts: {},
      awardShortlists: {},
    };
  }

  ensureShape() {
    this.state.schemaVersion = 2;
    this.state.stories ||= {};
    this.state.processedMessages ||= {};
    this.state.squadNumbers ||= {};
    this.state.metadata ||= {};
    this.state.operations ||= {};
    for (const name of ['production', 'test']) {
      this.state.operations[name] ||= this.emptyOperationsScope();
      const scope = this.state.operations[name];
      scope.matchRecords ||= {};
      scope.spotlightSelections ||= [];
      scope.managementLogs ||= [];
      scope.scheduleRuns ||= {};
      scope.mediaPosts ||= {};
      scope.awardShortlists ||= {};
    }
  }

  operationsScope(options = {}) {
    this.ensureShape();
    return this.state.operations[options.testMode ? 'test' : 'production'];
  }

  load() {
    try {
      if (!fs.existsSync(this.filePath)) return;
      const parsed = JSON.parse(fs.readFileSync(this.filePath, 'utf8'));
      this.state.stories = parsed.stories || {};
      this.state.processedMessages = parsed.processedMessages || {};
      this.state.squadNumbers = parsed.squadNumbers || {};
      this.state.metadata = parsed.metadata || {};
      this.state.schemaVersion = parsed.schemaVersion || 1;
      this.state.operations = parsed.operations || {};
      this.ensureShape();
    } catch (error) {
      console.error('Could not load RT Football Media state:', error.message);
    }
  }

  persist() {
    const directory = path.dirname(this.filePath);
    fs.mkdirSync(directory, { recursive: true });
    const temporary = this.filePath + '.tmp';
    fs.writeFileSync(temporary, JSON.stringify(this.state, null, 2));
    fs.renameSync(temporary, this.filePath);
  }

  getStory(id) {
    const story = this.state.stories[id];
    return story ? clone(story) : null;
  }

  listStories() {
    return Object.values(this.state.stories).map(clone);
  }

  putStory(story) {
    const next = { ...story, updatedAt: new Date().toISOString() };
    this.state.stories[story.id] = clone(next);
    this.persist();
    return clone(next);
  }

  patchStory(id, values) {
    const current = this.state.stories[id];
    if (!current) return null;
    return this.putStory({ ...current, ...values, id });
  }

  deleteStory(id) {
    delete this.state.stories[id];
    this.persist();
  }

  getSquadNumber(teamKey, number) {
    const assignment = this.state.squadNumbers[teamKey] && this.state.squadNumbers[teamKey][String(number)];
    return assignment ? clone(assignment) : null;
  }

  assignSquadNumber(teamKey, number, assignment) {
    if (!this.state.squadNumbers[teamKey]) this.state.squadNumbers[teamKey] = {};
    this.state.squadNumbers[teamKey][String(number)] = clone({
      ...assignment,
      number: String(number),
      assignedAt: new Date().toISOString(),
    });
    this.persist();
    return this.getSquadNumber(teamKey, number);
  }

  listSquadNumbers(teamKey) {
    return Object.values(this.state.squadNumbers[teamKey] || {}).map(clone);
  }

  releaseSquadNumbersForPlayer(teamKey, playerName) {
    const assignments = this.state.squadNumbers[teamKey] || {};
    const target = String(playerName || '').trim().toLowerCase();
    const released = [];
    for (const [number, assignment] of Object.entries(assignments)) {
      if (String(assignment.playerName || '').trim().toLowerCase() !== target) continue;
      delete assignments[number];
      released.push(number);
    }
    if (released.length) this.persist();
    return released;
  }

  getMetadata(key) {
    return this.state.metadata[key] === undefined ? undefined : clone(this.state.metadata[key]);
  }

  setMetadata(key, value) {
    this.state.metadata[key] = clone(value);
    this.persist();
    return this.getMetadata(key);
  }

  listMetadata(prefix = '') {
    return Object.entries(this.state.metadata)
      .filter(([key]) => !prefix || key.startsWith(prefix))
      .map(([key, value]) => ({ key, value: clone(value) }));
  }

  putMatchRecord(record, options = {}) {
    const scope = this.operationsScope(options);
    if (!record || !record.id) throw new Error('A match record requires an id.');
    const next = {
      ...record,
      testMode: Boolean(options.testMode),
      updatedAt: new Date().toISOString(),
    };
    scope.matchRecords[record.id] = clone(next);
    this.persist();
    return clone(next);
  }

  patchMatchRecord(id, values, options = {}) {
    const scope = this.operationsScope(options);
    const current = scope.matchRecords[id];
    if (!current) return null;
    return this.putMatchRecord({ ...current, ...values, id }, options);
  }

  getMatchRecord(id, options = {}) {
    const value = this.operationsScope(options).matchRecords[id];
    return value ? clone(value) : null;
  }

  listMatchRecords(filters = {}, options = {}) {
    return Object.values(this.operationsScope(options).matchRecords)
      .filter(record => !filters.teamKey || record.teamKey === filters.teamKey)
      .filter(record => !filters.season || record.season === filters.season)
      .sort((a, b) => String(a.playedAt || a.matchDate || '').localeCompare(String(b.playedAt || b.matchDate || '')))
      .map(clone);
  }

  recordSpotlightSelection(selection, options = {}) {
    const scope = this.operationsScope(options);
    const next = {
      ...selection,
      testMode: Boolean(options.testMode),
      selectedAt: selection.selectedAt || new Date().toISOString(),
    };
    scope.spotlightSelections.push(clone(next));
    this.persist();
    return clone(next);
  }

  listSpotlightSelections(teamKey, options = {}) {
    return this.operationsScope(options).spotlightSelections
      .filter(item => !teamKey || item.teamKey === teamKey)
      .map(clone);
  }

  patchSpotlightSelection(id, values, options = {}) {
    const scope = this.operationsScope(options);
    const index = scope.spotlightSelections.findIndex(item => item.id === id);
    if (index < 0) return null;
    scope.spotlightSelections[index] = {
      ...scope.spotlightSelections[index],
      ...clone(values),
      id,
      updatedAt: new Date().toISOString(),
    };
    this.persist();
    return clone(scope.spotlightSelections[index]);
  }

  addManagementLog(entry, options = {}) {
    const scope = this.operationsScope(options);
    const next = {
      id: entry.id || `${Date.now()}-${Math.random().toString(16).slice(2, 10)}`,
      ...entry,
      testMode: Boolean(options.testMode),
      createdAt: entry.createdAt || new Date().toISOString(),
    };
    scope.managementLogs.push(clone(next));
    if (scope.managementLogs.length > 5000) scope.managementLogs.splice(0, scope.managementLogs.length - 5000);
    this.persist();
    return clone(next);
  }

  listManagementLogs(options = {}) {
    return this.operationsScope(options).managementLogs.map(clone);
  }

  claimScheduleRun(key, details = {}, options = {}) {
    const scope = this.operationsScope(options);
    if (scope.scheduleRuns[key]) return false;
    scope.scheduleRuns[key] = {
      ...details,
      key,
      testMode: Boolean(options.testMode),
      claimedAt: new Date().toISOString(),
    };
    this.persist();
    return true;
  }

  getScheduleRun(key, options = {}) {
    const value = this.operationsScope(options).scheduleRuns[key];
    return value ? clone(value) : null;
  }

  releaseScheduleRun(key, options = {}) {
    const scope = this.operationsScope(options);
    if (!scope.scheduleRuns[key]) return false;
    delete scope.scheduleRuns[key];
    this.persist();
    return true;
  }

  putMediaPost(post, options = {}) {
    const scope = this.operationsScope(options);
    if (!post || !post.id) throw new Error('A media post requires an id.');
    const next = { ...post, testMode: Boolean(options.testMode), updatedAt: new Date().toISOString() };
    scope.mediaPosts[post.id] = clone(next);
    this.persist();
    return clone(next);
  }

  patchMediaPost(id, values, options = {}) {
    const scope = this.operationsScope(options);
    if (!scope.mediaPosts[id]) return null;
    return this.putMediaPost({ ...scope.mediaPosts[id], ...values, id }, options);
  }

  listMediaPosts(options = {}) {
    return Object.values(this.operationsScope(options).mediaPosts).map(clone);
  }

  putAwardShortlist(shortlist, options = {}) {
    const scope = this.operationsScope(options);
    if (!shortlist || !shortlist.id) throw new Error('An award shortlist requires an id.');
    scope.awardShortlists[shortlist.id] = clone({
      ...shortlist,
      testMode: Boolean(options.testMode),
      updatedAt: new Date().toISOString(),
    });
    this.persist();
    return clone(scope.awardShortlists[shortlist.id]);
  }

  listAwardShortlists(options = {}) {
    return Object.values(this.operationsScope(options).awardShortlists).map(clone);
  }

  clearTestData() {
    this.ensureShape();
    this.state.operations.test = this.emptyOperationsScope();
    this.persist();
  }

  isProcessed(messageId) {
    return Boolean(this.state.processedMessages[messageId]);
  }

  markProcessed(messageId, status) {
    this.state.processedMessages[messageId] = {
      status: status || 'detected',
      updatedAt: new Date().toISOString(),
    };
    this.pruneProcessed();
    this.persist();
  }

  pruneProcessed(maxEntries = 2000) {
    const entries = Object.entries(this.state.processedMessages);
    if (entries.length <= maxEntries) return;
    entries
      .sort(([, a], [, b]) => String(a.updatedAt).localeCompare(String(b.updatedAt)))
      .slice(0, entries.length - maxEntries)
      .forEach(([id]) => delete this.state.processedMessages[id]);
  }
}

module.exports = { StateStore };
