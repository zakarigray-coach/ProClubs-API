const crypto = require('node:crypto');
const {
  SlashCommandBuilder, PermissionFlagsBits: P, PermissionsBitField,
  ChannelType: C, MessageFlags, AttachmentBuilder,
} = require('discord.js');
const { archiveCandidates } = require('./clubOperations');

const COMMAND_NAMES = Object.freeze([
  'server-audit', 'permission-audit', 'media-audit', 'onboarding-audit',
  'cleanup-preview', 'server-map', 'apply-changes',
]);
const DANGEROUS = ['Administrator', 'ManageGuild', 'ManageRoles', 'ManageChannels',
  'ManageWebhooks', 'BanMembers', 'KickMembers', 'MentionEveryone'];
const TEXT = [C.GuildText, C.GuildAnnouncement, C.GuildForum, C.GuildMedia];
const TTL = 15 * 60 * 1000;
const MAX_ACTIONS = 20;
const MAX_HISTORY = 50;
const FLAGS = Object.keys(P);
const normalize = value => String(value || '').toLowerCase().replace(/^[^a-z0-9]+/, '')
  .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const hash = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
const values = collection => [...collection.values()];
const has = (permissions, flag) => Boolean(permissions?.has(P[flag]));
const overwriteData = channel => values(channel.permissionOverwrites.cache)
  .map(o => ({ id: o.id, type: o.type, allow: o.allow.bitfield.toString(), deny: o.deny.bitfield.toString() }))
  .sort((a, b) => a.id.localeCompare(b.id));
const channelData = channel => ({
  id: channel.id, name: channel.name, type: channel.type, parentId: channel.parentId,
  position: channel.rawPosition, topic: channel.topic ?? null, overwrites: overwriteData(channel),
});
const roleData = role => ({ id: role.id, name: role.name, position: role.rawPosition,
  permissions: role.permissions.bitfield.toString(), managed: role.managed });
function snapshot(guild) {
  return { guildId: guild.id, ownerId: guild.ownerId,
    channels: values(guild.channels.cache).filter(c => !c.isThread()).map(channelData).sort((a, b) => a.id.localeCompare(b.id)),
    roles: values(guild.roles.cache).map(roleData).sort((a, b) => a.id.localeCompare(b.id)) };
}

function buildCommands() {
  return COMMAND_NAMES.map(name => {
    const command = new SlashCommandBuilder().setName(name)
      .setDescription({
        'server-audit': 'Privately audit server structure, security and club operations',
        'permission-audit': 'Privately inspect hierarchy, effective access and overwrites',
        'media-audit': 'Review RT Football Media organization and archive candidates',
        'onboarding-audit': 'Review welcome, registration and verification workflows',
        'cleanup-preview': 'Preview one exact owner-requested change; never applies it',
        'server-map': 'Export categories, channel order, roles and access policy',
        'apply-changes': 'Apply an unexpired preview with its exact confirmation phrase',
      }[name]).setDMPermission(false).setDefaultMemberPermissions(0n);
    if (name === 'cleanup-preview') {
      command.addStringOption(o => o.setName('action').setDescription('Exact change to review').setRequired(true)
        .addChoices(...['rename', 'topic', 'move', 'position', 'overwrite', 'role-permissions']
          .map(value => ({ name: value, value }))));
      command.addChannelOption(o => o.setName('channel').setDescription('Target channel (except role-permissions)'));
      command.addRoleOption(o => o.setName('role').setDescription('Target role for permissions or overwrite'));
      command.addStringOption(o => o.setName('value').setDescription('New name/topic, position integer, or comma-separated permission names'));
      command.addChannelOption(o => o.setName('category').setDescription('Destination for move').addChannelTypes(C.GuildCategory));
      command.addStringOption(o => o.setName('allow').setDescription('Overwrite allow: comma-separated Discord permission names'));
      command.addStringOption(o => o.setName('deny').setDescription('Overwrite deny: comma-separated Discord permission names'));
    }
    if (name === 'apply-changes') {
      command.addStringOption(o => o.setName('preview_id').setDescription('ID from cleanup-preview').setRequired(true));
      command.addStringOption(o => o.setName('confirmation').setDescription('Exact APPLY phrase from the preview').setRequired(true));
    }
    if (['server-audit', 'media-audit', 'cleanup-preview'].includes(name)) {
      command.addIntegerOption(o => o.setName('inactive_days').setDescription('Inactivity review threshold (default 45)')
        .setMinValue(7).setMaxValue(365));
    }
    return command;
  });
}

function policyFromEnv(env = process.env) {
  const ids = name => String(env[name] || '').split(',').map(x => x.trim()).filter(Boolean);
  return {
    ownerId: env.BOT_OWNER_ID || null,
    managementRoleIds: ids('AUDITOR_MANAGEMENT_ROLE_IDS'),
    managementCategoryIds: ids('AUDITOR_MANAGEMENT_CATEGORY_IDS'),
    protectedChannelIds: ids('AUDITOR_PROTECTED_CHANNEL_IDS'),
    teams: {
      birmingham: { roleId: env.BIRMINGHAM_ROLE_ID || null, categoryIds: ids('AUDITOR_BIRMINGHAM_CATEGORY_IDS'), prefix: 'ml1' },
      crownfc: { roleId: env.MLPC_ROLE_ID || null, categoryIds: ids('AUDITOR_CROWNFC_CATEGORY_IDS'), prefix: 'mlpc' },
    },
  };
}

