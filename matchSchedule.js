const crypto = require('crypto');
const {
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  ChannelType,
  GuildScheduledEventEntityType,
  GuildScheduledEventPrivacyLevel,
  GuildScheduledEventStatus,
  ForumLayoutType,
  PermissionFlagsBits,
  SortOrderType,
} = require('discord.js');

const TIMEZONE = 'America/New_York';
const TAGS = ['Upcoming', 'Home', 'Away', 'Completed', 'Win', 'Loss', 'Draw'];
const MLPC_SCHEDULE_2026 = `Oct 19 | 8:00 PM | dream chaserz | Home
Oct 19 | 8:30 PM | Nexus Royals FC | Home
Oct 21 | 8:00 PM | ROJIBLANCOS FC MLPC | Home
Oct 21 | 8:30 PM | NAVEX FC | Away
Oct 26 | 8:00 PM | 008KID | Away
Oct 26 | 8:30 PM | Tequileros FC | Away
Oct 28 | 8:00 PM | MW Syndicate | Away
Oct 28 | 8:30 PM | Mythic MoBz | Away
Nov 2 | 8:00 PM | LEONEZ XI | Away
Nov 2 | 8:30 PM | FC WEPA | Away
Nov 4 | 8:00 PM | Rhythm XI | Away
Nov 4 | 8:30 PM | Fc NOVA XI | Home
Nov 9 | 8:00 PM | D Gaming Elite | Home
Nov 9 | 8:30 PM | Club City FC B | Home
Nov 11 | 8:00 PM | ML$ Sickos | Home
Nov 11 | 8:30 PM | AFO XI | Home
Nov 16 | 8:00 PM | KTW Squad | Home
Nov 16 | 8:30 PM | dream chaserz | Away
Nov 18 | 8:00 PM | Nexus Royals FC | Away
Nov 18 | 8:30 PM | ROJIBLANCOS FC MLPC | Away
Nov 23 | 8:00 PM | NAVEX FC | Home
Nov 23 | 8:30 PM | 008KID | Home
Nov 25 | 8:00 PM | Tequileros FC | Home
Nov 25 | 8:30 PM | MW Syndicate | Home
Nov 30 | 8:00 PM | Mythic MoBz | Home
Nov 30 | 8:30 PM | LEONEZ XI | Home
Dec 2 | 8:00 PM | FC WEPA | Home
Dec 2 | 8:30 PM | Rhythm XI | Home
Dec 7 | 8:00 PM | Fc NOVA XI | Away
Dec 7 | 8:30 PM | D Gaming Elite | Away
Dec 9 | 8:00 PM | Club City FC B | Away
Dec 9 | 8:30 PM | ML$ Sickos | Away
Dec 14 | 8:00 PM | AFO XI | Away
Dec 14 | 8:30 PM | KTW Squad | Away`;

const CLUBS = {
  crownfc: { label: 'CrownFC', league: 'MLPC Bronze S4', season: '2026', forum: 'mlpc-match-center', roleEnv: 'MLPC_ROLE_ID', footer: 'FOR THE CROWN.', eventFooter: 'For the Crown.', emoji: '👑' },
  birmingham: { label: 'Birmingham City', league: 'Masters Premier League', season: '2026', forum: 'mpl-match-center', roleEnv: 'BIRMINGHAM_ROLE_ID', footer: 'KEEP RIGHT ON.', eventFooter: 'Keep Right On.', emoji: '🔵' },
};

function norm(value) { return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }
function fixtureKey(teamKey, iso, opponent) { return crypto.createHash('sha1').update(`${teamKey}|${iso}|${norm(opponent)}`).digest('hex').slice(0, 20); }
function metadataKey(id) { return `fixture:${id}`; }
function fixtures(store, teamKey) { return store.listMetadata('fixture:').map(item => item.value).filter(item => item && (!teamKey || item.teamKey === teamKey)); }
function getFixture(store, id) { return store.getMetadata(metadataKey(id)); }
function saveFixture(store, value) { return store.setMetadata(metadataKey(value.fixtureId), { ...value, updatedAt: new Date().toISOString() }); }
function matchLabel(value) { return String(Number(value) || 0).padStart(2, '0'); }

