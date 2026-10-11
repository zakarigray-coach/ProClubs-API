// One-time owner-approved removal from the active queue, before the bot loads it.
const fs=require('node:fs');
const path=require('node:path');
const VERSION='owner-queue-reset-2026-10-11';
const CUTOFF=Date.parse('2026-10-11T16:12:39Z');
function planQueueReset(state) {
  const remove=[];
  for(const [id,record] of Object.entries(state.stories || {})) {
    if(!['signing','weekly_recap'].includes(record.type))continue;
    if(['published','published_partial','publishing'].includes(record.state))continue;
    const created=Date.parse(record.createdAt || '');
    if(Number.isFinite(created)&&created>CUTOFF)continue;
    remove.push({id,type:record.type,state:record.state});
  }
  return remove;
}
function retirePendingStories(statePath,log=console.log) {
  if(!fs.existsSync(statePath))return;
  const state=JSON.parse(fs.readFileSync(statePath,'utf8'));
  if(state.metadata?.[VERSION]){log('RT FIX 6 already completed: '+JSON.stringify(state.metadata[VERSION]));return;}
  const remove=planQueueReset(state);
  const backup=path.join(path.dirname(statePath),'rt-state-before-'+VERSION+'.json');
  // Never overwrite the original backup when retrying after an interrupted write.
  if(!fs.existsSync(backup))fs.copyFileSync(statePath,backup,fs.constants.COPYFILE_EXCL);
  for(const item of remove)delete state.stories[item.id];
  const metadataRemoved=[];
  for(const [key,batch] of Object.entries(state.metadata || {})) {
    if(!key.startsWith('signingBatch:'))continue;
    const created=Date.parse(batch.createdAt || '');
    if(Number.isFinite(created)&&created>CUTOFF)continue;
    metadataRemoved.push(key);delete state.metadata[key];
  }
  const counts=remove.reduce((result,item)=>{result[item.type]=(result[item.type] || 0)+1;return result;},{});
  const result={version:VERSION,completedAt:new Date().toISOString(),removed:remove.length,byType:counts,signingBatchesRemoved:metadataRemoved.length,remainingStories:Object.keys(state.stories || {}).length,backup};
  state.metadata ||= {};state.metadata[VERSION]=result;
  fs.writeFileSync(statePath+'.tmp',JSON.stringify(state,null,2));fs.renameSync(statePath+'.tmp',statePath);
  const verified=JSON.parse(fs.readFileSync(statePath,'utf8'));
  if(remove.some(item=>verified.stories[item.id]))throw new Error('Active queue verification failed');
  log('RT FIX 6 complete: '+JSON.stringify(result));return result;
}
module.exports={retirePendingStories,planQueueReset,VERSION};
