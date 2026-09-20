const {
  Client,
  GatewayIntentBits,
  EmbedBuilder,
  SlashCommandBuilder,
  REST,
  Routes,
  ChannelType,
  PermissionFlagsBits,
  MessageFlags,
  ButtonBuilder,
  ActionRowBuilder,
  ButtonStyle,
  SnowflakeUtil,
} = require('discord.js');

let OpenAI;
try { OpenAI = require('openai'); } catch { OpenAI = null; }

const pendingAudits = new Map();
const SOURCE_CHANNELS = {
  '1549837450854142002': { teamKey: 'birmingham', type: 'signing' },
  '1549837405761052853': { teamKey: 'crownfc', type: 'signing' },
};
const SIGNING_ANGLES = [
  'earning a starting place through competition',
  'tactical fit and understanding the club’s playing style',
  'leadership and standards inside the dressing room',
  'versatility and helping the squad in multiple situations',
  'club culture, trust, and becoming part of the group',
  'development, improvement, and learning from teammates',
  'ambition, trophies, and competing at the highest level',
  'handling pressure and delivering in important matches',
];
const LEADERSHIP_ROLES = ['Head Coach', 'Assistant Manager', 'Sporting Director', 'Club Owner'];

function randomChoice(items) {
  return items[Math.floor(Math.random() * items.length)];
}

const TEAMS = {
  birmingham: {
    label: 'Birmingham City', league: 'MPL', reporter: 'Raine',
    outlet: 'Raine at St. Andrew’s', color: 0x00a1e4, emoji: '🔵',
    voice: 'Polished and observant football journalism with a grounded matchday tone. Connect the signing to Birmingham City, St. Andrew’s, and the MPL challenge without overhyping it.',
    alertRoleEnv: 'BIRMINGHAM_ROLE_ID',
  },
  crownfc: {
    label: 'CrownFC', league: 'MLPC', reporter: 'Teagan',
    outlet: 'Teagan Behind the Crown', color: 0x7bafd4, emoji: '👑',
    voice: 'Confident, energetic, and personality-driven football reporting. Connect the signing to CrownFC ambition, competition, and what it means behind the Crown without becoming unrealistic.',
    alertRoleEnv: 'MLPC_ROLE_ID',
  },
};

function clubOption(command) {
  return command.addStringOption(o => o.setName('club').setDescription('Club').setRequired(true)
    .addChoices(
      { name: 'Birmingham City (Raine)', value: 'birmingham' },
      { name: 'CrownFC (Teagan)', value: 'crownfc' },
    ));
}

const match = clubOption(new SlashCommandBuilder().setName('match').setDescription('Turn a match graphic into a news article'))
  .addAttachmentOption(o => o.setName('graphic').setDescription('OurProClubs or match-stat graphic').setRequired(true))
  .addStringOption(o => o.setName('context').setDescription('Optional facts not visible in the graphic'));

const signing = clubOption(new SlashCommandBuilder().setName('signing').setDescription('Announce a player signing'))
  .addStringOption(o => o.setName('player').setDescription('Player name or gamer tag').setRequired(true))
  .addStringOption(o => o.setName('position').setDescription('Position(s)').setRequired(true))
  .addStringOption(o => o.setName('player_comment').setDescription('Optional real player comment; otherwise the bot creates a simulated one'))
  .addStringOption(o => o.setName('club_comment').setDescription('Optional real coach/owner comment; otherwise the bot creates a simulated one'))
  .addStringOption(o => o.setName('details').setDescription('Experience or additional signing details'))
  .addAttachmentOption(o => o.setName('graphic').setDescription('Optional signing graphic'));

const release = clubOption(new SlashCommandBuilder().setName('release').setDescription('Publish a player departure'))
  .addStringOption(o => o.setName('player').setDescription('Player name or gamer tag').setRequired(true))
  .addStringOption(o => o.setName('details').setDescription('Optional farewell note'));

const setupServer = new SlashCommandBuilder()
  .setName('setup-server')
  .setDescription('Create the RT Football Media category and reporter channels')
  .setDefaultMemberPermissions(PermissionFlagsBits.ManageChannels);