function easternParts(date) {
  return Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: TIMEZONE, year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23' }).formatToParts(date).filter(p => p.type !== 'literal').map(p => [p.type, p.value]));
}
function zonedDate(year, month, day, hour, minute) {
  const wanted = Date.UTC(year, month - 1, day, hour, minute);
  let guess = wanted;
  for (let i = 0; i < 3; i++) {
    const p = easternParts(new Date(guess));
    const shown = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute);
    guess += wanted - shown;
  }
  return new Date(guess);
}
function parseSchedule(text, { year = 2026 } = {}) {
  const rows = []; const invalid = [];
  const months = {jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12};
  String(text || '').split(/\r?\n/).forEach((raw, index) => {
    const line = raw.trim(); if (!line) return;
    const parts = line.split('|').map(v => v.trim());
    if (parts.length !== 4) { invalid.push({ line:index + 1, text:line, reason:'Expected Date | Time | Opponent | Home/Away' }); return; }
    const dm = parts[0].match(/^([A-Za-z]{3,9})\s+(\d{1,2})(?:,?\s+(\d{4}))?$/);
    const tm = parts[1].match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
    const homeAway = /^(home|away)$/i.test(parts[3]) ? parts[3][0].toUpperCase() + parts[3].slice(1).toLowerCase() : null;
    const month = dm && months[dm[1].slice(0,3).toLowerCase()]; const day = dm && +dm[2]; const rowYear = dm && +(dm[3] || year);
    let hour = tm && +tm[1]; const minute = tm && +tm[2];
    if (!dm || !month || day < 1 || day > 31 || !tm || hour < 1 || hour > 12 || minute > 59 || !parts[2] || !homeAway) { invalid.push({ line:index + 1, text:line, reason:'Invalid date, time, opponent, or Home/Away value' }); return; }
    if (tm[3].toUpperCase() === 'PM' && hour !== 12) hour += 12; if (tm[3].toUpperCase() === 'AM' && hour === 12) hour = 0;
    const kickoff = zonedDate(rowYear, month, day, hour, minute);
    if (+easternParts(kickoff).day !== day || +easternParts(kickoff).month !== month) { invalid.push({ line:index + 1, text:line, reason:'Date does not exist' }); return; }
    rows.push({ opponent:parts[2], homeAway, kickoffAt:kickoff.toISOString(), dateLabel:`${dm[1].slice(0,3)[0].toUpperCase()}${dm[1].slice(1,3).toLowerCase()} ${day}`, timeLabel:`${((hour + 11) % 12) + 1}:${String(minute).padStart(2,'0')} ${hour >= 12 ? 'PM' : 'AM'}`, year:rowYear });
  });
  return { rows, invalid };
}

