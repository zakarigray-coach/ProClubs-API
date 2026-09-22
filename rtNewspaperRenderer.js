const sharp = require('sharp');

const WIDTH = 1024;
const HEIGHT = 1536;

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
    const next = line ? `${line} ${word}` : word;
    if (!line || next.length <= maxChars) line = next;
    else { lines.push(line); line = word; if (lines.length >= maxLines) break; }
  }
  if (line && lines.length < maxLines) lines.push(line);
  return lines.slice(0, maxLines);
}
function textLines(lines, x, y, dy, attrs) {
  return `<text x="${x}" y="${y}" ${attrs}>${lines.map((line, i) => `<tspan x="${x}" dy="${i ? dy : 0}">${esc(line)}</tspan>`).join('')}</text>`;
}
function realQuote(value) {
  const v = clean(value);
  return Boolean(v) && !/^no .*comment/i.test(v) && !/not supplied/i.test(v);
}
function quoteExcerpt(value, maxWords = 13) {
  const q = clean(value);
  if (!realQuote(q)) return 'NO PLAYER COMMENT SUPPLIED.';
  const words = q.split(/\s+/);
  if (words.length <= maxWords) return q;
  const sentences = q.match(/[^.!?]+[.!?]+/g) || [];
  let out = '';
  for (const s of sentences) {
    const test = `${out} ${s.trim()}`.trim();
    if (test.split(/\s+/).length > maxWords) break;
    out = test;
  }
  return out || words.slice(0, maxWords).join(' ');
}
function dateLabel(value) {
  const d = new Date(`${value || ''} 12:00:00 UTC`);
  if (Number.isNaN(d.getTime())) return clean(value).toUpperCase();
  return d.toLocaleDateString('en-US', { timeZone: 'UTC', weekday: 'long', month: 'short', day: 'numeric', year: 'numeric' }).toUpperCase();
}
function leagueLabel(team, teamKey) {
  if (teamKey === 'crownfc') return 'MAJOR LEAGUE PRO CLUBS';
  return 'MASTERS PREMIER LEAGUE\nLEAGUE 1';
}
function theme(teamKey) {
  return teamKey === 'crownfc'
    ? { accent: '#17C5F3', accent2: '#0D7DA8', dark: '#03070C', ink: '#F7F7F2', paper: '#E8E2D6', clubText: '#17C5F3', footer: 'BUILT DIFFERENT.', footer2: 'MORE THAN A CLUB.' }
    : { accent: '#188DE8', accent2: '#0D4DA2', dark: '#040911', ink: '#F8F6F1', paper: '#E8E2D6', clubText: '#FFFFFF', footer: 'A NEW ERA', footer2: 'TAKING SHAPE.' };
}
function uniqueSidebar(team, teamKey, type, story) {
  const player = clean(story.playerName || 'The player', 50);
  const position = clean(story.position || '', 30);
  const number = clean(story.playerNumber || '', 10);
  const previous = clean(story.previousClub || '', 70);
  const league = teamKey === 'crownfc' ? 'MLPC' : 'MPL League 1';
  const quote = `“${quoteExcerpt(story.playerQuote, 12)}”${realQuote(story.playerQuote) ? ` — ${player}` : ''}`;

  if (type === 'signing') {
    return [
      ['KEY STORY 1', position ? `${player} joins the squad as a ${position}.` : `${player} joins the squad.`],
      ['KEY STORY 2', previous ? `The new arrival comes from ${previous}.` : number ? `Squad number ${number} has been assigned.` : 'The signing is officially confirmed.'],
      ['KEY STORY 3', `${team.label} continue preparations for ${league}.`],
      ['PLAYER QUOTE', quote],
    ];
  }
  if (type === 'match') {
    return [
      ['KEY STORY 1', 'Final result and decisive match moments.'],
      ['KEY STORY 2', 'Individual performances and verified player stats.'],
      ['KEY STORY 3', `What the result means for ${team.label}.`],
      ['PLAYER QUOTE', quote],
    ];
  }
  return [
    ['KEY STORY 1', clean(story.subheadline || `${team.label} lead today’s club report.`, 95)],
    ['KEY STORY 2', `A separate club angle from the ${league} campaign.`],
    ['KEY STORY 3', clean(story.reporterNote || 'What comes next for the squad and club.', 95)],
    ['PLAYER QUOTE', quote],
  ];
}
function headlineLines(value) {
  const h = clean(value || 'CLUB NEWS', 90).toUpperCase();
  for (const cfg of [{ c: 18, l: 2, s: 76, d: 70 }, { c: 23, l: 3, s: 62, d: 58 }, { c: 30, l: 3, s: 50, d: 48 }]) {
    const lines = wrap(h, cfg.c, cfg.l);
    if (lines.join(' ').length >= h.length) return { lines, size: cfg.s, dy: cfg.d };
  }
  return { lines: wrap(h, 32, 3), size: 46, dy: 45 };
}

