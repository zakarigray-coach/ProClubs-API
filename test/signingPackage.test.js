const test = require('node:test');
const assert = require('node:assert/strict');
const { packageComplete, packageMissingFields, runIndependentBatch } = require('../signingPackage');

function baseRecord(teamKeys = ['birmingham']) {
  return { id:'story-1', teamKey:teamKeys[0], signingTeamKeys:teamKeys, selectedPlayerName:'', announcementName:'', position:'', signingNumbers:{}, graphic:null };
}
function apply(record, step) {
  if (step === 'identity') Object.assign(record,{selectedPlayerName:'Player A',announcementName:'Ace',position:'CAM'});
  if (step === 'number') Object.assign(record,{playerNumber:'10',signingNumbers:{birmingham:'10'}});
  if (step === 'photo') record.graphic={localPath:'/data/stories/story-1/source.png'};
}

test('single-club package completes in every response order', () => {
  const orders = [
    ['identity','number','photo'],['identity','photo','number'],['number','identity','photo'],
    ['number','photo','identity'],['photo','identity','number'],['photo','number','identity'],
  ];
  for (const order of orders) {
    const record=baseRecord();
    for (const step of order) apply(record,step);
    assert.equal(packageComplete(record,()=>true),true,order.join(' → '));
  }
});

test('both-club package requires independent numbers and permits the same value', () => {
  const record=baseRecord(['birmingham','crownfc']);
  apply(record,'identity'); apply(record,'photo');
  record.signingNumbers={birmingham:'17'}; record.playerNumber='17';
  assert.deepEqual(packageMissingFields(record,()=>true),['crownfcNumber']);
  record.signingNumbers.crownfc='17';
  assert.equal(packageComplete(record,()=>true),true);
});

test('a saved photo path must still exist before forwarding', () => {
  const record=baseRecord(); apply(record,'identity'); apply(record,'number'); apply(record,'photo');
  assert.deepEqual(packageMissingFields(record,()=>false),['photo']);
});

test('batch processing isolates DM and player-specific failures', async () => {
  const users=[{id:'1',username:'One'},{id:'2',username:'Two'},{id:'3',username:'Three'}];
  const result=await runIndependentBatch(users,async user=>{
    if(user.id==='2')return {memberName:'Two',contacted:false};
    if(user.id==='3')throw new Error('missing role');
    return {memberName:'One',contacted:true};
  });
  assert.equal(result.started.length,1);
  assert.equal(result.failed.length,2);
});
