const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {retirePendingStories,planQueueReset}=require('../retirePendingStories');
test('queue reset removes old packages and drafts, preserving new work, published history and football data',()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'rt-queue-')),file=path.join(dir,'state.json');
  const state={stories:{package:{type:'signing',state:'package_forwarded',quickSign:true},draft:{type:'weekly_recap',state:'draft_ready'},published:{type:'signing',state:'published'},new:{type:'signing',state:'waiting_for_package',createdAt:'2026-10-12T00:00:00Z'},match:{type:'match',state:'draft_ready'}},metadata:{'signingBatch:old':{},fixture:{opponent:'Chelsea'}},squadNumbers:{birmingham:{22:{playerName:'Tru'}}},processedMessages:{recap:'saved'},operations:{production:{matchRecords:{one:{score:'2-0'}},mediaPosts:{news:{published:true}}}}};
  fs.writeFileSync(file,JSON.stringify(state));
  try {
    assert.equal(planQueueReset(state).length,2);
    const result=retirePendingStories(file,()=>{});assert.equal(result.removed,2);
    const next=JSON.parse(fs.readFileSync(file));
    assert.deepEqual(Object.keys(next.stories),['published','new','match']);
    for(const key of ['squadNumbers','processedMessages','operations'])assert.deepEqual(next[key],state[key]);
    assert.deepEqual(JSON.parse(fs.readFileSync(result.backup)),state);
    const before=fs.readFileSync(file,'utf8');retirePendingStories(file,()=>{});assert.equal(fs.readFileSync(file,'utf8'),before);
  }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
