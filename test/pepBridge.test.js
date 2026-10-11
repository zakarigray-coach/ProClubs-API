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
    return {ok:true,json:async()=>({version:1,report_id:7,status:'draft',article:'Cup sample',matches:[],cover_count:2}),arrayBuffer:async()=>Buffer.from(isCover?'PNG sample':'')};
  };
  await sendReview(interaction,7,'42',{url:'https://example.test',token:'test',fetchImpl});
  assert.equal(delivered.files.length,3);
  assert.equal(delivered.files[1].name,'RT_Cup_7_1.png');
  assert.equal(delivered.files[2].name,'RT_Cup_7_2.png');
});