async function renderNewspaper({ team = {}, teamKey = 'birmingham', type = 'club', story = {}, date = '', issueNumber = 27, heroBuffer = null, brandBuffer = null, mastheadBuffer = null } = {}) {
  const t = theme(teamKey);
  const headline = headlineLines(story.headline);
  const sub = wrap(clean(story.subheadline || `${team.label || 'Club'} exclusive`, 140).toUpperCase(), 42, 2);
  const source = clean(story.source || story.reporterNote || `${team.reporter || 'RT Football Media'} reporting`, 90).toUpperCase();
  const rows = uniqueSidebar(team, teamKey, type, story);
  const club = clean(team.label || (teamKey === 'crownfc' ? 'CrownFC' : 'Birmingham City'), 50).toUpperCase();
  const league = leagueLabel(team, teamKey).split('\n');
  const footerTop = teamKey === 'crownfc' ? 'BUILT DIFFERENT.' : 'A NEW ERA';
  const footerBottom = teamKey === 'crownfc' ? 'MORE THAN A CLUB.' : 'TAKING SHAPE.';

  const composites = [];
  if (heroBuffer) {
    composites.push({ input: await sharp(heroBuffer).rotate().resize(676, 485, { fit: 'cover', position: 'attention' }).png().toBuffer(), left: 42, top: 755 });
  }
  if (brandBuffer) {
    composites.push({ input: await sharp(brandBuffer).rotate().resize(120, 120, { fit: 'contain' }).png().toBuffer(), left: 46, top: 340 });
    composites.push({ input: await sharp(brandBuffer).rotate().resize(150, 150, { fit: 'contain' }).png().toBuffer(), left: 46, top: 1295 });
  }
  if (mastheadBuffer) {
    composites.push({ input: await sharp(mastheadBuffer).rotate().resize(610, 170, { fit: 'contain' }).png().toBuffer(), left: 45, top: 28 });
  }

  const rowMarkup = rows.map((row, i) => {
    const y = 515 + i * 180;
    const bodyLines = wrap(row[1], 25, i === 3 ? 2 : 4);
    return `<text x="748" y="${y}" font-family="DejaVu Sans" font-size="26" font-weight="900" fill="#FFFFFF">${esc(row[0])}</text>
      ${textLines(bodyLines, 748, y + 38, 25, `font-family="DejaVu Sans" font-size="17" font-weight="500" fill="#E8EEF4"`)}
      ${i < 3 ? `<line x1="748" y1="${y + 142}" x2="972" y2="${y + 142}" stroke="${t.accent}" stroke-width="4"/>` : ''}`;
  }).join('');

  const clubTextX = brandBuffer ? 182 : 44;
  const svg = `<svg width="1024" height="1536" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <filter id="grain"><feTurbulence baseFrequency=".55" numOctaves="4" seed="7"/><feColorMatrix values=".8 0 0 0 .3 0 .8 0 0 .3 0 0 .8 0 .3 0 0 0 .12 0"/></filter>
      <linearGradient id="head" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#020814"/><stop offset=".55" stop-color="#061A31"/><stop offset="1" stop-color="#000"/></linearGradient>
      <linearGradient id="clubbar" x1="0" y1="0" x2="1" y2="0"><stop stop-color="${teamKey === 'crownfc' ? '#051018' : '#0B3E8C'}"/><stop offset=".65" stop-color="${teamKey === 'crownfc' ? '#031018' : '#1769C6'}"/><stop offset="1" stop-color="#05070B"/></linearGradient>
    </defs>
    <rect width="1024" height="1536" fill="${t.paper}"/>
    <rect x="14" y="14" width="996" height="1508" rx="4" fill="#EAE4D8" stroke="#141414" stroke-width="3"/>
    <rect x="28" y="26" width="968" height="235" fill="url(#head)"/>
    <rect x="28" y="26" width="968" height="235" filter="url(#grain)" opacity=".5"/>
    ${mastheadBuffer ? '' : `<text x="58" y="128" font-family="DejaVu Sans" font-size="72" font-weight="900" font-style="italic" fill="#FFFFFF">RT MEDIA</text>
      <text x="62" y="177" font-family="DejaVu Sans" font-size="20" font-weight="700" letter-spacing="7" fill="#DDE7F0">PRO CLUBS NEWS NETWORK</text>`}
    <text x="760" y="83" font-family="DejaVu Sans" font-size="20" font-weight="900" fill="${t.accent}">REAL CLUBS.</text>
    <text x="760" y="113" font-family="DejaVu Sans" font-size="20" font-weight="900" fill="${t.accent}">REAL STORIES.</text>
    <text x="760" y="143" font-family="DejaVu Sans" font-size="20" font-weight="900" fill="${t.accent}">ALL FOOTBALL</text>
    <text x="760" y="173" font-family="DejaVu Sans" font-size="20" font-weight="900" fill="${t.accent}">THAT MATTERS.</text>
    <rect x="28" y="263" width="968" height="42" fill="#F7F3EA" stroke="#111" stroke-width="2"/>
    <text x="42" y="291" font-family="DejaVu Sans" font-size="15" font-weight="900" fill="#111">${esc(dateLabel(date))}</text>
    <text x="395" y="291" text-anchor="middle" font-family="DejaVu Sans" font-size="13" font-weight="800" fill="#111">TRANSFER NEWS  |  MATCHDAY  |  CLUB UPDATES  |  COMMUNITY</text>
    <text x="976" y="291" text-anchor="end" font-family="DejaVu Sans" font-size="15" font-weight="900" fill="#111">ISSUE #${esc(String(issueNumber || 27).replace(/^0+/, ''))}</text>
    <rect x="28" y="308" width="968" height="140" fill="url(#clubbar)"/>
    <text x="${clubTextX}" y="376" font-family="DejaVu Sans" font-size="58" font-weight="900" ${teamKey === 'crownfc' ? 'font-style="italic"' : ''} fill="${t.clubText}">${esc(club)}</text>
    ${textLines(league, 786, 348, 26, `font-family="DejaVu Sans" font-size="17" font-weight="800" fill="#FFFFFF"`)}
    <rect x="28" y="449" width="690" height="50" fill="${teamKey === 'crownfc' ? '#071119' : '#0E5CB7'}" stroke="#F2F2F2" stroke-width="2"/>
    <text x="373" y="482" text-anchor="middle" font-family="DejaVu Sans" font-size="21" font-weight="900" letter-spacing="7" fill="#FFFFFF">EXCLUSIVE</text>
    <rect x="728" y="449" width="268" height="769" fill="#05080C" stroke="#F4F4F4" stroke-width="2"/>
    <text x="748" y="491" font-family="DejaVu Sans" font-size="28" font-weight="900" fill="#FFFFFF">INSIDE TODAY</text>
    <line x1="748" y1="502" x2="972" y2="502" stroke="${t.accent}" stroke-width="4"/>
    ${rowMarkup}
    ${textLines(headline.lines, 42, 562, headline.dy, `font-family="DejaVu Sans" font-size="${headline.size}" font-weight="900" fill="#0A0A0A"`)}
    ${textLines(sub, 42, 690, 38, `font-family="DejaVu Sans" font-size="34" font-weight="900" fill="${t.accent2}"`)}
    <line x1="42" y1="730" x2="718" y2="730" stroke="#111" stroke-width="3"/>
    <text x="380" y="750" text-anchor="middle" font-family="DejaVu Sans" font-size="16" font-weight="900" fill="#222">SOURCE: ${esc(source)}</text>
    ${heroBuffer ? '' : `<rect x="42" y="755" width="676" height="485" fill="#13243A"/><text x="380" y="1000" text-anchor="middle" font-family="DejaVu Sans" font-size="28" font-weight="800" fill="#DDE7F0">RT FOOTBALL MEDIA</text>`}
    <rect x="28" y="1255" width="968" height="245" fill="#03070B"/>
    <line x1="28" y1="1255" x2="996" y2="1255" stroke="${t.accent}" stroke-width="4"/>
    <text x="245" y="1340" font-family="DejaVu Sans" font-size="55" font-weight="900" fill="#FFFFFF">${esc(footerTop)}</text>
    <text x="245" y="1407" font-family="DejaVu Sans" font-size="66" font-weight="900" font-style="italic" fill="${t.accent}">${esc(footerBottom)}</text>
    <text x="625" y="1455" text-anchor="middle" font-family="DejaVu Sans" font-size="19" font-weight="800" letter-spacing="3" fill="#FFFFFF">${teamKey === 'crownfc' ? 'MORE THAN A CLUB.' : 'BIGGER STAGE. SAME AMBITION.'}</text>
  </svg>`;

  return sharp({ input: Buffer.from(svg) }).composite(composites).png().toBuffer();
}

module.exports = { renderNewspaper };