function availabilityCounts(fixture) {
  const values = Object.values(fixture.availability || {}); return { available:values.filter(v=>v.status==='available').length, maybe:values.filter(v=>v.status==='maybe').length, unavailable:values.filter(v=>v.status==='unavailable').length };
}
function groupedNames(fixture, status) { const names = Object.values(fixture.availability || {}).filter(v=>v.status===status).map(v=>v.name); return names.length ? names.join(', ') : 'None'; }
function resultLabel(fixture) { return fixture.status === 'cancelled' ? 'CANCELLED' : fixture.status === 'completed' ? `${fixture.ourScore}-${fixture.opponentScore} (${fixture.result})` : 'Pending'; }
function bodyFor(fixture) {
  const c = availabilityCounts(fixture); const lobby = new Date(new Date(fixture.kickoffAt).getTime() - 30*60000);
  const lobbyTime = lobby.toLocaleTimeString('en-US',{timeZone:TIMEZONE,hour:'numeric',minute:'2-digit'});
  return `🏆 ${fixture.league}\n\n📅 Date: ${fixture.dateLabel}\n⏰ Kickoff: ${fixture.timeLabel} ET\n🎮 Lobby: ${lobbyTime} ET\n🏟️ Location: ${fixture.homeAway}\n\n**AVAILABILITY**\n✅ Available: ${c.available} — ${groupedNames(fixture,'available')}\n❓ Maybe: ${c.maybe} — ${groupedNames(fixture,'maybe')}\n❌ Unavailable: ${c.unavailable} — ${groupedNames(fixture,'unavailable')}\n\n**MATCHDAY**\nLineup:\nResult: ${resultLabel(fixture)}\nFinal Score: ${fixture.status === 'completed' ? `${fixture.ourScore}-${fixture.opponentScore}` : ''}\nHighlights:\nRT Football Media Recap: ${fixture.recapUrl || ''}\n\n${fixture.status === 'cancelled' ? '**THIS MATCH HAS BEEN CANCELLED.**\n\n' : ''}${CLUBS[fixture.teamKey].footer}`;
}
function buttonsFor(fixture) {
  const disabled = ['completed','cancelled'].includes(fixture.status);
  return [new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId(`match_availability:${fixture.fixtureId}:available`).setLabel('Available').setEmoji('✅').setStyle(ButtonStyle.Success).setDisabled(disabled),
    new ButtonBuilder().setCustomId(`match_availability:${fixture.fixtureId}:maybe`).setLabel('Maybe').setEmoji('❓').setStyle(ButtonStyle.Secondary).setDisabled(disabled),
    new ButtonBuilder().setCustomId(`match_availability:${fixture.fixtureId}:unavailable`).setLabel('Unavailable').setEmoji('❌').setStyle(ButtonStyle.Danger).setDisabled(disabled),
  )];
}
function forumFor(guild, teamKey) { return guild.channels.cache.find(c => c.type === ChannelType.GuildForum && norm(c.name) === CLUBS[teamKey].forum); }
function tagIds(forum, names) { return names.map(name => forum.availableTags.find(t => t.name.toLowerCase() === name.toLowerCase())?.id).filter(Boolean); }
function titleFor(f) { return `Match ${matchLabel(f.matchNumber)} — ${f.dateLabel} — ${CLUBS[f.teamKey].label} vs ${f.opponent} — ${f.timeLabel}`.slice(0,100); }

async function createOrUpdateDiscord(guild, store, fixture) {
  const club = CLUBS[fixture.teamKey]; const forum = forumFor(guild, fixture.teamKey);
  if (!forum) throw new Error(`${club.label} Match Center forum was not found. Ask management to verify the forum channel name and bot access.`);
  let thread = fixture.forumPostId ? await guild.channels.fetch(fixture.forumPostId).catch(()=>null) : null;
  if (!thread) {
    const initialTags = fixture.status === 'completed' ? ['Completed',fixture.result] : fixture.status === 'cancelled' ? [] : ['Upcoming',fixture.homeAway];
    thread = await forum.threads.create({ name:titleFor(fixture), message:{content:bodyFor(fixture),components:buttonsFor(fixture),allowedMentions:{parse:[]}}, appliedTags:tagIds(forum,initialTags), reason:'Official league fixture import' });
    fixture.forumPostId = thread.id; fixture.forumChannelId = forum.id;
    // Persist the post immediately. If Discord event creation fails, a retry
    // reuses this post instead of creating a duplicate.
    fixture = saveFixture(store, fixture);
  } else {
    await thread.setName(titleFor(fixture));
    const starter = await thread.fetchStarterMessage(); await starter.edit({content:bodyFor(fixture),components:buttonsFor(fixture),allowedMentions:{parse:[]}});
    const desired = fixture.status === 'completed' ? ['Completed',fixture.result] : fixture.status === 'cancelled' ? [] : ['Upcoming',fixture.homeAway];
    await thread.setAppliedTags(tagIds(forum,desired));
  }
  let event = fixture.discordEventId ? await guild.scheduledEvents.fetch(fixture.discordEventId).catch(()=>null) : null;
  if (!event && fixture.status === 'upcoming') {
    event = await guild.scheduledEvents.create({ name:`${club.label} vs ${fixture.opponent} — ${fixture.league}`.slice(0,100), description:`${fixture.league}\n${club.label} vs ${fixture.opponent}\nHome/Away: ${fixture.homeAway}\nLobby opens 30 minutes before kickoff.\n${club.eventFooter}`.slice(0,1000), scheduledStartTime:new Date(fixture.kickoffAt), scheduledEndTime:new Date(new Date(fixture.kickoffAt).getTime()+90*60000), privacyLevel:GuildScheduledEventPrivacyLevel.GuildOnly, entityType:GuildScheduledEventEntityType.External, entityMetadata:{location:`${fixture.homeAway} • ${club.label}`}, reason:'Official league fixture import' });
    fixture.discordEventId = event.id;
  } else if (event && fixture.status === 'upcoming') {
    await event.edit({name:`${club.label} vs ${fixture.opponent} — ${fixture.league}`.slice(0,100),scheduledStartTime:new Date(fixture.kickoffAt),scheduledEndTime:new Date(new Date(fixture.kickoffAt).getTime()+90*60000),entityMetadata:{location:`${fixture.homeAway} • ${club.label}`}});
  }
  return saveFixture(store, fixture);
}

