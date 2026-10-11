const fs = require('node:fs');
const path = require('node:path');
const GUILD_ID = '1524828767426707587';
const CHANNEL_ID = '1551687518003658822';
const MESSAGE_ID = '1551687580767223940';

const toolsFields = [
  { name:'🧰 Club Tools', value:'Use the tools below for club statistics, match analysis and official league records.' },
  { name:'📊 ProClubsTracker+ (PCT+)', value:'Match logs, team and player statistics, and performance analysis. [Birmingham stats](https://proclubstracker.com/club/309106?platform=common-gen5&tab=pctplus)' },
  { name:'🏆 NACL — Official League Records', value:'Check Birmingham’s league fixtures, results, roster and recorded season statistics on NACL. [Birmingham team page](https://naclubsleagues.com/teams/MPL%20BirminghamCity)' },
];

function buildDirectory(embeds) {
  return embeds.map(embed => {
    if (embed.title !== 'Official Clubhouse Directory') return embed;
    const fields = (embed.fields || []).flatMap(field => {
      if (/Crown\s*FC|Club Tools/i.test(field.name)) return toolsFields;
      if (/Pep|OurProClubs|RT Football Media|ProClubsTracker|NACL/i.test(field.name)) return [];
      if (/Welcome/i.test(field.name)) return [{...field,value:'Server rules and access to club channels.'}];
      return [field];
    });
    if (!fields.some(field => field.name === '🧰 Club Tools')) throw new Error('Expected directory section not found');
    return { ...embed, description:'Welcome to the competitive home of Birmingham City in MPL. Find club information, community spaces and our football tools below.', fields };
  });
}

async function updateClubDirectory(client, options = {}) {
  const env=options.env || process.env;
  const log=options.log || console.log;
  if (env.DISCORD_GUILD_ID !== GUILD_ID) return;
  const file=path.join(env.RT_DATA_DIR || '/data','club-directory-tools-v2.json');
  const journal=fs.existsSync(file) ? JSON.parse(fs.readFileSync(file,'utf8')) : {};
  if (journal.completedAt) return;
  const channel=await client.channels.fetch(CHANNEL_ID);
  if (channel.guildId !== GUILD_ID) throw new Error('Directory guild mismatch');
  const message=await channel.messages.fetch(MESSAGE_ID);
  if (message.author.id !== client.user.id) throw new Error('RT does not own this directory post');
  const original=message.embeds.map(embed => embed.toJSON());
  const embeds=buildDirectory(original);
  if (!embeds.some(embed => embed.title === 'Official Clubhouse Directory')) throw new Error('Directory title mismatch');
  const save=()=>{ fs.mkdirSync(path.dirname(file),{recursive:true}); fs.writeFileSync(file+'.tmp',JSON.stringify(journal,null,2)); fs.renameSync(file+'.tmp',file); };
  if (!journal.original) { journal.original={messageId:MESSAGE_ID,content:message.content,embeds:original}; save(); }
  await message.edit({embeds});
  const verified=await channel.messages.fetch(MESSAGE_ID);
  const directory=verified.embeds.find(embed=>embed.title==='Official Clubhouse Directory');
  const normalize=fields=>(fields || []).map(({name,value,inline})=>({name,value,inline:!!inline}));
  if (JSON.stringify(normalize(directory?.fields))!==JSON.stringify(normalize(embeds.find(embed=>embed.title==='Official Clubhouse Directory').fields))) throw new Error('Directory verification failed');
  journal.completedAt=new Date().toISOString(); save();
  log('RT club directory updated and verified: '+message.url);
}
module.exports={ buildDirectory, updateClubDirectory };
