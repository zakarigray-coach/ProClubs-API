// One owner-requested cleanup. Channel IDs, history and permissions stay intact.
const fs = require('node:fs');
const path = require('node:path');

const GUILD_ID = '1524828767426707587';
const VERSION = 'birmingham-mpl-2026-10-11-v1';
const ml1Pattern = /(^|[^a-z0-9])ml[-_ ]?1(?=$|[^a-z0-9])/gi;

function scrubDescription(text) {
  if (text == null || !/\bCrown\s*FC\b/i.test(text)) return text;
  return String(text)
    .replace(/(Birmingham City(?:\s+(?:in\s+)?MPL)?)\s+(?:and|&|\/|\|)\s+Crown\s*FC(?:\s+(?:in\s+)?MLPC)?/gi, '$1')
    .replace(/Crown\s*FC(?:\s+(?:in\s+)?MLPC)?\s+(?:and|&|\/|\|)\s+(Birmingham City(?:\s+(?:in\s+)?MPL)?)/gi, '$1')
    .replace(/\bCrown\s*FC(?:['’]s)?\b/gi, '')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/^[ \t]*[—–:|•-][ \t]*/gm, '')
    .replace(/\s+([,.;:])/g, '$1').trim() || null;
}

function mplName(name) {
  return name.replace(ml1Pattern, (match, prefix) => {
    const token=match.slice(prefix.length);
    return prefix + (token===token.toUpperCase() ? 'MPL' : 'mpl');
  });
}

function leagueChannelKeys(teamKey, suffix) {
  return teamKey==='crownfc' ? ['mlpc-'+suffix] : ['mpl-'+suffix,'ml1-'+suffix];
}

function persist(file, journal) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file + '.tmp', JSON.stringify(journal, null, 2));
  fs.renameSync(file + '.tmp', file);
}

async function directorySnapshot(guild, log) {
  const channels = guild.channels.cache.filter(channel =>
    /club[-_ ]?directory/i.test(channel.name));
  const snapshots = [];
  for (const channel of channels.values()) {
    if (!channel.messages) continue;
    try {
      const recent = await channel.messages.fetch({ limit: 25 });
      const pinned = await channel.messages.fetchPinned();
      const messages = new Map([...recent, ...pinned]);
      const posts = [...messages.values()].filter(message =>
        message.author?.bot && (message.embeds?.length || message.content?.trim()));
      for (const message of posts.slice(0,10)) {
        const snapshot = {
          channelId: channel.id, channelName: channel.name, messageId: message.id,
          url: message.url, content: message.content,
          embeds: message.embeds.map(embed => ({
            title: embed.title, description: embed.description,
            fields: embed.fields, footer: embed.footer?.text,
          })),
          buttons: (message.components || []).flatMap(row => row.components || [])
            .map(button => ({ label: button.label, url: button.url })),
        };
        snapshots.push(snapshot);
        log('RT current club directory: ' + JSON.stringify(snapshot));
      }
    } catch (error) {
      log('RT directory read failed: ' + JSON.stringify({ channelId:channel.id, code:error.code || error.name }));
    }
  }
  return snapshots;
}

async function runBirminghamRebrand(client, options = {}) {
  const env = options.env || process.env;
  const log = options.log || console.log;
  if (!client?.user || env.DISCORD_GUILD_ID !== GUILD_ID) return { status:'scope-mismatch' };
  const guild = await client.guilds.fetch(GUILD_ID);
  await guild.channels.fetch();
  const file = path.join(env.RT_DATA_DIR || '/data', 'birmingham-rebrand-journal.json');
  const journal = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file,'utf8'))
    : { version:VERSION, guildId:GUILD_ID, originals:[], applied:[] };
  if (journal.version !== VERSION || journal.guildId !== GUILD_ID) throw new Error('Cleanup journal scope mismatch');
  const changes=[]; const errors=[];
  // Always inspect the live directory; publication awaits the owner's new contents.
  const directory = await directorySnapshot(guild,log);
  try { await require('./clubDirectoryUpdate').updateClubDirectory(client,options); }
  catch(error) { log('RT club directory update failed: '+(error.code || error.message)); }
  try { await require('./liveWorkflowAudit').runLiveWorkflowAudit(client,options); }
  catch(error) { log('RT AUDIT failed: '+(error.code || error.message)); }
  try { await require('./approvedWorkflowFixes').fixYourBotLiveAccess(client,options); }
  catch(error) { log('RT FIX 1 failed: '+(error.code || error.message)); }
  try { await require('./approvedWorkflowFixes').fixWelcomeAccess(client,options); }
  catch(error) { log('RT FIX 2 failed: '+(error.code || error.message)); }
  try { await require('./approvedWorkflowFixes').prepareRtPermissions(client,options); }
  catch(error) { log('RT FIX 3 failed: '+(error.code || error.message)); }
  try { await require('./approvedWorkflowFixes').fixSupatimerAccess(client,options); }
  catch(error) { log('RT FIX 4 failed: '+(error.code || error.message)); }
  if (!journal.completedAt) {
    const reason='Owner-requested Birmingham cleanup: remove CrownFC descriptions and rename ML1 to MPL';
    const description=scrubDescription(guild.description);
    if (description !== guild.description) {
      if (!journal.originals.some(item => item.kind==='guild-description')) {
        journal.originals.push({ kind:'guild-description', id:guild.id, description:guild.description });
        persist(file,journal);
      }
      try { await guild.edit({ description, reason }); changes.push({ id:guild.id, kind:'guild-description' }); }
      catch (error) { errors.push({ id:guild.id, kind:'guild-description', code:error.code || error.name }); }
    }
    for (const channel of guild.channels.cache.values()) {
      const name=mplName(channel.name);
      const original=journal.originals.find(item => item.kind==='channel' && item.id===channel.id);
      const lastApplied=journal.applied.findLast(item => item.id===channel.id && Object.hasOwn(item,'topic'));
      // Refine our own prior edit without overwriting any later human changes.
      const topic=scrubDescription(original && lastApplied && channel.topic===lastApplied.topic
        ? original.topic : channel.topic);
      const update={};
      if (name!==channel.name) update.name=name;
      if (topic!==channel.topic) update.topic=topic;
      if (!Object.keys(update).length) continue;
      if (!journal.originals.some(item => item.kind==='channel' && item.id===channel.id)) {
        journal.originals.push({ kind:'channel', id:channel.id, name:channel.name, topic:channel.topic });
        persist(file,journal);
      }
      try {
        const before=channel.name;
        await channel.edit({ ...update, reason });
        const change={ id:channel.id, before, ...update };
        changes.push(change); journal.applied.push(change); persist(file,journal);
      } catch (error) { errors.push({ id:channel.id, name:channel.name, code:error.code || error.name }); }
    }
    await guild.channels.fetch();
    const remaining=[...guild.channels.cache.values()].filter(channel =>
      /\bCrown\s*FC\b/i.test(channel.topic || '') || mplName(channel.name)!==channel.name);
    if (!remaining.length && !errors.length && !/\bCrown\s*FC\b/i.test(guild.description || '')) {
      journal.completedAt=new Date().toISOString();
    }
    journal.lastErrors=errors; persist(file,journal);
  }
  const result={ version:VERSION, status:journal.completedAt?'completed':'needs-attention',
    changes, errors, directoryPosts:directory.length };
  log('RT Birmingham rebrand result: ' + JSON.stringify(result));
  return result;
}

module.exports = { scrubDescription, mplName, leagueChannelKeys, directorySnapshot, runBirminghamRebrand };
