require('dotenv').config();
const express = require('express');
const cors = require('cors');
const { TextChannel, Message, MessageFlags } = require('discord.js');
const { buildResponse, archetypes, costModels } = require('./optimizer');
const reporterBot = require('./reporterBot');
const { startBot } = reporterBot;
const { mountClubPortal } = require('./clubPortal');

const app = express();
const PORT = process.env.PORT || 3000;
const botHealth = { status: 'starting', checkedAt: new Date().toISOString(), error: null };

app.use(cors());
app.use(express.json({ limit: '1mb' }));
app.set('trust proxy', 1);
mountClubPortal(app, { getClient: () => portalClient });
let portalClient = null;

app.get('/health', (req, res) => {
  const ok = botHealth.status !== 'error';
  res.status(ok ? 200 : 503).json({ ok, service: 'proclubs-custom-api', bot: botHealth.status, checkedAt: botHealth.checkedAt });
});

app.get('/archetypes', (req, res) => {
  res.json({ archetypes });
});

app.get('/cost-models/default', (req, res) => {
  res.json(costModels);
});

app.post('/optimize-build', (req, res) => {
  try {
    const result = buildResponse(req.body || {});
    if (result.error) return res.status(400).json(result);
    res.json(result);
  } catch (err) {
    res.status(400).json({ error: err.message || 'Unable to optimize build.' });
  }
});

app.post('/calculate-build', (req, res) => {
  try {
    const result = buildResponse(req.body || {});
    if (result.error) return res.status(400).json(result);
    res.json(result);
  } catch (err) {
    res.status(400).json({ error: err.message || 'Unable to calculate build.' });
  }
});

app.listen(PORT, () => {
  console.log(`proclubs-custom-api running on port ${PORT}`);
});

function retireLegacySlashCommands() {
  const retired = new Set(['signing']);
  if (Array.isArray(reporterBot.commands)) {
    for (let index = reporterBot.commands.length - 1; index >= 0; index -= 1) {
      if (retired.has(reporterBot.commands[index]?.name)) reporterBot.commands.splice(index, 1);
    }
  }
  if (Array.isArray(reporterBot.COMMAND_NAMES)) {
    for (let index = reporterBot.COMMAND_NAMES.length - 1; index >= 0; index -= 1) {
      if (retired.has(reporterBot.COMMAND_NAMES[index])) reporterBot.COMMAND_NAMES.splice(index, 1);
    }
  }
  console.log('Safe Phase 2: retired legacy slash commands:', [...retired].join(', '));
}

function isZeroGameMl1StatsPayload(payload) {
  const embed = payload?.embeds?.[0];
  const data = typeof embed?.toJSON === 'function' ? embed.toJSON() : (embed?.data || embed || {});
  const title = String(data.title || '');
  const fields = Array.isArray(data.fields) ? data.fields : [];
  const teamRecord = String(fields.find(field => String(field.name || '').toLowerCase() === 'team record')?.value || '');
  return /^Birmingham City\s*•/i.test(title) && /\*\*GP:\*\*\s*0\b/i.test(teamRecord);
}

function isMl1StatsChannel(channel) {
  const name = String(channel?.name || '').toLowerCase().replace(/^[^a-z0-9]+/, '');
  return name.includes('ml1-stats');
}

function suppressPrematureMl1StatsPosts() {
  if (TextChannel?.prototype?.send && !TextChannel.prototype.send.__rtMl1StatsGuard) {
    const originalSend = TextChannel.prototype.send;
    async function guardedSend(payload) {
      if (isMl1StatsChannel(this) && isZeroGameMl1StatsPayload(payload)) {
        console.log('ML1 stats post suppressed because no verified match has been played yet.');
        return {
          id: '0',
          pin: async () => null,
        };
      }
      return originalSend.call(this, payload);
    }
    guardedSend.__rtMl1StatsGuard = true;
    guardedSend.__rtOriginalSend = originalSend;
    TextChannel.prototype.send = guardedSend;
  }

  if (Message?.prototype?.edit && !Message.prototype.edit.__rtMl1StatsGuard) {
    const originalEdit = Message.prototype.edit;
    async function guardedEdit(payload) {
      if (isMl1StatsChannel(this.channel) && isZeroGameMl1StatsPayload(payload)) {
        console.log('ML1 zero-game stats edit suppressed; removing the stale stats post until a verified match exists.');
        await this.delete().catch(() => {});
        return this;
      }
      return originalEdit.call(this, payload);
    }
    guardedEdit.__rtMl1StatsGuard = true;
    guardedEdit.__rtOriginalEdit = originalEdit;
    Message.prototype.edit = guardedEdit;
  }
}

