const fs = require('fs');
const path = require('path');
const { AttachmentBuilder, ActionRowBuilder, ButtonBuilder, ButtonStyle, ChannelType } = require('discord.js');
const sharp = require('sharp');
const OpenAI = require('openai');

const TZ = process.env.NEWS_TIMEZONE || 'America/New_York';
const DATA_DIRECTORY = process.env.RT_DATA_DIR || path.join(__dirname, '.data');
const STATE_PATH = path.join(DATA_DIRECTORY, 'rt-player-spotlights.json');
const CHECK_MS = 10 * 60 * 1000;

const TEAM_CONFIG = {
  birmingham: {
    label: 'Birmingham City', league: 'MPL • LEAGUE 1', reporter: 'Raine',
    channelKeys: ['raine-at-st-andrews', 'raine-reports'], roleEnv: 'BIRMINGHAM_ROLE_ID',
    primary: '#0057B8', deep: '#003B7A', humor: 'dry, sharp, understated football humor',
  },
  crownfc: {
    label: 'CrownFC', league: 'MLPC', reporter: 'Teagan',
    channelKeys: ['teagan-behind-the-crown', 'teagan-reports'], roleEnv: 'MLPC_ROLE_ID',
    primary: '#7BAFD4', deep: '#15253A', humor: 'playful, energetic, cheeky football humor',
  },
};

const QUESTION_BANK = [
  'What has stood out to you most about the club since joining?',
  'How would you describe the direction the club is heading?',
  'What part of your game are you most confident in right now?',
  'What are you working on improving this season?',
  'What does a successful season look like to you personally?',
  'What does a successful season look like for the team?',
  'Which part of the club culture do you enjoy most?',
  'What kind of teammate do you try to be in the dressing room?',
  'What position or role brings out your best football?',
  'What do you think this squad can do when everything clicks?',
  'What is one thing supporters or teammates might not know about your approach to the game?',
  'Who on the squad pushes you to be better?',
  'What is your favorite type of match to play in?',
  'What is one moment with the club you have enjoyed so far?',
  'What do you want teammates to be able to count on you for?',
  'How do you reset after a rough match?',
  'What is one football habit or superstition you have?',
  'If you could describe this squad in three words, what would they be?',
  'What is one goal you want to check off before the season ends?',
  'What message would you give the rest of the squad heading into the next run of matches?',
  'Who has the best banter in the squad?',
  'What is the funniest harmless thing that has happened around the club so far?',
  'If your play style had a nickname, what would it be?',
  'What is one thing this team does better than people outside the club realize?',
];

function emptyState() {
  return { selected: { birmingham: [], crownfc: [] }, active: {}, history: [], lastRuns: {} };
}

function loadState() {
  try {
    if (!fs.existsSync(STATE_PATH)) return emptyState();
    return { ...emptyState(), ...JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')) };
  } catch (error) {
    console.error('Could not load player spotlight state:', error.message);
    return emptyState();
  }
}

let state = loadState();
function saveState() {
  fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });
  const temp = STATE_PATH + '.tmp';
  fs.writeFileSync(temp, JSON.stringify(state, null, 2));
  fs.renameSync(temp, STATE_PATH);
}

function etParts(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: TZ, weekday: 'short', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(date);
  const get = type => parts.find(part => part.type === type)?.value;
  return { weekday: get('weekday'), year: get('year'), month: get('month'), day: get('day'), hour: Number(get('hour')), minute: Number(get('minute')) };
}

