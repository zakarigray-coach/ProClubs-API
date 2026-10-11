"""Team sessions and layout templates in Pep's existing SQLite database."""
import hashlib
import json
import secrets
from datetime import datetime,timezone,timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from .database import utcnow

ET=ZoneInfo('America/New_York')
TYPES=('Practice','Scrim','Match','Tournament','Meeting','Other')
RESPONSES=('Available','Maybe','Unavailable')
SECTIONS=('description','time','type','club','location','required','deadline','minimum','lineup','attendance','notes')
SCHEMA='''
CREATE TABLE IF NOT EXISTS session_templates (
 template_id INTEGER PRIMARY KEY,guild_id TEXT NOT NULL,name TEXT NOT NULL,layout TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1,updated_by TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(guild_id,name)
);
CREATE TABLE IF NOT EXISTS team_sessions (
 session_id INTEGER PRIMARY KEY,guild_id TEXT NOT NULL,request_id TEXT NOT NULL,title TEXT NOT NULL,
 session_type TEXT NOT NULL CHECK(session_type IN ('Practice','Scrim','Match','Tournament','Meeting','Other')),
 start_at TEXT NOT NULL,end_at TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',location TEXT NOT NULL,
 voice_channel_id TEXT,post_channel_id TEXT NOT NULL,club TEXT NOT NULL,required INTEGER NOT NULL CHECK(required IN (0,1)),
 deadline_at TEXT,min_players INTEGER NOT NULL CHECK(min_players BETWEEN 0 AND 100),lineup_note TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '',template_id INTEGER NOT NULL REFERENCES session_templates(template_id),
 message_id TEXT,event_id TEXT,status TEXT NOT NULL DEFAULT 'Scheduled' CHECK(status IN ('Scheduled','Cancelled','Completed')),
 revision INTEGER NOT NULL DEFAULT 1,created_by TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 sync_needed INTEGER NOT NULL DEFAULT 1,sync_error TEXT,event_notice TEXT,delivery_attempts INTEGER NOT NULL DEFAULT 0,
 lease_owner TEXT,lease_until TEXT,embed_hash TEXT,event_hash TEXT,last_sync_at TEXT,
 UNIQUE(guild_id,request_id),CHECK(end_at>start_at)
);
CREATE INDEX IF NOT EXISTS team_sessions_time ON team_sessions(guild_id,start_at);
CREATE TABLE IF NOT EXISTS session_rsvps (
 session_id INTEGER NOT NULL REFERENCES team_sessions(session_id),user_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('Available','Maybe','Unavailable')),display_name TEXT NOT NULL,
 updated_by TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(session_id,user_id)
);
CREATE TABLE IF NOT EXISTS session_changes (
 id INTEGER PRIMARY KEY,session_id INTEGER REFERENCES team_sessions(session_id),actor_id TEXT NOT NULL,
 action TEXT NOT NULL,details TEXT NOT NULL,created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS planner_logins (
 token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,guild_id TEXT NOT NULL,expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS planner_web_sessions (
 token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,guild_id TEXT NOT NULL,expires_at TEXT NOT NULL
);
'''


def hash_token(value):return hashlib.sha256(value.encode()).hexdigest()


def local_time(day,time):
    """Eastern wall time, with explicit rejection of ambiguous or skipped DST times."""
    try:
        naive=datetime.fromisoformat(day+'T'+time)
        if naive.tzinfo:return naive.astimezone(timezone.utc).isoformat()
        a=naive.replace(tzinfo=ET,fold=0);b=naive.replace(tzinfo=ET,fold=1)
        if a.astimezone(timezone.utc).astimezone(ET).replace(tzinfo=None)!=naive:
            raise ValueError('That local time does not exist during the daylight-saving change.')
        if a.utcoffset()!=b.utcoffset():raise ValueError('That time occurs twice. Add an offset, such as 01:30-04:00.')
        return a.astimezone(timezone.utc).isoformat()
    except (TypeError,ValueError) as error:
        raise ValueError('Use YYYY-MM-DD and HH:MM in Eastern time. '+str(error)) from None


def default_layout(name):
    return {'header':'{title}','colour':'#154a91','logo_url':'','banner_url':'',
            'footer':'Pep • Birmingham Tactical Coach 🔵 | Keep Right On','date_format':'discord',
            'order':list(SECTIONS),'hidden':[],
            'buttons':{s:{'label':s,'emoji':e} for s,e in zip(RESPONSES,('✅','❓','❌'))},'custom_fields':[]}