function disableLegacySigningChannelIntake(client) {
  if (!client) return;

  // /sign and /sign-batch already identify the player before collection begins.
  // The old channel watcher was still seeing transaction/signing posts and then
  // privately asking management to choose the player a second time. Keep the
  // DM package collector and match watcher, but ignore guild messages posted in
  // signing/transaction channels.
  const signingChannelIds = new Set([
    process.env.BIRMINGHAM_SIGNING_CHANNEL_ID,
    process.env.CROWNFC_SIGNING_CHANNEL_ID,
    '1549837450854142002',
    '1549837405761052853',
  ].filter(Boolean));

  const listeners = client.listeners('messageCreate');
  if (!listeners.length) return;

  client.removeAllListeners('messageCreate');
  for (const listener of listeners) {
    client.on('messageCreate', async message => {
      if (message.guild) {
        const channelName = String(message.channel?.name || '').toLowerCase();
        const legacySigningChannel = signingChannelIds.has(message.channelId) ||
          channelName.includes('signing-announcements') ||
          channelName.includes('transactions');
        if (legacySigningChannel) return;
      }
      return listener(message);
    });
  }

  console.log('Legacy signing-channel intake disabled. /sign and /sign-batch remain the signing entry points.');
}

function disableLegacySigningInteractions(client) {
  if (!client) return;
  const retiredPrefixes = [
    'signing_player:',
    'signing_facts:',
    'announcement_name:',
    'player_quote_only:',
    'player_package:',
    'quote:',
    'quote_submit:',
    'quote_owner:',
    'owner_quote_submit:',
    'number:start:quote:',
    'number:start:decline:',
  ];
  const listeners = client.listeners('interactionCreate');
  if (!listeners.length) return;

  client.removeAllListeners('interactionCreate');
  for (const listener of listeners) {
    client.on('interactionCreate', async interaction => {
      const customId = String(interaction.customId || '');
      if (retiredPrefixes.some(prefix => customId.startsWith(prefix))) {
        const payload = {
          content: 'This old RT Media signing control has been retired. Start or resume the player through `/sign`, `/sign-batch`, or `/signing-status`.',
        };
        if (interaction.inGuild?.()) payload.flags = MessageFlags.Ephemeral;
        try {
          if (interaction.deferred || interaction.replied) await interaction.followUp(payload);
          else await interaction.reply(payload);
        } catch {}
        return;
      }
      return listener(interaction);
    });
  }

  console.log('Legacy signing quote/player-selection controls disabled.');
}

async function cleanupPrematureMl1Stats(client) {
  if (!client?.user) return;
  try {
    const guild = process.env.DISCORD_GUILD_ID
      ? await client.guilds.fetch(process.env.DISCORD_GUILD_ID).catch(() => null)
      : client.guilds.cache.first();
    if (!guild) return;
    await guild.channels.fetch();
    const channel = guild.channels.cache.find(item => item.isTextBased?.() && isMl1StatsChannel(item));
    if (!channel?.messages) return;
    const recent = await channel.messages.fetch({ limit: 50 }).catch(() => null);
    if (!recent) return;
    const premature = recent.filter(message => {
      if (message.author?.id !== client.user.id) return false;
      const embed = message.embeds?.[0];
      return isZeroGameMl1StatsPayload({ embeds: embed ? [embed] : [] });
    });
    for (const message of premature.values()) {
      await message.delete().catch(() => {});
    }
    if (premature.size) console.log(`Removed ${premature.size} premature ML1 stats post(s).`);
  } catch (error) {
    console.error('ML1 stats cleanup failed:', error.message);
  }
}

retireLegacySlashCommands();
suppressPrematureMl1StatsPosts();

startBot().then(async client => {
  portalClient = client;
  disableLegacySigningChannelIntake(client);
  disableLegacySigningInteractions(client);
  await cleanupPrematureMl1Stats(client);
  botHealth.status = client ? 'ready' : 'disabled';
  botHealth.checkedAt = new Date().toISOString();
}).catch(err => {
  botHealth.status = 'error';
  botHealth.error = err.message;
  botHealth.checkedAt = new Date().toISOString();
  console.error('Discord bot failed to start:', err);
  process.exitCode = 1;
});