async function importSchedule({guild,store,teamKey,text,year=2026}) {
  const club=CLUBS[teamKey]; if(!club) throw new Error('Unknown club.');
  let botMember = guild.members?.me || null;
  if (!botMember && typeof guild.members?.fetchMe === 'function') botMember = await guild.members.fetchMe().catch(() => null);
  if (botMember?.permissions && (!botMember.permissions.has(PermissionFlagsBits.CreateEvents) || !botMember.permissions.has(PermissionFlagsBits.ManageEvents))) {
    throw new Error('RT Football Media needs Create Events and Manage Events permissions before schedules can be imported. No fixtures were changed.');
  }
  const parsed=parseSchedule(text,{year});
  parsed.rows.sort((a,b)=>a.kickoffAt.localeCompare(b.kickoffAt) || a.opponent.localeCompare(b.opponent));
  const forum=forumFor(guild,teamKey);
  if(!forum) throw new Error(`${club.label} Match Center forum was not found. Ask management to verify the forum channel name and bot access.`);
  if(typeof forum.edit==='function') await forum.edit({defaultForumLayout:ForumLayoutType.ListView,defaultSortOrder:SortOrderType.CreationDate,reason:'Official Match Center chronological archive'});
  const report={imported:0,duplicates:0,invalid:parsed.invalid,postsCreated:0,eventsCreated:0,fixtures:[]};
  const orderedRows=parsed.rows.map((row,index)=>({row,officialNumber:index+1}));
  const seen=new Set();
  // Discord displays Creation Time newest-first. Creating Match 34 first and
  // Match 01 last produces the requested visible Match 01 → Match 34 order.
  for(const {row,officialNumber} of [...orderedRows].reverse()){
    const id=fixtureKey(teamKey,row.kickoffAt,row.opponent); if(seen.has(id)){report.duplicates++;continue;} seen.add(id);
    let fixture=getFixture(store,id); const existing=Boolean(fixture);
    if(!fixture) fixture={matchNumber:officialNumber,fixtureId:id,teamKey,club:club.label,league:club.league,season:String(year),opponent:row.opponent,date:row.dateLabel,kickoff:row.timeLabel,dateLabel:row.dateLabel,timeLabel:row.timeLabel,kickoffAt:row.kickoffAt,timezone:TIMEZONE,homeAway:row.homeAway,status:'upcoming',result:null,ourScore:null,opponentScore:null,availability:{},reminder24hSent:false,reminder30mSent:false,createdAt:new Date().toISOString()};
    else fixture={...fixture,matchNumber:fixture.matchNumber||officialNumber,date:fixture.date||row.dateLabel,kickoff:fixture.kickoff||row.timeLabel,opponent:fixture.opponent||row.opponent,homeAway:fixture.homeAway||row.homeAway};
    const hadPost=fixture.forumPostId, hadEvent=fixture.discordEventId; fixture=await createOrUpdateDiscord(guild,store,fixture);
    if(existing) report.duplicates++; else report.imported++;
    if(!hadPost&&fixture.forumPostId)report.postsCreated++; if(!hadEvent&&fixture.discordEventId)report.eventsCreated++; report.fixtures.push(fixture);
  }
  const numbered=report.fixtures.map(f=>Number(f.matchNumber)).sort((a,b)=>a-b);
  report.numberingValid=numbered.length===parsed.rows.length && new Set(numbered).size===numbered.length && numbered.every((number,index)=>number===index+1);
  report.creationOrderValid=report.fixtures.every((fixture,index)=>Number(fixture.matchNumber)===parsed.rows.length-index);
  return report;
}

