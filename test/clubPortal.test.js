const test = require('node:test');
const assert = require('node:assert/strict');
const express = require('express');
const { mountClubPortal, encodeToken, decodeToken, safeReturnTo } = require('../clubPortal');

test('signed sessions reject tampering and expired tokens', () => {
  const secret = 'local-test-secret';
  const valid = encodeToken({ id: '123456789012345678', exp: Math.floor(Date.now() / 1000) + 60 }, secret);
  assert.equal(decodeToken(valid, secret).id, '123456789012345678');
  assert.equal(decodeToken(valid + 'x', secret), null);
  assert.equal(decodeToken(encodeToken({ id: '123', exp: 1 }, secret), secret), null);
  assert.equal(safeReturnTo('//evil.example'), '/clubs');
  assert.equal(safeReturnTo('/birmingham/members'), '/birmingham/members');
});

test('member pages enforce live club roles, including revocation and both-club access', async () => {
  const previous = Object.fromEntries(['DISCORD_GUILD_ID', 'DISCORD_TOKEN', 'CLUB_SITE_SESSION_SECRET',
    'BIRMINGHAM_ROLE_ID', 'MLPC_ROLE_ID', 'BOT_OWNER_ID'].map(key => [key, process.env[key]]));
  Object.assign(process.env, { DISCORD_GUILD_ID: '100000000000000001', DISCORD_TOKEN: 'bot-test',
    CLUB_SITE_SESSION_SECRET: 'test-secret', BIRMINGHAM_ROLE_ID: 'role-b',
    MLPC_ROLE_ID: 'role-c', BOT_OWNER_ID: '999999999999999999' });
  const roles = new Set(['role-b']);
  const member = { displayName: 'Player', user: { bot: false },
    roles: { cache: { has: role => roles.has(role) } },
    displayAvatarURL: () => 'https://example.com/avatar.png' };
  const guild = { members: { fetch: async options => options ? member : new Map([['one', member]]) } };
  const client = { isReady: () => true, guilds: { fetch: async () => guild } };
  const app = express();
  mountClubPortal(app, { getClient: () => client });
  const server = app.listen(0);
  try {
    const url = 'http://127.0.0.1:' + server.address().port;
    const cookie = 'cc_session=' + encodeToken({
      id: '123456789012345678', exp: Math.floor(Date.now() / 1000) + 300,
    }, process.env.CLUB_SITE_SESSION_SECRET);
    const page = path => fetch(url + path, { headers: { Cookie: cookie } });
    assert.equal((await page('/birmingham/members')).status, 200);
    assert.equal((await page('/crownfc/members')).status, 403);
    roles.add('role-c');
    assert.equal((await page('/crownfc/members')).status, 200);
    roles.delete('role-b');
    assert.equal((await page('/birmingham/members')).status, 403);
  } finally {
    server.close();
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
});