async function refresh(guild) {
  await guild.fetch();
  const [channels, roles] = await Promise.all([guild.channels.fetch(), guild.roles.fetch()]);
  // Bulk fetches populate caches but need not evict stale deleted entries.
  for (const channel of values(guild.channels.cache)) {
    if (!channel.isThread() && !channels.has(channel.id)) guild.channels.cache.delete(channel.id);
  }
  for (const role of values(guild.roles.cache)) if (!roles.has(role.id)) guild.roles.cache.delete(role.id);
  return guild.members.fetchMe();
}

function issue(report, area, severity, code, target, evidence, recommendation) {
  if (report.findings.length >= 5000) {
    report.coverage.omittedFindings = (report.coverage.omittedFindings || 0) + 1;
    return;
  }
  report.findings.push({ area, severity, code, targetId: target?.id || null,
    targetName: target?.name || null, evidence, recommendation });
}
function teamForChannel(channel, guild, policy) {
  for (const [key, team] of Object.entries(policy.teams)) {
    if (team.categoryIds.includes(channel.id) || team.categoryIds.includes(channel.parentId)) return key;
  }
  const name = normalize(channel.name);
  const parent = normalize(guild.channels.cache.get(channel.parentId)?.name);
  if (/birmingham/.test(parent) || /^(ml1|birmingham)-/.test(name) || (channel.type === C.GuildCategory && /birmingham/.test(name))) return 'birmingham';
  if (/crown-?fc/.test(parent) || /^(mlpc|crown-?fc)-/.test(name) || (channel.type === C.GuildCategory && /crown-?fc/.test(name))) return 'crownfc';
  return null;
}
function isManagement(channel, guild, policy) {
  return policy.managementCategoryIds.includes(channel.id) || policy.managementCategoryIds.includes(channel.parentId)
    || /management|managers-only|staff-room|recruitment-review/.test(normalize(channel.name))
    || /management|managers-only/.test(normalize(guild.channels.cache.get(channel.parentId)?.name));
}
function roleAccess(channel, role) {
  return channel.permissionsFor(role);
}

