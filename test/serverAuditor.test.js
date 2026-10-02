const test = require('node:test');
const assert = require('node:assert/strict');
const { Collection, PermissionsBitField, PermissionFlagsBits: P, ChannelType: C } = require('discord.js');
const { createServerAuditor, inspectServer, buildCommands, parsePermissions, policyFromEnv } = require('../serverAuditor');

function fixture() {
  let time = 10000000000;
  const metadata = new Map();
  const writes = [];
  const perms = names => new PermissionsBitField(names.map(name => P[name]));
  const role = (id, name, position, permissions = []) => ({ id, name, rawPosition: position, position,
    permissions: perms(permissions), managed: false, members: new Collection(),
    comparePositionTo(other) { return this.position - other.position; },
    async setPermissions(next) { writes.push('role'); this.permissions = new PermissionsBitField(next); },
  });
  const everyone = role('guild', '@everyone', 0);
  const player = role('player', 'Birmingham Players', 1);
  const crown = role('crown', 'CrownFC Players', 2);
  const botRole = role('bot-role', 'RT Bot', 4, ['ManageRoles', 'ManageChannels', 'ViewChannel', 'ReadMessageHistory', 'SendMessages']);
  const bot = { id: 'bot', user: { bot: true }, permissions: botRole.permissions,
    roles: { highest: botRole, cache: new Collection([[botRole.id, botRole]]) } };
  const channel = (id, name, type = C.GuildText, parentId = null) => ({
    id, name, type, parentId, rawPosition: 0, topic: '', permissionsLocked: true,
    permissionOverwrites: { cache: new Collection(), async edit(id, next) {
      writes.push('overwrite'); this.cache.set(id, { id, type: 0,
        allow: perms(Object.keys(next).filter(n => next[n] === true)),
        deny: perms(Object.keys(next).filter(n => next[n] === false)) });
    } },
    isThread() { return false; },
    permissionsFor(subject) { return subject === bot ? bot.permissions : perms(['ViewChannel']); },
    messages: { async fetch() { return new Collection(); } },
    async setName(name) { writes.push('rename'); this.name = name; },
    async setTopic(topic) { writes.push('topic'); this.topic = topic; },
    async setPosition(position) { writes.push('position'); this.rawPosition = position; },
    async setParent(parent) { writes.push('move'); this.parentId = parent; },
  });
  const general = channel('general', 'general');
  const welcome = channel('welcome', 'WELCOME', C.GuildCategory);
  const birmingham = channel('birmingham', 'Birmingham City', C.GuildCategory);
  const crownCategory = channel('crown-category', 'CrownFC', C.GuildCategory);
  const practice = channel('practice', 'ml1-practice', C.GuildText, birmingham.id);
  const guild = { id: 'guild', name: 'Castle & Crown', ownerId: 'owner', async fetch() { return this; },
    channels: { cache: new Collection([general, welcome, birmingham, crownCategory, practice].map(c => [c.id, c])), async fetch(id) { return id ? this.cache.get(id) : this.cache; } },
    roles: { cache: new Collection([everyone, player, crown, botRole].map(r => [r.id, r])), everyone, async fetch(id) { return id ? this.cache.get(id) : this.cache; } },
    members: { cache: new Collection([[bot.id, bot]]), async fetchMe() { return bot; } },
    async fetchOnboarding() { return { enabled: true, defaultChannels: new Collection(), prompts: new Collection() }; },
  };
  const store = { getMetadata(key) { return metadata.has(key) ? structuredClone(metadata.get(key)) : undefined; },
    setMetadata(key, value) { metadata.set(key, structuredClone(value)); },
    addManagementLog(entry) { metadata.set('lastLog', entry); }, listMetadata() { return []; }, listMediaPosts() { return []; } };
  const policy = policyFromEnv({ BIRMINGHAM_ROLE_ID: 'player', MLPC_ROLE_ID: 'crown',
    AUDITOR_BIRMINGHAM_CATEGORY_IDS: 'birmingham', AUDITOR_CROWNFC_CATEGORY_IDS: 'crown-category' });
  const auditor = createServerAuditor({ stateStore: store, policy, now: () => time });
  return { auditor, guild, store, metadata, writes, general, practice, policy, player, bot, perms,
    tick(ms) { time += ms; } };
}