const auditServer = new SlashCommandBuilder()
  .setName('audit-server')
  .setDescription('Privately review cleanup opportunities before approving any changes')
  .addIntegerOption(option => option
    .setName('inactive_days')
    .setDescription('Flag text channels inactive for this many days (default 45)')
    .setMinValue(7)
    .setMaxValue(365))
  .setDefaultMemberPermissions(PermissionFlagsBits.ManageChannels);

const commands = [match, signing, release, setupServer, auditServer].map(command => command.toJSON());

function clean(value, max) {
  return String(value || '').trim().slice(0, max || 1000);
}

async function aiArticle(team, type, facts, graphic) {
  if (!process.env.OPENAI_API_KEY || !OpenAI) return null;
  const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  const signingDirection = type === 'signing' ? {
    angle: randomChoice(SIGNING_ANGLES),
    leadershipRole: randomChoice(LEADERSHIP_ROLES),
  } : null;
  const userContent = [{
    type: 'input_text',
    text: 'Story type: ' + type + '\nSupplied facts: ' + JSON.stringify(facts) +
      (signingDirection ? '\nSigning angle and management voice to use this time: ' +
        JSON.stringify(signingDirection) : '') +
      '\nRead every legible fact in the attached graphic. If something is unclear, omit it.',
  }];
  if (graphic) userContent.push({ type: 'input_image', image_url: graphic.url, detail: 'high' });

  const response = await client.responses.create({
    model: process.env.OPENAI_MODEL || 'gpt-5-mini',
    max_output_tokens: 900,
    input: [
      {
        role: 'system',
        content: 'You are ' + team.reporter + ', a football reporter for RT Football Media covering ' +
          team.label + ' in ' + team.league + '. Your distinct writing voice: ' + team.voice + ' Analyze the supplied graphic according to the story type. ' +
          'For a match, identify visible teams, score, ratings, goals, assists, saves, cards, and other stats. ' +
          'For a signing, first read the player name, visible shirt number, club branding, league branding, and any other ' +
          'legible announcement details. If the player name is Tru, the all-caps headline must be exactly “A SIGNING THAT ' +
          'CHANGES EVERYTHING”. For every other player, create a fresh headline suited to that particular signing and do not ' +
          'reuse “Marquee Signing” as a generic label. Write a complete football-reporter article—not a generic club caption. Use this ' +
          'structure: (1) a sharp all-caps headline, (2) a strong news lead announcing the move, (3) a paragraph explaining ' +
          'what the addition could mean for the squad using only visible/supplied facts, (4) exactly one natural player ' +
          'comment, (5) exactly one club-leadership comment, and (6) a final reporter-analysis sentence in your distinct voice. ' +
          'Use genuine supplied comments verbatim when available. Otherwise create varied simulated press-conference-style ' +
          'comments tied to the provided signing angle. Attribute the player comment to the visible player name. Attribute ' +
          'the leadership comment only to the provided role—Head Coach, Assistant Manager, Sporting Director, or Club Owner—' +
          'never invent a real person’s name. Each comment should sound conversational and specific, with one or two sentences. ' +
          'Avoid repeated stock phrases, invented career history, statistics, promises, or personal facts. Aim for 220–350 ' +
          'words and finish with the italic line “Simulated press-conference comments.”',
      },
      { role: 'user', content: userContent },
    ],
  });
  return clean(response.output_text, 3800) || null;
}

