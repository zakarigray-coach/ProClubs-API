require('dotenv').config();
const fs = require('fs');
const path = require('path');
const { StateStore } = require('./stateStore');

const CLEANUP_KEY = 'storyCleanup:2026-09-29-v1';
const DATA_DIRECTORY = process.env.RT_DATA_DIR || (process.env.RAILWAY_ENVIRONMENT ? '/data' : path.join(__dirname, '.data'));
const STATE_PATH = path.join(DATA_DIRECTORY, 'rt-football-media-state.json');
const store = new StateStore(STATE_PATH);

function countBy(records, selector) {
  const counts = {};
  for (const record of records) {
    const key = String(selector(record) || 'unknown');
    counts[key] = (counts[key] || 0) + 1;
  }
  return Object.fromEntries(Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])));
}

function recordTime(record) {
  const value = record.updatedAt || record.createdAt || record.publishedAt || record.packageForwardedAt;
  const parsed = Date.parse(value || '');
  return Number.isFinite(parsed) ? parsed : 0;
}

function isExpired(timestamp, now) {
  const value = Number(timestamp);
  return Number.isFinite(value) && value > 0 && value < now;
}

function auditAndClean() {
  const existing = store.getMetadata(CLEANUP_KEY);
  if (existing) {
    console.log('RT story cleanup already completed:', JSON.stringify(existing));
    return existing;
  }

  const now = Date.now();
  const DAY = 24 * 60 * 60 * 1000;
  const records = store.listStories();
  const before = {
    total: records.length,
    byState: countBy(records, record => record.state),
    byType: countBy(records, record => record.type),
    quickSign: records.filter(record => record.quickSign).length,
  };

  const activeSquadStoryIds = new Set();
  for (const teamKey of ['birmingham', 'crownfc']) {
    for (const assignment of store.listSquadNumbers(teamKey)) {
      if (assignment.storyId) activeSquadStoryIds.add(String(assignment.storyId));
    }
  }

  const deletions = [];
  const kept = [];

  for (const record of records) {
    const state = String(record.state || 'unknown');
    const ageMs = Math.max(0, now - recordTime(record));
    let reason = '';

    // Current /sign and /sign-batch packages remain available to /signing-status,
    // player spotlights, award media, and future identity references.
    if (record.quickSign) {
      kept.push({ id: record.id, reason: 'current_quick_sign_package' });
      continue;
    }

    // Preserve the signing story for any player who is still tied to an active
    // squad-number assignment. Older media may use that stored player image.
    if (activeSquadStoryIds.has(String(record.id))) {
      kept.push({ id: record.id, reason: 'active_squad_reference' });
      continue;
    }

    if (['published', 'cancelled', 'failed', 'approval_expired'].includes(state)) {
      reason = `terminal_${state}`;
    } else if (state === 'package_forwarded') {
      reason = 'completed_legacy_package';
    } else if (['selecting', 'selecting_matches', 'collecting_facts'].includes(state)) {
      if (isExpired(record.selectionExpiresAt, now) || ageMs > 2 * DAY) reason = 'expired_selection_workflow';
    } else if (state === 'draft_ready') {
      if (isExpired(record.approvalExpiresAt, now) || ageMs > 7 * DAY) reason = 'expired_owner_approval';
    } else if (['waiting_for_quote', 'waiting_for_package'].includes(state)) {
      if (isExpired(record.quoteExpiresAt, now) || isExpired(record.selectionExpiresAt, now) || ageMs > 7 * DAY) {
        reason = 'stale_legacy_collection';
      }
    } else if (state === 'quote_unavailable') {
      if (ageMs > 2 * DAY) reason = 'stale_quote_exception';
    } else if (state === 'publishing') {
      if (ageMs > 6 * 60 * 60 * 1000) reason = 'stale_publish_attempt';
    } else if (state === 'published_partial') {
      if (ageMs > 14 * DAY) reason = 'stale_partial_publish';
    } else if (ageMs > 30 * DAY) {
      reason = 'unknown_or_obsolete_over_30_days';
    }

    if (reason) deletions.push({ id: record.id, state, type: record.type || 'unknown', reason });
    else kept.push({ id: record.id, reason: 'still_actionable_or_recent' });
  }

  if (deletions.length && fs.existsSync(STATE_PATH)) {
    const backupPath = path.join(DATA_DIRECTORY, `rt-football-media-state.pre-cleanup-${Date.now()}.json`);
    fs.copyFileSync(STATE_PATH, backupPath);
    console.log('RT story cleanup backup created:', backupPath);
  }

  for (const item of deletions) delete store.state.stories[item.id];

  const remaining = Object.values(store.state.stories);
  const report = {
    version: CLEANUP_KEY,
    completedAt: new Date().toISOString(),
    before,
    deleted: deletions.length,
    kept: remaining.length,
    deletedByReason: countBy(deletions, item => item.reason),
    deletedByState: countBy(deletions, item => item.state),
    afterByState: countBy(remaining, record => record.state),
    activeSquadReferencesProtected: activeSquadStoryIds.size,
    quickSignPackagesProtected: records.filter(record => record.quickSign).length,
  };

  store.state.metadata[CLEANUP_KEY] = report;
  store.persist();

  console.log('RT STORY CLEANUP AUDIT:', JSON.stringify(report));
  return report;
}

try {
  auditAndClean();
} catch (error) {
  console.error('RT story cleanup failed:', error.stack || error.message);
  process.exitCode = 1;
}