async function inspectServer(guild, store, policy, { inactiveDays = 45, now = Date.now() } = {}) {
  const me = await refresh(guild);
  const channels = values(guild.channels.cache).filter(c => !c.isThread());
  const roles = values(guild.roles.cache);
  const report = { version: 1, guildId: guild.id, guildName: guild.name,
    generatedAt: new Date(now).toISOString(), findings: [], snapshot: snapshot(guild),
    coverage: { members: 'cached only; unused roles and multi-role access are not conclusively assessed',
      activity: 'latest message only, at most 50 text/announcement channels; no empty-channel proof',
      media: 'tracked RT Media posts in this guild only; no arbitrary post content is read',
      access: 'effective role access, overwrites and cached member combinations; administrator bypass included',
      classification: 'configured category IDs preferred; name matches are review hints',
      mutations: 'none' } };
  const add = (...args) => issue(report, ...args);
  const groups = new Map();
  for (const channel of channels) {
    const key = `${channel.type}:${normalize(channel.name)}`;
    const group = groups.get(key) || []; group.push(channel); groups.set(key, group);
    if (channel.type === C.GuildCategory) {
      if (!channels.some(c => c.parentId === channel.id)) add('structure', 'review', 'empty-category', channel,
        'No child channels found in the fetched channel list.', 'Review its intended purpose; keep it until the owner decides.');
      continue;
    }
    if (!channel.parentId) add('structure', 'review', 'uncategorized', channel,
      'Channel has no category.', 'Review placement in Welcome, Community, Management, a club, RT Media, or The Grounds.');
    if (TEXT.includes(channel.type) && !channel.topic?.trim()) add('structure', 'review', 'missing-topic', channel,
      'No channel topic/description.', 'Document purpose, who posts, expected workflow and authoritative links.');
    if (TEXT.includes(channel.type) && /\s|[A-Z]/.test(channel.name)) add('structure', 'review', 'naming', channel,
      'Text channel contains whitespace or uppercase characters.', 'Review against the existing decorated lowercase-hyphen naming convention.');
    const team = teamForChannel(channel, guild, policy);
    if (team && /^(ml1|mlpc)-/.test(normalize(channel.name)) && !normalize(channel.name).startsWith(policy.teams[team].prefix + '-')) {
      add('operations', 'warning', 'misplaced-club-channel', channel, 'Club prefix conflicts with its category.', 'Check Birmingham / CrownFC ownership before moving.');
    }
    const parent = guild.channels.cache.get(channel.parentId);
    if (parent && channel.permissionsLocked === false) add('permissions', 'review', 'unsynced-overwrites', channel,
      'Permission overwrites differ from the parent category.', 'Review deliberate exceptions; never blindly sync a private club channel.');
    for (const overwrite of values(channel.permissionOverwrites.cache)) {
      const dangerous = DANGEROUS.filter(flag => has(overwrite.allow, flag));
      if (dangerous.length) add('permissions', 'warning', 'dangerous-overwrite', channel,
        `Overwrite ${overwrite.id} explicitly allows: ${dangerous.join(', ')}. Some permissions are guild-only and cannot be granted here.`,
        'Review the target and its effective access; remove excessive channel capabilities only after preview.');
      if (overwrite.type === 0 && !guild.roles.cache.has(overwrite.id)) add('permissions', 'review', 'orphan-overwrite', channel,
        `Role overwrite ${overwrite.id} has no fetched role.`, 'Review stale role policy manually.');
    }
    if (isManagement(channel, guild, policy)) {
      const allowed = new Set(policy.managementRoleIds);
      if (!allowed.size) add('permissions', 'warning', 'management-policy-missing', channel,
        'No explicit management role allowlist.', 'Set AUDITOR_MANAGEMENT_ROLE_IDS; leadership names alone do not prove authorization.');
      for (const role of roles.filter(r => !r.managed && !allowed.has(r.id))) {
        if (has(roleAccess(channel, role), 'ViewChannel')) add('permissions', 'warning', 'management-access', channel,
          `Role ${role.name} (${role.id}) can view this management area.`, 'Confirm authorization, including Administrator bypass and combined roles.');
      }
      for (const overwrite of values(channel.permissionOverwrites.cache).filter(o => o.type === 1)) {
        add('permissions', 'review', 'management-member-exception', channel,
          `Member-specific overwrite ${overwrite.id}: allow=${overwrite.allow.bitfield}, deny=${overwrite.deny.bitfield}.`,
          'Review named exceptions against the approved management roster.');
      }
    }
    if (team && /practice|schedule|availability|roster|lineup|tactic|locker/.test(normalize(channel.name))) {
      const other = guild.roles.cache.get(policy.teams[team === 'birmingham' ? 'crownfc' : 'birmingham'].roleId);
      if (other && has(roleAccess(channel, other), 'ViewChannel')) add('permissions', 'warning', 'cross-club-access', channel,
        `Opposing club role ${other.name} can view operational channel for ${team}.`, 'Confirm whether intentionally shared; public media and results may be shared.');
    }
    const required = ['ViewChannel'];
    if (TEXT.includes(channel.type)) required.push('ReadMessageHistory');
    const missing = required.filter(flag => !has(channel.permissionsFor(me), flag));
    if (missing.length) add('permissions', 'warning', 'bot-channel-access', channel,
      `Auditor bot lacks ${missing.join(', ')}.`, 'Grant only capabilities needed for the configured workflow.');
    if (/rt-media|raine|teagan|match-center|stats/.test(normalize(channel.name))) {
      const postFlags = [C.GuildForum, C.GuildMedia].includes(channel.type)
        ? ['ViewChannel', 'SendMessages', 'SendMessagesInThreads', 'EmbedLinks', 'AttachFiles']
        : ['ViewChannel', 'SendMessages', 'EmbedLinks', 'AttachFiles'];
      const cannotPost = postFlags.filter(flag => !has(channel.permissionsFor(me), flag));
      if (cannotPost.length) add('media', 'warning', 'bot-publishing-access', channel,
        `Bot lacks ${cannotPost.join(', ')} for media/stat publishing.`, 'Check the destination permissions without granting Administrator.');
    }
  }
  for (const group of groups.values()) if (group.length > 1) add('structure', 'review', 'duplicate-names', group[0],
    `Same normalized name/type: ${group.map(c => `${c.name} (${c.id})`).join(', ')}.`,
    'Compare audience and workflows; matching names do not prove redundancy.');
  for (const role of roles) {
    const dangerous = DANGEROUS.filter(flag => has(role.permissions, flag));
    if (dangerous.length) add('permissions', has(role.permissions, 'Administrator') ? 'critical' : 'warning', 'role-capabilities', role,
      `${role.managed ? 'Integration-managed' : 'Assignable'} role capabilities: ${dangerous.join(', ')}.`,
      'Review least privilege and intended responsibility; managed roles require their integration owner.');
    if (role.id !== guild.id && !role.managed && !role.members.size) add('permissions', 'review', 'possibly-unused-role', role,
      'No members in the local cache; the full roster has not been fetched.', 'Verify the complete member list and integration use before any retirement.');
  }
  for (const id of policy.managementRoleIds) {
    const role = guild.roles.cache.get(id);
    if (!role) add('permissions', 'warning', 'management-role-missing', null,
      `Configured management role ${id} does not exist.`, 'Reconcile the explicit management allowlist.');
    else if (Object.values(policy.teams).some(team => {
      const clubRole = guild.roles.cache.get(team.roleId);
      return clubRole && role.comparePositionTo(clubRole) <= 0;
    })) add('permissions', 'review', 'management-hierarchy', role,
      'Management role is not above every configured player role.', 'Review intended hierarchy; position alone does not grant channel access.');
  }
  if (!has(me.permissions, 'ManageRoles')) add('permissions', 'warning', 'bot-registration-role-permission', null,
    'Bot lacks ManageRoles.', 'Registration cannot assign configured club roles; review minimum required rights.');
  for (const [key, team] of Object.entries(policy.teams)) {
    const role = guild.roles.cache.get(team.roleId);
    if (!role) add('permissions', 'warning', 'club-role-missing', null, `${key} role ID is missing or invalid.`, 'Configure the existing club role ID.');
    else if (role.managed || me.roles.highest.comparePositionTo(role) <= 0) add('permissions', 'warning', 'club-role-hierarchy', role,
      'Bot cannot manage this role due to integration ownership or hierarchy.', 'Place the bot above assignable club roles, below management roles.');
  }
  if (policy.teams.birmingham.roleId && policy.teams.birmingham.roleId === policy.teams.crownfc.roleId) add('permissions', 'critical', 'club-role-collision', null,
    'Birmingham and CrownFC use the same role ID.', 'Use distinct roles; dual-club membership must be an explicit registration decision.');
  const cachedMembers = values(guild.members.cache);
  for (const channel of channels.filter(c => isManagement(c, guild, policy))) {
    for (const member of cachedMembers.filter(m => !m.user.bot && m.id !== guild.ownerId && m.id !== policy.ownerId
      && !policy.managementRoleIds.some(id => m.roles.cache.has(id)))) {
      if (has(channel.permissionsFor(member), 'ViewChannel')) add('permissions', 'warning', 'cached-member-management-access', channel,
        `Cached member ${member.id} can view management with their combined roles.`, 'Check this exception; members outside the cache remain unassessed.');
    }
  }
  for (const member of cachedMembers.filter(m => m.user.bot)) if (has(member.permissions, 'Administrator')) add('permissions', 'warning', 'bot-administrator', null,
    `Cached bot ${member.id} has Administrator.`, 'Review that integration against its documented minimum permissions.');

  const names = channels.map(c => normalize(c.name));
  const entryChecks = [
    ['welcome', /welcome|start-here/], ['rules', /rules/], ['registration', /register|registration/],
    ['verification', /verif|registration/], ['club information', /club-info|club-information/],
  ];
  for (const [label, pattern] of entryChecks) if (!names.some(n => pattern.test(n))) add('onboarding', 'warning', 'entry-workflow-missing', null,
    `No channel name matched ${label}.`, 'Verify the existing entry flow; naming alone cannot prove functionality.');
  for (const channel of channels.filter(c => /welcome|start-here|rules|register|registration/.test(normalize(c.name)))) {
    if (!has(channel.permissionsFor(guild.roles.everyone), 'ViewChannel')) add('onboarding', 'warning', 'entry-hidden', channel,
      '@everyone cannot view the entry channel.', 'Confirm unverified new arrivals have another reachable entry path.');
  }
  const requests = store.listMetadata('onboardingRequest:').map(x => x.value).filter(x => x.guildId === guild.id);
  const pending = requests.filter(r => r.status === 'pending');
  add('onboarding', 'info', 'registration-queue', null, `${pending.length} tracked pending registration request(s).`,
    'Verify management review buttons and the intended approver role; auditor does not assign membership.');
  for (const r of pending.filter(r => now - new Date(r.createdAt).getTime() > 7 * 86400000)) add('onboarding', 'review', 'stale-registration', null,
    `Request ${r.id || r.requestId || r.userId} has waited over seven days.`, 'Review with football operations management.');
  try {
    const onboarding = await guild.fetchOnboarding();
    if (!onboarding.enabled) add('onboarding', 'review', 'native-onboarding-disabled', null,
      'Discord native onboarding is disabled.', 'Confirm the existing registration panel is the intended entry path.');
    report.onboarding = { enabled: onboarding.enabled, defaultChannelIds: [...onboarding.defaultChannels.keys()],
      prompts: values(onboarding.prompts).map(prompt => ({ id: prompt.id, title: prompt.title,
        options: values(prompt.options).map(option => ({ id: option.id, roleIds: [...option.roles.keys()], channelIds: [...option.channels.keys()] })) })) };
    for (const prompt of report.onboarding.prompts) for (const option of prompt.options) {
      const clubRoles = Object.values(policy.teams).map(t => t.roleId).filter(Boolean);
      if (option.roleIds.some(id => clubRoles.includes(id) || policy.managementRoleIds.includes(id))) add('onboarding', 'critical', 'self-assign-sensitive-role', null,
        `Onboarding option ${option.id} assigns a club or management role.`, 'Keep registration approval with the owner / approved football operations manager.');
    }
  } catch (error) { report.coverage.onboarding = `Native onboarding unavailable (${error.code || 'API error'}); not verified.`; }
  for (const team of Object.keys(policy.teams)) {
    const teamChannels = channels.filter(c => teamForChannel(c, guild, policy) === team);
    for (const [label, pattern] of [['practice/scheduling', /practice|schedule|availability/], ['roster', /roster|squad/],
      ['lineup', /lineup|formation|tactic/], ['Match Center', /match-center|matchday|league-center/], ['statistics', /stats|statistics/]]) {
      if (!teamChannels.some(c => pattern.test(normalize(c.name)))) add('operations', 'review', 'club-workflow-missing', null,
        `${team}: no ${label} channel name match.`, 'Verify the authoritative existing workflow before adding duplicate channels.');
    }
  }
  const categories = channels.filter(c => c.type === C.GuildCategory).sort((a, b) => a.rawPosition - b.rawPosition);
  report.categoryOrder = categories.map(c => ({ id: c.id, name: c.name, position: c.rawPosition }));
  const welcomeIndex = categories.findIndex(c => /welcome|start-here/.test(normalize(c.name)));
  if (welcomeIndex > 0) add('structure', 'review', 'entry-order', categories[welcomeIndex],
    'Entry category is below another category.', 'Review top-to-bottom newcomer flow while preserving restricted access.');
  const mediaCategory = categories.find(c => /rt.*media/.test(normalize(c.name)));
  if (!mediaCategory) add('media', 'review', 'media-organization', null, 'No RT Media category name match.', 'Verify where Raine, Teagan, shared newsroom and archive live.');
  for (const [label, pattern] of [['Raine coverage', /raine/], ['Teagan coverage', /teagan/], ['media archive', /archive/], ['management approvals', /management|approval/]]) {
    if (!names.some(n => pattern.test(n))) add('media', 'review', 'media-workflow-missing', null, `No channel name matched ${label}.`, 'Review the publishing and approval route.');
  }
  const tracked = store.listMediaPosts().filter(post => post.guildId === guild.id);
  report.mediaArchiveCandidates = archiveCandidates(tracked, new Date(now), 30).map(post => ({
    id: post.id, channelId: post.channelId, headline: post.headline, publishedAt: post.publishedAt,
  }));
  for (const post of report.mediaArchiveCandidates) add('media', 'review', 'aged-media', null,
    `Tracked post ${post.id} in ${post.channelId} is at least 30 days old.`, 'Age is an archive review signal; confirm relevance and destination. No posts are moved or deleted.');
  for (const post of tracked.filter(p => !guild.channels.cache.has(p.channelId))) add('media', 'warning', 'media-destination-missing', null,
    `Tracked post ${post.id} references missing channel ${post.channelId}.`, 'Reconcile the tracked destination; do not recreate or discard history automatically.');
  report.activity = [];
  const historyChannels = channels.filter(c => [C.GuildText, C.GuildAnnouncement].includes(c.type));
  report.coverage.activityTotal = historyChannels.length;
  for (const channel of historyChannels.slice(0, MAX_HISTORY)) {
    const permission = channel.permissionsFor(me);
    if (!has(permission, 'ViewChannel') || !has(permission, 'ReadMessageHistory')) {
      report.activity.push({ channelId: channel.id, status: 'unavailable' }); continue;
    }
    try {
      const latest = (await channel.messages.fetch({ limit: 1 })).first();
      report.activity.push({ channelId: channel.id, status: latest ? 'sampled' : 'no-visible-message', latestAt: latest?.createdTimestamp || null });
      if (latest && now - latest.createdTimestamp > inactiveDays * 86400000) add('structure', 'review', 'inactive-sample', channel,
        `Latest visible message is over ${inactiveDays} days old; threads, voice use and seasonal relevance were not assessed.`,
        'Review actual use and season plans; inactivity never authorizes deletion.');
    } catch (error) { report.activity.push({ channelId: channel.id, status: 'unavailable', code: error.code || 'API error' }); }
  }
  return report;
}

