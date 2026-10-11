const {test}=require('node:test'),assert=require('node:assert/strict');
const {ACTIVE_TEAM_KEYS,isActiveClub,activeCommands}=require('../activeClubs');
test('retired club is excluded from jobs and command choices without changing historical definitions',()=>{
  assert.deepEqual(ACTIVE_TEAM_KEYS,['birmingham']);assert(!isActiveClub('crownfc'));assert(!isActiveClub('both'));
  const original=[{name:'sign',options:[{name:'club',choices:[{name:'Birmingham',value:'birmingham'},{name:'CrownFC',value:'crownfc'},{name:'Both',value:'both'}]}]},{name:'import-mlpc-schedule'},{name:'setup-server'},{name:'streamline-server'},{name:'pepreport'}];
  const next=activeCommands(original);
  assert.deepEqual(next.map(x=>x.name),['sign','pepreport']);
  assert.deepEqual(next[0].options[0].choices.map(x=>x.value),['birmingham']);
  assert.equal(original[0].options[0].choices.length,3);
});
test('Birmingham reminders continue while saved CrownFC fixtures remain untouched',async()=>{
  const {runReminders}=require('../matchSchedule');
  const now=new Date('2026-10-20T00:00:00Z');
  const fixtures=['birmingham','crownfc'].map(teamKey=>({fixtureId:teamKey,teamKey,status:'upcoming',kickoffAt:'2026-10-20T01:00:00Z',forumPostId:teamKey,opponent:'Chelsea',timeLabel:'9 PM'}));
  const sent=[],saved=[];
  const store={listMetadata:()=>fixtures.map(value=>({value})),setMetadata:(key,value)=>saved.push({key,value})};
  const guild={channels:{fetch:async id=>({send:async()=>sent.push(id)})}};
  await runReminders({guild,store,now,teamKeys:ACTIVE_TEAM_KEYS});
  assert.deepEqual(sent,['birmingham']);assert.equal(saved.length,1);assert.equal(saved[0].value.teamKey,'birmingham');assert.equal(fixtures[1].reminder24hSent,undefined);
});
