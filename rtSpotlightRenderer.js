const sharp = require('sharp');

const WIDTH = 1024;
const HEIGHT = 1536;
const LAYOUTS = ['cover-left', 'cover-right', 'feature-split'];

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

function wrap(value, maxChars, maxLines) {
  const words = clean(value, 3000).split(' ').filter(Boolean);
  const lines = [];
  let line = '';
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (!line || next.length <= maxChars) {
      line = next;
      continue;
    }
    lines.push(line);
    line = word;
    if (lines.length >= maxLines) break;
  }
  if (line && lines.length < maxLines) lines.push(line);
  return lines.slice(0, maxLines);
}

function textLines(lines, x, y, lineHeight, attrs = '') {
  return `<text x="${x}" y="${y}" ${attrs}>${lines.map((line, index) =>
    `<tspan x="${x}" dy="${index ? lineHeight : 0}">${escapeXml(line)}</tspan>`
  ).join('')}</text>`;
}

function hashSeed(value) {
  let hash = 0;
  for (const char of String(value || '')) hash = ((hash << 5) - hash + char.charCodeAt(0)) | 0;
  return Math.abs(hash);
}

function selectSpotlightLayout(story = {}, previousLayout = '') {
  const seed = hashSeed(`${story.playerName || ''}|${story.headline || ''}|${story.position || ''}`);
  const available = LAYOUTS.filter(layout => layout !== previousLayout);
  return available[seed % available.length] || LAYOUTS[seed % LAYOUTS.length];
}

async function preparedImage(buffer, width, height, position = 'centre') {
  if (!buffer) return null;
  return sharp(buffer).rotate().resize(width, height, { fit: 'cover', position }).png().toBuffer();
}

function themeFor(teamKey) {
  if (teamKey === 'crownfc') {
    return {
      bg: '#07111d', panel: '#0e1d2e', ink: '#f5f8fb', muted: '#b7c7d7',
      accent: '#7BAFD4', accent2: '#b8d7ea', rule: '#304b63',
    };
  }
  return {
    bg: '#f2eee6', panel: '#ffffff', ink: '#11161c', muted: '#525b64',
    accent: '#0067b9', accent2: '#54a9df', rule: '#b9b5ae',
  };
}

