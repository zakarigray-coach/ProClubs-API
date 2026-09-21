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
  AttachmentBuilder,
  StringSelectMenuBuilder,
  Partials,
} = require('discord.js');

const sharp = require('sharp');

let OpenAI;
try { OpenAI = require('openai'); } catch { OpenAI = null; }

const pendingAudits = new Map();
const pendingSignings = new Map();
const pendingPlayerQuotes = new Map();
const QUOTE_WAIT_MS = Math.max(2, Number(process.env.QUOTE_WAIT_MINUTES) || 10) * 60 * 1000;
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
    reporterCompetition: 'the Masters Premier League’s Tier League 1 division',
    outlet: 'Raine at St. Andrew’s', color: 0x00a1e4, emoji: '🔵',
    voice: 'Polished and observant football journalism with a grounded matchday tone. Connect the signing to Birmingham City, St. Andrew’s, and the MPL challenge without overhyping it.',
    alertRoleEnv: 'BIRMINGHAM_ROLE_ID',
  },
  crownfc: {
    label: 'CrownFC', league: 'MLPC', reporter: 'Teagan',
    reporterCompetition: 'MLPC',
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

function extractJson(value) {
  const text = String(value || '').trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  const start = text.indexOf('{');
  const end = text.lastIndexOf('}');
  if (start < 0 || end < start) throw new Error('The AI response did not contain newspaper data.');
  return JSON.parse(text.slice(start, end + 1));
}

function normalizeStory(team, type, value, facts) {
  const source = value || {};
  const playerName = clean(source.playerName || facts.player || 'NEW ARRIVAL', 40);
  const playerQuote = /^tru$/i.test(playerName)
    ? 'Because I’m a baller.'
    : clean(source.playerQuote || '', 220);
  return {
    headline: clean(source.headline || (type === 'match' ? 'MATCHDAY VERDICT' : 'A NEW CHAPTER BEGINS'), 90).toUpperCase(),
    subheadline: clean(source.subheadline || team.label + ' make the news in ' + team.league, 140),
    playerName,
    playerNumber: clean(source.playerNumber || '', 8),
    body: clean(source.body || source.article || '', 700),
    playerQuote,
    leadershipQuote: clean(source.leadershipQuote || '', 220),
    leadershipRole: clean(source.leadershipRole || 'Club Representative', 40),
    reporterNote: clean(source.reporterNote || '', 220),
  };
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
      '\nThe supplied facts include the Discord message caption. Treat clear caption facts as authoritative. ' +
      'Read every legible fact in the attached graphic. If graphic text is unclear but the caption identifies the player, ' +
      'club, league, position, or number, use the caption and still write the complete story. Omit only details missing from both.',
  }];
  if (graphic) userContent.push({ type: 'input_image', image_url: graphic.url, detail: 'high' });

  const response = await client.responses.create({
    model: process.env.OPENAI_MODEL || 'gpt-5-mini',
    max_output_tokens: 700,
    input: [
      {
        role: 'system',
        content: 'You are ' + team.reporter + ', a football reporter for RT Football News covering ' +
          team.label + ' in ' + team.league + '. Your distinct writing voice: ' + team.voice + ' Analyze the supplied graphic according to the story type. ' +
          'For a match, identify visible teams, score, ratings, goals, assists, saves, cards, and other stats. ' +
          'For a signing, first use any player name, position, number, club, league, and signing angle supplied in the Discord caption, ' +
          'then read the player name, visible shirt number, club branding, league branding, and any other ' +
          'legible announcement details. If the player name is Tru, the all-caps headline must be exactly “A SIGNING THAT ' +
          'CHANGES EVERYTHING”. If the player name is Trap, the all-caps headline must be exactly “THE OFFENSIVE GAME-CHANGER ' +
          'ARRIVES” and the story must frame him as a major playmaking addition who can bring creativity and improve the attack, ' +
          'without inventing statistics or career history. For every other player, create a fresh headline suited to that particular ' +
          'signing and do not reuse “Marquee Signing” as a generic label. Create concise copy for a readable newspaper front page—not a long Discord article. ' +
          'Return only valid JSON with exactly these keys: headline, subheadline, playerName, playerNumber, body, playerQuote, ' +
          'leadershipQuote, leadershipRole, reporterNote. The headline must be all caps and no more than 9 words. The subheadline ' +
          'must be no more than 18 words. The body must be 50–70 words and cover the announcement plus what it could mean for ' +
          'the squad using only visible or supplied facts. Each quote must be 12–24 words. The reporterNote must be one sentence ' +
          'of no more than 22 words in the reporter’s voice. ' +
          'Use genuine supplied comments verbatim when available. Otherwise create varied simulated press-conference-style ' +
          'comments tied to the provided signing angle. Attribute the player comment to the visible player name. Attribute ' +
          'the leadership comment only to the provided role—Head Coach, Assistant Manager, Sporting Director, or Club Owner—' +
          'never invent a real person’s name. Each comment should sound conversational and specific, with one or two sentences. ' +
          'Avoid repeated stock phrases, invented career history, statistics, promises, or personal facts. Do not use Markdown.',
      },
      { role: 'user', content: userContent },
    ],
  });
  return normalizeStory(team, type, extractJson(response.output_text), facts);
}

