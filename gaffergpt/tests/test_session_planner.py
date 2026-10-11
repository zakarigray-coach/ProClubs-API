import asyncio
import json
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import discord
from aiohttp.test_utils import TestClient,TestServer
from gaffergpt.database import Database
from gaffergpt.session_store import SessionStore,local_time,validate_layout,default_layout,hash_token
from gaffergpt.session_planner import SessionService,RSVPView,render_embed,register_sessions
from gaffergpt.media_api import create_app

class Message:
    def __init__(self,id,embed):self.id=id;self.embeds=[embed];self.author=SimpleNamespace(id=999);self.edits=0
    async def edit(self,**args):self.embeds=[args['embed']];self.edits+=1
class Channel:
    id=10;guild=SimpleNamespace(id=2)
    def __init__(self):self.messages=[]
    def permissions_for(self,member):return SimpleNamespace(view_channel=True)
    async def send(self,**args):
        m=Message(100+len(self.messages),args['embed']);self.messages.append(m);return m
    async def fetch_message(self,id):return next(m for m in self.messages if m.id==id)
    async def history(self,**args):
        for m in self.messages:yield m
class Event:
    def __init__(self,id,**args):self.id=id;self.creator_id=999;self.description=args['description'];self.status=discord.EventStatus.scheduled;self.edits=[]
    async def edit(self,**args):
        self.edits.append(args)
        for k,v in args.items():setattr(self,k,v)
        return self
class Guild:
    id=2;channels=[]
    def __init__(self):self.events=[];self.allow=True
    async def fetch_scheduled_events(self):return self.events
    async def create_scheduled_event(self,**args):
        if not self.allow:raise discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),{'code':50013,'message':'Missing Permissions'})
        event=Event(200+len(self.events),**args);self.events.append(event);return event
    async def fetch_scheduled_event(self,id):return next(e for e in self.events if e.id==id)
    async def fetch_member(self,id):
        if id==77:raise discord.NotFound(SimpleNamespace(status=404,reason='Missing'),{'code':10007,'message':'Unknown Member'})
        return SimpleNamespace(id=id,roles=[SimpleNamespace(id=5)] if id==3 else [],display_name='Coach' if id==1 else 'Player',bot=False)
class Bot:
    def __init__(self,db):
        self.db=db;self.config=SimpleNamespace(guild_id=2,owner_id=1,management_role_ids=(5,));self.user=SimpleNamespace(id=999);self.channel=Channel();self.guild=Guild()
        self.sessions=SessionService(self)
    def get_guild(self,id):return self.guild
    async def fetch_channel(self,id):return self.channel

