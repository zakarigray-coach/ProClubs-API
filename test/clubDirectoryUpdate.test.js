const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {buildDirectory,updateClubDirectory}=require('../clubDirectoryUpdate');

test('directory replaces CrownFC with tool descriptions within Discord limits',()=>{
  const original=[{title:'Official Clubhouse Directory',description:'CrownFC',color:123,fields:[{name:'Welcome',value:'Keep me'},{name:'CrownFC • MLPC',value:'old'}],footer:{text:'Keep footer'}}];
  const [next]=buildDirectory(original);
  assert.equal(next.fields[0].value,'Keep me');
  assert.equal(next.color,123); assert.equal(next.footer.text,'Keep footer');
  assert(!JSON.stringify(next).includes('CrownFC'));
  assert(next.fields.some(f=>f.name==='⚽ OurProClubs Premium'));
  assert(next.fields.every(f=>f.value.length<=1024));
  assert(JSON.stringify(next).length<6000);
  assert.equal(original[0].fields.length,2);
});

test('edits only RT-owned directory, backs up originals and sends no duplicate posts on restart',async()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'rt-directory-'));
  let edits=0;
  const message={author:{id:'rt'},content:'',url:'directory-link',embeds:[{title:'Official Clubhouse Directory',fields:[{name:'CrownFC',value:'old'}],toJSON(){return {title:this.title,fields:this.fields};}}],async edit({embeds}){edits++;this.embeds=embeds;}};
  const channel={guildId:'1524828767426707587',messages:{fetch:async()=>message}};
  const client={user:{id:'rt'},channels:{fetch:async()=>channel}};
  const options={env:{DISCORD_GUILD_ID:channel.guildId,RT_DATA_DIR:dir},log:()=>{}};
  try {
    message.author.id='other';
    await assert.rejects(updateClubDirectory(client,options),/does not own/);
    assert.equal(edits,0);
    message.author.id='rt';
    await updateClubDirectory(client,options);
    await updateClubDirectory(client,options);
    assert.equal(edits,1);
    const saved=JSON.parse(fs.readFileSync(path.join(dir,'club-directory-tools-v1.json')));
    assert.equal(saved.original.embeds[0].fields[0].name,'CrownFC');
    assert(saved.completedAt);
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});
