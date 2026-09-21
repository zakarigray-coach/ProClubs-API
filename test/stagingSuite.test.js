const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { StateStore } = require('../stateStore');
const { runPrivateDryRun } = require('../stagingSuite');

test('full 27-point private dry run passes and clears only TEST data', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'rt-staging-'));
  const store = new StateStore(path.join(directory, 'state.json'));
  store.putMatchRecord({ id: 'production-match', teamKey: 'birmingham', players: [] });
  const report = runPrivateDryRun(store);
  assert.equal(report.summary.total, 27);
  assert.equal(report.summary.failed, 0);
  assert.equal(report.summary.passed, 27);
  assert.equal(store.listMatchRecords({}, { testMode: true }).length, 0);
  assert.equal(store.listManagementLogs({ testMode: true }).length, 0);
  assert.equal(store.listMatchRecords().length, 1);
});
