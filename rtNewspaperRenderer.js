'use strict';

const sharp = require('sharp');
const WIDTH = 1024;
const HEIGHT = 1536;
const RT_NEWSPAPER_RENDERER_VERSION = 'reference-locked-v1-20260922';

const THEMES = {
  birmingham: { blue:'#0752B8', cyan:'#149CFF', navy:'#03142B', ink:'#080B10', paper:'#F1EEE7', footer1:'A NEW ERA', footer2:'TAKING SHAPE.', footer3:'BIGGER STAGE. SAME AMBITION.' },
  crownfc: { blue:'#00BCEB', cyan:'#28D8FF', navy:'#02090F', ink:'#05080C', paper:'#EEEAE1', footer1:'BUILT DIFFERENT.', footer2:'', footer3:'MORE THAN A CLUB.' }
};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
const clean=(s,n=500)=>String(s??'').replace(/\s+/g,' ').trim().slice(0,n);
function wrap(s,max,limit=99){const w=clean(s,1200).split(' '),o=[];let l='';for(const x of w){const n=l?l+' '+x:x;if(n.length>max&&l){o.push(l);l=x;if(o.length>=limit)break}else l=n}if(l&&o.length<limit)o.push(l);return o;}
function lines(a,x,y,dy,attrs){return a.map((v,i)=>'<text x="'+x+'" y="'+(y+i*dy)+'" '+attrs+'>'+esc(v)+'</text>').join('');}
function headline(s){let size=68,max=22;if(clean(s).length>50){size=54;max=28}if(clean(s).length>78){size=46;max=34}return {a:wrap(s||'CLUB NEWS',max,2),size};}
function storyRows(story){const raw=Array.isArray(story.keyStories)?story.keyStories:[];const out=[];for(let i=0;i<3;i++){const r=raw[i]||{};out.push({title:clean(r.title||('KEY STORY '+(i+1)),34),body:clean(r.summary||r.body||story.summary||story.subheadline||'',180)});}out.push({title:'PLAYER QUOTE',body:clean(story.playerQuote||story.quote||'No player comment provided.',130)});return out;}
async function image(buf,w,h,position='attention'){if(!buf)return null;try{return await sharp(buf).rotate().resize(w,h,{fit:'cover',position}).png().toBuffer()}catch{return null}}
async function renderNewspaper({team={},teamKey='birmingham',story={},date='',issueNumber=1,heroBuffer=null,brandBuffer=null,mastheadBuffer=null}={}){
  const key=teamKey==='crownfc'?'crownfc':'birmingham',t=THEMES[key];
  const club=key==='crownfc'?'CROWNFC':'BIRMINGHAM CITY';
  const league=key==='crownfc'?'MAJOR LEAGUE PRO CLUBS':'MASTERS PREMIER LEAGUE\nLEAGUE 1';
  const h=headline(story.headline||story.title);
  const sub=wrap(story.subheadline||story.summary||'RT FOOTBALL MEDIA EXCLUSIVE',52,2);
  const source=clean(story.sourceLine||story.source||('RT FOOTBALL MEDIA • '+(team.reporter||'CLUB DESK')),75);
  const rows=storyRows(story);
  const hero=await image(heroBuffer,690,590);
  const crest=await image(brandBuffer,150,150,'centre');
  const mast=await image(mastheadBuffer,976,245,'centre');
  const rowSvg=rows.map((r,i)=>{const y=600+i*185;return '<text x="765" y="'+y+'" font-family="DejaVu Sans" font-size="25" font-weight="900" fill="#fff">'+esc(r.title)+'</text>'+lines(wrap(r.body,26,i===3?2:4),765,y+34,25,'font-family="DejaVu Sans" font-size="17" font-weight="600" fill="#F4F4F4"')+'<line x1="765" y1="'+(y+145)+'" x2="982" y2="'+(y+145)+'" stroke="'+t.cyan+'" stroke-width="4"/>';}).join('');
  const leagueSvg=lines(league.split('\n'),790,330,28,'font-family="DejaVu Sans" font-size="18" font-weight="900" fill="#fff"');
  const svg='<svg width="1024" height="1536" xmlns="http://www.w3.org/2000/svg"><defs><filter id="grain"><feTurbulence baseFrequency=".75" numOctaves="4" seed="7"/><feColorMatrix values=".8 0 0 0 .2 0 .8 0 0 .2 0 0 .8 0 .2 0 0 0 .10 0"/></filter></defs><rect width="1024" height="1536" fill="'+t.paper+'"/><rect x="12" y="12" width="1000" height="1512" fill="none" stroke="#111" stroke-width="4"/><rect x="24" y="20" width="976" height="245" fill="'+t.navy+'"/><rect x="24" y="20" width="976" height="245" filter="url(#grain)" opacity=".7"/>'+(mast?'':'<text x="58" y="145" font-family="DejaVu Sans" font-size="88" font-weight="900" font-style="italic" fill="#fff">RT MEDIA</text><text x="315" y="205" font-family="DejaVu Sans" font-size="17" letter-spacing="8" fill="#fff">PRO CLUBS NEWS NETWORK</text>')+'<text x="815" y="82" font-family="DejaVu Sans" font-size="18" font-weight="900" fill="'+t.cyan+'">REAL CLUBS.</text><text x="815" y="111" font-family="DejaVu Sans" font-size="18" font-weight="900" fill="#fff">REAL STORIES.</text><text x="815" y="140" font-family="DejaVu Sans" font-size="18" font-weight="900" fill="#fff">ALL FOOTBALL</text><text x="815" y="169" font-family="DejaVu Sans" font-size="18" font-weight="900" fill="#fff">THAT MATTERS.</text><rect x="24" y="267" width="976" height="31" fill="#F5F2EB"/><text x="38" y="289" font-family="DejaVu Sans" font-size="13" font-weight="900">'+esc(date)+'</text><text x="512" y="289" text-anchor="middle" font-family="DejaVu Sans" font-size="12" font-weight="900">TRANSFER NEWS  |  MATCHDAY  |  CLUB UPDATES  |  COMMUNITY</text><text x="985" y="289" text-anchor="end" font-family="DejaVu Sans" font-size="13" font-weight="900">ISSUE #'+esc(issueNumber)+'</text><rect x="24" y="300" width="976" height="125" fill="'+(key==='crownfc'?t.ink:t.blue)+'"/>'+(crest?'':'')+'<text x="'+(key==='crownfc'?190:185)+'" y="372" font-family="DejaVu Sans" font-size="'+(key==='crownfc'?66:56)+'" font-weight="900" font-style="'+(key==='crownfc'?'italic':'normal')+'" fill="'+(key==='crownfc'?t.cyan:'#fff')+'">'+esc(club)+'</text>'+leagueSvg+'<rect x="24" y="427" width="720" height="42" fill="'+(key==='crownfc'?t.ink:t.blue)+'"/><text x="385" y="457" text-anchor="middle" font-family="DejaVu Serif" font-size="22" font-weight="900" letter-spacing="8" fill="#fff">EXCLUSIVE</text><rect x="752" y="427" width="248" height="808" fill="'+t.ink+'"/><rect x="752" y="427" width="248" height="55" fill="'+t.blue+'"/><text x="876" y="464" text-anchor="middle" font-family="DejaVu Sans" font-size="27" font-weight="900" fill="#fff">INSIDE TODAY</text>'+lines(h.a,42,535,70,'font-family="DejaVu Sans" font-size="'+h.size+'" font-weight="900" fill="#080808"')+lines(sub,44,665,34,'font-family="DejaVu Sans" font-size="27" font-weight="900" fill="'+t.blue+'"')+'<text x="385" y="731" text-anchor="middle" font-family="DejaVu Sans" font-size="15" font-weight="900" fill="#111">SOURCE: '+esc(source)+'</text><rect x="34" y="748" width="700" height="487" fill="'+t.navy+'" stroke="#111" stroke-width="4"/>'+rowSvg+'<rect x="24" y="1248" width="976" height="256" fill="'+t.ink+'"/><line x1="24" y1="1248" x2="1000" y2="1248" stroke="'+t.cyan+'" stroke-width="4"/><text x="650" y="1342" text-anchor="middle" font-family="DejaVu Sans" font-size="58" font-weight="900" fill="#fff">'+esc(t.footer1)+'</text>'+(t.footer2?'<text x="650" y="1410" text-anchor="middle" font-family="DejaVu Sans" font-size="62" font-weight="900" font-style="italic" fill="'+t.cyan+'">'+esc(t.footer2)+'</text>':'')+'<text x="650" y="1470" text-anchor="middle" font-family="DejaVu Serif" font-size="25" font-weight="900" letter-spacing="3" fill="#fff">'+esc(t.footer3)+'</text></svg>';
  const comp=[{input:Buffer.from(svg),left:0,top:0}];
  if(mast)comp.unshift({input:mast,left:24,top:20});
  if(hero)comp.splice(mast?1:0,0,{input:hero,left:34,top:748});
  if(crest){comp.push({input:crest,left:38,top:286});comp.push({input:crest,left:50,top:1300});}
  return sharp({create:{width:WIDTH,height:HEIGHT,channels:4,background:t.paper}}).composite(comp).png().toBuffer();
}
module.exports={renderNewspaper,RT_NEWSPAPER_RENDERER_VERSION};
