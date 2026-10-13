'use strict';

const fs = require('fs');
const path = require('path');
const { ActionRowBuilder, ButtonBuilder, ButtonStyle, ChannelType, MessageFlags,
  GuildScheduledEventEntityType, GuildScheduledEventPrivacyLevel, PermissionFlagsBits } = require('discord.js');

const CUP_ID = 'minglewood-2026-10-13-round-1';
const TITLE = 'Minglewood Cup R1 — Middlesbrough vs Birmingham City';
const KICKOFF = '2026-10-14T02:00:00.000Z';
const POSTER = path.join(__dirname, 'assets', 'minglewood-cup-round1.jpg');
const key = `cup:${CUP_ID}`;
const availabilityUpdates = new Map();
async function serializeUpdate(lockKey, operation) {
  const previous = availabilityUpdates.get(lockKey) || Promise.resolve();
  const update = previous.catch(() => {}).then(operation);
  availabilityUpdates.set(lockKey, update);
  try { return await update; }
  finally { if (availabilityUpdates.get(lockKey) === update) availabilityUpdates.delete(lockKey); }
}
const norm = value => String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const link = (guildId, channelId) => `https://discord.com/channels/${guildId}/${channelId}`;
function unique(items, label) {
  if (items.length !== 1) throw Error(`${label}: expected exactly one match, found ${items.length}. Candidates: ${items.map(x => `${x.name} (${x.id})`).join(', ') || 'none'}`);
  return items[0];
}
function buttons(disabled = false) {
  return [new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId(`cup_availability:${CUP_ID}:yes`).setLabel('YES — Available').setEmoji('✅').setStyle(ButtonStyle.Success).setDisabled(disabled),
    new ButtonBuilder().setCustomId(`cup_availability:${CUP_ID}:no`).setLabel('NO — Unavailable').setEmoji('❌').setStyle(ButtonStyle.Danger).setDisabled(disabled)
  )];
}
function body(record) {
  const votes = Object.values(record.availability || {});
  const group = status => votes.filter(v => v.status === status);
  const names = status => group(status).map(v => v.name.replace(/[@*_`~<>\r\n]/g, '')).join(', ') || 'None yet';
  return `🏆 **MINGLEWOOD CUP — ROUND 1**\n**Middlesbrough vs Birmingham City — Away**\n**Single elimination**\n\n📅 Tuesday, October 13, 2026\n⚽ **Kickoff: 10:00 PM ET**\n🎮 **Be online by 8:00 PM ET**\n🚨 **ABSOLUTELY NO LATER THAN 8:30 PM ET**\n\n**MARK YOUR AVAILABILITY**\nEveryone needs to select **YES or NO** below ASAP so we can prep the lineup early. Your latest selection replaces your previous response. If you will be late or need to leave early, tell management in this thread.\n\n✅ YES: ${group('yes').length} — ${names('yes')}\n❌ NO: ${group('no').length} — ${names('no')}\n\n**LINEUP**\nManagement will post the confirmed lineup in this thread once availability is collected.\n\n📺 **Watch live:** <#${record.liveChannelId}>\nLive stream and match updates will be in Live Games.\n${record.eventId ? `📅 **[Discord Event](https://discord.com/events/${record.guildId}/${record.eventId})**\n` : ''}\n**Keep Right On 💙**`;
}
async function setupCup({ guild, store, now = new Date(), posterPath = POSTER }) {
  let record = store.getMetadata(key);
  if (record?.status === 'complete') return record;
  if (now >= new Date(KICKOFF)) throw Error('Cup kickoff has passed; automatic setup is disabled.');
  if (!fs.existsSync(posterPath)) throw Error('Cup poster is missing. Nothing was posted.');
  await guild.channels.fetch();
  await guild.roles.fetch();
  const channels = [...guild.channels.cache.values()];
  const roles = [...guild.roles.cache.values()];
  let playerRoles = roles.filter(r => norm(r.name) === 'birmingham-city-players');
  // Existing configured club role is acceptable only when its name identifies Birmingham.
  if (!playerRoles.length) playerRoles = roles.filter(r => r.id === process.env.BIRMINGHAM_ROLE_ID && norm(r.name).includes('birmingham'));
  const playerRole = unique(playerRoles, 'Birmingham City players role');
  const live = unique(channels.filter(c => c.type === ChannelType.GuildText && norm(c.name) === 'live-games'), 'Live Games channel');
  let forums = channels.filter(c => c.type === ChannelType.GuildForum && ['mpl-match-center', 'ml1-match-center'].includes(norm(c.name)));
  if (forums.length > 1) forums = forums.filter(c => norm(c.parent?.name).includes('birmingham'));
  const forum = unique(forums, 'Birmingham Match Center forum');
  const botMember = guild.members?.me || (guild.members?.fetchMe ? await guild.members.fetchMe() : null);
  if (botMember) {
    if (!botMember.permissions.has(PermissionFlagsBits.CreateEvents)) throw Error('RT Media needs Create Events. No cup post was created.');
    const perms = forum.permissionsFor(botMember);
    if (!perms?.has([PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.SendMessagesInThreads, PermissionFlagsBits.AttachFiles, PermissionFlagsBits.ReadMessageHistory])) throw Error('RT Media needs forum view, post, thread reply, message history and attachment permissions.');
    if (!playerRole.mentionable && !perms.has(PermissionFlagsBits.MentionEveryone)) throw Error('RT Media cannot notify the Birmingham City players role: it needs Mention Everyone permission in this forum or a mentionable player role.');
  }
  record = { ...record, id: CUP_ID, guildId: guild.id, forumChannelId: forum.id, playerRoleId: playerRole.id,
    liveChannelId: live.id, kickoffAt: KICKOFF, availability: record?.availability || {}, status: 'setting-up' };
  const save = () => {
    record.availability = store.getMetadata(key)?.availability || record.availability;
    store.setMetadata(key, record);
  };
  save();
  let thread = record.forumPostId ? await guild.channels.fetch(record.forumPostId).catch(() => null) : null;
  if (!thread) {
    const active = await forum.threads.fetchActive();
    const archived = await forum.threads.fetchArchived({ limit: 100 });
    const matches = [...active.threads.values(), ...archived.threads.values()].filter(t => t.name === TITLE);
    if (matches.length > 1) throw Error('Multiple matching cup posts exist. No additional post was created.');
    thread = matches[0];
    if (thread && botMember && thread.ownerId !== botMember.id) throw Error('A cup post with this title already exists from another author; review it before automated editing.');
    if (!thread) thread = await forum.threads.create({name: TITLE, message:{content:body(record), components:buttons(),
      files:[{attachment:posterPath,name:'minglewood-cup-round1.jpg'}], allowedMentions:{parse:[]}},
      appliedTags:forum.availableTags.filter(t => ['Upcoming','Away','Cup'].includes(t.name)).map(t => t.id), reason:'Owner-requested Minglewood Cup Round 1 setup'});
    record.forumPostId = thread.id; save();
  }
  let event = record.eventId ? await guild.scheduledEvents.fetch(record.eventId).catch(() => null) : null;
  if (!event) {
    const allEvents = await guild.scheduledEvents.fetch();
    const matches = [...allEvents.values()].filter(e => e.name === TITLE && new Date(e.scheduledStartTimestamp || e.scheduledStartTime).toISOString() === KICKOFF);
    if (matches.length > 1) throw Error('Multiple matching cup events exist. No additional event was created.');
    event = matches[0];
    if (!event) event = await guild.scheduledEvents.create({name:TITLE,
      description:`Minglewood Cup — Round 1, single elimination.\nAway at Middlesbrough.\nKickoff: 10:00 PM ET.\nBe online by 8:00 PM ET; absolutely NO LATER than 8:30 PM ET.\nMark YES or NO in the forum ASAP so management can prepare the lineup early.\nCup forum: ${link(guild.id,thread.id)}\nLive Games: ${link(guild.id,live.id)}\nKeep Right On 💙`,
      scheduledStartTime:new Date(KICKOFF),scheduledEndTime:new Date('2026-10-14T03:30:00.000Z'),
      entityType:GuildScheduledEventEntityType.External,privacyLevel:GuildScheduledEventPrivacyLevel.GuildOnly,
      entityMetadata:{location:'EA FC Pro Clubs — away at Middlesbrough'},image:fs.readFileSync(posterPath),reason:'Owner-requested cup event'});
    record.eventId = event.id; save();
  }
  if (thread.archived) await thread.setArchived(false);
  await serializeUpdate(`${guild.id}:${thread.id}`, async () => {
    save();
    const starter = await thread.fetchStarterMessage();
    await starter.edit({content:body(record),components:buttons(),allowedMentions:{parse:[]}});
  });
  if (!record.pingMessageId) {
    const content = `<@&${playerRole.id}>\n**MINGLEWOOD CUP — AVAILABILITY**\nCup tonight away at Middlesbrough, **10:00 PM ET kickoff — single elimination**. Everyone needs to mark **YES or NO** on the buttons above ASAP so I can prep the lineup early.\n\nBe on by **8:00 PM ET**, absolutely **NO LATER than 8:30 PM ET**. If anything changes, let management know.\n\n📺 Live feed: <#${live.id}>\nKeep Right On 💙`;
    const recent = thread.messages?.fetch ? await thread.messages.fetch({limit:50}) : null;
    const existing = recent && [...recent.values()].find(m => m.content === content && (!botMember || m.author.id === botMember.id));
    const ping = existing || await thread.send({content,allowedMentions:{roles:[playerRole.id],users:[],parse:[]}});
    record.pingMessageId = ping.id; save();
  }
  record.status = 'complete';record.completedAt = new Date().toISOString();save();
  return record;
}

async function handleCupAvailability(interaction, store) {
  const [,id,status] = String(interaction.customId).split(':');
  const record = id === CUP_ID ? store.getMetadata(key) : null;
  if (!record || !['yes','no'].includes(status) || interaction.guildId !== record.guildId || interaction.channelId !== record.forumPostId) {
    return interaction.reply({content:'This cup availability request is not active.',flags:MessageFlags.Ephemeral});
  }
  const memberRoles = interaction.member?.roles;
  const isPlayer = memberRoles?.cache?.has(record.playerRoleId) || (Array.isArray(memberRoles) && memberRoles.includes(record.playerRoleId));
  if (!isPlayer) return interaction.reply({content:'Only Birmingham City players can mark cup availability.',flags:MessageFlags.Ephemeral});
  if (new Date() >= new Date(record.kickoffAt)) return interaction.reply({content:'Cup availability is closed because kickoff has passed.',flags:MessageFlags.Ephemeral});
  await interaction.deferReply({flags:MessageFlags.Ephemeral});
  const lockKey = `${record.guildId}:${record.forumPostId}`;
  return serializeUpdate(lockKey, async () => {
    const latest = store.getMetadata(key);
    latest.availability[interaction.user.id] = {status,name:interaction.member.displayName || interaction.user.username || 'Player',updatedAt:new Date().toISOString()};
    store.setMetadata(key, latest);
    const starter = await interaction.channel.fetchStarterMessage();
    await starter.edit({content:body(latest),components:buttons(),allowedMentions:{parse:[]}});
    return interaction.editReply({content:`Your cup availability is now **${status.toUpperCase()}**.`});
  });
}

async function runCupSetup(client, store) {
  if (process.env.RT_CUP_SETUP_REQUEST !== CUP_ID) return;
  try {
    const guild = await client.guilds.fetch(process.env.DISCORD_GUILD_ID);
    const result = await setupCup({guild,store});
    console.log('RT_CUP_SETUP_RESULT',JSON.stringify({status:result.status,forumPostUrl:link(result.guildId,result.forumPostId),eventUrl:`https://discord.com/events/${result.guildId}/${result.eventId}`,liveGamesUrl:link(result.guildId,result.liveChannelId),roleId:result.playerRoleId,pingMessageId:result.pingMessageId}));
  } catch (error) { console.error('RT_CUP_SETUP_FAILED:',error.message); }
}
module.exports = {setupCup,handleCupAvailability,runCupSetup,CUP_ID};
