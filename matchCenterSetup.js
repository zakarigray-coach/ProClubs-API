'use strict';

const { ChannelType, PermissionFlagsBits } = require('discord.js');

const TAGS = ['Upcoming', 'Home', 'Away', 'Completed', 'Win', 'Loss', 'Draw'];

const CLUBS = {
  crownfc: {
    categoryTerms: ['crown', 'mlpc'],
    finalName: '📅・mlpc-match-center',
    temporaryName: '📅・mlpc-match-center-new',
    topic: 'CrownFC MLPC Match Center — individual match threads for fixtures, availability, lineups, results, clips and RT Football Media coverage. One post per official match.',
    roleEnvironmentName: 'MLPC_ROLE_ID',
    legacyNames: ['mlpc-match-center', 'mlpc-match-results'],
  },
  birmingham: {
    categoryTerms: ['birmingham', 'mpl'],
    alternateCategoryTerms: ['birmingham', 'ml1'],
    finalName: '📅・mpl-match-center',
    temporaryName: '📅・mpl-match-center-new',
    topic: 'Birmingham City MPL Match Center — individual match threads for fixtures, availability, lineups, results, clips and RT Football Media coverage. One post per official match.',
    roleEnvironmentName: 'BIRMINGHAM_ROLE_ID',
    legacyNames: ['mpl-match-center', 'mpl-match-results', 'ml1-match-center', 'ml1-match-results'],
  },
};