async function reorderMatchCenterForum({guild,store,teamKey,version='visible-matchday-order-v1'}){
  const marker=`matchCenterOrder:${teamKey}`;
  if(store.getMetadata(marker)?.version===version)return {teamKey,skipped:true,migrated:0,deleted:0};
  const club=CLUBS[teamKey];if(!club)throw new Error('Unknown club.');
  const forum=forumFor(guild,teamKey);if(!forum)throw new Error(`${club.label} Match Center forum was not found.`);
  const chronological=fixtures(store,teamKey).sort((a,b)=>a.kickoffAt.localeCompare(b.kickoffAt));
  if(!chronological.length)return {teamKey,skipped:true,migrated:0,deleted:0,noFixtures:true};
  for(const [index,current] of chronological.entries())saveFixture(store,{...current,matchNumber:current.matchNumber||index+1});
  if(typeof forum.edit==='function')await forum.edit({defaultForumLayout:ForumLayoutType.ListView,defaultSortOrder:SortOrderType.CreationDate,reason:'Display official matches in matchday order'});
  let migrated=0,deleted=0;
  for(const original of [...chronological].reverse()){
    let fixture=getFixture(store,original.fixtureId);
    if(fixture.forumOrderVersion===version)continue;
    // Persist both IDs while the replacement is in progress. If Railway or
    // Discord interrupts the migration, startup can resume without creating a
    // second replacement or forgetting which old post still needs deletion.
    const oldThreadId=fixture.forumReorderOldThreadId||fixture.forumPostId;
    let replacement=fixture.forumReorderReplacementId
      ?await guild.channels.fetch(fixture.forumReorderReplacementId).catch(()=>null)
      :null;
    if(!replacement){
      fixture=saveFixture(store,{...fixture,forumReorderOldThreadId:oldThreadId,forumPostId:null,forumChannelId:null});
      fixture=await createOrUpdateDiscord(guild,store,fixture);
      fixture=saveFixture(store,{...fixture,forumReorderOldThreadId:oldThreadId,forumReorderReplacementId:fixture.forumPostId});
      replacement=await guild.channels.fetch(fixture.forumPostId).catch(()=>null);
      migrated++;
    }
    const oldThread=oldThreadId?await guild.channels.fetch(oldThreadId).catch(()=>null):null;
    if(oldThread&&oldThread.id!==fixture.forumPostId){
      await oldThread.delete('Owner-approved replacement with chronologically ordered Match Center post');
      deleted++;
    }
    fixture=saveFixture(store,{...fixture,forumOrderVersion:version,forumReorderOldThreadId:null,forumReorderReplacementId:null,previousForumPostIds:[...new Set([...(fixture.previousForumPostIds||[]),oldThreadId].filter(Boolean))]});
  }
  store.setMetadata(marker,{version,teamKey,migrated,deleted,completedAt:new Date().toISOString()});
  return {teamKey,skipped:false,migrated,deleted};
}