function parsePermissions(value) {
  const names = String(value || '').split(',').map(x => x.trim()).filter(Boolean);
  if (names.some(n => !FLAGS.includes(n))) throw new Error('Use exact Discord permission names, such as ViewChannel or SendMessages.');
  return [...new Set(names)].sort();
}
function actionFromOptions(options) {
  const type = options.getString('action', true);
  const action = { type };
  if (type === 'role-permissions') {
    action.roleId = options.getRole('role', true).id;
    action.permissions = parsePermissions(options.getString('value', true));
  } else {
    action.channelId = options.getChannel('channel', true).id;
    if (type === 'move') action.parentId = options.getChannel('category', true).id;
    if (type === 'rename' || type === 'topic') action.value = options.getString('value', true);
    if (type === 'position') {
      const raw = options.getString('value', true);
      if (!/^\d+$/.test(raw)) throw new Error('Position must be a nonnegative integer.');
      action.value = Number(raw);
    }
    if (type === 'overwrite') {
      action.roleId = options.getRole('role', true).id;
      action.allow = parsePermissions(options.getString('allow'));
      action.deny = parsePermissions(options.getString('deny'));
      if (action.allow.some(flag => action.deny.includes(flag))) throw new Error('A permission cannot be both allowed and denied.');
    }
  }
  return action;
}

