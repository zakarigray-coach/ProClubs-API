const test = require('node:test');
const assert = require('node:assert/strict');
const { commands, COMMAND_NAMES } = require('../reporterBot');

test('registered command names are unique and match the dispatcher source of truth', () => {
  assert.equal(new Set(COMMAND_NAMES).size, COMMAND_NAMES.length);
  assert.deepEqual(commands.map(command=>command.name), COMMAND_NAMES);
});

test('temporary and obsolete command surfaces are not registered', () => {
  assert.equal(COMMAND_NAMES.includes('setup-match-centers'), false);
  assert.equal(COMMAND_NAMES.includes('signing-batch'), false);
});

test('production command set contains the repaired signing and schedule workflows', () => {
  for (const name of ['sign','sign-batch','import-mlpc-schedule','import-mpl-schedule','nextmatch','schedule','result','edit-match','cancel-match']) {
    assert.equal(COMMAND_NAMES.includes(name),true,name);
  }
});