function dateKey(parts) { return `${parts.year}-${parts.month}-${parts.day}`; }
function clean(value, max = 1000) { return String(value || '').trim().slice(0, max); }
function escapeXml(value) { return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;'); }
function wrapLines(value, maxChars, maxLines) {
  const words = String(value || '').replace(/\s+/g, ' ').trim().split(' ').filter(Boolean);
  const lines = []; let line = '';
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (next.length <= maxChars || !line) line = next;
    else { lines.push(line); line = word; if (lines.length === maxLines) break; }
  }
  if (lines.length < maxLines && line) lines.push(line);
  return lines.slice(0, maxLines);
}
function tspans(lines, x, y, lineHeight, attrs) {
  return `<text x="${x}" y="${y}" ${attrs}>${lines.map((line, index) => `<tspan x="${x}" dy="${index ? lineHeight : 0}">${escapeXml(line)}</tspan>`).join('')}</text>`;
}
function pickQuestions(seed) {
  const pool = [...QUESTION_BANK];
  let n = seed;
  const selected = [];
  while (selected.length < 5 && pool.length) {
    n = (n * 9301 + 49297) % 233280;
    selected.push(pool.splice(n % pool.length, 1)[0]);
  }
  return selected;
}
function reporterChannel(guild, config) {
  return guild.channels.cache.find(channel => channel.type === ChannelType.GuildText && config.channelKeys.some(key => String(channel.name || '').toLowerCase().includes(key)));
}
function ownerId(guild) { return process.env.BOT_OWNER_ID || guild.ownerId; }

async function choosePlayer(guild, teamKey) {
  const config = TEAM_CONFIG[teamKey];
  const roleId = process.env[config.roleEnv];
  if (!roleId) return null;
  await guild.members.fetch().catch(() => {});
  const role = guild.roles.cache.get(roleId) || await guild.roles.fetch(roleId).catch(() => null);
  if (!role) return null;
  const used = new Set(state.selected[teamKey] || []);
  const eligible = [...role.members.values()].filter(member => !member.user.bot && !used.has(member.id));
  if (!eligible.length) return null;
  return eligible[Math.floor(Math.random() * eligible.length)];
}

async function beginSpotlight(client, guild, teamKey) {
  const config = TEAM_CONFIG[teamKey];
  if (Object.values(state.active).some(item => item.teamKey === teamKey && !['published','cancelled'].includes(item.status))) return;
  const member = await choosePlayer(guild, teamKey);
  if (!member) {
    const owner = await client.users.fetch(ownerId(guild)).catch(() => null);
    if (owner) await owner.send(`🎙️ ${config.reporter} could not start this week's ${config.label} Player Spotlight because every current eligible player has already been featured (or the club role is empty). New roster members will automatically become eligible.`).catch(() => {});
    return;
  }
  const now = Date.now();
  const id = `${teamKey}-${now}`;
  const questions = pickQuestions(Number(String(now).slice(-7)) + member.id.slice(-4).split('').reduce((a,b)=>a+Number(b),0));
  state.selected[teamKey] = [...new Set([...(state.selected[teamKey] || []), member.id])];
  state.active[id] = {
    id, teamKey, userId: member.id, playerName: member.displayName, questions,
    status: 'waiting_response', createdAt: new Date().toISOString(), response: '', photoUrl: '', approved: false,
  };
  saveState();

  const user = await client.users.fetch(member.id).catch(() => null);
  if (!user) return;
  const list = questions.map((q, i) => `**${i + 1}.** ${q}`).join('\n');
  await user.send({
    content: `🎙️ **${config.reporter} from RT Football Media — Player Spotlight**\n\nYou've been randomly selected for this week's **${config.label} Player Spotlight** for Castle & Crown Collective. I just need five quick answers. Keep them as short or detailed as you like.\n\n${list}\n\nPlease reply in one message using **1–5** so I can match each answer to the question. You have through Friday to respond. You can also attach a player image if you'd like it considered for the feature. The spotlight is scheduled for Saturday at **10:00 AM Eastern** after club approval.`,
    allowedMentions: { parse: [] },
  }).catch(async () => {
    state.active[id].status = 'dm_failed'; saveState();
    const owner = await client.users.fetch(ownerId(guild)).catch(() => null);
    if (owner) await owner.send(`⚠️ ${config.reporter} selected **${member.displayName}** for Player Spotlight, but their DMs are closed. They will remain marked as selected so the feature rotation does not repeat them.`).catch(() => {});
  });
}

