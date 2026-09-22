const sharp = require('sharp');

const WIDTH = 1024;
const HEIGHT = 1536;

// LOCKED RT FOOTBALL MEDIA NEWSPAPER TEMPLATE
// SOLE NEWSPAPER DESIGN: owner-approved 2026-09-22 RT Media front page.
// Reference composition: distressed print border; stadium RT masthead; compact date/nav strip;
// photographic club banner; EXCLUSIVE strap; oversized two-tone editorial headline;
// torn-paper article/byline at left; dominant player artwork center; photographic INSIDE TODAY
// cards at right with story #4 reserved for PLAYER QUOTE; photographic stadium footer.
// No legacy flat-card/newspaper variants are permitted. Birmingham artwork must use the
// newest official 2026/27 kit references supplied by reporterBot.js.

function clean(value, max = 2000) {
  return String(value || '').replace(/\s+/g, ' ').replace(/\.{3}|…/g, '').trim().slice(0, max);
}
function esc(value) {
  return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}
function wrap(value, maxChars, maxLines) {
  const words = clean(value).split(' ').filter(Boolean);
  const lines = []; let line = '';
  for (const word of words) {
    const next = line ? line + ' ' + word : word;
    if (!line || next.length <= maxChars) line = next;
    else {
      lines.push(line); line = word;
      if (lines.length >= maxLines) break;
    }
  }
  if (line && lines.length < maxLines) lines.push(line);
  return lines.slice(0, maxLines);
}
function textLines(lines, x, y, dy, attrs) {
  return '<text x="' + x + '" y="' + y + '" ' + attrs + '>' +
    lines.map((line, i) => '<tspan x="' + x + '" dy="' + (i ? dy : 0) + '">' + esc(line) + '</tspan>').join('') +
    '</text>';
}
function realQuote(value) {
  const v = clean(value);
  return Boolean(v) && !/^no .*comment/i.test(v) && !/not supplied/i.test(v);
}
function completeQuote(value, maxWords = 16) {
  const q = clean(value);
  if (!realQuote(q)) return 'NO PLAYER COMMENT SUPPLIED.';
  const words = q.split(/\s+/);
  if (words.length <= maxWords) return q;
  const sentences = q.match(/[^.!?]+[.!?]+/g) || [];
  const complete = sentences.find(s => s.trim().split(/\s+/).length <= maxWords);
  return complete ? complete.trim() : q;
}
function dateLabel(value) {
  const d = new Date(String(value || '') + ' 12:00:00 UTC');
  if (Number.isNaN(d.getTime())) return clean(value).toUpperCase();
  return d.toLocaleDateString('en-US', { timeZone: 'UTC', weekday: 'long', month: 'short', day: 'numeric', year: 'numeric' }).toUpperCase();
}
function theme(teamKey) {
  return teamKey === 'crownfc'
    ? { accent: '#19C5F4', deep: '#07131D', royal: '#0C527A', paper: '#EEE8DB', clubText: '#FFFFFF' }
    : { accent: '#1596ED', deep: '#061426', royal: '#0753A7', paper: '#EEE8DB', clubText: '#FFFFFF' };
}
function leagueLines(teamKey) {
  return teamKey === 'crownfc' ? ['MAJOR LEAGUE', 'PRO CLUBS'] : ['MASTERS', 'PREMIER LEAGUE', 'LEAGUE 1'];
}
function headlineSpec(value) {
  const h = clean(value || 'CLUB NEWS', 90).toUpperCase();
  const tests = [
    { chars: 17, lines: 2, size: 78, dy: 72 },
    { chars: 21, lines: 2, size: 66, dy: 62 },
    { chars: 25, lines: 3, size: 55, dy: 53 },
    { chars: 31, lines: 3, size: 46, dy: 45 },
  ];
  for (const cfg of tests) {
    const lines = wrap(h, cfg.chars, cfg.lines);
    if (lines.join(' ').length >= h.length) return { ...cfg, lines };
  }
  return { lines: wrap(h, 34, 3), size: 42, dy: 42 };
}
function sidebarStories(team, teamKey, type, story) {
  const player = clean(story.playerName || 'The player', 42);
  const position = clean(story.position || '', 28);
  const previous = clean(story.previousClub || '', 55);
  const number = clean(story.playerNumber || '', 8);
  const league = teamKey === 'crownfc' ? 'MLPC' : 'MPL League 1';
  if (type === 'signing') return [
    ['1', player.toUpperCase() + ' SIGNS', position ? position + ' joins the squad for the new campaign.' : 'The new arrival is officially confirmed.'],
    ['2', 'SQUAD STRENGTHENS', previous ? 'The new arrival joins from ' + previous + '.' : number ? 'Squad number ' + number + ' has been assigned.' : team.label + ' add another piece to the squad.'],
    ['3', 'FOCUS TURNS TO SEASON', team.label + ' continue preparations for ' + league + '.'],
    ['4', 'PLAYER QUOTE', realQuote(story.playerQuote) ? '“' + completeQuote(story.playerQuote, 16) + '” — ' + player : 'NO PLAYER COMMENT SUPPLIED.'],
  ];
  if (type === 'match') return [
    ['1', 'MATCHDAY VERDICT', 'The final result and decisive moments from the fixture.'],
    ['2', 'PERFORMANCE WATCH', 'Verified individual performances from the match.'],
    ['3', 'WHAT COMES NEXT', 'Attention turns to the next ' + league + ' challenge.'],
    ['4', 'PLAYER QUOTE', realQuote(story.playerQuote) ? '“' + completeQuote(story.playerQuote, 16) + '” — ' + player : 'NO PLAYER COMMENT SUPPLIED.'],
  ];
  return [
    ['1', 'TOP STORY', clean(story.subheadline || team.label + ' lead today’s report.', 80)],
    ['2', 'AROUND THE CLUB', team.label + ' continue work ahead of ' + league + '.'],
    ['3', 'WHAT COMES NEXT', clean(story.reporterNote || 'The squad turns attention to the next challenge.', 80)],
    ['4', 'PLAYER QUOTE', realQuote(story.playerQuote) ? '“' + completeQuote(story.playerQuote, 16) + '” — ' + player : 'NO PLAYER COMMENT SUPPLIED.'],
  ];
}
function articleCopy(team, type, story) {
  const article = clean(story.article || story.body || '', 700);
  if (article) return article;
  const player = clean(story.playerName || 'The new arrival', 50);
  const position = clean(story.position || 'player', 30);
  if (type === 'signing') return team.label + ' have confirmed the signing of ' + player + '. The ' + position + ' joins the squad as preparations continue for the new season.';
  return clean(story.subheadline || team.label + ' are back in the headlines.', 300);
}
async function safeImage(value, width, height, fit = 'cover', position = 'centre') {
  if (!Buffer.isBuffer(value) || !value.length) return null;
  try {
    return await sharp(value).rotate().resize(width, height, { fit, position }).png().toBuffer();
  } catch (error) {
    console.warn('RT Media skipped unusable newspaper image:', error.message);
    return null;
  }
}

