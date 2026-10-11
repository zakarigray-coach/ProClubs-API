const fs=require('node:fs');
const path=require('node:path');
const {PermissionFlagsBits:P}=require('discord.js');
const GUILD='1524828767426707587',CHANNEL='1558568206111604807';
const ROLE='1558566879164104724',BOT='1465409563191939228';
const GRANT={ViewChannel:true,SendMessages:true,EmbedLinks:true};

// Fix 1 only. Other audit changes require the owner's next approval.
async function fixYourBotLiveAccess(client,options={}) {
  const env=options.env || process.env,log=options.log || console.log;
  if(env.DISCORD_GUILD_ID!==GUILD) return;
  const file=path.join(env.RT_DATA_DIR || '/data','workflow-fix-1-yourbot.json');
  const journal=fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):{};
  if(journal.completedAt)return;
  const guild=await client.guilds.fetch(GUILD);
  const channel=await guild.channels.fetch(CHANNEL);
  const role=await guild.roles.fetch(ROLE);
  const member=await guild.members.fetch(BOT);
  if(channel.guildId!==GUILD || !role?.managed || !member.user.bot || !member.roles.cache.has(ROLE))throw new Error('YourBot target validation failed');
  const save=()=>{fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file+'.tmp',JSON.stringify(journal,null,2));fs.renameSync(file+'.tmp',file);};
  if(!journal.original){const overwrite=channel.permissionOverwrites.cache.get(ROLE);journal.original={guildId:GUILD,channelId:CHANNEL,roleId:ROLE,overwrite:overwrite?{allow:overwrite.allow.bitfield.toString(),deny:overwrite.deny.bitfield.toString()}:null};save();}
  // edit merges these three permissions; all other overwrite entries are retained.
  await channel.permissionOverwrites.edit(role,GRANT,{reason:'Owner approved audit fix 1: YourBot Twitch notification channel access'});
  const verified=await guild.channels.fetch(CHANNEL);
  const permissions=verified.permissionsFor(member);
  const checks=Object.keys(GRANT).map(name=>({permission:name,allowed:permissions.has(P[name])}));
  if(checks.some(check=>!check.allowed))throw new Error('YourBot permission verification failed');
  journal.completedAt=new Date().toISOString();journal.checks=checks;save();
  log('RT FIX 1 complete: '+JSON.stringify({channel:verified.name,bot:member.user.username,checks}));
}
async function fixWelcomeAccess(client,options={}) {
  const env=options.env || process.env,log=options.log || console.log;
  if(env.DISCORD_GUILD_ID!==GUILD)return;
  const file=path.join(env.RT_DATA_DIR || '/data','workflow-fix-2-welcome.json');
  const journal=fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):{originals:[],applied:[]};
  if(journal.completedAt)return;
  const guild=await client.guilds.fetch(GUILD);
  const save=()=>{fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file+'.tmp',JSON.stringify(journal,null,2));fs.renameSync(file+'.tmp',file);};
  const grant={ViewChannel:true,ReadMessageHistory:true,SendMessages:false,CreatePublicThreads:false,CreatePrivateThreads:false,SendMessagesInThreads:false};
  for(const id of ['1540112327033102486','1536967792862175334','1551687518003658822']) {
    const channel=await guild.channels.fetch(id);
    if(channel.guildId!==GUILD)throw new Error('Welcome channel scope mismatch');
    if(!journal.originals.some(item=>item.channelId===id)){const previous=channel.permissionOverwrites.cache.get(GUILD);journal.originals.push({channelId:id,overwrite:previous?{allow:previous.allow.bitfield.toString(),deny:previous.deny.bitfield.toString()}:null});save();}
    await channel.permissionOverwrites.edit(guild.roles.everyone,grant,{reason:'Owner approved audit fix 2: readable Welcome, Rules and Directory'});
    const verified=await guild.channels.fetch(id),permissions=verified.permissionsFor(guild.roles.everyone);
    if(Object.entries(grant).some(([name,allowed])=>permissions.has(P[name])!==allowed))throw new Error('Welcome access verification failed: '+id);
    journal.applied.push(id);save();
    log('RT FIX 2 verified: '+JSON.stringify({channel:verified.name,view:true,history:true,generalPosting:false}));
  }
  journal.completedAt=new Date().toISOString();save();log('RT FIX 2 complete');
}
module.exports={fixYourBotLiveAccess,fixWelcomeAccess};