function parseAnswers(text, questions) {
  const raw = clean(text, 3500);
  const answers = [];
  for (let i = 1; i <= questions.length; i++) {
    const match = raw.match(new RegExp(`(?:^|\\n)\\s*${i}[.)-]?\\s*([\\s\\S]*?)(?=\\n\\s*${i + 1}[.)-]?\\s|$)`, 'i'));
    answers.push(match ? clean(match[1], 600) : '');
  }
  return answers;
}

async function buildSpotlightCopy(config, feature) {
  const hasResponse = Boolean(feature.response);
  const answers = hasResponse ? parseAnswers(feature.response, feature.questions) : [];
  if (!process.env.OPENAI_API_KEY) {
    return {
      headline: `${feature.playerName.toUpperCase()} IN THE SPOTLIGHT`,
      subheadline: hasResponse ? `${config.reporter} sits down with ${feature.playerName} for this week's ${config.label} feature.` : `${config.reporter} profiles ${feature.playerName} after the player was unavailable for this week's Q&A.`,
      article: hasResponse ? answers.map((a,i)=>a ? `${feature.questions[i]} — ${a}` : '').filter(Boolean).join(' ') : `${feature.playerName} is part of the ${config.label} squad. No interview answers were submitted before the deadline, so RT Football Media has not attributed any quotes to the player.`,
      reporterNote: hasResponse ? `Five quick questions, one player, and no press-conference podium required.` : `No fake quotes here. ${config.reporter} keeps the spotlight factual when a player misses the interview window.`,
    };
  }
  const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  const interview = hasResponse ? feature.questions.map((q,i)=>({ question:q, answer:answers[i] || '' })) : [];
  const response = await client.responses.create({
    model: process.env.OPENAI_MODEL || 'gpt-5-mini', max_output_tokens: 1100,
    input: [
      { role: 'system', content: `You are ${config.reporter}, RT Football Media's reporter covering ${config.label}. Write a professional weekly Player Spotlight for Castle & Crown Collective. Your humor style is ${config.humor}. Use an occasional clever football pun, dry aside, or light adult-but-professional joke when natural, but do not force humor into every paragraph. Never humiliate a player, joke about appearance or identity, use sexual humor, slurs, or make light of injuries or sensitive issues. Facts must stay accurate. NEVER invent a quote, answer, opinion, career fact, statistic, or personal detail. If no interview response was provided, clearly write an editorial profile based only on the verified fact that the named person is a member of the club; say no Q&A response was received and do not simulate an interview. Return JSON only with headline, subheadline, article, reporterNote.` },
      { role: 'user', content: JSON.stringify({ player: feature.playerName, club: config.label, league: config.league, interview, responded: hasResponse }) },
    ],
  });
  const text = String(response.output_text || '').replace(/^```(?:json)?\s*/i,'').replace(/\s*```$/,'');
  const start = text.indexOf('{'), end = text.lastIndexOf('}');
  const parsed = start >= 0 && end > start ? JSON.parse(text.slice(start,end+1)) : {};
  return {
    headline: clean(parsed.headline || `${feature.playerName} IN THE SPOTLIGHT`, 90).toUpperCase(),
    subheadline: clean(parsed.subheadline || `${config.reporter} profiles ${feature.playerName}.`, 180),
    article: clean(parsed.article || '', 3500),
    reporterNote: clean(parsed.reporterNote || '', 250),
  };
}