function validateAction(action, guild, me, policy) {
  const supported = ['rename', 'topic', 'move', 'position', 'overwrite', 'role-permissions'];
  if (!supported.includes(action.type)) throw new Error('Unsupported action; deletion and AI-generated operations are disabled.');
  const role = action.roleId ? guild.roles.cache.get(action.roleId) : null;
  if (action.roleId && !role) throw new Error('Target role no longer exists.');
  if (action.type === 'role-permissions' || action.type === 'overwrite') {
    if (!has(me.permissions, 'ManageRoles')) throw new Error('Bot needs ManageRoles.');
    if (role.id === guild.id || role.managed || me.roles.cache.has(role.id)
      || me.roles.highest.comparePositionTo(role) <= 0 || policy.managementRoleIds.includes(role.id)) {
      throw new Error('Everyone, integration, bot, management, and roles above the bot are protected.');
    }
    const names = action.type === 'role-permissions' ? action.permissions : [...action.allow, ...action.deny];
    if (!Array.isArray(names) || names.some(n => !FLAGS.includes(n))) throw new Error('Invalid permission list.');
    if ((action.type === 'role-permissions' ? action.permissions : action.allow).some(n => !has(me.permissions, n))) {
      throw new Error('The bot cannot grant permissions it does not possess.');
    }
  }
  if (action.type === 'role-permissions') return;
  const channel = guild.channels.cache.get(action.channelId);
  if (!channel || channel.isThread()) throw new Error('Only existing guild channels are supported.');
  if (policy.protectedChannelIds.includes(channel.id) || policy.protectedChannelIds.includes(channel.parentId)
    || isManagement(channel, guild, policy)) throw new Error('Protected or management channels require manual Discord administration.');
  const permission = action.type === 'overwrite' ? 'ManageRoles' : 'ManageChannels';
  if (!has(channel.permissionsFor(me), permission)) throw new Error(`Bot lacks ${permission} in this channel.`);
  if (action.type === 'overwrite' && action.allow.some(n => action.deny.includes(n))) throw new Error('Conflicting overwrite permissions.');
  if (action.type === 'rename' && (typeof action.value !== 'string' || action.value.trim().length < 1 || action.value.length > 100)) throw new Error('Channel name must be 1–100 characters.');
  if (action.type === 'topic' && (!TEXT.includes(channel.type) || typeof action.value !== 'string' || action.value.length > 1024)) throw new Error('Topic must be at most 1024 characters in a supported text/forum channel.');
  if (action.type === 'position' && (!Number.isSafeInteger(action.value) || action.value < 0 || action.value >= guild.channels.cache.size)) throw new Error('Position is outside the server channel range.');
  if (action.type === 'move') {
    const parent = guild.channels.cache.get(action.parentId);
    if (channel.type === C.GuildCategory || !parent || parent.type !== C.GuildCategory) throw new Error('Move requires a channel and an existing category.');
    if (policy.protectedChannelIds.includes(parent.id) || isManagement(parent, guild, policy)
      || !has(parent.permissionsFor(me), 'ManageChannels')) throw new Error('Destination is protected or not manageable by the bot.');
    if (values(guild.channels.cache).filter(c => c.parentId === parent.id).length >= 50 && channel.parentId !== parent.id) throw new Error('Destination category is full.');
    const oldTeam = teamForChannel(channel, guild, policy);
    const destinationTeam = teamForChannel(parent, guild, policy);
    if (oldTeam && oldTeam !== destinationTeam) throw new Error('Moving club operations across club boundaries requires manual review.');
  }
}