function fallbackArticle(team, type, facts) {
  if (type === 'match') {
    return 'The match graphic was received, but image analysis requires an OpenAI API key. ' +
      (facts.context ? facts.context : 'Add OPENAI_API_KEY to let the reporter read the score and stats automatically.');
  }
  if (type === 'signing') {
    const playerName = facts.player || 'the club’s newest signing';
    const playerComment = facts.playerComment
      ? '“' + facts.playerComment.replace(/^["“]|["”]$/g, '') + '” — ' + playerName
      : '';
    const clubComment = facts.clubComment
      ? '“' + facts.clubComment.replace(/^["“]|["”]$/g, '') + '” — Club representative'
      : '';
    const comments = [playerComment, clubComment].filter(Boolean).join('\n\n');
    return team.label + ' has officially added ' + playerName + ' to the squad ahead of its ' +
      team.league + ' campaign.' + (facts.details ? ' ' + facts.details : '') +
      (comments ? '\n\n' + comments : '') + '\n\nWelcome to the club, ' + playerName + '.';
  }
  return team.label + ' confirms that ' + facts.player + ' has departed the club.' +
    (facts.details ? ' ' + facts.details : '') + '\n\nThe club thanks ' + facts.player +
    ' for their time and wishes them the best moving forward.';
}

async function buildStory(team, type, facts, graphic) {
  try {
    const article = await aiArticle(team, type, facts, graphic);
    if (article) return article;
    if (graphic) throw new Error('AI article generation is unavailable. Check OPENAI_API_KEY and API billing.');
    return fallbackArticle(team, type, facts);
  } catch (error) {
    console.error('AI article generation failed:', {
      status: error.status,
      code: error.code,
      type: error.type,
      message: error.message,
    });
    if (graphic) throw error;
    return fallbackArticle(team, type, facts);
  }
}

function makeEmbed(team, title, story, graphic) {
  const logoUrl = process.env.RT_MEDIA_LOGO_URL;
  const author = { name: team.outlet };
  const footer = { text: team.reporter + ' • ' + team.league };
  if (logoUrl) {
    author.iconURL = logoUrl;
    footer.iconURL = logoUrl;
  }
  const embed = new EmbedBuilder()
    .setColor(team.color)
    .setAuthor(author)
    .setTitle(title)
    .setDescription(story)
    .setFooter(footer)
    .setTimestamp();
  if (graphic && graphic.contentType && graphic.contentType.startsWith('image/')) embed.setImage(graphic.url);
  return embed;
}

async function registerCommands(token, clientId, guildId) {
  const rest = new REST({ version: '10' }).setToken(token);
  const route = guildId ? Routes.applicationGuildCommands(clientId, guildId) : Routes.applicationCommands(clientId);
  await rest.put(route, { body: commands });
  console.log('Registered ' + commands.length + ' Discord commands.');
}