async function heroArtwork(config, feature) {
  if (feature.photoUrl) {
    try {
      const response = await fetch(feature.photoUrl);
      if (response.ok) return Buffer.from(await response.arrayBuffer());
    } catch {}
  }
  if (!process.env.OPENAI_API_KEY) return null;
  const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  const response = await client.images.generate({
    model: process.env.OPENAI_IMAGE_MODEL || 'gpt-image-2.5-sunburst',
    size: process.env.OPENAI_IMAGE_SIZE || '1536x1024', quality: process.env.OPENAI_IMAGE_QUALITY || 'medium',
    prompt: `Create a landscape professional football editorial image for a Player Spotlight about ${config.label}. Use ${config.primary}, ${config.deep}, black, white and stadium lighting. Do not depict an identifiable real person because no verified player photo is being used. Show a premium tunnel, dressing-room shirt silhouette, stadium seats, floodlights or training-ground scene. No words, logos, numbers, sponsors or watermarks. Leave negative space for newspaper typography.`,
  });
  const encoded = response?.data?.[0]?.b64_json;
  return encoded ? Buffer.from(encoded, 'base64') : null;
}

async function renderSpotlight(config, feature, copy) {
  const width=1080, height=1350, paper='#F1EEE7';
  const hero = await heroArtwork(config, feature);
  const articleLines = wrapLines(copy.article, 44, 18);
  const noteLines = wrapLines(copy.reporterNote, 48, 4);
  const headlineLines = wrapLines(copy.headline, 19, 3);
  const headSize = headlineLines.length >= 3 ? 58 : 72;
  const date = new Intl.DateTimeFormat('en-US',{timeZone:TZ,month:'short',day:'2-digit',year:'numeric'}).format(new Date()).toUpperCase();
  const svg = `<svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
  <rect width="1080" height="1350" fill="${paper}"/><rect x="14" y="14" width="1052" height="1322" fill="none" stroke="#151515" stroke-width="2"/>
  <rect x="18" y="18" width="1044" height="210" fill="#07111E"/><text x="58" y="121" font-family="DejaVu Sans" font-size="86" font-style="italic" font-weight="800" fill="#fff">RT</text><text x="205" y="130" font-family="DejaVu Sans" font-size="94" font-weight="900" fill="#fff">MEDIA</text><rect x="202" y="153" width="430" height="8" fill="${config.primary}"/><text x="211" y="195" font-family="DejaVu Sans" font-size="16" letter-spacing="7" fill="#E8EEF6">PRO CLUBS NEWS NETWORK</text>
  <text x="1018" y="80" text-anchor="end" font-family="DejaVu Sans" font-size="18" font-weight="800" fill="#fff">PLAYER SPOTLIGHT</text><text x="1018" y="110" text-anchor="end" font-family="DejaVu Sans" font-size="16" fill="#DCE6F3">${escapeXml(config.label.toUpperCase())}</text><text x="1018" y="140" text-anchor="end" font-family="DejaVu Sans" font-size="16" fill="#DCE6F3">${escapeXml(date)}</text>
  <rect x="18" y="238" width="1044" height="62" fill="${config.deep}"/><text x="50" y="279" font-family="DejaVu Sans" font-size="33" font-weight="900" fill="#fff">${escapeXml(feature.playerName.toUpperCase())}</text><text x="1030" y="277" text-anchor="end" font-family="DejaVu Sans" font-size="18" font-weight="800" fill="#fff">${escapeXml(config.league)}</text>
  ${headlineLines.map((line,i)=>`<text x="42" y="${385+i*(headSize+4)}" font-family="DejaVu Sans" font-size="${headSize}" font-weight="900" letter-spacing="-3" fill="${i===headlineLines.length-1 && headlineLines.length>1?config.primary:'#111'}">${escapeXml(line)}</text>`).join('')}
  ${tspans(wrapLines(copy.subheadline,76,2),42,585,27,'font-family="DejaVu Serif" font-size="22" font-weight="700" fill="#202020"')}
  <rect x="40" y="650" width="550" height="400" fill="#132033" stroke="#111" stroke-width="2"/>
  <rect x="610" y="650" width="438" height="400" fill="#F8F5EE" stroke="#111" stroke-width="2"/><text x="632" y="688" font-family="DejaVu Serif" font-size="25" font-weight="900" fill="#111">THE FEATURE</text>${tspans(articleLines,632,722,19,'font-family="DejaVu Serif" font-size="15" fill="#171717"')}
  <rect x="40" y="1070" width="1008" height="215" fill="#08111C"/><rect x="40" y="1070" width="9" height="215" fill="${config.primary}"/><text x="72" y="1110" font-family="DejaVu Sans" font-size="21" font-weight="800" fill="${config.primary}">${escapeXml(config.reporter.toUpperCase())} • PLAYER SPOTLIGHT</text>${tspans(noteLines,72,1150,25,'font-family="DejaVu Serif" font-size="18" font-style="italic" fill="#EAF0F6"')}<text x="1018" y="1260" text-anchor="end" font-family="DejaVu Sans" font-size="14" letter-spacing="2" fill="#fff">CASTLE &amp; CROWN COLLECTIVE</text>
  <rect x="18" y="1300" width="1044" height="36" fill="#07111E"/><text x="540" y="1324" text-anchor="middle" font-family="DejaVu Sans" font-size="14" letter-spacing="3" fill="#fff">RT MEDIA • REAL CLUBS. REAL STORIES. ALL FOOTBALL THAT MATTERS.</text></svg>`;
  const composites=[];
  if (hero) {
    const image = await sharp(hero).rotate().resize(546,396,{fit:'cover',position:'north'}).png().toBuffer();
    composites.push({input:image,left:42,top:652});
  }
  return sharp(Buffer.from(svg)).composite(composites).png({compressionLevel:9}).toBuffer();
}

