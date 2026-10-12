const test=require('node:test');
const assert=require('node:assert/strict');
const {fetchReport,sendReview,checkConnection}=require('../pepBridge');
const report={version:1,report_id:7,status:'draft',article:'Verified selected matches only',matches:[{match_id:1,match_type:'Practice'}]};
const options={url:'http://pep.test:8080',token:'test-secret',fetchImpl:async(url,request)=>{
 assert.equal(request.headers.Authorization,'Bearer test-secret');assert.equal(request.redirect,'error');
 return {ok:true,json:async()=>url.pathname==='/health'?{ok:true,service:'pep-central-store'}:report};
}};
test('authenticated central report and health',async()=>{assert.deepEqual(await fetchReport(7,options),report);assert.equal(await checkConnection(options),true);});
test('invalid or unavailable report fails safely',async()=>{await assert.rejects(fetchReport(0,options));await assert.rejects(fetchReport(7,{...options,fetchImpl:async()=>({ok:false,status:404})}));});
test('private owner download never public send',async()=>{let reply;await sendReview({user:{id:'owner'},editReply:async r=>{reply=r;}},7,'owner',options);assert.equal(reply.files[0].attachment.toString(),report.article);assert.match(reply.content,/nothing has been published/);assert.deepEqual(reply.allowedMentions,{parse:[]});});
test('non-owner cannot retrieve',async()=>{let called=false;await sendReview({user:{id:'other'},editReply:async()=>{}},7,'owner',{...options,fetchImpl:async()=>{called=true;}});assert.equal(called,false);});
test('closed report rejected',async()=>{await assert.rejects(fetchReport(7,{...options,fetchImpl:async()=>({ok:true,json:async()=>({...report,status:'skipped'})})}));});

test('optional photo travels with private draft through authenticated central store', async()=>{
 let reply;
 await sendReview({user:{id:'owner'},editReply:async r=>{reply=r;}},7,'owner',{...options,fetchImpl:async(url,request)=>{
  assert.equal(request.headers.Authorization,'Bearer test-secret');
  return url.pathname.endsWith('/photo') ? {ok:true,arrayBuffer:async()=>Buffer.from('photo bytes')} : {ok:true,json:async()=>({...report,photo_extension:'png'})};
 }});
 assert.equal(reply.files.length,2);assert.equal(reply.files[1].name,'Featured_Player_7.png');
 assert.deepEqual(reply.allowedMentions,{parse:[]});
});

test('cup cards accompany the same private report without public posting', async () => {
  const { sendReview } = require('../pepBridge');
  let delivered;
  const interaction = {user:{id:'42'},editReply:async value => {delivered=value;}};
  const fetchImpl=async url => {
    const isCover=String(url).includes('/covers/');
    return {ok:true,json:async()=>({version:1,report_id:7,status:'draft',article:'Cup sample',matches:[],competition_context:{event:{report_type:'Cup'}},cover_count:2}),arrayBuffer:async()=>Buffer.from(isCover?'PNG sample':'')};
  };
  await sendReview(interaction,7,'42',{url:'https://example.test',token:'test',fetchImpl});
  assert.equal(delivered.files.length,3);
  assert.equal(delivered.files[1].name,'RT_Cup_7_1.png');
  assert.equal(delivered.files[2].name,'RT_Cup_7_2.png');
});


test('weekly approved media cards use the same private bridge', async () => {
  let delivered;
  await sendReview({user:{id:'owner'},editReply:async r=>{delivered=r;}},7,'owner',{
    ...options,fetchImpl:async url=>({ok:true,json:async()=>({...report,cover_count:2}),arrayBuffer:async()=>Buffer.from('approved template')})
  });
  assert.equal(delivered.files.length,3);
  assert.equal(delivered.files[1].name,'RT_Media_7_1.png');
  assert.deepEqual(delivered.allowedMentions,{parse:[]});
});

test('content-only report delivers readable paragraphs after one cover and JSON', async()=>{
 const replies=[];
 const current={...report,cover_count:1,cover_payload:{headline:'Blues Find Mixed Fortunes'},discord_article:'By Raine | RT Football Media\n\n'+ 'A'.repeat(1100)+'\n\n'+'B'.repeat(1100)};
 await sendReview({user:{id:'owner'},editReply:async r=>replies.push(r),followUp:async r=>replies.push(r)},7,'owner',{
  ...options,fetchImpl:async url=>({ok:true,json:async()=>current,arrayBuffer:async()=>Buffer.from('cover')})
 });
 assert.equal(replies.length,3);
 assert.equal(replies.slice(1).map(r=>r.content).join('\n\n'),current.discord_article);
 assert.ok(replies[0].files.some(f=>f.name==='RT_Cover_7.json'));
 assert.ok(replies.slice(1).every(r=>r.ephemeral && r.content.length<=2000));
});
