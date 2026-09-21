const sharp = require('sharp');

const WIDTH = 1080;
const HEIGHT = 1350;

function escapeXml(value) {
  return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

function wrapLines(value, maxChars, maxLines) {
  const words = String(value || '').replace(/\s+/g, ' ').trim().split(' ').filter(Boolean);
  const lines = [];
  let line = '';
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (!line || next.length <= maxChars) line = next;
    else {
      lines.push(line);
      line = word;
      if (lines.length === maxLines) break;
    }
  }
  if (lines.length < maxLines && line) lines.push(line);
  if (lines.length === maxLines && lines.join(' ').length < words.join(' ').length) {
    lines[maxLines - 1] = lines[maxLines - 1].replace(/[.,;:!?]?$/, '…');
  }
  return lines.slice(0, maxLines);
}

function textLines(lines, x, y, lineHeight, attrs) {
  return `<text x="${x}" y="${y}" ${attrs}>${lines.map((line, index) =>
    `<tspan x="${x}" dy="${index ? lineHeight : 0}">${escapeXml(line)}</tspan>`
  ).join('')}</text>`;
}

function palette(teamKey) {
  if (teamKey === 'crownfc') {
    return { accent: '#65C7F2', accent2: '#2D79D6', ink: '#F7FBFF', muted: '#B9C8D8', panel: '#111D2B' };
  }
  return { accent: '#00A6E8', accent2: '#1665C1', ink: '#F7FBFF', muted: '#BBC8D6', panel: '#101D2B' };
}

function realQuote(value) {
  return value && !/^no .*comment/i.test(value) && !/not supplied/i.test(value);
}

