const sharp = require('sharp');

const WIDTH = 1024;
const HEIGHT = 1536;

function clean(value, max = 1000) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, max);
}

function escapeXml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function hashSeed(value) {
  let hash = 0;
  for (const char of String(value || '')) hash = ((hash << 5) - hash + char.charCodeAt(0)) | 0;
  return Math.abs(hash);
}

function batchComposition(count, variationKey = '') {
  const options = {
    2: ['duo-centered', 'duo-offset'],
    3: ['trio-pyramid', 'trio-line'],
    4: ['four-arc', 'four-line'],
    5: ['five-pyramid', 'five-line'],
  };
  const list = options[count] || [];
  if (!list.length) throw new Error('Signing class must contain 2–5 players.');
  return list[hashSeed(variationKey) % list.length];
}

function validateBatchSigningData(teamKey, players, marqueePlayerId = '') {
  if (!['birmingham', 'crownfc'].includes(teamKey)) throw new Error('Unknown club for signing class.');
  if (!Array.isArray(players) || players.length < 2 || players.length > 5) throw new Error('Signing class must contain 2–5 players.');
  const ids = new Set();
  for (const player of players) {
    if (!player || !clean(player.name, 40)) throw new Error('Every signing-class player needs a name.');
    if (!clean(player.position, 60)) throw new Error(`A position is required for ${clean(player.name, 40)}.`);
    const id = clean(player.id, 80);
    if (id) {
      if (ids.has(id)) throw new Error('A player cannot appear twice in the same signing class.');
      ids.add(id);
    }
  }
  if (marqueePlayerId && !players.some(player => String(player.id) === String(marqueePlayerId))) {
    throw new Error('The marquee player must be part of the selected signing class.');
  }
  return true;
}

function theme(teamKey) {
  return teamKey === 'crownfc'
    ? { bg: '#07111d', ink: '#ffffff', muted: '#b9cad9', accent: '#7BAFD4', rule: '#29445d' }
    : { bg: '#07121f', ink: '#ffffff', muted: '#cbd4dd', accent: '#00A1E4', rule: '#29465d' };
}

async function renderBatchSigningPoster({ teamKey = 'birmingham', players = [], artBuffer = null, brandBuffer = null, season = '2026/27', composition = '', marqueePlayerId = '' } = {}) {
  validateBatchSigningData(teamKey, players, marqueePlayerId);
  const t = theme(teamKey);
  const club = teamKey === 'crownfc' ? 'CROWNFC' : 'BIRMINGHAM CITY';
  const league = teamKey === 'crownfc' ? 'MLPC' : 'MPL • LEAGUE 1';
  const artTop = 300;
  const artHeight = 940;
  const composites = [];
  if (artBuffer) {
    const art = await sharp(artBuffer).rotate().resize(944, artHeight, { fit: 'cover', position: 'centre' }).png().toBuffer();
    composites.push({ input: art, left: 40, top: artTop });
  }
  if (brandBuffer) {
    const crest = await sharp(brandBuffer).rotate().resize(115, 115, { fit: 'contain' }).png().toBuffer();
    composites.push({ input: crest, left: 844, top: 48 });
  }

  const slotWidth = 944 / players.length;
  const labels = players.map((player, index) => {
    const x = 40 + slotWidth * index;
    const isMarquee = marqueePlayerId && String(player.id) === String(marqueePlayerId);
    const nameSize = players.length >= 5 ? 22 : players.length === 4 ? 25 : 29;
    return `<rect x="${x}" y="1240" width="${slotWidth}" height="170" fill="#000" fill-opacity="${isMarquee ? '0.84' : '0.72'}" stroke="${isMarquee ? t.accent : t.rule}" stroke-width="${isMarquee ? 4 : 1}"/>
      <text x="${x + slotWidth / 2}" y="1295" text-anchor="middle" font-family="DejaVu Sans" font-weight="900" font-size="${nameSize}" fill="#fff">${escapeXml(clean(player.name, 30).toUpperCase())}</text>
      <text x="${x + slotWidth / 2}" y="1332" text-anchor="middle" font-family="DejaVu Sans" font-weight="700" font-size="18" fill="${t.accent}">${escapeXml(clean(player.position, 28).toUpperCase())}</text>
      ${player.number ? `<text x="${x + slotWidth / 2}" y="1368" text-anchor="middle" font-family="DejaVu Sans" font-weight="800" font-size="18" fill="${t.muted}">#${escapeXml(clean(player.number, 3))}</text>` : ''}`;
  }).join('');

  const svg = `<svg width="${WIDTH}" height="${HEIGHT}" xmlns="http://www.w3.org/2000/svg">
    <rect width="1024" height="1536" fill="${t.bg}"/>
    <rect x="24" y="24" width="976" height="1488" fill="none" stroke="${t.rule}" stroke-width="2"/>
    <text x="54" y="86" font-family="DejaVu Sans" font-weight="900" font-size="34" fill="${t.accent}">RT FOOTBALL MEDIA</text>
    <text x="54" y="130" font-family="DejaVu Sans" font-weight="900" font-size="52" fill="${t.ink}">${escapeXml(club)}</text>
    <text x="54" y="166" font-family="DejaVu Sans" font-weight="700" font-size="18" letter-spacing="3" fill="${t.muted}">${escapeXml(league)} • ${escapeXml(season)}</text>
    <line x1="54" y1="190" x2="970" y2="190" stroke="${t.accent}" stroke-width="6"/>
    <text x="54" y="252" font-family="DejaVu Sans" font-weight="900" font-size="55" fill="${t.ink}">SIGNING CLASS</text>
    <text x="965" y="252" text-anchor="end" font-family="DejaVu Sans" font-weight="700" font-size="16" fill="${t.muted}">${escapeXml(composition || batchComposition(players.length, season))}</text>
    ${artBuffer ? '' : `<rect x="40" y="${artTop}" width="944" height="${artHeight}" fill="#101d2b" stroke="${t.rule}" stroke-width="2"/><text x="512" y="760" text-anchor="middle" font-family="DejaVu Sans" font-size="24" fill="${t.muted}">RT FOOTBALL MEDIA SIGNING CLASS</text>`}
    ${labels}
    <text x="54" y="1472" font-family="DejaVu Sans" font-weight="700" font-size="16" fill="${t.muted}">${players.length} NEW SIGNINGS • ONE CLUB • ONE ANNOUNCEMENT</text>
  </svg>`;

  return sharp({ input: Buffer.from(svg) }).composite(composites).png().toBuffer();
}

module.exports = { batchComposition, validateBatchSigningData, renderBatchSigningPoster };