async function startBot() {
  const token = process.env.DISCORD_TOKEN;
  const clientId = process.env.DISCORD_CLIENT_ID;
  if (!token || !clientId) {
    console.log('Discord bot disabled: add DISCORD_TOKEN and DISCORD_CLIENT_ID to start it.');
    return null;
  }

  await registerCommands(token, clientId, process.env.DISCORD_GUILD_ID);
  const client = new Client({
    intents: [
      GatewayIntentBits.Guilds,
      GatewayIntentBits.GuildMessages,
      GatewayIntentBits.MessageContent,
    ],
  });
  client.once('ready', () => console.log('RT Football Media logged in as ' + client.user.tag));

  client.on('messageCreate', async message => {
    if (!message.guild || message.author.id === client.user.id) return;

    const channelName = String(message.channel.name || '').toLowerCase();
    const categoryName = String(message.channel.parent && message.channel.parent.name || '').toLowerCase();
    const location = categoryName + ' ' + channelName;

    const configuredSource = SOURCE_CHANNELS[message.channel.id];
    let team = configuredSource ? TEAMS[configuredSource.teamKey] : null;
    if (!team && location.includes('mlpc')) team = TEAMS.crownfc;
    else if (!team && (location.includes('mpl') || location.includes('ml1'))) team = TEAMS.birmingham;
    if (!team) return;

    let type = configuredSource ? configuredSource.type : null;
    if (!type && channelName.includes('match-results')) type = 'match';
    else if (!type && channelName.includes('signing-announcements')) type = 'signing';
    if (!type) return;

    console.log('Media graphic detected:', {
      channelId: message.channel.id,
      channelName,
      team: team.label,
      type,
      attachments: message.attachments.size,
      embeds: message.embeds.length,
    });

    const attachment = message.attachments.find(item =>
      (item.contentType && item.contentType.startsWith('image/')) ||
      /\.(png|jpe?g|webp|gif)(?:\?|$)/i.test(item.url)
    );
    const embeddedUrl = message.embeds.find(item => item.image && item.image.url)?.image?.url ||
      message.embeds.find(item => item.thumbnail && item.thumbnail.url)?.thumbnail?.url;
    const imageUrl = attachment ? attachment.url : embeddedUrl;
    if (!imageUrl) return;

    try {
      await message.channel.sendTyping();
      const graphic = { url: imageUrl, contentType: attachment && attachment.contentType || 'image/unknown' };
      const facts = { context: clean(message.content, 1000) };
      const story = await buildStory(team, type, facts, graphic);
      const title = type === 'match'
        ? team.emoji + ' MATCH REPORT | ' + team.label
        : team.emoji + ' OFFICIAL SIGNING | ' + team.label;
      const reporterKeys = team === TEAMS.crownfc
        ? ['teagan-behind-the-crown', 'teagan-reports']
        : ['raine-at-st-andrews', 'raine-reports'];
      const reporterChannel = message.guild.channels.cache.find(channel =>
        channel.type === ChannelType.GuildText &&
        reporterKeys.some(key => String(channel.name || '').toLowerCase().includes(key))
      );
      const destination = reporterChannel || message.channel;
      const alertRoleId = process.env[team.alertRoleEnv];
      const post = { embeds: [makeEmbed(team, title, story, graphic)] };
      if (alertRoleId) {
        post.content = '<@&' + alertRoleId + '>';
        post.allowedMentions = { parse: [], roles: [alertRoleId] };
      }
      await destination.send(post);
    } catch (error) {
      console.error('Automatic reporter post failed:', error);
      const diagnostic = error.status || error.code || 'unknown error';
      try {
        await message.channel.send(
          '⚠️ RT Football Media detected this graphic, but the AI article request failed (' +
          diagnostic + '). Check Railway logs. No incomplete reporter post was published.'
        );
      } catch {}
    }
  });

  client.on('interactionCreate', async interaction => {
    if (interaction.isButton() && interaction.customId.startsWith('server_audit:')) {
      const [, action, auditId] = interaction.customId.split(':');
      const audit = pendingAudits.get(auditId);
      if (!audit || audit.expiresAt < Date.now()) {
        pendingAudits.delete(auditId);
        return interaction.reply({ content: 'This audit approval has expired. Run /audit-server again.', flags: MessageFlags.Ephemeral });
      }
      if (interaction.user.id !== audit.ownerId) {
        return interaction.reply({ content: 'Only the person who requested this audit can approve it.', flags: MessageFlags.Ephemeral });
      }
      if (action === 'cancel') {
        pendingAudits.delete(auditId);
        return interaction.update({ content: 'Cleanup cancelled. No server changes were made.', embeds: [], components: [] });
      }

      const deleted = [];
      const skipped = [];
      for (const channelId of audit.emptyCategoryIds) {
        const category = interaction.guild.channels.cache.get(channelId);
        if (!category || category.type !== ChannelType.GuildCategory) {
          skipped.push(channelId + ' (missing)');
          continue;
        }
        const stillEmpty = !interaction.guild.channels.cache.some(channel => channel.parentId === category.id);
        if (!stillEmpty) {
          skipped.push(category.name + ' (no longer empty)');
          continue;
        }
        try {
          const name = category.name;
          await category.delete('Approved RT Football Media server cleanup');
          deleted.push(name);
        } catch {
          skipped.push(category.name + ' (permission error)');
        }
      }
      pendingAudits.delete(auditId);
      return interaction.update({
        content: 'Approved cleanup finished.\nDeleted empty categories: ' +
          (deleted.length ? deleted.join(', ') : 'none') +
          '\nSkipped: ' + (skipped.length ? skipped.join(', ') : 'none') +
          '\nNo channels, messages, or roles were deleted.',
        embeds: [],
        components: [],
      });
    }

    if (!interaction.isChatInputCommand()) return;
    if (!['match', 'signing', 'release', 'setup-server', 'audit-server'].includes(interaction.commandName)) return;
    const privateCommand = ['setup-server', 'audit-server'].includes(interaction.commandName);
    await interaction.deferReply(privateCommand ? { flags: MessageFlags.Ephemeral } : {});

    if (interaction.commandName === 'audit-server') {
      if (!interaction.memberPermissions.has(PermissionFlagsBits.ManageChannels)) {
        return interaction.editReply('You need the Manage Channels permission to run a server audit.');
      }

      const inactiveDays = interaction.options.getInteger('inactive_days') || 45;
      const cutoff = Date.now() - inactiveDays * 24 * 60 * 60 * 1000;
      const channels = [...interaction.guild.channels.cache.values()];
      const categories = channels.filter(channel => channel.type === ChannelType.GuildCategory);
      const textChannels = channels.filter(channel =>
        [ChannelType.GuildText, ChannelType.GuildAnnouncement, ChannelType.GuildForum].includes(channel.type)
      );

      const emptyCategories = categories.filter(category =>
        !channels.some(channel => channel.parentId === category.id)
      );
      const uncategorized = channels.filter(channel =>
        channel.type !== ChannelType.GuildCategory && channel.parentId === null
      );
      const inactive = textChannels.filter(channel => {
        if (!channel.lastMessageId) return true;
        return SnowflakeUtil.timestampFrom(channel.lastMessageId) < cutoff;
      });

      const nameGroups = new Map();
      for (const channel of channels.filter(item => item.type !== ChannelType.GuildCategory)) {
        const key = String(channel.name || '').toLowerCase();
        if (!nameGroups.has(key)) nameGroups.set(key, []);
        nameGroups.get(key).push(channel);
      }
      const duplicates = [...nameGroups.values()].filter(group => group.length > 1);

      const unusedRoles = [...interaction.guild.roles.cache.values()].filter(role =>
        role.id !== interaction.guild.id && !role.managed && role.members.size === 0
      );
      const adminRoles = [...interaction.guild.roles.cache.values()].filter(role =>
        role.id !== interaction.guild.id && role.permissions.has(PermissionFlagsBits.Administrator)
      );

      const list = (items, render) => {
        if (!items.length) return 'None found';
        const shown = items.slice(0, 12).map(render);
        if (items.length > 12) shown.push('…and ' + (items.length - 12) + ' more');
        return shown.join('\n').slice(0, 1024);
      };

      const report = new EmbedBuilder()
        .setColor(0x7BAFD4)
        .setTitle('RT Football Media • Server Cleanup Audit')
        .setDescription(
          'Review only—nothing has been changed. The approval button deletes only categories that are empty at approval time.'
        )
        .addFields(
          {
            name: 'Safe cleanup: empty categories (' + emptyCategories.length + ')',
            value: list(emptyCategories, item => '• ' + item.name),
          },
          {
            name: 'Inactive text channels, ' + inactiveDays + '+ days (' + inactive.length + ')',
            value: list(inactive, item => '• #' + item.name),
          },
          {
            name: 'Uncategorized channels (' + uncategorized.length + ')',
            value: list(uncategorized, item => '• ' + item.name),
          },
          {
            name: 'Duplicate channel names (' + duplicates.length + ' groups)',
            value: list(duplicates, group => '• ' + group[0].name + ' ×' + group.length),
          },
          {
            name: 'Unused roles—review manually (' + unusedRoles.length + ')',
            value: list(unusedRoles, item => '• ' + item.name),
          },
          {
            name: 'Administrator roles—security review (' + adminRoles.length + ')',
            value: list(adminRoles, item => '• ' + item.name),
          }
        )
        .setFooter({ text: 'Approval expires in 15 minutes • No messages, channels, or roles are auto-deleted' })
        .setTimestamp();

      const auditId = interaction.id;
      pendingAudits.set(auditId, {
        ownerId: interaction.user.id,
        emptyCategoryIds: emptyCategories.map(item => item.id),
        expiresAt: Date.now() + 15 * 60 * 1000,
      });
      setTimeout(() => pendingAudits.delete(auditId), 15 * 60 * 1000);

      const buttons = new ActionRowBuilder().addComponents(
        new ButtonBuilder()
          .setCustomId('server_audit:apply:' + auditId)
          .setLabel('Approve Safe Cleanup')
          .setStyle(ButtonStyle.Danger)
          .setDisabled(emptyCategories.length === 0),
        new ButtonBuilder()
          .setCustomId('server_audit:cancel:' + auditId)
          .setLabel('Cancel')
          .setStyle(ButtonStyle.Secondary)
      );
      return interaction.editReply({ embeds: [report], components: [buttons] });
    }

    if (interaction.commandName === 'setup-server') {
      if (!interaction.memberPermissions.has(PermissionFlagsBits.ManageChannels)) {
        return interaction.editReply('You need the Manage Channels permission to run this setup.');
      }

      const categoryName = '𓊆 📰 𓊇 RT FOOTBALL MEDIA';
      let category = interaction.guild.channels.cache.find(channel =>
        channel.type === ChannelType.GuildCategory &&
        String(channel.name || '').toLowerCase().includes('rt football media')
      );
      if (!category) {
        category = await interaction.guild.channels.create({
          name: categoryName,
          type: ChannelType.GuildCategory,
          reason: 'RT Football Media automatic setup',
        });
      }

      const reporterChannels = [
        {
          key: 'raine-at-st-andrews',
          name: '🔵・raine-at-st-andrews',
          topic: 'Raine at St. Andrew’s reporting on Birmingham City in MPL for RT Football Media.',
        },
        {
          key: 'teagan-behind-the-crown',
          name: '👑・teagan-behind-the-crown',
          topic: 'Teagan Behind the Crown reporting on CrownFC in MLPC for RT Football Media.',
        },
      ];

      const created = [];
      const existing = [];
      for (const reporter of reporterChannels) {
        let channel = interaction.guild.channels.cache.find(item =>
          item.type === ChannelType.GuildText &&
          String(item.name || '').toLowerCase().includes(reporter.key)
        );
        if (channel) {
          existing.push(channel.toString());
          if (channel.parentId !== category.id) await channel.setParent(category);
        } else {
          channel = await interaction.guild.channels.create({
            name: reporter.name,
            type: ChannelType.GuildText,
            parent: category.id,
            topic: reporter.topic,
            reason: 'RT Football Media automatic setup',
          });
          created.push(channel.toString());
        }
      }

      return interaction.editReply(
        'RT Football Media setup complete.\nCreated: ' +
        (created.length ? created.join(', ') : 'none') +
        '\nAlready available: ' + (existing.length ? existing.join(', ') : 'none')
      );
    }

    const team = TEAMS[interaction.options.getString('club')];
    if (!team) return interaction.editReply('That club is not configured.');

    let facts;
    let title;
    if (interaction.commandName === 'match') {
      facts = { context: clean(interaction.options.getString('context'), 1000) };
      title = team.emoji + ' MATCH REPORT | ' + team.label;
    } else if (interaction.commandName === 'signing') {
      facts = {
        player: clean(interaction.options.getString('player'), 100),
        position: clean(interaction.options.getString('position'), 100),
        playerComment: clean(interaction.options.getString('player_comment'), 400),
        clubComment: clean(interaction.options.getString('club_comment'), 400),
        details: clean(interaction.options.getString('details'), 700),
      };
      title = team.emoji + ' OFFICIAL: ' + facts.player + ' SIGNS';
    } else {
      facts = {
        player: clean(interaction.options.getString('player'), 100),
        details: clean(interaction.options.getString('details'), 700),
      };
      title = 'CLUB UPDATE: ' + facts.player;
    }

    const graphic = interaction.options.getAttachment('graphic');
    const story = await buildStory(team, interaction.commandName, facts, graphic);
    await interaction.editReply({ embeds: [makeEmbed(team, title, story, graphic)] });
  });

  await client.login(token);
  return client;
}

module.exports = { startBot };