function fallbackArticle(team, type, facts) {
  if (type === 'match') {
    return normalizeStory(team, type, {
      headline: 'MATCHDAY REPORT',
      subheadline: team.label + ' make the headlines in ' + team.league,
      body: facts.context || 'The match graphic was received, but automatic image analysis was unavailable.',
      reporterNote: 'The full story will develop as verified match details become available.',
    }, facts);
  }
  if (type === 'signing') {
    const playerName = facts.player || 'the club’s newest signing';
    return normalizeStory(team, type, {
      headline: 'A NEW CHAPTER BEGINS',
      subheadline: playerName + ' officially joins ' + team.label,
      playerName,
      body: team.label + ' has officially added ' + playerName + ' to the squad ahead of its ' +
        team.league + ' campaign. ' + (facts.details || 'The new arrival will now prepare to compete for a place and contribute to the group.'),
      playerQuote: facts.playerComment || 'I am ready to compete, learn the system and give everything for the group.',
      leadershipQuote: facts.clubComment || 'This addition gives us another strong option and raises the competition inside the squad.',
      leadershipRole: 'Club Representative',
      reporterNote: 'This is a move that adds fresh energy to the next chapter.',
    }, facts);
  }
  return normalizeStory(team, type, {
    headline: 'CLUB UPDATE',
    subheadline: team.label + ' confirm a squad departure',
    playerName: facts.player,
    body: team.label + ' confirms that ' + facts.player + ' has departed the club. ' +
      (facts.details || 'The club thanks the player for their time and wishes them the best moving forward.'),
    reporterNote: 'The squad now turns its attention toward the next stage of the campaign.',
  }, facts);
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

function escapeXml(value) {
  return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

function wrapLines(value, maxChars, maxLines) {
  const words = String(value || '').replace(/\s+/g, ' ').trim().split(' ').filter(Boolean);
  const lines = [];
  let line = '';
  for (const word of words) {
    const next = line ? line + ' ' + word : word;
    if (next.length <= maxChars || !line) line = next;
    else {
      lines.push(line);
      line = word;
      if (lines.length === maxLines) break;
    }
  }
  if (lines.length < maxLines && line) lines.push(line);
  if (words.length && lines.length === maxLines) {
    const joined = lines.join(' ');
    if (joined.length < String(value || '').trim().length) lines[maxLines - 1] = lines[maxLines - 1].replace(/[.,;:!?]?$/, '…');
  }
  return lines.slice(0, maxLines);
}

function tspans(lines, x, y, lineHeight, attrs) {
  return '<text x="' + x + '" y="' + y + '" ' + attrs + '>' + lines.map((line, index) =>
    '<tspan x="' + x + '" dy="' + (index ? lineHeight : 0) + '">' + escapeXml(line) + '</tspan>'
  ).join('') + '</text>';
}

async function fetchImage(url) {
  if (!url) return null;
  const response = await fetch(url);
  if (!response.ok) throw new Error('Unable to download the supplied graphic (' + response.status + ').');
  return Buffer.from(await response.arrayBuffer());
}

async function newspaperGraphic(team, type, story, graphic) {
  const width = 1080;
  const height = 1350;
  const teamColor = '#3b3125';
  const date = new Intl.DateTimeFormat('en-US', {
    timeZone: process.env.NEWS_TIMEZONE || 'America/New_York',
    month: 'short', day: '2-digit', year: 'numeric',
  }).format(new Date()).toUpperCase();
  const headlineLines = wrapLines(story.headline, 24, 2);
  const headlineSize = headlineLines.length > 1 ? 62 : 72;
  const bodyLines = wrapLines(story.body, 33, 9);
  const playerQuoteLines = wrapLines(story.playerQuote, 18, 5);
  const leaderQuoteLines = wrapLines(story.leadershipQuote, 18, 5);
  const noteLines = wrapLines(story.reporterNote, 52, 2);
  const reporterLines = team.reporter === 'Raine'
    ? ['RAINE AT', 'ST.', 'ANDREW’S']
    : ['TEAGAN', 'BEHIND THE', 'CROWN'];
  const numberLine = story.playerNumber ? ' • NO. ' + story.playerNumber : '';

  const svg = `
  <svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
    <rect width="1080" height="1350" fill="#e9e0cf"/>
    <filter id="paper"><feTurbulence baseFrequency="0.75" numOctaves="2" seed="8" type="fractalNoise"/><feColorMatrix values="0 0 0 0 0.72 0 0 0 0 0.70 0 0 0 0 0.64 0 0 0 .10 0"/></filter>
    <rect width="1080" height="1350" filter="url(#paper)" opacity=".38"/>
    <rect x="20" y="20" width="1040" height="1310" fill="none" stroke="#8f8a80" stroke-width="2"/>
    <text x="44" y="55" font-family="Arial, sans-serif" font-size="14" letter-spacing="5" fill="#222">FOOTBALL • PASSION • PEOPLE • A BIGGER TOMORROW</text>
    <line x1="42" y1="69" x2="1038" y2="69" stroke="#222" stroke-width="2"/>
    <text x="42" y="167" font-family="Georgia, serif" font-weight="900" font-size="103" fill="#25221d">RT</text>
    <text x="175" y="167" font-family="Georgia, serif" font-weight="900" font-size="93" letter-spacing="-5" fill="#111">FOOTBALL NEWS</text>
    <text x="1038" y="52" text-anchor="end" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="#111">${escapeXml(date)} • VOL. 1</text>
    <line x1="42" y1="187" x2="1038" y2="187" stroke="#222" stroke-width="2"/>
    <text x="42" y="213" font-family="Arial, sans-serif" font-size="15" letter-spacing="3" fill="#222">REAL PLAYERS. REAL STORIES. MORE THAN A GAME.</text>
    <text x="1038" y="213" text-anchor="end" font-family="Arial, sans-serif" font-size="15" font-weight="700" fill="${teamColor}">${escapeXml(team.label.toUpperCase())} • ${escapeXml(team.league)}</text>
    <rect x="42" y="232" width="996" height="474" fill="#cfc3ab" stroke="#26221c" stroke-width="3"/>
    <rect x="42" y="232" width="250" height="474" fill="#27231d" opacity=".98"/>
    ${tspans(reporterLines, 66, 292, 45, 'font-family="Georgia, serif" font-size="35" font-weight="800" fill="#fff"')}
    <line x1="66" y1="475" x2="180" y2="475" stroke="#b49a67" stroke-width="7"/>
    ${tspans(wrapLines(story.subheadline, 17, 5), 66, 520, 28, 'font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#fff" letter-spacing="1"')}
    <text x="66" y="678" font-family="Arial, sans-serif" font-size="16" letter-spacing="2" fill="#c4ad7c">EXCLUSIVE • ${escapeXml(type.toUpperCase())}</text>
    <rect x="292" y="232" width="746" height="474" fill="#b9ad95"/>
    <line x1="42" y1="721" x2="1038" y2="721" stroke="#29251f" stroke-width="8"/>
    ${tspans(headlineLines, 42, 790, 66, `font-family="Georgia, serif" font-size="${headlineSize}" font-weight="900" fill="#181613" letter-spacing="-1"`)}
    <text x="42" y="${headlineLines.length > 1 ? 930 : 865}" font-family="Arial, sans-serif" font-size="24" font-weight="700" letter-spacing="4" fill="#44382a">${escapeXml(team.label.toUpperCase())}${escapeXml(numberLine)} • ${escapeXml(team.league)}</text>
    <line x1="42" y1="${headlineLines.length > 1 ? 950 : 886}" x2="1038" y2="${headlineLines.length > 1 ? 950 : 886}" stroke="#1d1d1d" stroke-width="2"/>
    ${tspans(bodyLines, 42, headlineLines.length > 1 ? 990 : 925, 27, 'font-family="Georgia, serif" font-size="22" fill="#171717"')}
    <rect x="470" y="${headlineLines.length > 1 ? 978 : 914}" width="270" height="250" fill="#ded3bd" stroke="#29251f" stroke-width="3"/>
    <text x="492" y="${headlineLines.length > 1 ? 1023 : 959}" font-family="Georgia, serif" font-size="50" fill="#3f3528">“</text>
    ${tspans(playerQuoteLines, 505, headlineLines.length > 1 ? 1060 : 996, 29, 'font-family="Georgia, serif" font-size="22" font-style="italic" fill="#171512"')}
    <text x="720" y="${headlineLines.length > 1 ? 1202 : 1138}" text-anchor="end" font-family="Arial, sans-serif" font-size="17" font-weight="700" fill="#3f3528">— ${escapeXml(story.playerName || 'PLAYER')}</text>
    <rect x="760" y="${headlineLines.length > 1 ? 978 : 914}" width="278" height="250" fill="#ded3bd" stroke="#29251f" stroke-width="3"/>
    <text x="782" y="${headlineLines.length > 1 ? 1023 : 959}" font-family="Georgia, serif" font-size="50" fill="#3f3528">“</text>
    ${tspans(leaderQuoteLines, 795, headlineLines.length > 1 ? 1060 : 996, 29, 'font-family="Georgia, serif" font-size="22" font-style="italic" fill="#171512"')}
    <text x="1018" y="${headlineLines.length > 1 ? 1202 : 1138}" text-anchor="end" font-family="Arial, sans-serif" font-size="16" font-weight="700" fill="#3f3528">— ${escapeXml(story.leadershipRole.toUpperCase())}</text>
    <line x1="42" y1="1250" x2="1038" y2="1250" stroke="#222" stroke-width="2"/>
    <text x="42" y="1280" font-family="Arial, sans-serif" font-size="17" font-weight="700" fill="${teamColor}">REPORTER’S NOTE • ${escapeXml(team.reporter.toUpperCase())}</text>
    ${tspans(noteLines, 315, 1280, 23, 'font-family="Georgia, serif" font-size="18" font-style="italic" fill="#222"')}
    <text x="1038" y="1320" text-anchor="end" font-family="Arial, sans-serif" font-size="12" letter-spacing="2" fill="#555">SIMULATED COMMENTS WHEN NOT SUPPLIED • RT FOOTBALL MEDIA</text>
  </svg>`;

  const composites = [];
  if (graphic && graphic.url) {
    const source = await fetchImage(graphic.url);
    const photo = await sharp(source).rotate().grayscale().tint('#b3a284').modulate({ brightness: 0.92, saturation: 0.25 }).resize(746, 474, {
      fit: 'cover', position: 'north',
    }).png().toBuffer();
    composites.push({ input: photo, left: 292, top: 232 });
  }
  return sharp(Buffer.from(svg)).composite(composites).png({ compressionLevel: 9 }).toBuffer();
}

function newspaperAttachment(buffer, team, type) {
  const slug = (team.label + '-' + type + '-rt-football-news').toLowerCase().replace(/[^a-z0-9]+/g, '-');
  return new AttachmentBuilder(buffer, { name: slug + '.png' });
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
      GatewayIntentBits.GuildMembers,
      GatewayIntentBits.GuildMessages,
      GatewayIntentBits.DirectMessages,
      GatewayIntentBits.MessageContent,
    ],
    partials: [Partials.Channel],
  });
  client.once('ready', () => console.log('RT Football Media logged in as ' + client.user.tag));

  function reporterChannelFor(guild, team) {
    const reporterKeys = team === TEAMS.crownfc
      ? ['teagan-behind-the-crown', 'teagan-reports']
      : ['raine-at-st-andrews', 'raine-reports'];
    return guild.channels.cache.find(channel =>
      channel.type === ChannelType.GuildText &&
      reporterKeys.some(key => String(channel.name || '').toLowerCase().includes(key))
    );
  }

  async function publishNewspaper(destination, team, type, facts, graphic, alertRoleId, storyOverride) {
    const story = storyOverride ? { ...storyOverride } : await buildStory(team, type, facts, graphic);
    if (facts.player) story.playerName = clean(facts.player, 40);
    if (facts.playerComment) {
      story.playerQuote = /^tru$/i.test(story.playerName)
        ? 'Because I’m a baller.'
        : clean(facts.playerComment, 220);
    }
    const newspaper = await newspaperGraphic(team, type, story, graphic);
    const post = { files: [newspaperAttachment(newspaper, team, type)] };
    if (alertRoleId) {
      post.content = '<@&' + alertRoleId + '>';
      post.allowedMentions = { parse: [], roles: [alertRoleId] };
    }
    await destination.send(post);
  }

  async function finishPendingSigning(signingId, quote) {
    const pending = pendingSignings.get(signingId);
    if (!pending || pending.state === 'publishing' || pending.state === 'published') return;
    pending.state = 'publishing';
    if (pending.timeout) clearTimeout(pending.timeout);
    if (pending.selectedUserId) pendingPlayerQuotes.delete(pending.selectedUserId);

    try {
      const guild = await client.guilds.fetch(pending.guildId);
      const destination = await guild.channels.fetch(pending.destinationChannelId);
      if (!destination || !destination.isTextBased()) throw new Error('Reporter channel is unavailable.');
      const team = TEAMS[pending.teamKey];
      const facts = {
        context: pending.context,
        player: pending.selectedPlayerName,
        playerComment: clean(quote, 400),
      };
      await publishNewspaper(
        destination, team, 'signing', facts, pending.graphic, pending.alertRoleId, pending.draftStory
      );
      pending.state = 'published';
      const requester = await client.users.fetch(pending.requesterUserId).catch(() => null);
      if (requester) {
        await requester.send(
          quote
            ? 'The player replied, and the RT Football News front page has been published.'
            : 'The quote window closed, so the RT Football News front page was published with a clearly labeled simulated quote.'
        ).catch(() => {});
      }
    } catch (error) {
      pending.state = 'failed';
      console.error('Pending signing front page failed:', error);
      const requester = await client.users.fetch(pending.requesterUserId).catch(() => null);
      if (requester) await requester.send('I could not publish the RT Football News front page. Please check the Railway logs.').catch(() => {});
    } finally {
      pendingSignings.delete(signingId);
    }
  }

  async function askForSigningPlayer(message, team, teamKey, destination, graphic, alertRoleId, draftStory) {
    const role = alertRoleId ? await message.guild.roles.fetch(alertRoleId).catch(() => null) : null;
    if (!role) return false;

    await message.guild.members.fetch().catch(error => {
      console.warn('Could not refresh guild members for signing dropdown:', error.message);
    });
    const members = [...role.members.values()]
      .filter(member => !member.user.bot)
      .sort((a, b) => a.displayName.localeCompare(b.displayName))
      .slice(0, 25);
    if (!members.length) return false;

    const signingId = message.id;
    const menu = new StringSelectMenuBuilder()
      .setCustomId('signing_player:' + signingId)
      .setPlaceholder('Select the player who signed')
      .addOptions(members.map(member => ({
        label: clean(member.displayName, 100),
        description: clean('@' + member.user.username, 100),
        value: member.id,
      })));
    const row = new ActionRowBuilder().addComponents(menu);
    pendingSignings.set(signingId, {
      requesterUserId: message.author.id,
      guildId: message.guild.id,
      sourceChannelId: message.channel.id,
      destinationChannelId: destination.id,
      teamKey,
      context: clean(message.content, 1000),
      graphic,
      draftStory,
      alertRoleId,
      state: 'selecting',
      expiresAt: Date.now() + 15 * 60 * 1000,
    });

    try {
      await message.author.send({
        content: team.reporter + ' from RT Football News detected a ' + team.label +
          ' signing announcement. Select the signed player below. This request is private and only visible in your DMs.',
        components: [row],
      });
      setTimeout(() => {
        const pending = pendingSignings.get(signingId);
        if (pending && pending.state === 'selecting') {
          finishPendingSigning(signingId, null);
        }
      }, 15 * 60 * 1000);
      return true;
    } catch (error) {
      pendingSignings.delete(signingId);
      console.warn('Could not DM the private signing dropdown:', error.message);
      return false;
    }
  }

  client.on('messageCreate', async message => {
    if (message.author.bot || message.author.id === client.user.id) return;

    if (!message.guild) {
      const signingId = pendingPlayerQuotes.get(message.author.id);
      if (!signingId || !message.content.trim()) return;
      const pending = pendingSignings.get(signingId);
      if (!pending || pending.state !== 'waiting_for_quote') return;
      pendingPlayerQuotes.delete(message.author.id);
      await message.reply('Thank you—your quote has been sent to RT Football News for the signing front page.').catch(() => {});
      await finishPendingSigning(signingId, message.content);
      return;
    }

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
      const reporterChannel = reporterChannelFor(message.guild, team);
      const destination = reporterChannel || message.channel;
      const alertRoleId = process.env[team.alertRoleEnv];
      if (type === 'signing') {
        const draftStory = await buildStory(team, type, facts, graphic);
        const isTru = /^tru$/i.test(draftStory.playerName) ||
          /\btru\b/i.test(message.content) ||
          draftStory.headline === 'A SIGNING THAT CHANGES EVERYTHING';
        if (isTru) {
          draftStory.playerName = 'Tru';
          draftStory.playerQuote = 'Because I’m a baller.';
          await publishNewspaper(destination, team, type, facts, graphic, alertRoleId, draftStory);
          return;
        }
        const teamKey = team === TEAMS.crownfc ? 'crownfc' : 'birmingham';
        const waitingForQuote = await askForSigningPlayer(
          message, team, teamKey, destination, graphic, alertRoleId, draftStory
        );
        if (waitingForQuote) return;
        await publishNewspaper(destination, team, type, facts, graphic, alertRoleId, draftStory);
        return;
      }
      await publishNewspaper(destination, team, type, facts, graphic, alertRoleId);
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
    if (interaction.isStringSelectMenu() && interaction.customId.startsWith('signing_player:')) {
      const signingId = interaction.customId.split(':')[1];
      const pending = pendingSignings.get(signingId);
      if (!pending || pending.expiresAt < Date.now() || pending.state !== 'selecting') {
        pendingSignings.delete(signingId);
        return interaction.update({ content: 'This private signing request has expired.', components: [] });
      }
      if (interaction.user.id !== pending.requesterUserId) {
        return interaction.reply({ content: 'Only the person who posted the signing graphic can choose the player.', flags: MessageFlags.Ephemeral });
      }

      const selectedUserId = interaction.values[0];
      const guild = await client.guilds.fetch(pending.guildId);
      const member = await guild.members.fetch(selectedUserId).catch(() => null);
      if (!member || member.user.bot) {
        return interaction.update({ content: 'That player could not be contacted. Please post the graphic again and choose another player.', components: [] });
      }

      const team = TEAMS[pending.teamKey];
      pending.selectedUserId = member.id;
      pending.selectedPlayerName = member.displayName;
      pending.state = 'waiting_for_quote';
      pending.expiresAt = Date.now() + QUOTE_WAIT_MS;
      pendingPlayerQuotes.set(member.id, signingId);

      try {
        await member.send(
          'Hi ' + member.displayName + '—this is ' + team.reporter + ' from RT Football News, covering ' +
          team.label + ' in ' + team.reporterCompetition + '. Your signing has just been announced, and I’m preparing the front page.\n\n' +
          'Could you reply here with a quick quote about joining ' + team.label +
          ' and what supporters can expect from you? Please keep it to one or two sentences. Your reply may be published as your player quote.'
        );
        await interaction.update({
          content: team.reporter + ' has privately contacted ' + member.displayName +
            '. The vintage front page will publish after the player replies or the ' +
            Math.round(QUOTE_WAIT_MS / 60000) + '-minute quote window closes.',
          components: [],
        });
        pending.timeout = setTimeout(() => finishPendingSigning(signingId, null), QUOTE_WAIT_MS);
      } catch (error) {
        pendingPlayerQuotes.delete(member.id);
        await interaction.update({
          content: member.displayName + ' has DMs disabled. The front page will be published with a clearly labeled simulated quote.',
          components: [],
        });
        await finishPendingSigning(signingId, null);
      }
      return;
    }

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
    if (interaction.commandName === 'match') {
      facts = { context: clean(interaction.options.getString('context'), 1000) };
    } else if (interaction.commandName === 'signing') {
      facts = {
        player: clean(interaction.options.getString('player'), 100),
        position: clean(interaction.options.getString('position'), 100),
        playerComment: clean(interaction.options.getString('player_comment'), 400),
        clubComment: clean(interaction.options.getString('club_comment'), 400),
        details: clean(interaction.options.getString('details'), 700),
      };
    } else {
      facts = {
        player: clean(interaction.options.getString('player'), 100),
        details: clean(interaction.options.getString('details'), 700),
      };
    }

    const graphic = interaction.options.getAttachment('graphic');
    const story = await buildStory(team, interaction.commandName, facts, graphic);
    const newspaper = await newspaperGraphic(team, interaction.commandName, story, graphic);
    await interaction.editReply({ files: [newspaperAttachment(newspaper, team, interaction.commandName)] });
  });

  await client.login(token);
  return client;
}

module.exports = { startBot, newspaperGraphic };