async function handleAvailability(interaction, store) {
  const [,id,status]=interaction.customId.split(':'); let fixture=getFixture(store,id); if(!fixture) return interaction.reply({content:'This fixture is no longer available.',ephemeral:true});
  const roleId=process.env[CLUBS[fixture.teamKey].roleEnv]; if(!roleId || !interaction.member.roles.cache.has(roleId)) return interaction.reply({content:`Only rostered ${CLUBS[fixture.teamKey].label} players can submit availability.`,ephemeral:true});
  fixture.availability ||= {}; fixture.availability[interaction.user.id]={status,name:interaction.member.displayName,userId:interaction.user.id,updatedAt:new Date().toISOString()}; fixture=saveFixture(store,fixture);
  const thread=interaction.channel; const starter=await thread.fetchStarterMessage(); await starter.edit({content:bodyFor(fixture),components:buttonsFor(fixture),allowedMentions:{parse:[]}});
  return interaction.reply({content:`Your availability is now **${status}** for ${CLUBS[fixture.teamKey].label} vs ${fixture.opponent}.`,ephemeral:true});
}

function findActive(store,teamKey,opponent){const q=norm(opponent);return fixtures(store,teamKey).filter(f=>f.status==='upcoming'&&norm(f.opponent)===q).sort((a,b)=>a.kickoffAt.localeCompare(b.kickoffAt))[0];}
async function recordResult({guild,store,teamKey,opponent,ourScore,opponentScore}){
  let f=findActive(store,teamKey,opponent); if(!f)throw new Error('No active fixture matched that club and opponent.');
  f.status='completed';f.ourScore=ourScore;f.opponentScore=opponentScore;f.result=ourScore>opponentScore?'Win':ourScore<opponentScore?'Loss':'Draw';f.reminder24hSent=true;f.reminder30mSent=true;f=await createOrUpdateDiscord(guild,store,f);
  if(f.discordEventId){const event=await guild.scheduledEvents.fetch(f.discordEventId).catch(()=>null);if(event&&[GuildScheduledEventStatus.Scheduled,GuildScheduledEventStatus.Active].includes(event.status))await event.setStatus(GuildScheduledEventStatus.Completed).catch(()=>{});}
  const recap={fixtureId:f.fixtureId,club:f.club,teamKey,reporter:teamKey==='crownfc'?'Teagan':'Raine',opponent:f.opponent,date:f.dateLabel,kickoff:f.timeLabel,homeAway:f.homeAway,finalScore:`${ourScore}-${opponentScore}`,result:f.result,forumPostLink:`https://discord.com/channels/${guild.id}/${f.forumPostId}`,discordEventId:f.discordEventId,availability:availabilityCounts(f),readyForApprovedRecap:true,createdAt:new Date().toISOString()};
  store.setMetadata(`matchRecapFixture:${f.fixtureId}`,recap); return {fixture:f,recap};
}
async function cancelMatch({guild,store,teamKey,opponent}){let f=findActive(store,teamKey,opponent);if(!f)throw new Error('No active fixture matched that club and opponent.');f.status='cancelled';f.reminder24hSent=true;f.reminder30mSent=true;f=await createOrUpdateDiscord(guild,store,f);if(f.discordEventId){const e=await guild.scheduledEvents.fetch(f.discordEventId).catch(()=>null);if(e)await e.delete('Official fixture cancelled').catch(()=>{});}return f;}
async function editMatch({guild,store,teamKey,opponent,newOpponent,date,time,homeAway,year=2026}){let f=findActive(store,teamKey,opponent);if(!f)throw new Error('No active fixture matched that club and opponent.');const parsed=parseSchedule(`${date||f.dateLabel} | ${time||f.timeLabel} | ${newOpponent||f.opponent} | ${homeAway||f.homeAway}`,{year});if(parsed.invalid.length)throw new Error(parsed.invalid[0].reason);const row=parsed.rows[0];f={...f,opponent:row.opponent,date:row.dateLabel,dateLabel:row.dateLabel,kickoff:row.timeLabel,timeLabel:row.timeLabel,kickoffAt:row.kickoffAt,homeAway:row.homeAway,reminder24hSent:false,reminder30mSent:false};return createOrUpdateDiscord(guild,store,f);}
async function runReminders({guild,store,now=new Date()}){const sent=[];for(let f of fixtures(store).filter(x=>x.status==='upcoming')){const diff=new Date(f.kickoffAt)-now;if(diff<=24*3600000&&diff>30*60000&&!f.reminder24hSent){const t=await guild.channels.fetch(f.forumPostId).catch(()=>null);if(t){const roleId=process.env[CLUBS[f.teamKey].roleEnv];await t.send({content:`${roleId?`<@&${roleId}>\n`:''}⏳ **MATCH TOMORROW**\n${CLUBS[f.teamKey].label} vs ${f.opponent}\nKickoff: ${f.timeLabel} ET\nPlease update your availability if needed.`,allowedMentions:{roles:roleId?[roleId]:[]}});f.reminder24hSent=true;saveFixture(store,f);sent.push(`${f.fixtureId}:24h`);}}
    if(diff<=30*60000&&diff>-15*60000&&!f.reminder30mSent){const t=await guild.channels.fetch(f.forumPostId).catch(()=>null);if(t){const roleId=process.env[CLUBS[f.teamKey].roleEnv];await t.send({content:`${roleId?`<@&${roleId}>\n`:''}${CLUBS[f.teamKey].emoji} **MATCHDAY — LOBBY OPEN**\n${CLUBS[f.teamKey].label} vs ${f.opponent}\nKickoff: ${f.timeLabel} ET\nLobby is open. Be ready and checked in.`,allowedMentions:{roles:roleId?[roleId]:[]}});f.reminder30mSent=true;saveFixture(store,f);sent.push(`${f.fixtureId}:30m`);}}
  }return sent;}