async function renderNewspaper(options) {
  const { team, teamKey, type, story, date, issueNumber, heroBuffer, brandBuffer, editionSeed } = options;
  const colors = palette(teamKey);
  const headline = wrapLines(story.headline, 19, 2);
  const longest = Math.max(1, ...headline.map(line => line.length));
  const headlineSize = longest > 18 ? 61 : longest > 14 ? 70 : 80;
  const article = story.article || story.body || story.subheadline;
  const storyLines = wrapLines(article, 43, 13);
  const quote = realQuote(story.playerQuote)
    ? `“${story.playerQuote}” — ${story.playerName || 'Player'}`
    : realQuote(story.leadershipQuote)
      ? `“${story.leadershipQuote}” — ${story.leadershipRole || 'Club representative'}`
      : story.reporterNote || 'Verified club coverage from RT Football Media.';
  const keyPoints = [story.seasonLine ? `OFFICIAL SEASON WINDOW — ${story.seasonLine}` : story.subheadline, story.body, story.reporterNote]
    .filter(Boolean).map(value => wrapLines(value, 25, 3)).slice(0, 3);
  const clubStrip = `${team.label.toUpperCase()} • ${team.league.toUpperCase()}`;
  const editionLabel = type === 'match' ? 'MATCHDAY EDITION' : type === 'spotlight' ? 'PLAYER SPOTLIGHT' : type === 'weekly_recap' ? 'WEEK IN REVIEW' : 'CLUB EXCLUSIVE';

  const svg = `<svg width="${WIDTH}" height="${HEIGHT}" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <linearGradient id="page" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#07101B"/><stop offset="1" stop-color="#0B1522"/></linearGradient>
      <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0"><stop stop-color="${colors.accent2}"/><stop offset=".55" stop-color="${colors.accent}"/><stop offset="1" stop-color="${colors.accent2}"/></linearGradient>
      <filter id="grain"><feTurbulence baseFrequency=".75" numOctaves="2" seed="${escapeXml(editionSeed || 7)}"/><feColorMatrix values="1 0 0 0 0 0 1 0 0 0 0 0 1 0 0 0 0 0 .035 0"/></filter>
    </defs>
    <rect width="1080" height="1350" fill="url(#page)"/>
    <rect width="1080" height="1350" filter="url(#grain)" opacity=".25"/>
    <rect x="24" y="22" width="1032" height="1306" fill="none" stroke="#30465D" stroke-width="2"/>
    <text x="54" y="78" font-family="DejaVu Sans" font-size="19" font-weight="700" letter-spacing="4" fill="${colors.accent}">PRO CLUBS NEWS NETWORK</text>
    <text x="1026" y="78" text-anchor="end" font-family="DejaVu Sans" font-size="18" fill="${colors.muted}">${escapeXml(date)} • ISSUE ${escapeXml(issueNumber)}</text>
    <line x1="54" y1="96" x2="1026" y2="96" stroke="${colors.accent}" stroke-width="3"/>
    <text x="54" y="181" font-family="DejaVu Serif" font-size="91" font-weight="700" letter-spacing="-3" fill="${colors.ink}">RT MEDIA</text>
    <text x="1026" y="150" text-anchor="end" font-family="DejaVu Sans" font-size="20" font-weight="700" letter-spacing="3" fill="${colors.accent}">${escapeXml(editionLabel)}</text>
    ${textLines(wrapLines('REAL CLUBS. REAL STORIES. ALL FOOTBALL THAT MATTERS.', 38, 2), 1026, 181, 24, `text-anchor="end" font-family="DejaVu Sans" font-size="16" font-weight="700" letter-spacing="1" fill="${colors.muted}"`)}
    <rect x="24" y="215" width="1032" height="52" fill="url(#accent)"/>
    <text x="540" y="250" text-anchor="middle" font-family="DejaVu Sans" font-size="24" font-weight="800" letter-spacing="5" fill="#07101B">${escapeXml(clubStrip)}</text>
    ${headline.map((line, index) => `<text x="54" y="${340 + index * 77}" font-family="DejaVu Serif" font-size="${headlineSize}" font-weight="700" letter-spacing="-2" fill="${index ? colors.accent : colors.ink}">${escapeXml(line)}</text>`).join('')}
    <line x1="54" y1="${headline.length > 1 ? 446 : 372}" x2="1026" y2="${headline.length > 1 ? 446 : 372}" stroke="#496078" stroke-width="2"/>
    ${textLines(wrapLines(story.subheadline, 67, 2), 54, headline.length > 1 ? 477 : 405, 27, `font-family="DejaVu Sans" font-size="22" font-weight="700" fill="${colors.muted}"`)}
    <rect x="54" y="520" width="640" height="455" rx="3" fill="#142334" stroke="#38516A" stroke-width="2"/>
    <rect x="716" y="520" width="310" height="455" rx="3" fill="${colors.panel}" stroke="#38516A" stroke-width="2"/>
    <text x="742" y="560" font-family="DejaVu Sans" font-size="17" font-weight="800" letter-spacing="3" fill="${colors.accent}">KEY STORYLINES</text>
    ${keyPoints.map((lines, index) => `<line x1="742" y1="${588 + index * 119}" x2="1000" y2="${588 + index * 119}" stroke="#30465D"/>${textLines(lines, 742, 618 + index * 119, 24, `font-family="DejaVu Sans" font-size="18" fill="${colors.ink}"`)}`).join('')}
    <line x1="54" y1="1002" x2="1026" y2="1002" stroke="${colors.accent}" stroke-width="3"/>
    <text x="54" y="1040" font-family="DejaVu Serif" font-size="28" font-weight="700" fill="${colors.ink}">${escapeXml(team.reporter.toUpperCase())} REPORTS</text>
    ${textLines(storyLines, 54, 1072, 23, `font-family="DejaVu Sans" font-size="17" fill="${colors.muted}"`)}
    <rect x="585" y="1029" width="441" height="235" fill="#101E2D" stroke="${colors.accent}" stroke-width="2"/>
    <text x="611" y="1067" font-family="DejaVu Sans" font-size="16" font-weight="800" letter-spacing="3" fill="${colors.accent}">FROM THE EDITORIAL DESK</text>
    ${textLines(wrapLines(quote, 39, 6), 611, 1104, 27, `font-family="DejaVu Serif" font-size="20" font-style="italic" fill="${colors.ink}"`)}
    <line x1="54" y1="1290" x2="1026" y2="1290" stroke="#496078" stroke-width="2"/>
    <text x="54" y="1318" font-family="DejaVu Sans" font-size="16" font-weight="700" fill="${colors.muted}">${escapeXml(team.outlet.toUpperCase())}</text>
    <text x="540" y="1318" text-anchor="middle" font-family="DejaVu Sans" font-size="16" font-weight="700" fill="${colors.muted}">CASTLE &amp; CROWN COLLECTIVE</text>
    <text x="1026" y="1318" text-anchor="end" font-family="DejaVu Sans" font-size="16" font-weight="700" fill="${colors.muted}">PAGE 1</text>
  </svg>`;

  const composites = [];
  if (heroBuffer) {
    const hero = await sharp(heroBuffer).rotate().resize(634, 449, { fit: 'cover', position: 'north' })
      .modulate({ brightness: 0.86, saturation: 0.9 }).png().toBuffer();
    composites.push({ input: hero, left: 57, top: 523 });
  }
  if (brandBuffer) {
    const brand = await sharp(brandBuffer).rotate().resize(82, 96, { fit: 'contain', background: { r: 7, g: 16, b: 27, alpha: 0 } }).png().toBuffer();
    composites.push({ input: brand, left: 944, top: 108 });
  }
  return sharp(Buffer.from(svg)).composite(composites).png({ compressionLevel: 9 }).toBuffer();
}

module.exports = { renderNewspaper, palette, wrapLines, WIDTH, HEIGHT };