class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(Path(self.tmp.name)/'db.sqlite');self.bot=Bot(self.db);self.service=self.bot.sessions;self.store=self.service.store
    async def asyncTearDown(self):self.tmp.cleanup()
    def data(self,**overrides):
        day=(datetime.now(timezone.utc)+timedelta(days=5)).date().isoformat()
        data={'title':'Minglewood Cup Prep Practice','session_type':'Practice','start_at':local_time(day,'20:00'),'end_at':local_time(day,'22:00'),'description':'Prepare our roles and tactics.','location':'Discord','voice_channel_id':None,'post_channel_id':'10','club':'MPL Birmingham City','required':1,'deadline_at':local_time(day,'18:00'),'min_players':9,'lineup_note':'Be available for Cup lineup consideration.','notes':'','template_id':self.store.templates()[0]['template_id']};data.update(overrides);return data
    async def test_full_create_rsvp_events_edit_cancel_lifecycle(self):
        row=self.store.create(self.data(),1,'command1');sid=row['session_id'];await self.service.sync(sid)
        self.assertEqual(len(self.bot.channel.messages),1);self.assertEqual(len(self.bot.guild.events),1)
        member=SimpleNamespace(id=4,display_name='DaddyGray10420')
        await self.service.respond(sid,member,'Available',4)
        payload=self.service.payload(sid);self.assertEqual(payload['counts']['Available'],1);self.assertIn('DaddyGray10420',str(self.bot.channel.messages[0].embeds[0].to_dict()))
        old=self.store.get(sid);self.store.edit(sid,{'title':'Updated cup prep'},1,old['revision']);await self.service.sync(sid)
        updated=self.store.get(sid);self.assertEqual(updated['message_id'],row['message_id'] or '100');self.assertEqual(updated['event_id'],'200');self.assertEqual(len(self.bot.channel.messages),1);self.assertEqual(len(self.bot.guild.events),1)
        self.assertEqual(self.bot.guild.events[0].name,'Updated cup prep')
        self.store.cancel(sid,1,'Postponed');await self.service.sync(sid)
        self.assertEqual(self.bot.guild.events[0].status,discord.EventStatus.cancelled);self.assertTrue(all(b.disabled for b in RSVPView(self.service,sid).children[:3]));self.assertIn('CANCELLED',self.bot.channel.messages[0].embeds[0].title)
        with self.assertRaises(ValueError):self.store.respond(sid,4,'Player','Available',4)
        self.assertEqual(len(self.db.rows('SELECT * FROM matches')),0)
    async def test_restart_dedup_and_crash_reconciliation(self):
        row=self.store.create(self.data(),1,'same-command');await self.service.sync(row['session_id'])
        self.assertEqual(self.store.create(self.data(),1,'same-command')['session_id'],row['session_id'])
        self.db.execute('UPDATE team_sessions SET message_id=NULL,event_id=NULL,sync_needed=1 WHERE session_id=?',(row['session_id'],))
        self.bot.sessions=SessionService(self.bot);await self.bot.sessions.sync(row['session_id'])
        self.assertEqual(len(self.bot.channel.messages),1);self.assertEqual(len(self.bot.guild.events),1);self.assertEqual(len(self.bot.sessions.store.attendance(row['session_id'])),0)
    async def test_availability_replaces_previous_choice_and_deadline(self):
        row=self.store.create(self.data(),1,'rsvp');sid=row['session_id']
        self.store.respond(sid,4,'Player','Available',4);self.store.respond(sid,4,'Player','Maybe',4)
        self.assertEqual(len(self.store.attendance(sid)),1);self.assertEqual(self.service.payload(sid)['counts']['Available'],0)
        with self.assertRaises(ValueError):self.store.respond(sid,4,'Player','Available',4,now=row['deadline_at'])
        self.store.respond(sid,4,'Player','Unavailable',1,True,now=row['deadline_at']);self.assertEqual(self.store.attendance(sid)[0]['status'],'Unavailable')
    async def test_template_updates_posts_and_optimistic_lock(self):
        row=self.store.create(self.data(),1,'layout');await self.service.sync(row['session_id']);t=self.store.template(row['template_id']);layout=t['layout'];layout['header']='⚽ {title}';layout['hidden']=['notes'];layout['order']=list(reversed(layout['order']));self.store.save_template(t['name'],layout,1,t['template_id'],t['revision']);await self.service.tick()
        self.assertTrue(self.bot.channel.messages[0].embeds[0].title.startswith('⚽'))
        with self.assertRaises(ValueError):self.store.save_template(t['name'],layout,1,t['template_id'],t['revision'])
    async def test_native_permissions_do_not_block_session(self):
        self.bot.guild.allow=False;row=self.store.create(self.data(),1,'denied');await self.service.sync(row['session_id'])
        saved=self.store.get(row['session_id']);self.assertIsNotNone(saved['message_id']);self.assertIsNone(saved['sync_error']);self.assertIn('Create Events',saved['event_notice']);self.bot.guild.allow=True;await self.service.tick();self.assertEqual(len(self.bot.guild.events),1)
    async def test_expired_buttons_update_and_completed_session_persists(self):
        row=self.store.create(self.data(),1,'closed');await self.service.sync(row['session_id']);self.db.execute('UPDATE team_sessions SET deadline_at=? WHERE session_id=?',('2000-01-01T00:00:00+00:00',row['session_id']));await self.service.tick();self.assertTrue(RSVPView(self.service,row['session_id']).children[0].disabled)
        self.db.execute('UPDATE team_sessions SET start_at=?,end_at=? WHERE session_id=?',('2000-01-01T00:00:00+00:00','2000-01-02T00:00:00+00:00',row['session_id']));await self.service.tick();self.assertEqual(self.store.get(row['session_id'])['status'],'Completed');self.assertEqual(len(self.store.list()),1)
    async def test_dates_and_layout_validation(self):
        self.assertEqual(local_time('2026-10-12','20:00'),'2026-10-13T00:00:00+00:00')
        for day,time in [('2026-03-08','02:30'),('2026-11-01','01:30')]:
            with self.assertRaises(ValueError):local_time(day,time)
        for changes in [{'colour':123},{'order':[{}]},{'hidden':[{}]},{'logo_url':'http://unsafe'},{'buttons':{}}]:
            layout=default_layout('');layout.update(changes)
            with self.assertRaises(ValueError):validate_layout(layout)
        with self.assertRaises(ValueError):self.store.create(self.data(end_at=self.data()['start_at']),1,'invalid')
        row=self.store.create(self.data(),1,'valid');await self.service.sync(row['session_id'])
        with self.assertRaises(ValueError):self.store.edit(row['session_id'],{'post_channel_id':'11'},1,row['revision'])
    async def test_command_registration_and_persistent_views(self):
        from gaffergpt.bot import GafferBot
        from gaffergpt.config import Config
        bot=GafferBot(Config('test',1,2,0,0,(5,),str(Path(self.tmp.name)/'commands.db'),False));group=bot.tree.get_command('session')
        self.assertEqual({c.name for c in group.commands},{'create','edit','cancel','attendance','view','events','dashboard'})
        self.assertTrue(group.get_command('create').checks);await bot.close()
        row=self.store.create(self.data(),1,'view');self.assertTrue(RSVPView(self.service,row['session_id']).is_persistent())
    async def test_http_auth_roles_csrf_and_events(self):
        client=TestClient(TestServer(create_app(self.db,'x'*48,self.bot)));await client.start_server()
        try:
            self.assertEqual((await client.get('/health')).status,401)
            self.assertEqual((await client.get('/health',headers={'Authorization':'Bearer '+'x'*48})).status,200)
            self.assertEqual((await client.get('/planner/api/events')).status,401)
            token=self.store.issue_login(4);res=await client.get('/planner/login?token='+token,allow_redirects=False);self.assertEqual(res.status,302);cookie=res.cookies['pep_planner'].value
            self.assertTrue(res.cookies['pep_planner']['httponly']);self.assertTrue(res.cookies['pep_planner']['secure'])
            headers={'Cookie':'pep_planner='+cookie,'X-Pep-CSRF':hash_token('csrf:'+cookie)}
            self.assertEqual((await client.get('/planner/login?token='+token,allow_redirects=False)).status,401)
            self.assertEqual((await client.post('/planner/api/events',json={},headers=headers)).status,403)
            row=self.store.create(self.data(),1,'http');await self.service.sync(row['session_id']);sid=row['session_id']
            self.assertEqual((await client.post(f'/planner/api/events/{sid}/rsvp',json={'status':'Available'},headers={'Cookie':'pep_planner='+cookie})).status,403)
            self.assertEqual((await client.post(f'/planner/api/events/{sid}/rsvp',json={'status':'Available'},headers=headers)).status,200)
            self.assertEqual((await client.post(f'/planner/api/events/{sid}/rsvp',json={'status':'Available','user_id':'3'},headers=headers)).status,403)
            response=await client.get('/planner/api/events',headers=headers);data=await response.json();self.assertEqual(data['sessions'][0]['counts']['Available'],1);self.assertNotIn('lease_owner',data['sessions'][0])
            page=await client.get('/planner/events/'+str(sid),headers=headers);self.assertEqual(page.status,200);self.assertIn('frame-ancestors',page.headers['Content-Security-Policy'])
            token=self.store.issue_login(1);response=await client.get('/planner/login?token='+token,allow_redirects=False);owner=response.cookies['pep_planner'].value;headers={'Cookie':'pep_planner='+owner,'X-Pep-CSRF':hash_token('csrf:'+owner)}
            self.assertEqual((await client.post(f'/planner/api/events/{sid}',json={'data':{'title':'HTTP edited'},'revision':self.store.get(sid)['revision']},headers=headers)).status,200)
            self.assertEqual((await client.post(f'/planner/api/events/{sid}/rsvp',json={'status':'Maybe','user_id':'3'},headers=headers)).status,200)
            self.assertEqual(len(self.bot.channel.messages),1)
        finally:await client.close()

    async def test_http_create_edit_template_and_cancel_preserve_identity(self):
        client=TestClient(TestServer(create_app(self.db,'x'*48,self.bot)));await client.start_server()
        try:
            token=self.store.issue_login(1);response=await client.get('/planner/login?token='+token,allow_redirects=False);cookie=response.cookies['pep_planner'].value;headers={'Cookie':'pep_planner='+cookie,'X-Pep-CSRF':hash_token('csrf:'+cookie)}
            with patch('gaffergpt.session_dashboard.discord.TextChannel',Channel):
                response=await client.post('/planner/api/events',json={'request_id':'dashboard1','data':self.data()},headers=headers)
                self.assertEqual(response.status,200,await response.text());row=await response.json();sid=row['session_id']
                again=await client.post('/planner/api/events',json={'request_id':'dashboard1','data':self.data()},headers=headers);self.assertEqual((await again.json())['session_id'],sid)
            template=self.store.template(row['template_id']);layout=template['layout'];layout['footer']='Birmingham • Keep Right On'
            response=await client.post('/planner/api/templates',json={'name':template['name'],'layout':layout,'template_id':template['template_id'],'revision':template['revision']},headers=headers);self.assertEqual(response.status,200)
            await self.service.tick();self.assertIn('Birmingham • Keep Right On',self.bot.channel.messages[0].embeds[0].footer.text)
            response=await client.post(f'/planner/api/events/{sid}/cancel',json={'reason':'Test complete'},headers=headers);self.assertEqual(response.status,200)
            self.assertEqual(len(self.bot.guild.events),1);self.assertEqual(len(self.bot.channel.messages),1)
        finally:await client.close()

    async def test_layout_overflow_held_before_creation_and_attendance_fits(self):
        template=self.store.templates()[0];layout=template['layout'];layout['custom_fields']=[{'key':'custom:'+str(i),'name':'Field '+str(i),'value':'X'*900} for i in range(8)];layout['order']+=['custom:'+str(i) for i in range(8)];saved=self.store.save_template('Too much',layout,1)
        with self.assertRaisesRegex(ValueError,'too much text'):self.service.validate_post(self.data(template_id=saved['template_id']))
        self.assertEqual(len(self.store.list()),0)
        row=self.store.create(self.data(description='X'*1800,lineup_note='X'*900,notes='X'*900),1,'big');sid=row['session_id']
        for i in range(90):self.store.respond(sid,1000+i,'Long player name '+str(i),('Available','Maybe','Unavailable')[i%3],1000+i)
        self.assertLessEqual(len(render_embed(self.store,self.store.get(sid))),5900)
        self.assertEqual(sum(self.service.payload(sid)['counts'].values()),90)

    async def test_role_revocation_and_expired_login(self):
        client=TestClient(TestServer(create_app(self.db,'x'*48,self.bot)));await client.start_server()
        try:
            token=self.store.issue_login(77);response=await client.get('/planner/login?token='+token,allow_redirects=False);cookie=response.cookies['pep_planner'].value
            self.assertEqual((await client.get('/planner/api/bootstrap',headers={'Cookie':'pep_planner='+cookie})).status,403)
            token=self.store.issue_login(1);self.db.execute('UPDATE planner_logins SET expires_at=?',('2000-01-01T00:00:00+00:00',))
            self.assertEqual((await client.get('/planner/login?token='+token,allow_redirects=False)).status,401)
        finally:await client.close()
