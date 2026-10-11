// Owner-requested inspection only: no Discord sends, edits or permission changes.
const fs=require('node:fs');
const path=require('node:path');
const {inspectServer,policyFromEnv}=require('./serverAuditor');
async function runLiveWorkflowAudit(client,options={}) {
  const env=options.env || process.env,log=options.log || console.log;
  if (env.DISCORD_GUILD_ID!=='1524828767426707587') return;
  const root=env.RT_DATA_DIR || '/data';
  const file=path.join(root,'workflow-audit-2026-10-11.json');
  if (fs.existsSync(file)) return;
  const guild=await client.guilds.fetch(env.DISCORD_GUILD_ID);
  let memberCoverage='full member fetch failed; cached only';
  try {await guild.members.fetch();memberCoverage='full member fetch succeeded';} catch(error){log('RT AUDIT member coverage: '+(error.code || error.name));}
  // Read persisted state directly so inspecting it cannot migrate or modify it.
  const state=JSON.parse(fs.readFileSync(path.join(root,'rt-football-media-state.json'),'utf8'));
  const store={
    listMetadata:prefix=>Object.entries(state.metadata || {}).filter(([key])=>key.startsWith(prefix)).map(([key,value])=>({key,value})),
    listMediaPosts:()=>Object.values(state.operations?.production?.mediaPosts || {}),
  };
  const policy=policyFromEnv(env);
  const report=await inspectServer(guild,store,policy);
  report.coverage.members=memberCoverage;
  report.policy=policy;
  report.members=guild.members.cache.map(member=>({id:member.id,name:member.user.username,bot:member.user.bot,roles:member.roles.cache.map(role=>role.id)}));
  report.stateSummary={stories:Object.values(state.stories || {}).reduce((counts,story)=>{const key=(story.teamKey || 'unknown')+':'+story.type+':'+story.state;counts[key]=(counts[key] || 0)+1;return counts;},{}),metadataKeys:Object.keys(state.metadata || {}),matchRecords:Object.values(state.operations?.production?.matchRecords || {}).length};
  fs.writeFileSync(file+'.tmp',JSON.stringify(report,null,2));fs.renameSync(file+'.tmp',file);
  log('RT AUDIT summary: '+JSON.stringify({coverage:report.coverage,policy,counts:{channels:report.snapshot.channels.length,roles:report.snapshot.roles.length,members:report.members.length,findings:report.findings.length},state:report.stateSummary}));
  for(const finding of report.findings)log('RT AUDIT finding: '+JSON.stringify(finding));
  for(const role of report.snapshot.roles)log('RT AUDIT role: '+JSON.stringify(role));
  for(const channel of report.snapshot.channels)log('RT AUDIT channel: '+JSON.stringify(channel));
  for(const member of report.members)log('RT AUDIT member: '+JSON.stringify(member));
  log('RT AUDIT complete: '+report.generatedAt);
}
module.exports={runLiveWorkflowAudit};