test('all seven commands are guild-only, default-hidden, with explicit confirmation options', () => {
  const commands = buildCommands().map(c => c.toJSON());
  assert.equal(commands.length, 7);
  assert.equal(new Set(commands.map(c => c.name)).size, 7);
  for (const c of commands) { assert.equal(c.dm_permission, false); assert.equal(c.default_member_permissions, '0'); }
  assert.ok(commands.find(c => c.name === 'apply-changes').options.every(o => o.required));
});
test('audit and exact preview perform zero Discord writes', async () => {
  const f = fixture();
  const report = await inspectServer(f.guild, f.store, f.policy);
  assert.ok(report.findings.some(r => r.code === 'cross-club-access'));
  assert.match(report.coverage.members, /cached only/);
  assert.equal(report.coverage.mutations, 'none');
  const plan = await f.auditor.preview(f.guild, 'owner', [{ type: 'rename', channelId: 'general', value: 'community' }]);
  assert.equal(plan.changes[0].before.name, 'general');
  assert.deepEqual(f.writes, []);
});
test('ordinary administrators cannot create or apply an owner preview', async () => {
  const f = fixture();
  await assert.rejects(f.auditor.preview(f.guild, 'admin', [{ type: 'rename', channelId: 'general', value: 'community' }]), /owner/);
  const plan = await f.auditor.preview(f.guild, 'owner', [{ type: 'rename', channelId: 'general', value: 'community' }]);
  await assert.rejects(f.auditor.apply(f.guild, 'admin', plan.id, plan.confirmation), /owner/);
  assert.deepEqual(f.writes, []);
});
test('exact confirmation applies once, logs before/after intent, and cannot replay', async () => {
  const f = fixture();
  const plan = await f.auditor.preview(f.guild, 'owner', [{ type: 'rename', channelId: 'general', value: 'community' }]);
  await assert.rejects(f.auditor.apply(f.guild, 'owner', plan.id, 'yes'), /confirmation/);
  const journal = await f.auditor.apply(f.guild, 'owner', plan.id, plan.confirmation);
  assert.equal(journal.status, 'applied');
  assert.equal(journal.changes[0].before.name, 'general');
  assert.equal(f.general.name, 'community');
  assert.equal(journal.results[0].after.name, 'community');
  await assert.rejects(f.auditor.apply(f.guild, 'owner', plan.id, plan.confirmation), /consumed/);
  assert.deepEqual(f.writes, ['rename']);
});
test('expiry, server drift, cross-guild use and tampered actions reject without mutation', async () => {
  for (const mode of ['expiry', 'drift', 'guild', 'tamper']) {
    const f = fixture();
    const plan = await f.auditor.preview(f.guild, 'owner', [{ type: 'rename', channelId: 'general', value: 'community' }]);
    if (mode === 'expiry') f.tick(16 * 60000);
    if (mode === 'drift') f.player.permissions = f.perms(['Administrator']);
    if (mode === 'guild') f.guild.id = 'another';
    if (mode === 'tamper') { const altered = f.store.getMetadata(`serverAuditor:preview:${plan.id}`); altered.changes[0].action.value = 'hijacked'; f.store.setMetadata(`serverAuditor:preview:${plan.id}`, altered); }
    await assert.rejects(f.auditor.apply(f.guild, 'owner', plan.id, plan.confirmation));
    assert.deepEqual(f.writes, []);
  }
});
test('protected targets, deletion, cross-club moves and unknown permissions are rejected', async () => {
  const f = fixture();
  for (const action of [
    { type: 'delete', channelId: 'general' },
    { type: 'role-permissions', roleId: 'guild', permissions: [] },
    { type: 'role-permissions', roleId: 'bot-role', permissions: [] },
    { type: 'overwrite', channelId: 'general', roleId: 'player', allow: ['Administrator'], deny: [] },
    { type: 'move', channelId: 'practice', parentId: 'crown-category' },
  ]) await assert.rejects(f.auditor.preview(f.guild, 'owner', [action]));
  assert.throws(() => parsePermissions('view_channel'), /exact Discord/);
  assert.deepEqual(f.writes, []);
});
test('overwrite replacement preserves unrelated overwrites', async () => {
  const f = fixture();
  f.general.permissionOverwrites.cache.set('crown', { id: 'crown', type: 0, allow: f.perms(['ViewChannel']), deny: f.perms([]) });
  const plan = await f.auditor.preview(f.guild, 'owner', [{ type: 'overwrite', channelId: 'general', roleId: 'player', allow: ['ViewChannel'], deny: ['SendMessages'] }]);
  await f.auditor.apply(f.guild, 'owner', plan.id, plan.confirmation);
  assert.ok(f.general.permissionOverwrites.cache.get('crown').allow.has(P.ViewChannel));
  assert.ok(f.general.permissionOverwrites.cache.get('player').deny.has(P.SendMessages));
});
test('first failed write stops the batch and consumes preview; no automatic rollback', async () => {
  const f = fixture();
  f.general.setTopic = async () => { throw new Error('Discord unavailable'); };
  const plan = await f.auditor.preview(f.guild, 'owner', [
    { type: 'rename', channelId: 'general', value: 'community' },
    { type: 'topic', channelId: 'general', value: 'Purpose' },
    { type: 'position', channelId: 'general', value: 1 },
  ]);
  const journal = await f.auditor.apply(f.guild, 'owner', plan.id, plan.confirmation);
  assert.equal(journal.status, 'failed');
  assert.deepEqual(journal.results.map(r => r.status), ['applied', 'failed']);
  assert.deepEqual(f.writes, ['rename']);
  await assert.rejects(f.auditor.apply(f.guild, 'owner', plan.id, plan.confirmation), /consumed/);
});
test('concurrent applies are serialized by guild', async () => {
  const f = fixture();
  let release;
  f.general.setName = async name => { await new Promise(resolve => { release = resolve; }); f.writes.push('rename'); f.general.name = name; };
  const plan = await f.auditor.preview(f.guild, 'owner', [{ type: 'rename', channelId: 'general', value: 'community' }]);
  const running = f.auditor.apply(f.guild, 'owner', plan.id, plan.confirmation);
  await new Promise(resolve => setImmediate(resolve));
  await assert.rejects(f.auditor.apply(f.guild, 'owner', plan.id, plan.confirmation), /in progress/);
  release(); await running;
  assert.deepEqual(f.writes, ['rename']);
});
test('persist failure before write leaves Discord untouched', async () => {
  const f = fixture();
  const plan = await f.auditor.preview(f.guild, 'owner', [{ type: 'rename', channelId: 'general', value: 'community' }]);
  f.store.setMetadata = () => { throw new Error('Disk full'); };
  await assert.rejects(f.auditor.apply(f.guild, 'owner', plan.id, plan.confirmation), /Disk full/);
  assert.deepEqual(f.writes, []);
});
test('after-state fetch failure is logged as an applied write and stops the batch', async () => {
  const f = fixture();
  const plan = await f.auditor.preview(f.guild, 'owner', [
    { type: 'rename', channelId: 'general', value: 'community' },
    { type: 'topic', channelId: 'general', value: 'Purpose' },
  ]);
  f.guild.channels.fetch = async function(id) { if (id) throw new Error('Read unavailable'); return this.cache; };
  const journal = await f.auditor.apply(f.guild, 'owner', plan.id, plan.confirmation);
  assert.equal(journal.status, 'failed');
  assert.equal(journal.results[0].status, 'applied');
  assert.match(journal.results[0].afterUnavailable, /verification fetch failed/);
  assert.deepEqual(f.writes, ['rename']);
});
test('restarting the auditor retains consumed approval in the existing store', async () => {
  const f = fixture();
  const plan = await f.auditor.preview(f.guild, 'owner', [{ type: 'rename', channelId: 'general', value: 'community' }]);
  await f.auditor.apply(f.guild, 'owner', plan.id, plan.confirmation);
  const restarted = createServerAuditor({ stateStore: f.store, policy: f.policy });
  await assert.rejects(restarted.apply(f.guild, 'owner', plan.id, plan.confirmation), /consumed/);
  assert.deepEqual(f.writes, ['rename']);
});
test('protected categories protect their children and cannot be move destinations', async () => {
  const f = fixture();
  f.policy.protectedChannelIds.push('birmingham');
  await assert.rejects(f.auditor.preview(f.guild, 'owner', [{ type: 'rename', channelId: 'practice', value: 'new-practice' }]), /Protected/);
  await assert.rejects(f.auditor.preview(f.guild, 'owner', [{ type: 'move', channelId: 'general', parentId: 'birmingham' }]), /protected/);
  assert.deepEqual(f.writes, []);
});
test('native onboarding role assignment and guild-scoped media are audited', async () => {
  const f = fixture();
  f.guild.fetchOnboarding = async () => ({ enabled: true, defaultChannels: new Collection(), prompts: new Collection([
    ['p', { id: 'p', title: 'Choose club', options: new Collection([['o', { id: 'o', roles: new Collection([['player', f.player]]), channels: new Collection() }]]) }],
  ]) });
  f.store.listMediaPosts = () => [
    { id: 'here', guildId: 'guild', channelId: 'general', managedBy: 'rt-media', state: 'published', publishedAt: '1970-01-01' },
    { id: 'elsewhere', guildId: 'other', channelId: 'general', managedBy: 'rt-media', state: 'published', publishedAt: '1970-01-01' },
  ];
  const report = await inspectServer(f.guild, f.store, f.policy);
  assert.ok(report.findings.some(f => f.code === 'self-assign-sensitive-role'));
  assert.deepEqual(report.mediaArchiveCandidates.map(p => p.id), ['here']);
  assert.deepEqual(f.writes, []);
});