async function preparePreview(client, guild, feature) {
  if (feature.previewSentAt) return;
  const config = TEAM_CONFIG[feature.teamKey];
  const copy = await buildSpotlightCopy(config, feature);
  const image = await renderSpotlight(config, feature, copy);
  const filePath = path.join(DATA_DIRECTORY, `spotlight-${feature.id}.png`);
  fs.mkdirSync(DATA_DIRECTORY,{recursive:true}); fs.writeFileSync(filePath,image);
  feature.copy=copy; feature.filePath=filePath; feature.status='awaiting_approval'; feature.previewSentAt=new Date().toISOString(); saveState();
  const owner = await client.users.fetch(ownerId(guild)).catch(()=>null);
  if (!owner) return;
  const row = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId(`spotlight:approve:${feature.id}`).setLabel('Approve Saturday Spotlight').setStyle(ButtonStyle.Success),
    new ButtonBuilder().setCustomId(`spotlight:hold:${feature.id}`).setLabel('Hold').setStyle(ButtonStyle.Secondary)
  );
  await owner.send({
    content: `🗞️ **${config.reporter}'s ${config.label} Player Spotlight preview**\nFeatured player: **${feature.playerName}**\n${feature.response ? 'The article uses only the player’s submitted answers.' : 'No response was received. This is an editorial profile with **no fabricated interview answers or quotes**.'}\n\nApprove it now and the bot will hold publication until **Saturday at 10:00 AM Eastern**.`,
    files:[new AttachmentBuilder(image,{name:`${feature.teamKey}-player-spotlight.png`})], components:[row], allowedMentions:{parse:[]}
  }).catch(()=>{});
}

async function publishFeature(client, guild, feature) {
  if (!feature.approved || feature.status === 'published' || !feature.filePath || !fs.existsSync(feature.filePath)) return;
  const config = TEAM_CONFIG[feature.teamKey];
  const channel = reporterChannel(guild, config);
  if (!channel) return;
  await channel.send({
    content:`🎙️ **${config.reporter}'s Weekly Player Spotlight** — **${feature.playerName}**\n${feature.copy?.subheadline || ''}`,
    files:[new AttachmentBuilder(feature.filePath,{name:`${feature.teamKey}-player-spotlight.png`})], allowedMentions:{parse:[]}
  });
  feature.status='published'; feature.publishedAt=new Date().toISOString();
  state.history.push({id:feature.id,teamKey:feature.teamKey,userId:feature.userId,playerName:feature.playerName,publishedAt:feature.publishedAt});
  saveState();
}

