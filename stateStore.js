const fs = require('fs');
const path = require('path');

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

class StateStore {
  constructor(filePath) {
    this.filePath = filePath;
    this.state = { stories: {}, processedMessages: {}, squadNumbers: {}, metadata: {} };
    this.load();
  }

  load() {
    try {
      if (!fs.existsSync(this.filePath)) return;
      const parsed = JSON.parse(fs.readFileSync(this.filePath, 'utf8'));
      this.state.stories = parsed.stories || {};
      this.state.processedMessages = parsed.processedMessages || {};
      this.state.squadNumbers = parsed.squadNumbers || {};
      this.state.metadata = parsed.metadata || {};
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