async function renderNewspaper({ team = {}, teamKey = 'birmingham', type = 'club', story = {}, date = '', issueNumber = 1, heroBuffer = null, brandBuffer = null, mastheadBuffer = null } = {}) {
  const t = theme(teamKey);
  const headline = headlineSpec(story.headline);
  const sub = wrap(clean(story.subheadline || (team.label || 'Club') + ' exclusive', 130).toUpperCase(), 42, 2);
  const club = clean(team.label || (teamKey === 'crownfc' ? 'CrownFC' : 'Birmingham City'), 42).toUpperCase();
  const league = leagueLines(teamKey);
  const rows = sidebarStories(team, teamKey, type, story);
  const article = wrap(articleCopy(team, type, story), 29, 7);
  const reporter = clean(team.reporter || 'RT FOOTBALL MEDIA', 40).toUpperCase();
  const hero = await safeImage(heroBuffer, 456, 574, 'cover', 'attention');
  const crestTop = await safeImage(brandBuffer, 112, 112, 'contain');
  const crestFooter = await safeImage(brandBuffer, 125, 125, 'contain');
  const masthead = await safeImage(mastheadBuffer, 710, 178, 'cover');

  const composites = [];
  if (masthead) composites.push({ input: masthead, left: 26, top: 22 });
  if (crestTop) composites.push({ input: crestTop, left: 42, top: 255 });
  if (crestFooter) composites.push({ input: crestFooter, left: 55, top: 1360 });
  if (hero) composites.push({ input: hero, left: 276, top: 718 });

  const sidebar = rows.map((row, i) => {
    const y = 544 + i * 177;
    const body = wrap(row[2], 25, i === 3 ? 2 : 3);
    return '<rect x="758" y="' + y + '" width="34" height="34" fill="' + t.accent + '"/>' +
      '<text x="775" y="' + (y + 26) + '" text-anchor="middle" font-family="DejaVu Sans" font-size="22" font-weight="900" fill="#fff">' + row[0] + '</text>' +
      '<text x="802" y="' + (y + 25) + '" font-family="DejaVu Sans" font-size="19" font-weight="900" fill="#fff">' + esc(row[1]) + '</text>' +
      textLines(body, 758, y + 65, 23, 'font-family="DejaVu Serif" font-size="16" font-weight="500" fill="#F1F1F1"') +
      (i < 3 ? '<line x1="758" y1="' + (y + 151) + '" x2="982" y2="' + (y + 151) + '" stroke="' + t.accent + '" stroke-width="4"/>' : '');
  }).join('');

  const footerMain = teamKey === 'crownfc' ? 'MORE THAN A CLUB.' : 'A BIGGER STAGE.';
  const footerAccent = teamKey === 'crownfc' ? 'BUILT FOR THE CROWN.' : 'SAME AMBITION.';
  const svg = '<svg width="' + WIDTH + '" height="' + HEIGHT + '" xmlns="http://www.w3.org/2000/svg">' +
    '<defs>' +
      '<filter id="grain"><feTurbulence baseFrequency=".7" numOctaves="3" seed="12"/><feColorMatrix values=".8 0 0 0 .2 0 .8 0 0 .2 0 0 .8 0 .2 0 0 0 .09 0"/></filter>' +
      '<linearGradient id="club" x1="0" y1="0" x2="1" y2="0"><stop stop-color="' + t.royal + '"/><stop offset=".72" stop-color="' + t.royal + '"/><stop offset="1" stop-color="' + t.deep + '"/></linearGradient>' +
    '</defs>' +
    '<rect width="1024" height="1536" fill="' + t.paper + '"/>' +
    '<rect x="12" y="12" width="1000" height="1512" fill="none" stroke="#171717" stroke-width="3"/>' +
    '<rect x="24" y="20" width="976" height="185" fill="' + t.deep + '"/>' +
    '<rect x="24" y="20" width="976" height="185" filter="url(#grain)" opacity=".55"/>' +
    (masthead ? '' : '<text x="52" y="124" font-family="DejaVu Sans" font-size="72" font-weight="900" font-style="italic" fill="#fff">RT MEDIA</text><text x="57" y="166" font-family="DejaVu Sans" font-size="16" font-weight="800" letter-spacing="6" fill="#fff">PRO CLUBS NEWS NETWORK</text>') +
    '<text x="812" y="72" font-family="DejaVu Sans" font-size="18" font-weight="900" fill="#fff">REAL CLUBS.</text>' +
    '<text x="812" y="100" font-family="DejaVu Sans" font-size="18" font-weight="900" fill="#fff">REAL STORIES.</text>' +
    '<text x="812" y="128" font-family="DejaVu Sans" font-size="18" font-weight="900" fill="#fff">ALL FOOTBALL</text>' +
    '<text x="812" y="156" font-family="DejaVu Sans" font-size="18" font-weight="900" fill="#fff">THAT MATTERS.</text>' +
    '<rect x="24" y="207" width="976" height="34" fill="#F8F4EA" stroke="#111" stroke-width="1"/>' +
    '<text x="38" y="230" font-family="DejaVu Sans" font-size="13" font-weight="900" fill="#111">' + esc(dateLabel(date)) + '</text>' +
    '<text x="512" y="230" text-anchor="middle" font-family="DejaVu Sans" font-size="12" font-weight="800" fill="#111">CLUB NEWS  |  MATCHDAY  |  TRANSFERS  |  COMMUNITY</text>' +
    '<text x="982" y="230" text-anchor="end" font-family="DejaVu Sans" font-size="13" font-weight="900" fill="#111">ISSUE #' + esc(String(issueNumber || 1)) + '</text>' +
    '<rect x="24" y="247" width="976" height="160" fill="url(#club)"/>' +
    '<text x="174" y="321" font-family="DejaVu Serif" font-size="' + (club.length > 18 ? 50 : 60) + '" font-weight="900" fill="' + t.clubText + '">' + esc(club) + '</text>' +
    '<text x="178" y="367" font-family="DejaVu Serif" font-size="25" font-weight="700" letter-spacing="8" fill="#fff">FOOTBALL CLUB</text>' +
    textLines(league, 755, 292, 27, 'font-family="DejaVu Sans" font-size="17" font-weight="900" fill="#fff"') +
    '<rect x="24" y="419" width="708" height="36" fill="' + t.royal + '"/>' +
    '<text x="52" y="444" font-family="DejaVu Sans" font-size="17" font-weight="900" letter-spacing="6" fill="#fff">EXCLUSIVE</text>' +
    '<rect x="744" y="419" width="256" height="873" fill="#06090D"/>' +
    '<text x="758" y="466" font-family="DejaVu Sans" font-size="31" font-weight="900" fill="#fff">INSIDE TODAY</text>' +
    '<line x1="758" y1="480" x2="982" y2="480" stroke="' + t.accent + '" stroke-width="5"/>' +
    '<text x="758" y="509" font-family="DejaVu Sans" font-size="13" font-weight="800" letter-spacing="1" fill="#E9E9E9">TOP STORIES AROUND ' + esc(club) + '</text>' +
    sidebar +
    textLines(headline.lines, 34, 526, headline.dy, 'font-family="DejaVu Serif" font-size="' + headline.size + '" font-weight="900" fill="#080808"') +
    textLines(sub, 36, 666, 31, 'font-family="DejaVu Sans" font-size="27" font-weight="900" fill="' + t.royal + '"') +
    '<line x1="36" y1="702" x2="730" y2="702" stroke="#111" stroke-width="2"/>' +
    '<rect x="34" y="718" width="228" height="574" fill="#F4EFE5"/>' +
    textLines(article, 40, 752, 25, 'font-family="DejaVu Serif" font-size="17" font-weight="500" fill="#171717"') +
    '<line x1="40" y1="955" x2="92" y2="955" stroke="' + t.royal + '" stroke-width="3"/>' +
    '<text x="40" y="985" font-family="DejaVu Sans" font-size="15" font-weight="900" fill="#111">BY ' + esc(reporter) + '</text>' +
    '<text x="40" y="1008" font-family="DejaVu Sans" font-size="12" font-weight="800" fill="#333">RT FOOTBALL MEDIA</text>' +
    (hero ? '' : '<rect x="276" y="718" width="456" height="574" fill="#142A42"/><text x="504" y="1000" text-anchor="middle" font-family="DejaVu Sans" font-size="24" font-weight="900" fill="#fff">RT FOOTBALL MEDIA</text>') +
    '<rect x="24" y="1310" width="976" height="194" fill="#03080D"/>' +
    '<line x1="24" y1="1310" x2="1000" y2="1310" stroke="' + t.accent + '" stroke-width="5"/>' +
    '<text x="220" y="1388" font-family="DejaVu Serif" font-size="48" font-weight="900" fill="#fff">' + esc(footerMain) + '</text>' +
    '<text x="220" y="1450" font-family="DejaVu Sans" font-size="52" font-weight="900" font-style="italic" fill="' + t.accent + '">' + esc(footerAccent) + '</text>' +
    '<text x="220" y="1482" font-family="DejaVu Sans" font-size="13" font-weight="800" letter-spacing="2" fill="#fff">' + esc(club) + '  |  ' + esc(teamKey === 'crownfc' ? 'MLPC' : 'MASTERS PREMIER LEAGUE') + '  |  2026/27</text>' +
    '</svg>';

  const base = sharp(Buffer.from(svg));
  if (composites.length) base.composite(composites);
  return base.png({ compressionLevel: 9 }).toBuffer();
}

module.exports = { renderNewspaper };