function upcoming(store,teamKey,now=new Date()){return fixtures(store,teamKey).filter(f=>f.status==='upcoming'&&new Date(f.kickoffAt)>=now).sort((a,b)=>a.kickoffAt.localeCompare(b.kickoffAt));}
function fixtureLink(guildId,f){return f.forumPostId?`https://discord.com/channels/${guildId}/${f.forumPostId}`:'Unavailable';}
function nextMatchText(store,teamKey,guildId){const f=upcoming(store,teamKey)[0];if(!f)return `No upcoming ${CLUBS[teamKey].label} fixture is currently saved.`;const c=availabilityCounts(f);const lobby=new Date(new Date(f.kickoffAt)-30*60000).toLocaleTimeString('en-US',{timeZone:TIMEZONE,hour:'numeric',minute:'2-digit'});return `${CLUBS[teamKey].emoji} **MATCH ${matchLabel(f.matchNumber)}**\n${CLUBS[teamKey].label} vs ${f.opponent}\n${f.dateLabel} • ${f.timeLabel} ET\n${f.homeAway}\nLobby: ${lobby} ET\n\nAvailable: ${c.available}\nMaybe: ${c.maybe}\nUnavailable: ${c.unavailable}\n\n[Match Center post](${fixtureLink(guildId,f)})${f.discordEventId?` • [Discord event](https://discord.com/events/${guildId}/${f.discordEventId})`:''}`;}
function scheduleText(store,teamKey,guildId,limit=8){const list=upcoming(store,teamKey).slice(0,limit);if(!list.length)return `No upcoming ${CLUBS[teamKey].label} fixtures are currently saved.`;return `**${CLUBS[teamKey].label} — Upcoming Schedule**\n`+list.map(f=>`• **MATCH ${matchLabel(f.matchNumber)} — ${f.dateLabel} • ${f.timeLabel} ET** — ${f.homeAway==='Home'?'vs':'at'} ${f.opponent}`).join('\n')+`\n\n[Open Match Center](${fixtureLink(guildId,list[0])})`;}

module.exports={CLUBS,TAGS,MLPC_SCHEDULE_2026,parseSchedule,fixtures,getFixture,importSchedule,reorderMatchCenterForum,handleAvailability,recordResult,cancelMatch,editMatch,runReminders,nextMatchText,scheduleText,availabilityCounts,fixtureKey,titleFor,matchLabel};