async function renderSpotlight({ team = {}, teamKey = 'birmingham', story = {}, heroBuffer = null, brandBuffer = null, previousLayout = '' } = {}) {
  const theme = themeFor(teamKey);
  const layout = story.spotlightLayout || selectSpotlightLayout(story, previousLayout);
  const player = clean(story.playerName || 'PLAYER SPOTLIGHT', 40).toUpperCase();
  const headline = clean(story.headline || `${player} IN THE SPOTLIGHT`, 90).toUpperCase();
  const subheadline = clean(story.subheadline || `${team.label || 'RT Football Media'} player feature`, 150);
  const position = clean(story.position || '', 60).toUpperCase();
  const quote = clean(story.playerQuote || '', 220);
  const article = clean(story.article || story.body || '', 1600);
  const headlineLines = wrap(headline, layout === 'feature-split' ? 22 : 19, 3);
  const subLines = wrap(subheadline, 48, 3);
  const articleLines = wrap(article, layout === 'feature-split' ? 54 : 42, layout === 'feature-split' ? 11 : 9);
  const quoteLines = quote ? wrap(`“${quote}”`, 38, 4) : [];
  const club = clean(team.label || (teamKey === 'crownfc' ? 'CrownFC' : 'Birmingham City'), 50).toUpperCase();
  const league = clean(team.league || (teamKey === 'crownfc' ? 'MLPC' : 'MPL • LEAGUE 1'), 50).toUpperCase();

  let heroX = 52, heroY = 418, heroW = 920, heroH = 620;
  let copyX = 64, copyY = 1140, copyW = 896;
  if (layout === 'cover-right') {
    heroX = 350; heroY = 378; heroW = 622; heroH = 760;
    copyX = 64; copyY = 465; copyW = 255;
  } else if (layout === 'feature-split') {
    heroX = 52; heroY = 408; heroW = 530; heroH = 760;
    copyX = 618; copyY = 500; copyW = 340;
  }

  const composites = [];
  if (heroBuffer) {
    const hero = await preparedImage(heroBuffer, heroW, heroH, layout === 'cover-right' ? 'attention' : 'centre');
    composites.push({ input: hero, left: heroX, top: heroY });
  }
  if (brandBuffer) {
    const brand = await sharp(brandBuffer).rotate().resize(112, 112, { fit: 'contain' }).png().toBuffer();
    composites.push({ input: brand, left: 832, top: 48 });
  }

  const headlineSize = headlineLines.length >= 3 ? 62 : headlineLines.length === 2 ? 72 : 82;
  const leftCopy = layout === 'cover-right';
  const articleSize = leftCopy ? 21 : 24;
  const articleChars = leftCopy ? 25 : layout === 'feature-split' ? 34 : 68;
  const articleWrapped = wrap(article, articleChars, leftCopy ? 16 : layout === 'feature-split' ? 18 : 7);

  const svg = `<svg width="${WIDTH}" height="${HEIGHT}" xmlns="http://www.w3.org/2000/svg">
    <rect width="1024" height="1536" fill="${theme.bg}"/>
    <rect x="28" y="28" width="968" height="1480" fill="none" stroke="${theme.rule}" stroke-width="2"/>
    <text x="58" y="92" font-family="DejaVu Sans" font-weight="900" font-size="34" fill="${theme.accent}">RT FOOTBALL MEDIA</text>
    <text x="58" y="132" font-family="DejaVu Sans" font-weight="700" font-size="17" letter-spacing="4" fill="${theme.muted}">PLAYER SPOTLIGHT</text>
    <line x1="58" y1="158" x2="790" y2="158" stroke="${theme.accent}" stroke-width="5"/>
    <text x="58" y="205" font-family="DejaVu Sans" font-weight="800" font-size="22" fill="${theme.ink}">${escapeXml(club)}</text>
    <text x="58" y="238" font-family="DejaVu Sans" font-weight="600" font-size="17" fill="${theme.muted}">${escapeXml(league)}</text>
    ${textLines(headlineLines, 58, 305, headlineSize * 0.95, `font-family="DejaVu Sans" font-weight="900" font-size="${headlineSize}" fill="${theme.ink}"`)}
    ${textLines(subLines, 60, 390, 28, `font-family="DejaVu Sans" font-weight="500" font-size="22" fill="${theme.muted}"`)}
    ${heroBuffer ? '' : `<rect x="${heroX}" y="${heroY}" width="${heroW}" height="${heroH}" fill="${theme.panel}" stroke="${theme.rule}" stroke-width="2"/><text x="${heroX + 32}" y="${heroY + 60}" font-family="DejaVu Sans" font-size="19" fill="${theme.muted}">RT FOOTBALL MEDIA EDITORIAL</text>`}
    <rect x="${heroX}" y="${heroY + heroH - 92}" width="${heroW}" height="92" fill="#000" fill-opacity="0.68"/>
    <text x="${heroX + 28}" y="${heroY + heroH - 48}" font-family="DejaVu Sans" font-weight="900" font-size="31" fill="#fff">${escapeXml(player)}</text>
    <text x="${heroX + 28}" y="${heroY + heroH - 18}" font-family="DejaVu Sans" font-weight="700" font-size="17" fill="${theme.accent2}">${escapeXml(position || 'PLAYER FEATURE')}</text>
    ${leftCopy || layout === 'feature-split' ? `<rect x="${copyX - 18}" y="${copyY - 52}" width="${copyW + 30}" height="650" fill="${theme.panel}" stroke="${theme.rule}" stroke-width="2"/>` : ''}
    ${quoteLines.length ? textLines(quoteLines, copyX, copyY, 34, `font-family="DejaVu Sans" font-style="italic" font-weight="700" font-size="26" fill="${theme.accent}"`) : ''}
    ${textLines(articleWrapped, copyX, copyY + (quoteLines.length ? 165 : 0), articleSize + 8, `font-family="DejaVu Sans" font-weight="400" font-size="${articleSize}" fill="${theme.ink}"`)}
    <line x1="58" y1="1453" x2="966" y2="1453" stroke="${theme.rule}" stroke-width="2"/>
    <text x="58" y="1484" font-family="DejaVu Sans" font-weight="700" font-size="15" fill="${theme.muted}">CASTLE &amp; CROWN COLLECTIVE • ${escapeXml(team.reporter || 'RT MEDIA')} REPORTING</text>
  </svg>`;

  return sharp({ input: Buffer.from(svg) })
    .composite(composites)
    .png()
    .toBuffer();
}

module.exports = { renderSpotlight, selectSpotlightLayout };