def validate_layout(layout):
    if not isinstance(layout,dict):raise ValueError('Layout must be an object.')
    allowed={'header','colour','logo_url','banner_url','footer','date_format','order','hidden','buttons','custom_fields'}
    if layout.keys()-allowed:raise ValueError('Unknown layout setting.')
    clean=default_layout('');clean.update(layout)
    for field,limit in [('header',200),('footer',500)]:
        if not isinstance(clean[field],str) or len(clean[field])>limit:raise ValueError('Layout '+field+' is too long.')
    import re
    if not isinstance(clean['colour'],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',clean['colour']):raise ValueError('Use a six-digit hex colour.')
    for field in ('logo_url','banner_url'):
        value=clean[field]
        if not isinstance(value,str) or len(value)>1000:raise ValueError('Invalid image URL.')
        if value:
            url=urlparse(value)
            if url.scheme!='https' or not url.netloc or url.username or url.password:raise ValueError('Use an HTTPS image URL without login credentials.')
    if clean['date_format'] not in ('discord','long','short'):raise ValueError('Choose Discord, long or short dates.')
    custom=clean['custom_fields']
    if not isinstance(custom,list) or len(custom)>8:raise ValueError('Use at most eight custom fields.')
    keys=[]
    for field in custom:
        if not isinstance(field,dict) or set(field)-{'key','name','value','inline'}:raise ValueError('Invalid custom field.')
        if not isinstance(field.get('key'),str) or not re.fullmatch(r'custom:[a-zA-Z0-9_-]{1,32}',field['key']):raise ValueError('Custom fields need a unique key.')
        if not isinstance(field.get('name'),str) or not 1<=len(field['name'])<=80:raise ValueError('Custom field names need 1–80 characters.')
        if not isinstance(field.get('value'),str) or len(field['value'])>900:raise ValueError('Custom field text is too long.')
        if type(field.get('inline',False)) is not bool:raise ValueError('Custom field inline must be true or false.')
        keys.append(field['key'])
    order=clean['order'];hidden=clean['hidden'];allowed_keys=set(SECTIONS)|set(keys)
    if len(set(keys))!=len(keys) or not isinstance(order,list) or not all(isinstance(k,str) for k in order) or len(order)!=len(set(order)) or set(order)!=allowed_keys:
        raise ValueError('Field order must contain every standard/custom section exactly once.')
    if not isinstance(hidden,list) or not all(isinstance(k,str) for k in hidden) or set(hidden)-allowed_keys:raise ValueError('Invalid hidden sections.')
    for status in RESPONSES:
        button=clean['buttons'].get(status) if isinstance(clean['buttons'],dict) else None
        if not isinstance(button,dict) or set(button)-{'label','emoji'}:raise ValueError('Keep all three attendance buttons.')
        if not isinstance(button.get('label'),str) or not 1<=len(button['label'])<=60:raise ValueError('Button labels need 1–60 characters.')
        if not isinstance(button.get('emoji'),str) or len(button['emoji'])>32:raise ValueError('Invalid button emoji.')
    return clean


class SessionStore:
    def __init__(self,db,guild_id):
        self.db=db;self.guild_id=str(guild_id)
        with db.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute('INSERT OR IGNORE INTO schema_migrations VALUES (4,?)',(utcnow(),))
            for name in ('Practice','Scrim','Match Night','Cup / Tournament'):
                layout=default_layout(name)
                if name=='Cup / Tournament':layout.update(colour='#ac8736',header='🏆 {title}')
                if name=='Match Night':layout.update(header='⚽ {title}')
                conn.execute('INSERT OR IGNORE INTO session_templates(guild_id,name,layout,updated_by,updated_at) VALUES (?,?,?,?,?)',
                             (self.guild_id,name,json.dumps(layout),'system',utcnow()))

    def templates(self):
        return [dict(row,layout=json.loads(row['layout'])) for row in self.db.rows('SELECT * FROM session_templates WHERE guild_id=? ORDER BY template_id',(self.guild_id,))]

    def template(self,template_id):
        row=self.db.one('SELECT * FROM session_templates WHERE guild_id=? AND template_id=?',(self.guild_id,template_id))
        if not row:raise ValueError('Template not found.')
        return dict(row,layout=json.loads(row['layout']))

    def save_template(self,name,layout,actor,template_id=None,revision=None):
        layout=validate_layout(layout)
        if not isinstance(name,str) or not 1<=len(name.strip())<=80:raise ValueError('Template name needs 1–80 characters.')
        with self.db.connect() as conn:
            if template_id:
                current=self.template(template_id)
                if current['revision']!=revision:raise ValueError('This layout changed. Reload before saving.')
                saved=conn.execute('UPDATE session_templates SET name=?,layout=?,revision=revision+1,updated_by=?,updated_at=? WHERE template_id=? AND guild_id=? AND revision=?',
                             (name.strip(),json.dumps(layout),str(actor),utcnow(),template_id,self.guild_id,revision))
                if not saved.rowcount:raise ValueError('This layout changed. Reload before saving.')
                conn.execute("UPDATE team_sessions SET sync_needed=1,revision=revision+1 WHERE template_id=? AND status='Scheduled'",(template_id,))
            else:
                template_id=conn.execute('INSERT INTO session_templates(guild_id,name,layout,updated_by,updated_at) VALUES (?,?,?,?,?)',
                                         (self.guild_id,name.strip(),json.dumps(layout),str(actor),utcnow())).lastrowid
        return self.template(template_id)

    def get(self,sid):
        row=self.db.one('SELECT * FROM team_sessions WHERE session_id=? AND guild_id=?',(sid,self.guild_id))
        if not row:raise ValueError('Session not found in this club server.')
        return row

    def list(self):
        return self.db.rows('SELECT * FROM team_sessions WHERE guild_id=? ORDER BY start_at DESC',(self.guild_id,))

    def validate(self,data):
        allowed={'title','session_type','start_at','end_at','description','location','voice_channel_id','post_channel_id','club','required','deadline_at','min_players','lineup_note','notes','template_id'}
        if not isinstance(data,dict):raise ValueError('Session fields must be an object.')
        if data.keys()-allowed:raise ValueError('Unknown session field.')
        required_keys=allowed-{'deadline_at','voice_channel_id'}
        if required_keys-data.keys():raise ValueError('Missing session fields: '+', '.join(sorted(required_keys-data.keys())))
        for key,limit in [('title',100),('description',1800),('location',100),('club',80),('lineup_note',900),('notes',900)]:
            if not isinstance(data.get(key),str) or len(data[key])>limit:raise ValueError('Invalid or oversized '+key+'.')
        if not data['title'].strip() or not data['club'].strip() or not data['location'].strip():raise ValueError('Title, club and location are required.')
        if data['session_type'] not in TYPES:raise ValueError('Choose a supported session type.')
        if type(data['required']) not in (int,bool) or data['required'] not in (0,1):raise ValueError('Attendance required must be true or false.')
        if type(data['min_players']) is not int or not 0<=data['min_players']<=100:raise ValueError('Minimum players must be 0–100.')
        for key in ('post_channel_id','voice_channel_id'):
            if data.get(key) is not None and not str(data[key]).isdigit():raise ValueError('Invalid Discord channel ID.')
        for key in ('start_at','end_at','deadline_at'):
            if data.get(key):
                value=datetime.fromisoformat(data[key])
                if value.tzinfo is None:
                    data[key]=local_time(value.date().isoformat(),value.strftime('%H:%M'))
                    value=datetime.fromisoformat(data[key])
                data[key]=value.astimezone(timezone.utc).isoformat()
        if not data.get('start_at') or not data.get('end_at'):raise ValueError('Start and end dates are required.')
        if not data.get('post_channel_id'):raise ValueError('Choose a posting channel.')
        if data['end_at']<=data['start_at']:raise ValueError('End time must follow the start. Use an end date for overnight sessions.')
        if data.get('deadline_at') and data['deadline_at']>data['start_at']:raise ValueError('Response deadline must be no later than the start.')
        self.template(data['template_id'])
        return data

    def create(self,data,actor,request_id):
        data=self.validate(dict(data));keys=list(data)
        with self.db.connect() as conn:
            inserted=conn.execute('INSERT OR IGNORE INTO team_sessions(guild_id,request_id,'+','.join(keys)+',created_by,created_at,updated_at) VALUES ('+','.join('?' for _ in range(len(keys)+5))+')',
                         [self.guild_id,str(request_id)]+[data[k] for k in keys]+[str(actor),utcnow(),utcnow()])
            row=conn.execute('SELECT session_id FROM team_sessions WHERE guild_id=? AND request_id=?',(self.guild_id,str(request_id))).fetchone()
            if inserted.rowcount:self.audit(conn,row['session_id'],actor,'create',data)
        return self.get(row['session_id'])

    def edit(self,sid,changes,actor,revision):
        old=self.get(sid)
        if old['status']=='Cancelled':raise ValueError('Cancelled sessions remain archived. Create a new session instead.')
        fields={k:old[k] for k in ('title','session_type','start_at','end_at','description','location','voice_channel_id','post_channel_id','club','required','deadline_at','min_players','lineup_note','notes','template_id')}
        if not isinstance(changes,dict):raise ValueError('Session changes must be an object.')
        if old['message_id'] and str(changes.get('post_channel_id',old['post_channel_id']))!=old['post_channel_id']:
            raise ValueError('Keep the original posting channel when editing a posted session.')
        fields.update(changes);fields=self.validate(fields)
        with self.db.connect() as conn:
            cur=conn.execute('UPDATE team_sessions SET '+','.join(k+'=?' for k in fields)+",revision=revision+1,updated_at=?,sync_needed=1,status='Scheduled' WHERE session_id=? AND guild_id=? AND revision=?",
                             [fields[k] for k in fields]+[utcnow(),sid,self.guild_id,revision])
            if not cur.rowcount:raise ValueError('This session changed. Reload before saving.')
            self.audit(conn,sid,actor,'edit',changes)
        return self.get(sid)

    def cancel(self,sid,actor,reason=''):
        self.get(sid)
        with self.db.connect() as conn:
            conn.execute("UPDATE team_sessions SET status='Cancelled',revision=revision+1,notes=?,updated_at=?,sync_needed=1 WHERE session_id=? AND guild_id=?",(str(reason)[:900],utcnow(),sid,self.guild_id))
            self.audit(conn,sid,actor,'cancel',{'reason':reason})
        return self.get(sid)

    def attendance(self,sid):
        self.get(sid)
        return self.db.rows('SELECT * FROM session_rsvps WHERE session_id=? ORDER BY display_name COLLATE NOCASE,user_id',(sid,))

    def respond(self,sid,user_id,name,status,actor,manual=False,now=None):
        if status not in RESPONSES:raise ValueError('Choose Available, Maybe or Unavailable.')
        now=now or utcnow()
        with self.db.connect() as conn:
            row=conn.execute('SELECT * FROM team_sessions WHERE session_id=? AND guild_id=?',(sid,self.guild_id)).fetchone()
            if not row:raise ValueError('Session not found.')
            if row['status']=='Cancelled':raise ValueError('This session is cancelled.')
            if not manual and (row['status']=='Completed' or now>=row['end_at'] or now>=(row['deadline_at'] or row['start_at'])):
                raise ValueError('Responses have closed. Ask management to make a correction.')
            conn.execute('INSERT INTO session_rsvps VALUES (?,?,?,?,?,?) ON CONFLICT(session_id,user_id) DO UPDATE SET status=excluded.status,display_name=excluded.display_name,updated_by=excluded.updated_by,updated_at=excluded.updated_at',
                         (sid,str(user_id),status,str(name)[:80],str(actor),now))
            conn.execute('UPDATE team_sessions SET sync_needed=1,revision=revision+1 WHERE session_id=?',(sid,))
            self.audit(conn,sid,actor,'manual RSVP' if manual else 'RSVP',{'user_id':str(user_id),'status':status})

    @staticmethod
    def audit(conn,sid,actor,action,details):
        conn.execute('INSERT INTO session_changes(session_id,actor_id,action,details,created_at) VALUES (?,?,?,?,?)',(sid,str(actor),action,json.dumps(details),utcnow()))

    def issue_login(self,user_id):
        with self.db.connect() as conn:
            conn.execute('DELETE FROM planner_logins WHERE expires_at<=?',(utcnow(),))
            conn.execute('DELETE FROM planner_web_sessions WHERE expires_at<=?',(utcnow(),))
        token=secrets.token_urlsafe(32)
        self.db.execute('INSERT INTO planner_logins VALUES (?,?,?,?)',(hash_token(token),str(user_id),self.guild_id,(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()))
        return token

    def consume_login(self,token):
        with self.db.connect() as conn:
            row=conn.execute('SELECT * FROM planner_logins WHERE token_hash=? AND guild_id=? AND expires_at>?',(hash_token(token),self.guild_id,utcnow())).fetchone()
            if not row:raise ValueError('This sign-in link expired or was already used. Run /session dashboard again.')
            conn.execute('DELETE FROM planner_logins WHERE token_hash=?',(hash_token(token),))
            cookie=secrets.token_urlsafe(32)
            conn.execute('INSERT INTO planner_web_sessions VALUES (?,?,?,?)',(hash_token(cookie),row['user_id'],self.guild_id,(datetime.now(timezone.utc)+timedelta(hours=12)).isoformat()))
        return cookie

    def web_identity(self,cookie):
        return self.db.one('SELECT * FROM planner_web_sessions WHERE token_hash=? AND guild_id=? AND expires_at>?',(hash_token(cookie),self.guild_id,utcnow()))
