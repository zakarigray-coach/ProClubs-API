"""Authenticated read-only RT bridge; SQLite remains the only match store."""
import hmac
from aiohttp import web


def report_payload(db, report_id):
    with db.connect() as conn:
        conn.execute('BEGIN')
        row=conn.execute('SELECT * FROM weekly_reports WHERE report_id=?',(report_id,)).fetchone()
        if not row or row['status'] not in ('draft','approved') or not row['article']:
            raise ValueError('No current review draft is available for that report.')
        report=dict(row)
        matches=[dict(r) for r in conn.execute('SELECT m.* FROM report_matches rm JOIN matches m USING(match_id) WHERE report_id=? ORDER BY played_at,match_id',(report_id,))]
        if not matches or any(not m['report_eligible'] or m['match_type'] not in ('Official','Practice') for m in matches):
            raise ValueError('Report selections need review.')
        if not report['include_development']:
            matches=[m for m in matches if m['match_type']=='Official']
        facts=[]
        for m in matches:
            facts.append({k:m[k] for k in ('match_id','played_at','opponent','birmingham_score','opponent_score','match_type','venue','competition')})
        return {'version':1,'report_id':report_id,'title':report['title'],'article':report['article'],
                'status':report['status'],'week_start':report['week_start'],'week_end':report['week_end'],
                'matches':facts,'published':False}


def create_app(db, secret):
    if len(secret)<32:
        raise ValueError('Reporter connection needs a strong configured secret.')
    @web.middleware
    async def authenticate(request, handler):
        supplied=request.headers.get('Authorization','')
        if not hmac.compare_digest(supplied.encode(),('Bearer '+secret).encode()):
            return web.json_response({'error':'Unauthorized'},status=401)
        return await handler(request)
    app=web.Application(middlewares=[authenticate])
    async def health(request):
        ok=db.one('PRAGMA quick_check')['quick_check']=='ok'
        return web.json_response({'ok':ok,'service':'pep-central-store'},status=200 if ok else 503)
    async def report(request):
        try:
            rid=int(request.match_info['report_id'])
            return web.json_response(report_payload(db,rid),headers={'Cache-Control':'no-store'})
        except (ValueError,TypeError):
            return web.json_response({'error':'Report is unavailable or needs review'},status=404)
    app.router.add_get('/health',health)
    app.router.add_get('/reports/{report_id}',report)
    return app


async def start_api(db, secret, port):
    runner=web.AppRunner(create_app(db,secret),access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner,'::',port).start()
    except Exception:
        await runner.cleanup()
        raise
    return runner
