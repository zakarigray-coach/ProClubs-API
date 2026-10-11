"""Private session dashboard on Pep's existing HTTP service."""
import hmac
import json
import sqlite3
from pathlib import Path
import discord
from aiohttp import web
from .session_store import hash_token, TYPES, RESPONSES, SECTIONS
from .session_planner import render_embed

MEMBER=web.RequestKey('pep_member',object)
MANAGER=web.RequestKey('pep_manager',bool)
ASSETS=Path(__file__).parent/'planner_assets'
COOKIE='pep_planner'
HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff',
         'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' https:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"}


def install_dashboard(app,bot):
    service=bot.sessions;store=service.store
    def route(handler,manager=False):
        async def protected(request):
            try:
                raw=request.cookies.get(COOKIE,'');identity=store.web_identity(raw)
                if not identity:raise web.HTTPUnauthorized(text='Run /session dashboard in Discord for a private sign-in link.')
                member,is_manager=await service.identity(identity['user_id'])
                if manager and not is_manager:raise web.HTTPForbidden(text='Approved management only.')
                if request.method!='GET' and not hmac.compare_digest(request.headers.get('X-Pep-CSRF',''),hash_token('csrf:'+raw)):
                    raise web.HTTPForbidden(text='Reload this page before saving.')
                request[MEMBER]=member;request[MANAGER]=is_manager
                response=await handler(request)
                response.headers.update(HEADERS)
                return response
            except (ValueError,TypeError,KeyError,json.JSONDecodeError,sqlite3.IntegrityError) as error:
                return web.json_response({'error':str(error) if not isinstance(error,sqlite3.IntegrityError) else 'That template name already exists.'},status=400,headers=HEADERS)
            except discord.HTTPException:
                raise web.HTTPForbidden(text='Pep cannot verify your current server membership or access.') from None
        return protected

    async def login(request):
        try:cookie=store.consume_login(request.query.get('token',''))
        except ValueError as error:raise web.HTTPUnauthorized(text=str(error)) from None
        sid=request.query.get('session','')
        target='/planner/events/'+sid if sid.isdigit() else '/planner/events'
        response=web.HTTPFound(target,headers=HEADERS)
        response.set_cookie(COOKIE,cookie,max_age=43200,httponly=True,secure=True,samesite='Strict',path='/planner/')
        raise response
    async def page(request):return web.FileResponse(ASSETS/'planner.html',headers=HEADERS)
    async def asset(request):
        name=request.match_info['name']
        if name not in ('planner.js','planner.css'):raise web.HTTPNotFound()
        return web.FileResponse(ASSETS/name,headers=HEADERS)
    async def bootstrap(request):
        guild=bot.get_guild(bot.config.guild_id)
        channels=[{'id':str(c.id),'name':c.name,'voice':isinstance(c,discord.VoiceChannel)} for c in getattr(guild,'channels',[]) if isinstance(c,(discord.TextChannel,discord.VoiceChannel)) and c.permissions_for(request[MEMBER]).view_channel]
        return web.json_response({'user':{'id':str(request[MEMBER].id),'name':request[MEMBER].display_name},'manager':request[MANAGER],
             'csrf':hash_token('csrf:'+request.cookies[COOKIE]),'templates':store.templates(),'types':TYPES,'responses':RESPONSES,'sections':SECTIONS,'channels':channels})
    async def events(request):
        rows=[service.payload(row['session_id']) for row in store.list()]
        # Delivery internals are never exposed to players or the browser.
        return web.json_response({'sessions':[public(row) for row in rows]})
    async def detail(request):return web.json_response(public(service.payload(int(request.match_info['sid']))))
    async def check_channels(data,member):
        for field in ('post_channel_id','voice_channel_id'):
            if not data.get(field):continue
            channel=await bot.fetch_channel(int(data[field]))
            expected=discord.TextChannel if field=='post_channel_id' else discord.VoiceChannel
            if not isinstance(channel,expected) or channel.guild.id!=bot.config.guild_id or not channel.permissions_for(member).view_channel:
                raise ValueError('Choose an accessible club '+('text' if field=='post_channel_id' else 'voice')+' channel.')
    async def save(request):
        body=await request.json();data=body['data'];sid=request.match_info.get('sid')
        await check_channels(data,request[MEMBER])
        if sid:
            old=store.get(int(sid))
            if data.get('post_channel_id',old['post_channel_id'])!=old['post_channel_id'] and old['message_id']:
                raise ValueError('Keep the original posting channel when editing a posted session.')
            combined={k:old[k] for k in ('title','session_type','start_at','end_at','description','location','voice_channel_id','post_channel_id','club','required','deadline_at','min_players','lineup_note','notes','template_id')}
            combined.update(data);service.validate_post(combined,int(sid))
            row=store.edit(int(sid),data,request[MEMBER].id,body['revision'])
        else:
            service.validate_post(data)
            row=store.create(data,request[MEMBER].id,body['request_id'])
        # Reject a layout that cannot be posted before attempting Discord delivery.
        render_embed(store,row)
        await service.sync(row['session_id'])
        return web.json_response(public(service.payload(row['session_id'])))
    async def cancel(request):
        body=await request.json();row=store.cancel(int(request.match_info['sid']),request[MEMBER].id,body.get('reason',''))
        await service.sync(row['session_id']);return web.json_response(public(service.payload(row['session_id'])))
    async def rsvp(request):
        body=await request.json();member=request[MEMBER];manual=False
        if body.get('user_id') and str(body['user_id'])!=str(member.id):
            if not request[MANAGER]:raise web.HTTPForbidden(text='Players can only change their own response.')
            member,_=await service.identity(body['user_id']);manual=True
        await service.respond(int(request.match_info['sid']),member,body['status'],request[MEMBER].id,manual)
        return web.json_response(public(service.payload(int(request.match_info['sid']))))
    async def template(request):
        body=await request.json()
        from .session_store import validate_layout
        layout=validate_layout(body['layout'])
        if body.get('template_id'):
            for row in store.list():
                if row['template_id']==body['template_id'] and row['status']=='Scheduled':
                    data={k:row[k] for k in ('title','session_type','start_at','end_at','description','location','voice_channel_id','post_channel_id','club','required','deadline_at','min_players','lineup_note','notes','template_id')}
                    service.validate_post(data,row['session_id'],layout)
        saved=store.save_template(body['name'],layout,request[MEMBER].id,body.get('template_id'),body.get('revision'))
        # Durable background sync updates sessions using this template.
        return web.json_response(saved)
    async def preview(request):
        body=await request.json()
        from .session_store import validate_layout
        layout=validate_layout(body['layout'])
        return web.json_response({'layout':layout})
    async def logout(request):
        bot.db.execute('DELETE FROM planner_web_sessions WHERE token_hash=?',(hash_token(request.cookies[COOKIE]),))
        response=web.json_response({'ok':True});response.del_cookie(COOKIE,path='/planner/');return response
    app.router.add_get('/planner/login',login)
    app.router.add_get('/planner/assets/{name}',asset)
    app.router.add_get('/planner/events',route(page))
    app.router.add_get('/planner/events/{sid}',route(page))
    app.router.add_get('/planner/api/bootstrap',route(bootstrap))
    app.router.add_get('/planner/api/events',route(events))
    app.router.add_get('/planner/api/events/{sid}',route(detail))
    app.router.add_post('/planner/api/events',route(save,True))
    app.router.add_post('/planner/api/events/{sid}',route(save,True))
    app.router.add_post('/planner/api/events/{sid}/cancel',route(cancel,True))
    app.router.add_post('/planner/api/events/{sid}/rsvp',route(rsvp))
    app.router.add_post('/planner/api/templates',route(template,True))
    app.router.add_post('/planner/api/preview',route(preview,True))
    app.router.add_post('/planner/api/logout',route(logout))


def public(row):
    hidden={'lease_owner','lease_until','embed_hash','event_hash','request_id','delivery_attempts'}
    return {key:value for key,value in row.items() if key not in hidden}
