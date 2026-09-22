const sharp = require('sharp');

const WIDTH = 1024;
const HEIGHT = 1536;
const LAYOUTS = ['locked-cover'];

function clean(value, max = 2000) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, max);
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
function selectSpotlightLayout() { return 'locked-cover'; }
function theme(teamKey) {
  return teamKey === 'crownfc'
    ? { bg: '#02070B', accent: '#18D0F5', accent2: '#0D7FA8', ink: '#FFFFFF', panel: '#061019', border: '#D9D7D1' }
    : { bg: '#06101D', accent: '#0798ED', accent2: '#0E5EB6', ink: '#FFFFFF', panel: '#0A1525', border: '#E6E3DC' };
}
function quote(value) {
  const q = clean(value, 220);
  return q ? `“${q}”` : '“NO PLAYER COMMENT SUPPLIED.”';
}
function featureTitle(story, player) {
  return clean(story.spotlightHeadline || story.nickname || story.headline || player, 44).toUpperCase();
}

async function renderSpotlight({ team = {}, teamKey = 'birmingham', story = {}, heroBuffer = null, brandBuffer = null } = {}) {
  const t = theme(teamKey);
  const player = clean(story.playerName || 'PLAYER', 40).toUpperCase();
  const position = clean(story.position || 'PLAYER', 24).toUpperCase();
  const number = clean(story.playerNumber || '', 8);
  const club = clean(team.label || (teamKey === 'crownfc' ? 'CrownFC' : 'Birmingham City'), 48).toUpperCase();
  const league = teamKey === 'crownfc' ? 'MAJOR LEAGUE PRO CLUBS' : 'MASTERS PREMIER LEAGUE';
  const title = featureTitle(story, player);
  const bigName = number ? `${player} #${number}` : player;
  const q = quote(story.playerQuote);
  const qLines = wrap(q, 24, 4);
  const excerpts = (Array.isArray(story.interviewExcerpts) ? story.interviewExcerpts : []).filter(Boolean).slice(0, 3);
  const interview = excerpts.length ? excerpts : [
    clean(story.article || story.body || 'The player discusses the club and the season ahead.', 180),
    clean(story.reporterNote || 'Leadership, standards and the next challenge.', 180),
    clean(story.subheadline || 'A closer look inside the squad.', 180),
  ];
  const composites = [];
  if (heroBuffer) {
    const main = await sharp(heroBuffer).rotate().resize(600, 1000, { fit: 'cover', position: 'attention' }).png().toBuffer();
    composites.push({ input: main, left: 212, top: 210 });
    const ghost = await sharp(heroBuffer).rotate().resize(380, 610, { fit: 'cover', position: 'attention' }).grayscale().modulate({ brightness: 0.62 }).png().toBuffer();
    composites.push({ input: ghost, left: 630, top: 175, blend: 'screen', opacity: 0.32 });
    const strip1 = await sharp(heroBuffer).rotate().resize(260, 245, { fit: 'cover', position: 'north' }).png().toBuffer();
    const strip2 = await sharp(heroBuffer).rotate().resize(260, 245, { fit: 'cover', position: 'attention' }).grayscale().png().toBuffer();
    const strip3 = await sharp(heroBuffer).rotate().resize(260, 245, { fit: 'cover', position: 'south' }).png().toBuffer();
    composites.push({ input: strip1, left: 55, top: 1205 });
    composites.push({ input: strip2, left: 323, top: 1205 });
    composites.push({ input: strip3, left: 591, top: 1205 });
  }
  if (brandBuffer) {
    composites.push({ input: await sharp(brandBuffer).rotate().resize(185, 185, { fit: 'contain' }).png().toBuffer(), left: 45, top: 185 });
  }

  const infoPanel = [
    ['POSITION', position],
    ['SQUAD NUMBER', number || '—'],
    ['CLUB', club],
    ['LEAGUE', teamKey === 'crownfc' ? 'MLPC' : 'MPL\nLEAGUE 1'],
  ];
  const infoMarkup = infoPanel.map((row, i) => {
    const y = 585 + i * 110;
    const valueLines = String(row[1]).split('\n');
    return `<text x="52" y="${y}" font-family="DejaVu Sans" font-size="15" font-weight="700" letter-spacing="2" fill="${t.accent}">${esc(row[0])}</text>
      ${textLines(valueLines, 52, y + 34, 28, `font-family="DejaVu Sans" font-size="26" font-weight="900" fill="#FFFFFF"`)}`;
  }).join('');

  const sectionNames = teamKey === 'crownfc' ? ['ON JOINING CROWNFC', 'ON LEADERSHIP', 'ON THE SEASON AHEAD'] : ['ON JOINING BIRMINGHAM', 'ON LEADERSHIP', 'ON THE SEASON AHEAD'];
  const interviewMarkup = interview.map((v, i) => {
    const y = 790 + i * 132;
    return `<text x="805" y="${y}" font-family="DejaVu Sans" font-size="16" font-weight="900" fill="${t.accent}">${esc(sectionNames[i])}</text>
      ${textLines(wrap(v, 21, 4), 805, y + 29, 23, `font-family="DejaVu Sans" font-size="15" font-weight="500" fill="#FFFFFF"`)}
      ${i < 2 ? `<line x1="805" y1="${y + 105}" x2="976" y2="${y + 105}" stroke="${t.accent}" stroke-width="3"/>` : ''}`;
  }).join('');

  const svg = `<svg width="1024" height="1536" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <filter id="grain"><feTurbulence baseFrequency=".55" numOctaves="4" seed="12"/><feColorMatrix values=".8 0 0 0 .2 0 .8 0 0 .2 0 0 .8 0 .2 0 0 0 .16 0"/></filter>
      <linearGradient id="fade" x1="0" y1="0" x2="0" y2="1"><stop stop-color="${t.bg}" stop-opacity="0"/><stop offset=".75" stop-color="${t.bg}" stop-opacity=".55"/><stop offset="1" stop-color="${t.bg}"/></linearGradient>
    </defs>
    <rect width="1024" height="1536" fill="${t.bg}"/>
    <rect width="1024" height="1536" filter="url(#grain)" opacity=".45"/>
    <rect x="22" y="22" width="980" height="1492" fill="none" stroke="${t.border}" stroke-width="3"/>
    <rect x="35" y="35" width="954" height="120" fill="#F7F5F0"/>
    <text x="60" y="105" font-family="DejaVu Sans" font-size="52" font-weight="900" fill="#05080C">RT</text>
    <text x="158" y="99" font-family="DejaVu Sans" font-size="39" font-weight="900" fill="#05080C">FOOTBALL</text>
    <text x="385" y="99" font-family="DejaVu Sans" font-size="39" font-weight="900" fill="${t.accent2}">MEDIA</text>
    <text x="162" y="132" font-family="DejaVu Sans" font-size="17" font-weight="700" letter-spacing="8" fill="#111">PLAYER SPOTLIGHT</text>
    <text x="960" y="77" text-anchor="end" font-family="DejaVu Sans" font-size="25" font-weight="900" letter-spacing="4" fill="#111">${esc(club)}</text>
    <text x="960" y="109" text-anchor="end" font-family="DejaVu Sans" font-size="15" font-weight="700" letter-spacing="3" fill="#111">${esc(league)}</text>
    <text x="960" y="135" text-anchor="end" font-family="DejaVu Sans" font-size="14" font-weight="700" letter-spacing="3" fill="#111">SEASON 2026/2027</text>
    <text x="52" y="480" font-family="DejaVu Sans" font-size="24" font-weight="900" fill="#FFFFFF">${teamKey === 'crownfc' ? 'LEADERSHIP\nDISCIPLINE\nEXPERIENCE\nIMPACT' : 'SAME\nCULTURE\nBIGGER\nSTAGES'}</text>
    ${infoMarkup}
    <text x="815" y="450" font-family="DejaVu Sans" font-size="85" font-weight="900" fill="${t.accent}">“</text>
    ${textLines(qLines, 790, 520, 42, `font-family="DejaVu Sans" font-size="30" font-weight="900" fill="#FFFFFF"`)}
    <text x="790" y="690" font-family="DejaVu Sans" font-size="44" font-weight="900" font-style="italic" fill="${t.accent}">${esc(bigName)}</text>
    <rect x="785" y="748" width="203" height="405" fill="#03070B" fill-opacity=".82" stroke="${t.accent}" stroke-width="2"/>
    ${interviewMarkup}
    <rect x="180" y="920" width="650" height="280" fill="url(#fade)"/>
    <text x="220" y="1002" font-family="DejaVu Sans" font-size="118" font-weight="900" font-style="italic" fill="#FFFFFF">${esc(player)}</text>
    ${number ? `<text x="720" y="1000" font-family="DejaVu Sans" font-size="84" font-weight="900" font-style="italic" fill="${t.accent}">#${esc(number)}</text>` : ''}
    <text x="512" y="1090" text-anchor="middle" font-family="DejaVu Sans" font-size="44" font-weight="900" letter-spacing="8" fill="#FFFFFF">${esc(title)}</text>
    <line x1="330" y1="1115" x2="694" y2="1115" stroke="${t.accent}" stroke-width="5"/>
    <text x="512" y="1155" text-anchor="middle" font-family="DejaVu Sans" font-size="18" font-weight="700" letter-spacing="5" fill="#FFFFFF">LEADERSHIP. DISCIPLINE. IMPACT.</text>
    <rect x="55" y="1205" width="796" height="245" fill="none" stroke="#FFFFFF" stroke-width="2"/>
    <text x="512" y="1490" text-anchor="middle" font-family="DejaVu Sans" font-size="17" font-weight="700" letter-spacing="5" fill="#FFFFFF">${esc(club)}  •  ${teamKey === 'crownfc' ? 'MLPC' : 'MPL'}  •  SEASON 2026/2027</text>
  </svg>`;

  return sharp({ input: Buffer.from(svg) }).composite(composites).png().toBuffer();
}

module.exports = { renderSpotlight, selectSpotlightLayout };
