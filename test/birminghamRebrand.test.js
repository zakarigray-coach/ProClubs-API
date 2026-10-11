const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const { Collection }=require('discord.js');
const { scrubDescription, mplName, leagueChannelKeys, runBirminghamRebrand }=require('../birminghamRebrand');

test('description cleanup removes the old club without changing unrelated names',()=>{
  assert.equal(scrubDescription('Home of Birmingham City and CrownFC.'),'Home of Birmingham City.');
  assert.equal(scrubDescription('Birmingham City in MPL and CrownFC in MLPC.'),'Birmingham City in MPL.');
  assert.equal(scrubDescription('CrownFC squad updates'),'squad updates');
  assert.equal(scrubDescription('Castle & Crown community'),'Castle & Crown community');
  assert.equal(scrubDescription('CrownFC'),null);
  assert.equal(scrubDescription(null),null);
});

test('only exact league tokens are renamed, preserving decorations and MLPC',()=>{
  assert.equal(mplName('📊・ml1-stats'),'📊・mpl-stats');
  assert.equal(mplName('Birmingham • ML1'),'Birmingham • MPL');
  assert.equal(mplName('mlpc-match-center'),'mlpc-match-center');
  assert.equal(mplName('ml10-stats'),'ml10-stats');
});

function fixture(temp) {
  const edits=[];
  const make=(id,name,topic)=>({id,name,topic,overwrites:['private'],
    async edit(update){ edits.push({id,...update}); Object.assign(this,update); }});
  const general=make('1','💬・general','Birmingham City and CrownFC community.');
  const stats=make('2','📊・ml1-stats','Birmingham City MPL statistics.');
  const history=make('3','archive','Keep historical records.');
  const directory=make('4','📌・club-directory','Club links');
  let directoryEdits=0;
  const post={id:'post',url:'https://discord.com/channels/guild/4/post',content:'',author:{bot:true},
    embeds:[{title:'Official Clubhouse Directory',description:'Existing directory',fields:[{name:'Welcome',value:'Rules and registration'}]}],
    async edit(){directoryEdits++;}};
  directory.messages={fetch:async()=>new Collection([['post',post]]),fetchPinned:async()=>new Collection([['post',post]])};
  const cache=new Collection([general,stats,history,directory].map(c=>[c.id,c]));
  const guild={id:'1524828767426707587',description:'Birmingham City and CrownFC.',
    channels:{cache,fetch:async()=>cache},async edit(update){Object.assign(this,update);}};
  return {guild,general,stats,history,edits,get directoryEdits(){return directoryEdits;},
    client:{user:{id:'bot'},guilds:{fetch:async()=>guild}},
    options:{env:{DISCORD_GUILD_ID:guild.id,RT_DATA_DIR:temp},log:()=>{}}};
}

test('cleanup keeps IDs/history/permissions and backs up original descriptions; restart is harmless',async()=>{
  const temp=fs.mkdtempSync(path.join(os.tmpdir(),'rt-rebrand-'));
  try {
    const f=fixture(temp);
    const result=await runBirminghamRebrand(f.client,f.options);
    assert.equal(result.status,'completed');
    assert.equal(result.directoryPosts,1);
    assert.equal(f.general.topic,'Birmingham City community.');
    assert.equal(f.stats.name,'📊・mpl-stats');
    assert.deepEqual(f.general.overwrites,['private']);
    assert.equal(f.history.topic,'Keep historical records.');
    assert.equal(f.directoryEdits,0);
    const journal=JSON.parse(fs.readFileSync(path.join(temp,'birmingham-rebrand-journal.json')));
    assert.equal(journal.originals.find(r=>r.id==='1').topic,'Birmingham City and CrownFC community.');
    const again=await runBirminghamRebrand(f.client,f.options);
    assert.equal(again.changes.length,0);
    assert.equal(f.edits.length,2);
  } finally { fs.rmSync(temp,{recursive:true,force:true}); }
});

test('missing permissions are reported and cannot mark the cleanup complete',async()=>{
  const temp=fs.mkdtempSync(path.join(os.tmpdir(),'rt-rebrand-'));
  try {
    const f=fixture(temp);
    f.stats.edit=async()=>{throw Object.assign(new Error('Missing Permissions'),{code:50013});};
    const result=await runBirminghamRebrand(f.client,f.options);
    assert.equal(result.status,'needs-attention');
    assert.equal(result.errors[0].code,50013);
    assert.equal(f.stats.name,'📊・ml1-stats');
  } finally {fs.rmSync(temp,{recursive:true,force:true});}
});

test('cleanup cannot touch another server',async()=>{
  const result=await runBirminghamRebrand({user:{id:'bot'},guilds:{fetch:()=>{throw Error('Must not fetch');}}},
    {env:{DISCORD_GUILD_ID:'other'}});
  assert.equal(result.status,'scope-mismatch');
});

 test('Birmingham lookups accept both sides of the rename while CrownFC keeps its own channels',()=>{
  assert.deepEqual(leagueChannelKeys('birmingham','stats'),['mpl-stats','ml1-stats']);
  assert.deepEqual(leagueChannelKeys('birmingham','transactions'),['mpl-transactions','ml1-transactions']);
  assert.deepEqual(leagueChannelKeys('crownfc','stats'),['mlpc-stats']);
});
