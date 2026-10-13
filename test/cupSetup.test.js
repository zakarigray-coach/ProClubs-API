const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { Collection, ChannelType } = require('discord.js');
const { StateStore } = require('../stateStore');
const { setupCup, handleCupAvailability, CUP_ID } = require('../cupSetup');

function fixture() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cup-'));
  const file = path.join(dir, 'state.json');
  const store = new StateStore(file);
  const posts = new Collection(), events = new Collection();
  const forum = { id:'forum',name:'📅・mpl-match-center',type:ChannelType.GuildForum,availableTags:[],threads:{
    fetchActive:async()=>({threads:posts}),fetchArchived:async()=>({threads:new Collection()}),
    create:async data=>{ const thread={id:'post',name:data.name,initial:data,message:{id:'starter',content:data.message.content,edit:async data=>{thread.message.content=data.content; thread.message.components=data.components;}},sent:[],send:async data=>{thread.sent.push(data);return {id:'ping'};},fetchStarterMessage:async()=>thread.message};posts.set(thread.id,thread);return thread;}
  }};
  const channels = new Collection([[forum.id,forum],['live',{id:'live',name:'📺・live-games',type:ChannelType.GuildText}]]);
  const roles = new Collection([['players',{id:'players',name:'Birmingham City players'}]]);
  const guild={id:'guild',channels:{cache:channels,fetch:async id=>id?(posts.get(id)||channels.get(id)):channels},roles:{cache:roles,fetch:async()=>roles},scheduledEvents:{fetch:async id=>id?events.get(id):events,create:async data=>{const event={id:'event',...data};events.set(event.id,event);return event;}}};
  return {store,file,guild,posts,events,roles,channels,now:new Date('2026-10-13T16:00:00Z'),posterPath:__filename};
}

test('cup setup creates a knockout post, kickoff event and single player ping',async()=>{
  const f=fixture();const result=await setupCup(f);
  const post=f.posts.get('post');
  assert.match(post.message.content,/single elimination/i);
  assert.ok(post.message.content.includes('\n'));
  assert.ok(!post.message.content.includes('\\n'));
  assert.match(post.message.content,/8:00 PM ET/);
  assert.match(post.message.content,/8:30 PM ET/);
  assert.match(post.message.content,/10:00 PM ET/);
  assert.match(post.message.content,/<#live>/);
  assert.match(post.message.content,/discord.com\/events\/guild\/event/);
  assert.equal(post.initial.message.files.length,1);
  assert.deepEqual(post.initial.message.components[0].toJSON().components.map(b=>b.label),['YES — Available','NO — Unavailable']);
  assert.equal(new Date(f.events.get('event').scheduledStartTime).toISOString(),'2026-10-14T02:00:00.000Z');
  assert.deepEqual(post.sent[0].allowedMentions.roles,['players']);
  assert.equal(post.sent.length,1);
  assert.equal(result.status,'complete');
});

test('restart reuses persistent IDs and does not repost or ping again',async()=>{
  const f=fixture();await setupCup(f); f.store=new StateStore(f.file); await setupCup(f);
  assert.equal(f.posts.size,1);assert.equal(f.events.size,1);assert.equal(f.posts.get('post').sent.length,1);
});

test('event failure saves the forum post and retry resumes without duplication',async()=>{
  const f=fixture(),create=f.guild.scheduledEvents.create;
  f.guild.scheduledEvents.create=async()=>{throw Error('Discord unavailable');};
  await assert.rejects(setupCup(f),/Discord unavailable/);
  assert.equal(f.store.getMetadata(`cup:${CUP_ID}`).forumPostId,'post');
  f.guild.scheduledEvents.create=create;await setupCup(f);assert.equal(f.posts.size,1);
});

test('availability replaces a player vote, updates counts and rejects outsiders',async()=>{
  const f=fixture();await setupCup(f);
  let reply;
  const interaction={customId:`cup_availability:${CUP_ID}:yes`,guildId:'guild',channelId:'post',user:{id:'p1'},member:{displayName:'Coach',roles:{cache:new Collection([['players',{}]])}},channel:f.posts.get('post'),deferReply:async()=>{},editReply:async data=>{reply=data;},reply:async data=>{reply=data;}};
  await handleCupAvailability(interaction,f.store);
  interaction.customId=`cup_availability:${CUP_ID}:no`;await handleCupAvailability(interaction,f.store);
  const saved=f.store.getMetadata(`cup:${CUP_ID}`);
  assert.equal(Object.keys(saved.availability).length,1);assert.equal(saved.availability.p1.status,'no');
  assert.match(interaction.channel.message.content,/NO: 1/);
  interaction.user={id:'outsider'};interaction.member.roles.cache.clear();await handleCupAvailability(interaction,f.store);
  assert.match(reply.content,/Only Birmingham City players/);assert.equal(Object.keys(f.store.getMetadata(`cup:${CUP_ID}`).availability).length,1);
});

test('ambiguous live channels and expired setup fail before posting',async()=>{
  const f=fixture();f.channels.set('live2',{id:'live2',name:'live-games',type:ChannelType.GuildText});
  await assert.rejects(setupCup(f),/Live Games/);assert.equal(f.posts.size,0);
  f.channels.delete('live2');f.now=new Date('2026-10-14T03:00:00Z');
  await assert.rejects(setupCup(f),/kickoff has passed/);assert.equal(f.posts.size,0);
});

test('simultaneous responses preserve both players and the latest displayed counts',async()=>{
  const f=fixture();await setupCup(f);
  const make=(id,status)=>({customId:`cup_availability:${CUP_ID}:${status}`,guildId:'guild',channelId:'post',user:{id},member:{displayName:id,roles:{cache:new Collection([['players',{}]])}},channel:f.posts.get('post'),deferReply:async()=>{},editReply:async()=>{},reply:async()=>{}});
  await Promise.all([handleCupAvailability(make('p1','yes'),f.store),handleCupAvailability(make('p2','no'),f.store)]);
  assert.equal(Object.keys(f.store.getMetadata(`cup:${CUP_ID}`).availability).length,2);
  assert.match(f.posts.get('post').message.content,/YES: 1/);assert.match(f.posts.get('post').message.content,/NO: 1/);
});

test('a player response while event setup is pending survives setup completion',async()=>{
  const f=fixture(),create=f.guild.scheduledEvents.create;
  f.guild.scheduledEvents.create=async data=>{
    const interaction={customId:`cup_availability:${CUP_ID}:yes`,guildId:'guild',channelId:'post',user:{id:'p1'},member:{displayName:'Coach',roles:{cache:new Collection([['players',{}]])}},channel:f.posts.get('post'),deferReply:async()=>{},editReply:async()=>{},reply:async()=>{}};
    await handleCupAvailability(interaction,f.store);return create(data);
  };
  await setupCup(f);
  assert.equal(f.store.getMetadata(`cup:${CUP_ID}`).availability.p1?.status,'yes');
  assert.match(f.posts.get('post').message.content,/YES: 1/);
});
