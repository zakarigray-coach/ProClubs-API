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
} = require('discord.js');

let OpenAI;
try { OpenAI = require('openai'); } catch { OpenAI = null; }

const TEAMS = {
  birmingham: {
    label: 'Birmingham City', league: 'MPL', reporter: 'Raine',
    outlet: 'Raine at St. Andrew’s', color: 0x00a1e4, emoji: '🔵',
  },
  crownfc: {
    label: 'CrownFC', league: 'MLPC', reporter: 'Teagan',
    outlet: 'Teagan Behind the Crown', color: 0x00b140, emoji: '👑',
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
  .addStringOption(o => o.setName('details').setDescription('Experience, strengths, or quote'))
  .addAttachmentOption(o => o.setName('graphic').setDescription('Optional signing graphic'));

const release = clubOption(new SlashCommandBuilder().setName('release').setDescription('Publish a player departure'))
  .addStringOption(o => o.setName('player').setDescription('Player name or gamer tag').setRequired(true))
  .addStringOption(o => o.setName('details').setDescription('Optional farewell note'));

const setupServer = new SlashCommandBuilder()
  .setName('setup-server')
  .setDescription('Create the RT Football Media category and reporter channels')
  .setDefaultMemberPermissions(PermissionFlagsBits.ManageChannels);

const commands = [match, signing, release, setupServer].map(command => command.toJSON());

function clean(value, max) {
  return String(value || '').trim().slice(0, max || 1000);
}

async function aiArticle(team, type, facts, graphic) {
  if (!process.env.OPENAI_API_KEY || !OpenAI) return null;
  const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  const userContent = [{
    type: 'input_text',
    text: 'Story type: ' + type + '\nSupplied facts: ' + JSON.stringify(facts) +
      '\nRead every legible fact in the attached graphic. If something is unclear, omit it.',
  }];
  if (graphic) userContent.push({ type: 'input_image', image_url: graphic.url, detail: 'high' });

  const response = await client.responses.create({
    model: process.env.OPENAI_MODEL || 'gpt-5-mini',
    max_output_tokens: 500,
    input: [
      {
        role: 'system',
        content: 'You are ' + team.reporter + ', a football reporter for RT Football Media covering ' +
          team.label + ' in ' + team.league + '. Analyze the supplied graphic according to the story type. ' +
          'For a match, identify visible teams, score, ratings, goals, assists, saves, cards, and other stats. ' +
          'For a signing, identify the visible player name, position, club branding, and announcement wording. ' +
          'Write an energetic social-media sports post using only visible or supplied facts. Never invent a stat, ' +
          'quote, player, position, or result. Start with a short all-caps headline, then write one or two short paragraphs.',
      },
      { role: 'user', content: userContent },
    ],
  });
  return clean(response.output_text, 2000) || null;
}

function fallbackArticle(team, type, facts) {
  if (type === 'match') {
    return 'The match graphic was received, but image analysis requires an OpenAI API key. ' +
      (facts.context ? facts.context : 'Add OPENAI_API_KEY to let the reporter read the score and stats automatically.');
  }
  if (type === 'signing') {
    return team.label + ' has officially added ' + facts.player + ' to the squad. The ' + facts.position +
      ' joins the club ahead of its ' + team.league + ' campaign.' +
      (facts.details ? ' ' + facts.details : '') + '\n\nWelcome to the club, ' + facts.player + '.';
  }
  return team.label + ' confirms that ' + facts.player + ' has departed the club.' +
    (facts.details ? ' ' + facts.details : '') + '\n\nThe club thanks ' + facts.player +
    ' for their time and wishes them the best moving forward.';
}

async function buildStory(team, type, facts, graphic) {
  try { return (await aiArticle(team, type, facts, graphic)) || fallbackArticle(team, type, facts); }
  catch (error) {
    console.error('AI generation failed; using built-in copy:', error.message);
    return fallbackArticle(team, type, facts);
  }
}

function makeEmbed(team, title, story, graphic) {
  const embed = new EmbedBuilder()
    .setColor(team.color)
    .setAuthor({ name: 'RT Football Media • ' + team.outlet })
    .setTitle(title)
    .setDescription(story)
    .setFooter({ text: 'Reported by ' + team.reporter + ' • ' + team.league })
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

    let team = null;
    if (location.includes('mlpc')) team = TEAMS.crownfc;
    else if (location.includes('mpl')) team = TEAMS.birmingham;
    if (!team) return;

    let type = null;
    if (channelName.includes('match-results')) type = 'match';
    else if (channelName.includes('signing-announcements')) type = 'signing';
    if (!type) return;

    const attachment = message.attachments.find(item =>
      (item.contentType && item.contentType.startsWith('image/')) ||
      /\.(png|jpe?g|webp|gif)$/i.test(item.url)
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
      const reporterKey = team === TEAMS.crownfc ? 'teagan-reports' : 'raine-reports';
      const reporterChannel = message.guild.channels.cache.find(channel =>
        channel.type === ChannelType.GuildText &&
        String(channel.name || '').toLowerCase().includes(reporterKey)
      );
      const destination = reporterChannel || message.channel;
      await destination.send({ embeds: [makeEmbed(team, title, story, graphic)] });
    } catch (error) {
      console.error('Automatic reporter post failed:', error);
    }
  });

  client.on('interactionCreate', async interaction => {
    if (!interaction.isChatInputCommand()) return;
    if (!['match', 'signing', 'release', 'setup-server'].includes(interaction.commandName)) return;
    await interaction.deferReply(interaction.commandName === 'setup-server' ? { flags: MessageFlags.Ephemeral } : {});

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
          key: 'raine-reports',
          name: '🔵・raine-reports',
          topic: 'Raine reporting on Birmingham City in MPL for RT Football Media.',
        },
        {
          key: 'teagan-reports',
          name: '👑・teagan-reports',
          topic: 'Teagan reporting on CrownFC in MLPC for RT Football Media.',
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