async function scheduleTick(client) {
  const guild = process.env.DISCORD_GUILD_ID ? await client.guilds.fetch(process.env.DISCORD_GUILD_ID).catch(()=>null) : client.guilds.cache.first();
  if (!guild) return;
  await guild.roles.fetch().catch(()=>{}); await guild.channels.fetch().catch(()=>{});
  const p=etParts(), key=dateKey(p);
  if (p.weekday==='Thu' && p.hour>=10 && !state.lastRuns[`select:${key}`]) {
    state.lastRuns[`select:${key}`]=true; saveState();
    for (const teamKey of Object.keys(TEAM_CONFIG)) await beginSpotlight(client,guild,teamKey).catch(console.error);
  }
  if (p.weekday==='Fri' && p.hour>=19 && !state.lastRuns[`preview:${key}`]) {
    state.lastRuns[`preview:${key}`]=true; saveState();
    for (const feature of Object.values(state.active)) {
      if (['waiting_response','dm_failed'].includes(feature.status)) await preparePreview(client,guild,feature).catch(console.error);
    }
  }
  if (p.weekday==='Sat' && p.hour>=10 && !state.lastRuns[`publish:${key}`]) {
    state.lastRuns[`publish:${key}`]=true; saveState();
    for (const feature of Object.values(state.active)) {
      if (feature.status==='awaiting_approval' && feature.approved) await publishFeature(client,guild,feature).catch(console.error);
    }
  }
}

function startPlayerSpotlights(client) {
  client.on('messageCreate', async message => {
    if (message.author.bot || message.guild) return;
    const feature = Object.values(state.active).find(item => item.userId===message.author.id && item.status==='waiting_response');
    if (!feature) return;
    const attachment = message.attachments.find(item => (item.contentType || '').startsWith('image/') || /\.(png|jpe?g|webp)(?:\?|$)/i.test(item.url));
    if (attachment) feature.photoUrl=attachment.url;
    if (message.content.trim()) feature.response=clean(message.content,3500);
    feature.respondedAt=new Date().toISOString(); feature.status='responded'; saveState();
    await message.reply(`Thanks — ${TEAM_CONFIG[feature.teamKey].reporter} has your Player Spotlight answers. The feature goes through club approval before Saturday's edition.`).catch(()=>{});
  });
  client.on('interactionCreate', async interaction => {
    if (!interaction.isButton() || !interaction.customId.startsWith('spotlight:')) return;
    const [,action,id]=interaction.customId.split(':'); const feature=state.active[id]; if(!feature) return;
    const guild=process.env.DISCORD_GUILD_ID ? await client.guilds.fetch(process.env.DISCORD_GUILD_ID).catch(()=>null) : client.guilds.cache.first();
    if (!guild || interaction.user.id!==ownerId(guild)) return interaction.reply({content:'Only the club owner can approve this spotlight.',ephemeral:true});
    if(action==='approve') { feature.approved=true; feature.status='awaiting_approval'; saveState(); return interaction.update({content:`✅ Approved. **${feature.playerName}** is queued for Saturday at 10:00 AM Eastern.`,components:[]}); }
    feature.status='held'; saveState(); return interaction.update({content:`⏸️ ${feature.playerName}'s spotlight has been held and will not publish automatically.`,components:[]});
  });
  scheduleTick(client).catch(console.error);
  const timer=setInterval(()=>scheduleTick(client).catch(console.error),CHECK_MS); timer.unref?.();
  console.log('Weekly Player Spotlight scheduler enabled: Thursday outreach, Friday preview, Saturday 10 AM ET publication after approval.');
}

module.exports={startPlayerSpotlights};
