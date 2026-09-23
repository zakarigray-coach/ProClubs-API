const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { Collection, ChannelType, GuildScheduledEventStatus } = require('discord.js');
const { StateStore } = require('../stateStore');
const {
  MLPC_SCHEDULE_2026,
  parseSchedule,
  importSchedule,
  fixtures,
  availabilityCounts,
  recordResult,
  runReminders,
  handleAvailability,
} = require('../matchSchedule');

function fakeDiscord() {
  let sequence = 0;
  const threads = new Collection();
  const events = new Collection();
  const starter = thread => ({ edit: async data => { thread.lastEdit = data; } });
  const forum = {
    id: 'forum-crown', name: '📅・mlpc-match-center', type: ChannelType.GuildForum,
    availableTags: ['Upcoming','Home','Away','Completed','Win','Loss','Draw'].map((name, i) => ({ name, id: `tag-${i}` })),
    threads: { create: async data => {
      const id = `thread-${++sequence}`;
      const thread = { id, name:data.name, messages:[], setName:async name=>{thread.name=name;}, setAppliedTags:async tags=>{thread.tags=tags;}, fetchStarterMessage:async()=>starter(thread), send:async data=>{thread.messages.push(data);} };
      threads.set(id, thread); return thread;
    } },
  };
  const channels = new Collection([[forum.id, forum]]);
  channels.fetch = async id => threads.get(id) || channels.get(id) || null;
  channels.cache = channels;
  const scheduledEvents = {
    create: async data => { const event={id:`event-${events.size+1}`,status:GuildScheduledEventStatus.Scheduled,...data,edit:async()=>{},setStatus:async status=>{event.status=status;},delete:async()=>{event.deleted=true;}}; events.set(event.id,event); return event; },
    fetch: async id => events.get(id) || null,
  };
  return { guild:{id:'guild-1',channels,scheduledEvents},threads,events };
}

test('official CrownFC schedule contains exactly 34 valid fixtures', () => {
  const parsed = parseSchedule(MLPC_SCHEDULE_2026, { year: 2026 });
  assert.equal(parsed.invalid.length, 0);
  assert.equal(parsed.rows.length, 34);
  assert.equal(parsed.rows[0].opponent, 'dream chaserz');
  assert.equal(parsed.rows.at(-1).opponent, 'KTW Squad');
});

test('parser reports invalid schedule rows instead of silently skipping them', () => {
  const parsed = parseSchedule('Oct 19 | bad time | Opponent | Home\nOct 20 | 8:00 PM | Team | Somewhere', { year: 2026 });
  assert.equal(parsed.rows.length, 0);
  assert.equal(parsed.invalid.length, 2);
});

test('MLPC import is idempotent across persistent reloads', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rt-schedule-'));
  const file = path.join(dir, 'state.json');
  const store = new StateStore(file);
  const fake = fakeDiscord();
  const first = await importSchedule({ guild:fake.guild, store, teamKey:'crownfc', text:MLPC_SCHEDULE_2026, year:2026 });
  assert.deepEqual({ imported:first.imported, duplicates:first.duplicates, posts:first.postsCreated, events:first.eventsCreated }, { imported:34, duplicates:0, posts:34, events:34 });
  assert.equal(fixtures(store,'crownfc').length, 34);
  const reloaded = new StateStore(file);
  const second = await importSchedule({ guild:fake.guild, store:reloaded, teamKey:'crownfc', text:MLPC_SCHEDULE_2026, year:2026 });
  assert.deepEqual({ imported:second.imported, duplicates:second.duplicates, posts:second.postsCreated, events:second.eventsCreated }, { imported:0, duplicates:34, posts:0, events:0 });
  assert.equal(fixtures(reloaded,'crownfc').length, 34);
});

test('availability totals count only each player latest saved response', () => {
  const fixture = { availability:{a:{status:'available'},b:{status:'maybe'},c:{status:'unavailable'},d:{status:'available'}} };
  assert.deepEqual(availabilityCounts(fixture), {available:2,maybe:1,unavailable:1});
  fixture.availability.a.status = 'maybe';
  assert.deepEqual(availabilityCounts(fixture), {available:1,maybe:2,unavailable:1});
});

test('result completes the same fixture, updates tags, event, and recap handoff', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rt-result-'));
  const store = new StateStore(path.join(dir, 'state.json'));
  const fake = fakeDiscord();
  await importSchedule({guild:fake.guild,store,teamKey:'crownfc',text:'Oct 19 | 8:30 PM | Nexus Royals FC | Home',year:2026});
  const outcome = await recordResult({guild:fake.guild,store,teamKey:'crownfc',opponent:'Nexus Royals FC',ourScore:3,opponentScore:1});
  assert.equal(outcome.fixture.status,'completed');
  assert.equal(outcome.fixture.result,'Win');
  assert.equal(fake.events.get(outcome.fixture.discordEventId).status,GuildScheduledEventStatus.Completed);
  assert.equal(store.getMetadata(`matchRecapFixture:${outcome.fixture.fixtureId}`).readyForApprovedRecap,true);
  assert.equal(fixtures(store,'crownfc').length,1);
});

test('reminders persist and do not send twice after a restart', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rt-reminder-'));
  const file = path.join(dir, 'state.json');
  const store = new StateStore(file); const fake = fakeDiscord();
  await importSchedule({guild:fake.guild,store,teamKey:'crownfc',text:'Oct 19 | 8:30 PM | Nexus Royals FC | Home',year:2026});
  const fixture=fixtures(store,'crownfc')[0];
  const now=new Date(new Date(fixture.kickoffAt).getTime()-23*3600000);
  const first=await runReminders({guild:fake.guild,store,now});
  const second=await runReminders({guild:fake.guild,store:new StateStore(file),now});
  assert.equal(first.length,1);
  assert.equal(second.length,0);
  assert.equal(fake.threads.get(fixture.forumPostId).messages.length,1);
});

test('availability rejects members without the matching club role', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rt-availability-'));
  const store = new StateStore(path.join(dir, 'state.json')); const fake = fakeDiscord();
  await importSchedule({guild:fake.guild,store,teamKey:'crownfc',text:'Oct 19 | 8:30 PM | Nexus Royals FC | Home',year:2026});
  const fixture=fixtures(store,'crownfc')[0]; process.env.MLPC_ROLE_ID='crown-role';
  let response;
  await handleAvailability({customId:`match_availability:${fixture.fixtureId}:available`,member:{roles:{cache:{has:()=>false}},displayName:'Player'},user:{id:'player'},reply:async value=>{response=value;}},store);
  assert.match(response.content,/Only rostered CrownFC players/);
  assert.equal(Object.keys(fixtures(store,'crownfc')[0].availability).length,0);
});
