const { EmbedBuilder, SlashCommandBuilder, PermissionFlagsBits, ChannelType } = require('discord.js');

const TEAM_URL = process.env.VIRTUALEAGUES_CROWNFC_URL || 'https://www.virtualeagues.com/teams/crownfc';
const POLL_MINUTES = Math.max(15, Number(process.env.MLPC_SCHEDULE_POLL_MINUTES) || 30);
const TIMEZONE = process.env.NEWS_TIMEZONE || 'America/New_York';
const TEAM_NAMES = ['crownfc', 'crown fc', 'clt'];

function cleanText(value, max = 200) {
  return String(value ?? '').replace(/\s+/g, ' ').trim().slice(0, max);
}

function normalize(value) {
  return cleanText(value, 200).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

function isCrown(value) {
  const n = normalize(value);
  return TEAM_NAMES.some(name => n === normalize(name) || n.includes(normalize(name)));
}

function teamName(value) {
  if (!value) return '';
  if (typeof value === 'string') return cleanText(value, 80);
  if (typeof value !== 'object') return '';
  for (const key of ['name', 'team_name', 'teamName', 'short_name', 'shortName', 'display_name', 'displayName', 'club_name', 'clubName', 'tag', 'abbreviation']) {
    if (value[key]) return cleanText(value[key], 80);
  }
  return '';
}

function firstValue(obj, keys) {
  for (const key of keys) {
    if (obj && obj[key] !== undefined && obj[key] !== null && obj[key] !== '') return obj[key];
  }
  return null;
}

function asDate(value) {
  if (!value) return null;
  if (typeof value === 'number') {
    const ms = value < 1e12 ? value * 1000 : value;
    const d = new Date(ms);
    return Number.isFinite(d.getTime()) ? d : null;
  }
  const raw = cleanText(value, 100);
  if (!raw) return null;
  const d = new Date(raw);
  return Number.isFinite(d.getTime()) ? d : null;
}

function fixtureFromObject(obj) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return null;
  const homeRaw = firstValue(obj, ['homeTeam', 'home_team', 'home', 'team1', 'homeClub', 'home_club']);
  const awayRaw = firstValue(obj, ['awayTeam', 'away_team', 'away', 'team2', 'awayClub', 'away_club']);
  const home = teamName(homeRaw);
  const away = teamName(awayRaw);
  if (!home || !away || (!isCrown(home) && !isCrown(away))) return null;

  const date = asDate(firstValue(obj, [
    'scheduledAt', 'scheduled_at', 'kickoff', 'kickoffAt', 'kickoff_at', 'startTime', 'start_time',
    'matchDate', 'match_date', 'date', 'datetime', 'startsAt', 'starts_at'
  ]));
  const status = cleanText(firstValue(obj, ['status', 'matchStatus', 'match_status', 'state']) || 'Scheduled', 30);
  const competition = cleanText(firstValue(obj, ['competitionName', 'competition_name', 'competition', 'leagueName', 'league_name', 'league']) || 'MLPC', 80);
  const round = cleanText(firstValue(obj, ['roundName', 'round_name', 'round', 'matchday', 'matchDay', 'week']) || '', 50);
  const id = cleanText(firstValue(obj, ['id', 'matchId', 'match_id', 'fixtureId', 'fixture_id']) || `${home}|${away}|${date ? date.toISOString() : ''}`, 160);
  const homeScore = firstValue(obj, ['homeScore', 'home_score', 'scoreHome', 'score_home']);
  const awayScore = firstValue(obj, ['awayScore', 'away_score', 'scoreAway', 'score_away']);
  const hasScore = Number.isFinite(Number(homeScore)) && Number.isFinite(Number(awayScore));
  return {
    id, home, away, date: date ? date.toISOString() : null, status, competition, round,
    score: hasScore ? `${Number(homeScore)}-${Number(awayScore)}` : '',
    sourceUrl: TEAM_URL,
  };
}

function collectFixtures(value, output = [], seen = new Set(), depth = 0) {
  if (depth > 14 || value === null || value === undefined) return output;
  if (Array.isArray(value)) {
    for (const item of value) collectFixtures(item, output, seen, depth + 1);
    return output;
  }
  if (typeof value !== 'object') return output;
  const fixture = fixtureFromObject(value);
  if (fixture && !seen.has(fixture.id)) {
    seen.add(fixture.id);
    output.push(fixture);
  }
  for (const child of Object.values(value)) collectFixtures(child, output, seen, depth + 1);
  return output;
}

