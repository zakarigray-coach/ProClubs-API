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
const RT_PERMISSIONS=['ViewChannel','ReadMessageHistory','SendMessages','SendMessagesInThreads','EmbedLinks','AttachFiles','AddReactions','CreatePublicThreads','ManageMessages','ManageThreads','ManageChannels','ManageRoles','ManageGuild','ManageWebhooks','ViewAuditLog','CreateEvents','ManageEvents'];
async function prepareRtPermissions(client,options={}) {
  const env=options.env || process.env,log=options.log || console.log;
  if(env.DISCORD_GUILD_ID!==GUILD)return;
  const file=path.join(env.RT_DATA_DIR || '/data','workflow-fix-3-rt.json');
  const journal=fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):{originals:[]};
  if(journal.completedAt)return;
  const guild=await client.guilds.fetch(GUILD);await guild.roles.fetch();await guild.channels.fetch();
  const me=await guild.members.fetchMe();
  const admin=guild.roles.cache.get('1534904508205895833');
  const player=guild.roles.cache.get(env.BIRMINGHAM_ROLE_ID);
  if(!player || !admin)throw new Error('RT role prerequisites missing');
  const save=()=>{fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file+'.tmp',JSON.stringify(journal,null,2));fs.renameSync(file+'.tmp',file);};
  let role=journal.roleId?guild.roles.cache.get(journal.roleId):null;
  if(journal.preparedAt && role && me.roles.cache.has(role.id)) {
    if(me.permissions.has(P.Administrator)){log('RT FIX 3 waiting: remove Admin from RT only; replacement remains ready');return;}
    const missing=[];
    for(const channel of guild.channels.cache.values()) {
      if(channel.isThread())continue;
      const required=channel.isTextBased()?['ViewChannel','ReadMessageHistory','SendMessages','EmbedLinks','AttachFiles','SendMessagesInThreads']:['ViewChannel'];
      if(required.some(name=>!channel.permissionsFor(me).has(P[name])))missing.push(channel.name);
    }
    if(missing.length || RT_PERMISSIONS.some(name=>!me.permissions.has(P[name])) || role.position<=player.position)throw new Error('RT replacement verification failed: '+missing.join(','));
    journal.completedAt=new Date().toISOString();save();log('RT FIX 3 complete: Administrator absent; operations role and all channel access verified');return;
  }
  if(!role){role=await guild.roles.create({name:'RT Media Operations',permissions:RT_PERMISSIONS.map(name=>P[name]),mentionable:false,hoist:false,reason:'Owner approved replacement for RT Administrator'});journal.roleId=role.id;save();}
  if(role.permissions.has(P.Administrator))throw new Error('Replacement unexpectedly has Administrator');
  if(role.position<=player.position)await role.setPosition(player.position+1,{reason:'Keep RT above the player role it assigns'});
  if(!me.roles.cache.has(role.id))await me.roles.add(role,'Owner approved replacement permissions');
  const failures=[];
  for(const channel of guild.channels.cache.values()) {
    if(channel.isThread())continue;
    const text=channel.isTextBased();
    const grant=text?{ViewChannel:true,ReadMessageHistory:true,SendMessages:true,EmbedLinks:true,AttachFiles:true,SendMessagesInThreads:true}:{ViewChannel:true};
    if(!journal.originals.some(item=>item.channelId===channel.id)){const previous=channel.permissionOverwrites.cache.get(role.id);journal.originals.push({channelId:channel.id,overwrite:previous?{allow:previous.allow.bitfield.toString(),deny:previous.deny.bitfield.toString()}:null});save();}
    await channel.permissionOverwrites.edit(role,grant,{reason:'Preserve RT audit and publishing access without Administrator'});
    const verified=await guild.channels.fetch(channel.id),permissions=verified.permissionsFor(role);
    if(Object.keys(grant).some(name=>!permissions.has(P[name])))failures.push(channel.id);
  }
  if(failures.length)throw new Error('Replacement channel access failed: '+failures.join(','));
  await guild.roles.fetch();const refreshedRole=guild.roles.cache.get(role.id);
  if(refreshedRole.position<=guild.roles.cache.get(player.id).position)throw new Error('Replacement role hierarchy failed');
  journal.preparedAt=new Date().toISOString();save();
  const member=await guild.members.fetchMe();
  if(member.roles.cache.has(admin.id)) {
    // Discord forbids a bot managing roles at or above its own highest role.
    if(member.roles.highest.comparePositionTo(admin)<=0){journal.needsOwnerRemoveAdmin=true;save();log('RT FIX 3 ready; owner must remove Admin from RT only: '+JSON.stringify({bot:member.user.username,roleId:role.id,roleName:role.name,channelChecks:journal.originals.length,reason:'Admin is RT’s highest role; Discord role hierarchy prevents self-removal'}));return;}
    await member.roles.remove(admin,'Owner approved least privilege replacement');
  }
  const verified=await guild.members.fetchMe();
  if(verified.permissions.has(P.Administrator))throw new Error('RT still has Administrator through another role');
  journal.completedAt=new Date().toISOString();save();log('RT FIX 3 complete: Administrator removed; operations role verified');
}
async function fixSupatimerAccess(client,options={}) {
  const env=options.env || process.env,log=options.log || console.log;
  if(env.DISCORD_GUILD_ID!==GUILD)return;
  const file=path.join(env.RT_DATA_DIR || '/data','workflow-fix-4-supatimer.json');
  const journal=fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):{};
  if(journal.completedAt)return;
  const guild=await client.guilds.fetch(GUILD),channel=await guild.channels.fetch('1552394785501876277');
  const role=await guild.roles.fetch('1552395677743579189');
  if(!role?.managed || role.name!=='Supatimer' || channel.guildId!==GUILD)throw new Error('Supatimer scope mismatch');
  const save=()=>{fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file+'.tmp',JSON.stringify(journal,null,2));fs.renameSync(file+'.tmp',file);};
  if(!journal.original){const previous=channel.permissionOverwrites.cache.get(role.id);journal.original={channelId:channel.id,roleId:role.id,overwrite:previous?{allow:previous.allow.bitfield.toString(),deny:previous.deny.bitfield.toString()}:null};save();}
  const grant={ViewChannel:true,SendMessages:true,EmbedLinks:true,ReadMessageHistory:true};
  await channel.permissionOverwrites.edit(role,grant,{reason:'Owner approved audit fix 4: Supatimer availability posts'});
  const verified=await guild.channels.fetch(channel.id),permissions=verified.permissionsFor(role);
  if(Object.keys(grant).some(name=>!permissions.has(P[name])))throw new Error('Supatimer verification failed');
  journal.completedAt=new Date().toISOString();save();log('RT FIX 4 complete: Supatimer can read and post embeds in cnc-availability');
}
module.exports={fixYourBotLiveAccess,fixWelcomeAccess,prepareRtPermissions,fixSupatimerAccess,RT_PERMISSIONS};