function normalizedName(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function categoryMatches(category, definition) {
  const name = normalizedName(category && category.name);
  const primary = definition.categoryTerms.every(term => name.includes(term));
  const alternate = definition.alternateCategoryTerms && definition.alternateCategoryTerms.every(term => name.includes(term));
  return Boolean(primary || alternate);
}

function permissionOverwrites(guild, playerRoleId, managementRoleId) {
  const botId = guild.members.me.id;
  return [
    {
      id: guild.roles.everyone.id,
      deny: [
        PermissionFlagsBits.ViewChannel,
        PermissionFlagsBits.SendMessages,
        PermissionFlagsBits.CreatePublicThreads,
        PermissionFlagsBits.CreatePrivateThreads,
      ],
    },
    {
      id: playerRoleId,
      allow: [
        PermissionFlagsBits.ViewChannel,
        PermissionFlagsBits.SendMessagesInThreads,
        PermissionFlagsBits.EmbedLinks,
        PermissionFlagsBits.AttachFiles,
      ],
      deny: [
        PermissionFlagsBits.SendMessages,
        PermissionFlagsBits.CreatePublicThreads,
        PermissionFlagsBits.CreatePrivateThreads,
      ],
    },
    {
      id: managementRoleId,
      allow: [
        PermissionFlagsBits.ViewChannel,
        PermissionFlagsBits.SendMessages,
        PermissionFlagsBits.SendMessagesInThreads,
        PermissionFlagsBits.CreatePublicThreads,
        PermissionFlagsBits.ManageThreads,
        PermissionFlagsBits.ManageMessages,
        PermissionFlagsBits.EmbedLinks,
        PermissionFlagsBits.AttachFiles,
      ],
    },
    {
      id: botId,
      allow: [
        PermissionFlagsBits.ViewChannel,
        PermissionFlagsBits.SendMessages,
        PermissionFlagsBits.SendMessagesInThreads,
        PermissionFlagsBits.CreatePublicThreads,
        PermissionFlagsBits.ManageThreads,
        PermissionFlagsBits.ManageMessages,
        PermissionFlagsBits.EmbedLinks,
        PermissionFlagsBits.AttachFiles,
      ],
    },
  ];
}

function archivedName(channelName) {
  const normalized = normalizedName(channelName);
  if (normalized === 'mlpc-match-center') return 'mlpc-match-center-old';
  if (normalized === 'mpl-match-center') return 'mpl-match-center-old';
  if (normalized === 'ml1-match-center') return 'ml1-match-center-old';
  return channelName;
}

async function applyMatchCenterSetup(guild, options = {}) {
  await guild.channels.fetch();
  await guild.roles.fetch();
  const managementRoleId = options.managementRoleId || process.env.FOOTBALL_OPS_ROLE_ID || '1536963624747143199';
  const managementRole = guild.roles.cache.get(managementRoleId);
  if (!managementRole) throw new Error('The Vice President of Football Operations role could not be found. Nothing was changed.');
  if (!guild.members.me) await guild.members.fetchMe();

  const categories = [...guild.channels.cache.values()].filter(channel => channel.type === ChannelType.GuildCategory);
  const archive = categories.find(category => /(^|-)club-archive($|-)|(^|-)archive($|-)/.test(normalizedName(category.name)));
  if (!archive) throw new Error('The existing Club Archive category could not be found. Nothing was changed.');

  const preflight = {};
  for (const [clubKey, definition] of Object.entries(CLUBS)) {
    const category = categories.find(item => categoryMatches(item, definition));
    if (!category) throw new Error(`The ${clubKey === 'crownfc' ? 'CrownFC / MLPC' : 'Birmingham City / MPL'} category could not be found. Nothing was changed.`);
    const playerRoleId = process.env[definition.roleEnvironmentName];
    const playerRole = playerRoleId && guild.roles.cache.get(playerRoleId);
    if (!playerRole) throw new Error(`The ${clubKey === 'crownfc' ? 'CrownFC / MLPC' : 'Birmingham City / MPL'} player role could not be found. Nothing was changed.`);
    preflight[clubKey] = { definition, category, playerRoleId };
  }

  const report = { created: [], updated: [], renamed: [], moved: [], tags: {}, permissions: [] };
  for (const [clubKey, entry] of Object.entries(preflight)) {
    const { definition, category, playerRoleId } = entry;
    let forum = [...guild.channels.cache.values()].find(channel =>
      channel.type === ChannelType.GuildForum &&
      channel.parentId === category.id &&
      normalizedName(channel.name) === normalizedName(definition.finalName)
    );

    if (!forum) {
      forum = await guild.channels.create({
        name: definition.temporaryName,
        type: ChannelType.GuildForum,
        parent: category.id,
        topic: definition.topic,
        availableTags: TAGS.map(name => ({ name, moderated: false })),
        permissionOverwrites: permissionOverwrites(guild, playerRoleId, managementRoleId),
        reason: 'Approved Match Center forum conversion',
      });
      report.created.push(definition.finalName);
    } else {
      await forum.edit({
        topic: definition.topic,
        availableTags: TAGS.map(name => ({ name, moderated: false })),
        reason: 'Approved Match Center forum verification',
      });
      await forum.permissionOverwrites.set(permissionOverwrites(guild, playerRoleId, managementRoleId), 'Approved Match Center forum permissions');
      report.updated.push(definition.finalName);
    }

    const legacySet = new Set(definition.legacyNames);
    const legacyChannels = [...guild.channels.cache.values()].filter(channel =>
      [ChannelType.GuildText, ChannelType.GuildAnnouncement].includes(channel.type) &&
      legacySet.has(normalizedName(channel.name))
    );
    for (const channel of legacyChannels) {
      const nextName = archivedName(channel.name);
      if (nextName !== channel.name) {
        const previousName = channel.name;
        await channel.setName(nextName, 'Preserve old Match Center history before forum conversion');
        report.renamed.push(`${previousName} → ${nextName}`);
      }
      if (channel.parentId !== archive.id) {
        await channel.setParent(archive, { lockPermissions: false, reason: 'Archive old Match Center history without deletion' });
        report.moved.push(channel.name);
      }
    }

    if (forum.name !== definition.finalName) await forum.setName(definition.finalName, 'Activate approved Match Center forum');
    if (forum.parentId !== category.id) await forum.setParent(category, { lockPermissions: false, reason: 'Keep Match Center in its club category' });
    await forum.edit({ topic: definition.topic, availableTags: TAGS.map(name => ({ name, moderated: false })) });
    await forum.permissionOverwrites.set(permissionOverwrites(guild, playerRoleId, managementRoleId), 'Apply approved forum access model');
    report.tags[clubKey] = [...TAGS];
    report.permissions.push(`${definition.finalName}: players may reply but not create posts; management and RT Football Media may create/manage posts`);
  }

  return report;
}

module.exports = { CLUBS, TAGS, applyMatchCenterSetup, archivedName, categoryMatches, normalizedName, permissionOverwrites };