function decodeHtml(value) {
  return String(value || '')
    .replace(/&quot;/g, '"').replace(/&#34;/g, '"').replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#39;/g, "'");
}

function parseJsonScripts(html) {
  const values = [];
  const scriptRegex = /<script[^>]*>([\s\S]*?)<\/script>/gi;
  let match;
  while ((match = scriptRegex.exec(html))) {
    const body = decodeHtml(match[1]).trim();
    if (!body) continue;
    if (body.startsWith('{') || body.startsWith('[')) {
      try { values.push(JSON.parse(body)); } catch {}
    }
    const nextData = body.match(/__NEXT_DATA__\s*=\s*({[\s\S]+})\s*;?$/);
    if (nextData) {
      try { values.push(JSON.parse(nextData[1])); } catch {}
    }
    if (/crown\s*fc|crownfc|\bCLT\b/i.test(body)) {
      const unescaped = body.replace(/\\"/g, '"').replace(/\\n/g, ' ');
      const fragments = unescaped.match(/\{[^{}]{0,4000}(?:CrownFC|crownfc|Crown FC|\"CLT\")[^{}]{0,4000}\}/g) || [];
      for (const fragment of fragments.slice(0, 100)) {
        try { values.push(JSON.parse(fragment)); } catch {}
      }
    }
  }
  return values;
}

function parseVisibleFixtureText(html) {
  const text = decodeHtml(html)
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, '\n')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{2,}/g, '\n');
  const lines = text.split('\n').map(line => line.trim()).filter(Boolean);
  const output = [];
  for (let i = 0; i < lines.length; i += 1) {
    const window = lines.slice(Math.max(0, i - 3), i + 5).join(' | ');
    if (!/crown\s*fc|crownfc|\bCLT\b/i.test(window)) continue;
    const dateMatch = window.match(/(20\d{2}-\d{2}-\d{2}(?:[T ][0-9:.-]+Z?)?|(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+[A-Z][a-z]+\s+\d{1,2}(?:,\s*20\d{2})?(?:\s+\d{1,2}:\d{2}\s*(?:AM|PM|ET|EST|EDT))?)/i);
    if (!dateMatch) continue;
    const date = asDate(dateMatch[1]);
    if (!date) continue;
    const teams = window.split('|').map(cleanText).filter(Boolean);
    const crownIndex = teams.findIndex(isCrown);
    if (crownIndex < 0) continue;
    const opponent = teams.find((item, index) => index !== crownIndex && item.length >= 3 && item.length <= 60 && !/schedule|season|match|overview|stats|roster|standings|transfer|achievement|virtualeagues/i.test(item));
    if (!opponent) continue;
    const home = crownIndex < teams.indexOf(opponent) ? teams[crownIndex] : opponent;
    const away = home === teams[crownIndex] ? opponent : teams[crownIndex];
    output.push({ id: `text|${home}|${away}|${date.toISOString()}`, home, away, date: date.toISOString(), status: 'Scheduled', competition: 'MLPC', round: '', score: '', sourceUrl: TEAM_URL });
  }
  return output;
}

function dedupeFixtures(fixtures) {
  const map = new Map();
  for (const fixture of fixtures) {
    const key = [normalize(fixture.home), normalize(fixture.away), fixture.date || '', fixture.round || ''].join('|');
    if (!map.has(key)) map.set(key, fixture);
  }
  return [...map.values()].sort((a, b) => {
    const at = a.date ? new Date(a.date).getTime() : Number.MAX_SAFE_INTEGER;
    const bt = b.date ? new Date(b.date).getTime() : Number.MAX_SAFE_INTEGER;
    return at - bt;
  });
}

async function fetchSchedule() {
  const response = await fetch(TEAM_URL, {
    headers: {
      'accept': 'text/html,application/xhtml+xml,application/json',
      'user-agent': 'RT-Football-Media/1.0 (+Discord CrownFC schedule sync)',
      'cache-control': 'no-cache',
    },
    signal: AbortSignal.timeout(20000),
  });
  if (!response.ok) throw new Error(`Virtualeagues returned HTTP ${response.status}.`);
  const body = await response.text();
  const values = parseJsonScripts(body);
  let fixtures = [];
  for (const value of values) fixtures.push(...collectFixtures(value));
  if (!fixtures.length) fixtures = parseVisibleFixtureText(body);
  return dedupeFixtures(fixtures);
}

function formatDate(iso) {
  if (!iso) return 'Date TBD';
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) return 'Date TBD';
  return new Intl.DateTimeFormat('en-US', {
    timeZone: TIMEZONE, weekday: 'short', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
  }).format(date);
}

function isFinished(fixture) {
  return /ft|full|final|completed|forfeit|played/i.test(fixture.status || '') || Boolean(fixture.score);
}

function upcomingFixtures(fixtures) {
  const now = Date.now() - 6 * 60 * 60 * 1000;
  return fixtures.filter(fixture => !isFinished(fixture) && (!fixture.date || new Date(fixture.date).getTime() >= now));
}

function opponentFor(fixture) {
  return isCrown(fixture.home) ? fixture.away : fixture.home;
}

function locationFor(fixture) {
  return isCrown(fixture.home) ? 'Home' : 'Away';
}

function scheduleEmbed(fixtures) {
  const upcoming = upcomingFixtures(fixtures).slice(0, 12);
  const embed = new EmbedBuilder()
    .setColor(0x7bafd4)
    .setTitle('👑 CrownFC • MLPC Schedule')
    .setURL(TEAM_URL)
    .setDescription(upcoming.length
      ? 'Live schedule synced from CrownFC on Virtualeagues. This message updates when the published fixture data changes.'
      : 'No upcoming CrownFC fixtures were returned by Virtualeagues on the latest check.')
    .setFooter({ text: `Virtualeagues sync • ${TIMEZONE} • Checked ${new Intl.DateTimeFormat('en-US', { timeZone: TIMEZONE, dateStyle: 'medium', timeStyle: 'short' }).format(new Date())}` });
  if (upcoming.length) {
    embed.addFields(upcoming.map((fixture, index) => ({
      name: `${fixture.round ? fixture.round + ' • ' : ''}${index + 1}. vs ${opponentFor(fixture)}`.slice(0, 256),
      value: `📅 ${formatDate(fixture.date)}\n🏟️ ${locationFor(fixture)}${fixture.competition && !/^mlpc$/i.test(fixture.competition) ? ` • ${fixture.competition}` : ''}`.slice(0, 1024),
      inline: false,
    })));
  }
  return embed;
}

function nextMatchEmbed(fixtures) {
  const fixture = upcomingFixtures(fixtures)[0];
  const embed = new EmbedBuilder().setColor(0x7bafd4).setTitle('👑 CrownFC • Next MLPC Match').setURL(TEAM_URL);
  if (!fixture) return embed.setDescription('No upcoming CrownFC MLPC fixture is currently available from Virtualeagues.');
  return embed
    .setDescription(`**CrownFC vs ${opponentFor(fixture)}**`)
    .addFields(
      { name: 'Kickoff', value: formatDate(fixture.date), inline: true },
      { name: 'Venue', value: locationFor(fixture), inline: true },
      { name: 'Round', value: fixture.round || 'TBD', inline: true },
    )
    .setFooter({ text: 'Source: Virtualeagues' });
}

function normalizedChannelName(channel) {
  return String(channel?.name || '').toLowerCase().replace(/^[^a-z0-9]+/, '');
}

async function scheduleChannelFor(guild) {
  if (process.env.MLPC_SCHEDULE_CHANNEL_ID) {
    const configured = await guild.channels.fetch(process.env.MLPC_SCHEDULE_CHANNEL_ID).catch(() => null);
    if (configured?.isTextBased()) return configured;
  }
  await guild.channels.fetch();
  return guild.channels.cache.find(channel => channel.isTextBased() && ['mlpc-match-center', 'mlpc-schedule'].includes(normalizedChannelName(channel))) || null;
}

function fingerprint(fixtures) {
  return JSON.stringify(fixtures.map(f => [f.id, f.home, f.away, f.date, f.status, f.score, f.round]));
}

async function syncSchedule(client, stateStore, options = {}) {
  const guild = process.env.DISCORD_GUILD_ID
    ? await client.guilds.fetch(process.env.DISCORD_GUILD_ID).catch(() => null)
    : client.guilds.cache.first();
  if (!guild) throw new Error('The configured Discord server could not be found.');
  const channel = await scheduleChannelFor(guild);
  if (!channel) throw new Error('CrownFC schedule channel not found. Keep mlpc-match-center, mlpc-schedule, or set MLPC_SCHEDULE_CHANNEL_ID.');
  const fixtures = await fetchSchedule();
  if (!fixtures.length) throw new Error('Virtualeagues loaded, but no CrownFC fixture data was exposed on the public team page. No Discord schedule was changed.');

  const metadataKey = `virtualeaguesSchedule:${guild.id}`;
  const saved = stateStore.getMetadata(metadataKey) || {};
  const currentFingerprint = fingerprint(fixtures);
  let message = saved.messageId ? await channel.messages.fetch(saved.messageId).catch(() => null) : null;
  if (!message) {
    const recent = await channel.messages.fetch({ limit: 50 }).catch(() => null);
    message = recent?.find(item => item.author.id === client.user.id && item.embeds[0]?.title === '👑 CrownFC • MLPC Schedule') || null;
  }

  const payload = { embeds: [scheduleEmbed(fixtures)], allowedMentions: { parse: [] } };
  if (!message) {
    message = await channel.send(payload);
    await message.pin('CrownFC MLPC schedule').catch(() => {});
  } else if (saved.fingerprint !== currentFingerprint || options.force) {
    await message.edit(payload);
  }

  stateStore.setMetadata(metadataKey, {
    channelId: channel.id,
    messageId: message.id,
    fingerprint: currentFingerprint,
    fixtures,
    checkedAt: new Date().toISOString(),
    sourceUrl: TEAM_URL,
  });
  return { fixtures, channel, message, changed: saved.fingerprint !== currentFingerprint };
}

async function cachedOrFresh(client, stateStore) {
  const guild = process.env.DISCORD_GUILD_ID
    ? await client.guilds.fetch(process.env.DISCORD_GUILD_ID).catch(() => null)
    : client.guilds.cache.first();
  const cached = guild ? stateStore.getMetadata(`virtualeaguesSchedule:${guild.id}`) : null;
  if (cached?.fixtures?.length && cached.checkedAt && Date.now() - new Date(cached.checkedAt).getTime() < 10 * 60 * 1000) return cached.fixtures;
  return (await syncSchedule(client, stateStore)).fixtures;
}

async function registerScheduleCommands(guild) {
  const definitions = [
    new SlashCommandBuilder().setName('schedule').setDescription('Show the current CrownFC MLPC schedule'),
    new SlashCommandBuilder().setName('nextmatch').setDescription('Show CrownFC’s next MLPC fixture'),
    new SlashCommandBuilder().setName('sync-mlpc-schedule').setDescription('Force a fresh CrownFC schedule sync from Virtualeagues')
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild),
  ].map(command => command.toJSON());
  const existing = await guild.commands.fetch();
  for (const definition of definitions) {
    const found = existing.find(command => command.name === definition.name);
    if (found) await guild.commands.edit(found.id, definition);
    else await guild.commands.create(definition);
  }
}

async function startVirtualeaguesSchedule(client, stateStore) {
  const guild = process.env.DISCORD_GUILD_ID
    ? await client.guilds.fetch(process.env.DISCORD_GUILD_ID).catch(() => null)
    : client.guilds.cache.first();
  if (!guild) throw new Error('The configured Discord server could not be found for the MLPC schedule sync.');
  await registerScheduleCommands(guild);

  if (!client.__virtualeaguesScheduleListener) {
    client.__virtualeaguesScheduleListener = true;
    client.on('interactionCreate', async interaction => {
      if (!interaction.isChatInputCommand() || !['schedule', 'nextmatch', 'sync-mlpc-schedule'].includes(interaction.commandName)) return;
      try {
        if (interaction.commandName === 'sync-mlpc-schedule') {
          await interaction.deferReply({ ephemeral: true });
          const result = await syncSchedule(client, stateStore, { force: true });
          return interaction.editReply(`CrownFC schedule synced from Virtualeagues: ${upcomingFixtures(result.fixtures).length} upcoming fixture(s). Schedule board: ${result.channel}`);
        }
        await interaction.deferReply();
        const fixtures = await cachedOrFresh(client, stateStore);
        if (interaction.commandName === 'nextmatch') return interaction.editReply({ embeds: [nextMatchEmbed(fixtures)] });
        return interaction.editReply({ embeds: [scheduleEmbed(fixtures)] });
      } catch (error) {
        const message = `CrownFC schedule sync could not read verified fixture data from Virtualeagues right now: ${cleanText(error.message, 220)}`;
        if (interaction.deferred || interaction.replied) await interaction.editReply(message).catch(() => {});
        else await interaction.reply({ content: message, ephemeral: true }).catch(() => {});
      }
    });
  }

  await syncSchedule(client, stateStore).catch(error => console.error('Initial Virtualeagues CrownFC schedule sync failed:', error.message));
  const timer = setInterval(() => {
    syncSchedule(client, stateStore).catch(error => console.error('Virtualeagues CrownFC schedule sync failed:', error.message));
  }, POLL_MINUTES * 60 * 1000);
  timer.unref?.();
  console.log(`Virtualeagues CrownFC schedule sync enabled every ${POLL_MINUTES} minutes.`);
}

module.exports = {
  startVirtualeaguesSchedule,
  fetchSchedule,
  collectFixtures,
  parseJsonScripts,
  scheduleEmbed,
  nextMatchEmbed,
};
