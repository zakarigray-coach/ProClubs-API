const {
  Client,
  GatewayIntentBits,
  EmbedBuilder,
  SlashCommandBuilder,
  REST,
  Routes,
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

const match = clubOption(new SlashCommandBuilder().setName('match').setDescription('Publish an AI-style match report'))
  .addStringOption(o => o.setName('opponent').setDescription('Opponent').setRequired(true))
  .addIntegerOption(o => o.setName('our_score').setDescription('Your score').setRequired(true).setMinValue(0))
  .addIntegerOption(o => o.setName('their_score').setDescription('Opponent score').setRequired(true).setMinValue(0))
  .addStringOption(o => o.setName('details').setDescription('Scorers, assists, saves, MVP, and key moments').setRequired(true))
  .addAttachmentOption(o => o.setName('graphic').setDescription('Optional OurProClubs/result graphic'));

const signing = clubOption(new SlashCommandBuilder().setName('signing').setDescription('Announce a player signing'))
  .addStringOption(o => o.setName('player').setDescription('Player name or gamer tag').setRequired(true))
  .addStringOption(o => o.setName('position').setDescription('Position(s)').setRequired(true))
  .addStringOption(o => o.setName('details').setDescription('Experience, strengths, or quote'))
  .addAttachmentOption(o => o.setName('graphic').setDescription('Optional signing graphic'));

const release = clubOption(new SlashCommandBuilder().setName('release').setDescription('Publish a player departure'))
  .addStringOption(o => o.setName('player').setDescription('Player name or gamer tag').setRequired(true))
  .addStringOption(o => o.setName('details').setDescription('Optional farewell note'));

const commands = [match, signing, release].map(command => command.toJSON());

function clean(value, max) {
  return String(value || '').trim().slice(0, max || 1000);
}

async function aiArticle(team, type, facts) {
  if (!process.env.OPENAI_API_KEY || !OpenAI) return null;
  const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  const response = await client.responses.create({
    model: process.env.OPENAI_MODEL || 'gpt-5-mini',
    max_output_tokens: 350,
    input: [
      {
        role: 'system',
        content: 'You are ' + team.reporter + ', a football reporter for RT Football Media covering ' +
          team.label + ' in ' + team.league + '. Write energetic, credible Discord sports copy. ' +
          'Use only supplied facts. Never invent stats, quotes, or results. Return exactly two short paragraphs.',
      },
      { role: 'user', content: 'Story type: ' + type + '\nFacts: ' + JSON.stringify(facts) },
    ],
  });
  return clean(response.output_text, 1800) || null;
}

function fallbackArticle(team, type, facts) {
  if (type === 'match') {
    const result = facts.ourScore > facts.theirScore ? 'victory' :
      facts.ourScore < facts.theirScore ? 'defeat' : 'draw';
    return team.label + ' finished with a ' + facts.ourScore + '-' + facts.theirScore + ' ' + result +
      ' against ' + facts.opponent + '. ' + facts.details + '\n\nThe final whistle is in, and ' +
      team.reporter + ' has the story for RT Football Media.';
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

async function buildStory(team, type, facts) {
  try { return (await aiArticle(team, type, facts)) || fallbackArticle(team, type, facts); }
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
  const client = new Client({ intents: [GatewayIntentBits.Guilds] });
  client.once('ready', () => console.log('RT Football Media logged in as ' + client.user.tag));

  client.on('interactionCreate', async interaction => {
    if (!interaction.isChatInputCommand()) return;
    if (!['match', 'signing', 'release'].includes(interaction.commandName)) return;
    await interaction.deferReply();

    const team = TEAMS[interaction.options.getString('club')];
    if (!team) return interaction.editReply('That club is not configured.');

    let facts;
    let title;
    if (interaction.commandName === 'match') {
      facts = {
        opponent: clean(interaction.options.getString('opponent'), 100),
        ourScore: interaction.options.getInteger('our_score'),
        theirScore: interaction.options.getInteger('their_score'),
        details: clean(interaction.options.getString('details'), 1000),
      };
      title = team.emoji + ' FULL TIME | ' + team.label + ' ' + facts.ourScore + '-' +
        facts.theirScore + ' ' + facts.opponent;
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
    const story = await buildStory(team, interaction.commandName, facts);
    await interaction.editReply({ embeds: [makeEmbed(team, title, story, graphic)] });
  });

  await client.login(token);
  return client;
}

module.exports = { startBot };