function describeAction(action, guild) {
  const channel = action.channelId ? guild.channels.cache.get(action.channelId) : null;
  const role = action.roleId ? guild.roles.cache.get(action.roleId) : null;
  const before = action.type === 'role-permissions' ? roleData(role) : channelData(channel);
  return { action, targetName: channel?.name || role?.name, before,
    warning: action.type === 'overwrite' ? 'This replaces the target role overwrite, including resetting unspecified permissions to inherit.'
      : action.type === 'role-permissions' ? 'This replaces all permissions on this role and affects every member with it.'
        : action.type === 'move' ? 'Existing overwrites will be preserved (lockPermissions=false); destination permissions will not be synced.'
          : action.type === 'position' ? 'Discord may shift sibling positions when this channel moves.' : 'Only the specified property changes.' };
}

function formatReport(report, area = null) {
  const findings = area ? report.findings.filter(f => f.area === area) : report.findings;
  return [
    `# Castle & Crown Collective — ${area || 'server'} audit`,
    `Server: ${report.guildName} (${report.guildId}) | Generated: ${report.generatedAt}`,
    'Review only. No server changes have been made.',
    '## Coverage', ...Object.entries(report.coverage).map(([key, value]) => `- ${key}: ${value}`),
    '## Findings', ...findings.map(f => `\n[${f.severity.toUpperCase()}] ${f.code} — ${f.targetName || 'server'} (${f.targetId || '-'})\nEvidence: ${f.evidence}\nReview: ${f.recommendation}`),
    findings.length ? '' : 'No findings in this scope. This is not proof of complete security.',
    '## Category order', ...report.categoryOrder.map(c => `${c.position}. ${c.name} (${c.id})`),
  ].join('\n');
}
function formatMap(guild, policy) {
  const channels = values(guild.channels.cache).filter(c => !c.isThread());
  const categories = channels.filter(c => c.type === C.GuildCategory).sort((a, b) => a.rawPosition - b.rawPosition || a.id.localeCompare(b.id));
  const lines = [`# Castle & Crown Collective — server map`, `Guild ${guild.id}`, 'Raw Discord positions within each type; exact IDs are authoritative.'];
  for (const category of [...categories, { id: null, name: 'Uncategorized' }]) {
    lines.push(`\n${category.rawPosition ?? '-'}. ${category.name} (${category.id || '-'})`);
    for (const channel of channels.filter(c => c.type !== C.GuildCategory && c.parentId === category.id)
      .sort((a, b) => a.rawPosition - b.rawPosition || a.id.localeCompare(b.id))) {
      lines.push(`  ${channel.rawPosition}. ${channel.name} (${channel.id}) [${C[channel.type]}] [${teamForChannel(channel, guild, policy) || 'shared'}]${isManagement(channel, guild, policy) ? ' [management]' : ''}`);
    }
  }
  lines.push('\nRoles (highest first):');
  for (const role of values(guild.roles.cache).sort((a, b) => b.comparePositionTo(a))) lines.push(`${role.position}. ${role.name} (${role.id})${role.managed ? ' [managed]' : ''} — ${role.permissions.toArray().join(', ') || 'none'}`);
  return lines.join('\n');
}

