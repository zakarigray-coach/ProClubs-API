const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {fixYourBotLiveAccess}=require('../approvedWorkflowFixes');
test('RT replacement covers publishing and role assignment without Administrator or moderation powers',()=>{
  const {RT_PERMISSIONS}=require('../approvedWorkflowFixes');
  const {PermissionFlagsBits:P}=require('discord.js');
  assert(RT_PERMISSIONS.every(name=>typeof P[name]==='bigint'));
  for(const name of ['Administrator','BanMembers','KickMembers','ModerateMembers','MentionEveryone'])assert(!RT_PERMISSIONS.includes(name));
  for(const name of ['ManageRoles','ManageChannels','ManageThreads','EmbedLinks','AttachFiles','ReadMessageHistory'])assert(RT_PERMISSIONS.includes(name));
});
test('approved fix targets only YourBot live channel, backs up permissions and skips completed retries',async()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'rt-fix1-'));let edits=0;
  const role={id:'1558566879164104724',managed:true};
  const channel={name:'live-games',guildId:'1524828767426707587',permissionOverwrites:{cache:new Map([[role.id,{allow:{bitfield:0n},deny:{bitfield:1024n}}]]),edit:async(target,grant)=>{assert.equal(target,role);assert.deepEqual(grant,{ViewChannel:true,SendMessages:true,EmbedLinks:true});edits++;}},permissionsFor:()=>({has:()=>true})};
  const guild={channels:{fetch:async id=>{assert.equal(id,'1558568206111604807');return channel;}},roles:{fetch:async()=>role},members:{fetch:async()=>({user:{bot:true,username:'YourBot'},roles:{cache:new Map([[role.id,role]])}})}};
  const client={guilds:{fetch:async()=>guild}},options={env:{DISCORD_GUILD_ID:channel.guildId,RT_DATA_DIR:dir},log:()=>{}};
  try{await fixYourBotLiveAccess(client,options);await fixYourBotLiveAccess(client,options);assert.equal(edits,1);const journal=JSON.parse(fs.readFileSync(path.join(dir,'workflow-fix-1-yourbot.json')));assert.equal(journal.original.overwrite.deny,'1024');assert(journal.completedAt);}finally{fs.rmSync(dir,{recursive:true,force:true});}
});