function createServerAuditor({ stateStore: store, policy = policyFromEnv(), now = () => Date.now() }) {
  if (!store) throw new Error('The auditor requires the existing StateStore.');
  const locks = new Set();
  const key = id => `serverAuditor:preview:${id}`;
  const owner = guild => policy.ownerId || guild.ownerId;
  const authorize = (guild, userId) => {
    if (!guild || userId !== owner(guild)) throw new Error('Only the configured Castle & Crown owner can use the auditor in a server.');
  };
  async function preview(guild, userId, actions) {
    authorize(guild, userId);
    if (!Array.isArray(actions) || !actions.length || actions.length > MAX_ACTIONS) throw new Error('A preview needs 1–20 exact owner-requested actions.');
    const me = await refresh(guild);
    actions.forEach(action => validateAction(action, guild, me, policy));
    const baseline = snapshot(guild);
    const id = crypto.randomUUID();
    const plan = { id, version: 1, guildId: guild.id, ownerId: userId, status: 'pending',
      createdAt: now(), expiresAt: now() + TTL, baseline, baselineHash: hash(baseline),
      changes: actions.map(action => describeAction(action, guild)) };
    plan.digest = hash(plan.changes);
    plan.confirmation = `APPLY ${id} ${plan.digest.slice(0, 12)}`;
    store.setMetadata(key(id), plan);
    store.addManagementLog({ action: 'server_auditor_preview', guildId: guild.id, ownerId: userId, previewId: id, digest: plan.digest });
    return plan;
  }
  async function apply(guild, userId, id, confirmation) {
    authorize(guild, userId);
    if (locks.has(guild.id)) throw new Error('Another auditor change is in progress for this guild.');
    locks.add(guild.id);
    try {
      const plan = store.getMetadata(key(id));
      if (!plan || plan.version !== 1 || plan.guildId !== guild.id || plan.ownerId !== userId) throw new Error('Preview does not belong to this owner and server.');
      if (plan.status !== 'pending') throw new Error('Preview has already been consumed; do not replay it.');
      if (plan.expiresAt <= now()) throw new Error('Preview expired. Create a new cleanup-preview.');
      if (confirmation !== plan.confirmation || plan.confirmation !== `APPLY ${id} ${hash(plan.changes).slice(0, 12)}` || plan.digest !== hash(plan.changes)) throw new Error('Exact preview confirmation is required.');
      const me = await refresh(guild);
      authorize(guild, userId);
      if (hash(snapshot(guild)) !== plan.baselineHash || hash(plan.baseline) !== plan.baselineHash) throw new Error('Server channels, roles, owner or permissions changed since preview. Review a fresh preview.');
      plan.changes.forEach(change => validateAction(change.action, guild, me, policy));
      const journal = { previewId: id, guildId: guild.id, ownerId: userId, status: 'applying',
        startedAt: now(), baseline: plan.baseline, changes: plan.changes, results: [] };
      // Persist intent and consume confirmation before any Discord write. A crash never auto-replays.
      store.setMetadata(`serverAuditor:journal:${id}`, journal);
      store.setMetadata(key(id), { ...plan, status: 'applying' });
      for (const change of plan.changes) {
        const action = change.action;
        const channel = action.channelId ? guild.channels.cache.get(action.channelId) : null;
        const reason = `Owner-approved Castle & Crown auditor preview ${id}`;
        try {
          if (action.type === 'rename') await channel.setName(action.value, reason);
          else if (action.type === 'topic') await channel.setTopic(action.value, reason);
          else if (action.type === 'position') await channel.setPosition(action.value, { reason });
          else if (action.type === 'move') await channel.setParent(action.parentId, { lockPermissions: false, reason });
          else if (action.type === 'role-permissions') await guild.roles.cache.get(action.roleId).setPermissions(action.permissions.map(n => P[n]), reason);
          else if (action.type === 'overwrite') {
            const next = Object.fromEntries(FLAGS.map(flag => [flag,
              action.allow.includes(flag) ? true : action.deny.includes(flag) ? false : null]));
            await channel.permissionOverwrites.edit(action.roleId, next, { reason });
          }
          const result = { action, status: 'applied', at: now() };
          journal.results.push(result);
          try {
            result.after = action.type === 'role-permissions'
              ? roleData(await guild.roles.fetch(action.roleId, { force: true }))
              : channelData(await guild.channels.fetch(action.channelId, { force: true }));
          } catch (error) {
            result.afterUnavailable = `Write returned successfully; verification fetch failed (${error.code || 'API error'}).`;
            journal.status = 'failed'; // Stop further writes when actual after-state cannot be verified.
          }
        } catch (error) {
          journal.results.push({ action, status: 'failed', code: error.code || null, message: error.message, at: now() });
          journal.status = 'failed';
        }
        store.setMetadata(`serverAuditor:journal:${id}`, journal);
        if (journal.status === 'failed') break;
      }
      journal.status = journal.status === 'failed' ? 'failed' : 'applied';
      journal.finishedAt = now();
      store.setMetadata(`serverAuditor:journal:${id}`, journal);
      store.setMetadata(key(id), { ...plan, status: journal.status });
      store.addManagementLog({ action: 'server_auditor_apply', guildId: guild.id, ownerId: userId, previewId: id, status: journal.status, results: journal.results });
      return journal;
    } finally { locks.delete(guild.id); }
  }
  async function handleInteraction(interaction) {
    if (!interaction.isChatInputCommand() || !COMMAND_NAMES.includes(interaction.commandName)) return false;
    try {
      authorize(interaction.guild, interaction.user.id);
      await interaction.deferReply({ flags: MessageFlags.Ephemeral });
      const guild = interaction.guild;
      if (interaction.commandName === 'apply-changes') {
        const journal = await apply(guild, interaction.user.id, interaction.options.getString('preview_id', true), interaction.options.getString('confirmation', true));
        await interaction.editReply({ content: `Preview ${journal.previewId}: ${journal.status}. ${journal.results.filter(r => r.status === 'applied').length} action(s) applied. ${journal.status === 'failed' ? 'Stopped at the first failure; earlier changes remain applied. Review the journal before another preview.' : 'Review the attached journal.'}`,
          files: [new AttachmentBuilder(Buffer.from(JSON.stringify(journal, null, 2)), { name: 'server-change-journal.json' })], allowedMentions: { parse: [] } });
      } else if (interaction.commandName === 'server-map') {
        await refresh(guild);
        await interaction.editReply({ content: 'Private server map. No changes made.', files: [
          new AttachmentBuilder(Buffer.from(formatMap(guild, policy)), { name: 'server-map.txt' }),
          new AttachmentBuilder(Buffer.from(JSON.stringify(snapshot(guild), null, 2)), { name: 'server-map.json' }),
        ], allowedMentions: { parse: [] } });
      } else {
        const report = await inspectServer(guild, store, policy, { inactiveDays: interaction.options.getInteger('inactive_days') || 45, now: now() });
        const area = { 'permission-audit': 'permissions', 'media-audit': 'media', 'onboarding-audit': 'onboarding' }[interaction.commandName] || null;
        const files = [new AttachmentBuilder(Buffer.from(formatReport(report, area)), { name: `${interaction.commandName}.txt` }),
          new AttachmentBuilder(Buffer.from(JSON.stringify(report, null, 2)), { name: 'server-audit-evidence.json' })];
        let content = `Private review: ${(area ? report.findings.filter(f => f.area === area) : report.findings).length} findings. No server changes made. Coverage and evidence are attached.`;
        if (interaction.commandName === 'cleanup-preview') {
          const plan = await preview(guild, interaction.user.id, [actionFromOptions(interaction.options)]);
          files.push(new AttachmentBuilder(Buffer.from(JSON.stringify(plan, null, 2)), { name: 'cleanup-preview.json' }));
          content = `Exact owner-requested change previewed. No changes made.\nPreview ID: ${plan.id}\nExpires in 15 minutes.\nReview cleanup-preview.json, then use /apply-changes with confirmation:\n${plan.confirmation}`;
        }
        store.addManagementLog({ action: 'server_auditor_report', guildId: guild.id, ownerId: interaction.user.id, command: interaction.commandName, findings: report.findings.length });
        await interaction.editReply({ content, files, allowedMentions: { parse: [] } });
      }
    } catch (error) {
      const payload = { content: `Auditor stopped: ${String(error.message).slice(0, 1200)}\nNo further actions will run. If applying was interrupted, inspect the persisted serverAuditor journal before retrying.`, allowedMentions: { parse: [] } };
      if (interaction.deferred || interaction.replied) await interaction.editReply(payload);
      else await interaction.reply({ ...payload, flags: MessageFlags.Ephemeral });
    }
    return true;
  }
  return { handleInteraction, preview, apply };
}

module.exports = { buildCommands, createServerAuditor, inspectServer, policyFromEnv,
  snapshot, formatMap, formatReport, actionFromOptions, parsePermissions, COMMAND_NAMES };
