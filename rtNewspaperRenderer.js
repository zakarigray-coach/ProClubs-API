const sharp = require('sharp');

const WIDTH = 1080;
const HEIGHT = 1350;

function escapeXml(value) {
  return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

function wrapLines(value, maxChars, maxLines, options = {}) {
  const words = String(value || '').replace(/\s+/g, ' ').trim().split(' ').filter(Boolean);
  const lines = [];
  let line = '';
  let consumed = 0;
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (!line || next.length <= maxChars) {
      line = next;
      consumed += 1;
    } else {
      lines.push(line);
      if (lines.length === maxLines) break;
      line = word;
      consumed += 1;
    }
  }
  if (lines.length < maxLines && line) lines.push(line);
  if (options.ellipsis && lines.length === maxLines && consumed < words.length) {
    lines[maxLines - 1] = lines[maxLines - 1].replace(/[.,;:!?]?$/, '…');
  }
  return lines.slice(0, maxLines);
}

function limitWords(value, count) {
  const words = String(value || '').replace(/\s+/g, ' ').trim().split(' ').filter(Boolean);
  if (words.length <= count) return words.join(' ');
  return `${words.slice(0, count).join(' ').replace(/[.,;:!?]?$/, '')}…`;
}

function textLines(lines, x, y, lineHeight, attrs) {
  return `<text x="${x}" y="${y}" ${attrs}>${lines.map((line, index) =>
    `<tspan x="${x}" dy="${index ? lineHeight : 0}">${escapeXml(line)}</tspan>`
  ).join('')}</text>`;
}

function palette(teamKey) {
  if (teamKey === 'crownfc') {
    return { accent: '#43BCEB', accent2: '#1769B0', ink: '#101318', muted: '#313943', dark: '#071421', paper: '#EEE9DE' };
  }
  return { accent: '#00A6E8', accent2: '#125EAA', ink: '#101318', muted: '#313943', dark: '#071421', paper: '#EEE9DE' };
}

function realQuote(value) {
  return value && !/^no .*comment/i.test(value) && !/not supplied/i.test(value);
}

function headlineLayout(value) {
  const clean = String(value || 'CLUB NEWS').replace(/\s+/g, ' ').trim().slice(0, 90);
  for (const candidate of [
    { chars: 22, lines: 2, size: 69, height: 70 },
    { chars: 27, lines: 3, size: 57, height: 59 },
    { chars: 33, lines: 3, size: 49, height: 52 },
  ]) {
    const wrapped = wrapLines(clean, candidate.chars, candidate.lines);
    if (wrapped.join(' ').length >= clean.length) return { ...candidate, wrapped };
  }
  return { chars: 36, lines: 3, size: 45, height: 48, wrapped: wrapLines(clean, 36, 3, { ellipsis: true }) };
}

function keyPoint(value, fallback) {
  return wrapLines(limitWords(value || fallback, 16), 25, 3, { ellipsis: true });
}

async function renderNewspaper(options) {
  const { team, teamKey, type, story, date, issueNumber, heroBuffer, brandBuffer, editionSeed } = options;
  const colors = palette(teamKey);
  const headline = headlineLayout(story.headline);
  const headlineStart = 371;
  const headlineBottom = headlineStart + ((headline.wrapped.length - 1) * headline.height);
  const subheadlineY = headlineBottom + 50;
  const contentTop = Math.max(579, subheadlineY + 49);
  const heroHeight = 449;
  const article = limitWords(story.article || story.body || story.subheadline, type === 'spotlight' ? 56 : 52);
  const storyLines = wrapLines(article, 49, 6, { ellipsis: true });
  const quote = realQuote(story.playerQuote)
    ? `“${limitWords(story.playerQuote, 28)}” — ${story.playerName || 'Player'}`
    : realQuote(story.leadershipQuote)
      ? `“${limitWords(story.leadershipQuote, 28)}” — ${story.leadershipRole || 'Club representative'}`
      : limitWords(story.reporterNote || 'Verified club coverage from RT Football Media.', 28);
  const keyPoints = [
    keyPoint(story.subheadline, `${team.label} club update`),
    keyPoint(story.body, `Verified details from ${team.reporter}`),
    keyPoint(story.seasonLine || story.reporterNote, `${team.league} context and club direction`),
  ];
  const clubStrip = `${team.label.toUpperCase()}  •  ${team.league.toUpperCase()}`;
  const editionLabel = type === 'match' ? 'MATCHDAY' : type === 'spotlight' ? 'PLAYER SPOTLIGHT' : type === 'weekly_recap' ? 'WEEK IN REVIEW' : type === 'signing' ? 'NEW SIGNING' : 'CLUB EXCLUSIVE';
  const sidebarTitle = type === 'spotlight' ? 'PLAYER FILE' : type === 'match' ? 'MATCH FILE' : 'INSIDE TODAY';

  const baseSvg = `<svg width="${WIDTH}" height="${HEIGHT}" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <filter id="paper"><feTurbulence baseFrequency=".42" numOctaves="3" seed="${escapeXml(editionSeed || 7)}"/><feColorMatrix values=".4 0 0 0 .55 0 .4 0 0 .52 0 0 .4 0 .45 0 0 0 .10 0"/></filter>
      <linearGradient id="mast" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#03080E"/><stop offset=".52" stop-color="#10263B"/><stop offset="1" stop-color="#02070C"/></linearGradient>
      <linearGradient id="club" x1="0" y1="0" x2="1" y2="0"><stop stop-color="${colors.accent2}"/><stop offset=".55" stop-color="${colors.accent}"/><stop offset="1" stop-color="${colors.accent2}"/></linearGradient>
      <clipPath id="storyClip"><rect x="41" y="1120" width="514" height="151"/></clipPath>
      <clipPath id="quoteClip"><rect x="591" y="1120" width="434" height="151"/></clipPath>
    </defs>
    <rect width="1080" height="1350" fill="${colors.paper}"/>
    <rect width="1080" height="1350" filter="url(#paper)" opacity=".50"/>
    <rect x="18" y="18" width="1044" height="188" fill="url(#mast)"/>
    <path d="M18 184 L1062 184" stroke="${colors.accent}" stroke-width="5"/>
    <text x="48" y="78" font-family="DejaVu Sans" font-size="18" font-weight="800" letter-spacing="5" fill="${colors.accent}">PRO CLUBS NEWS NETWORK</text>
    <text x="48" y="163" font-family="DejaVu Sans" font-size="88" font-weight="900" font-style="italic" letter-spacing="-6" fill="#F7F4EC">RT MEDIA</text>
    <text x="1028" y="69" text-anchor="end" font-family="DejaVu Sans" font-size="16" font-weight="700" letter-spacing="2" fill="#F7F4EC">REAL CLUBS. REAL STORIES.</text>
    <text x="1028" y="95" text-anchor="end" font-family="DejaVu Sans" font-size="16" font-weight="700" letter-spacing="2" fill="#F7F4EC">ALL FOOTBALL THAT MATTERS.</text>
    <text x="1028" y="151" text-anchor="end" font-family="DejaVu Sans" font-size="20" font-weight="900" letter-spacing="3" fill="${colors.accent}">${escapeXml(editionLabel)}</text>
    <rect x="18" y="210" width="1044" height="36" fill="#F7F4EC" stroke="${colors.ink}" stroke-width="2"/>
    <text x="36" y="235" font-family="DejaVu Sans" font-size="16" font-weight="800" letter-spacing="1" fill="${colors.ink}">${escapeXml(date)}</text>
    <text x="540" y="235" text-anchor="middle" font-family="DejaVu Sans" font-size="14" font-weight="700" letter-spacing="2" fill="${colors.ink}">TRANSFERS  |  MATCHDAY  |  CLUB NEWS  |  COMMUNITY</text>
    <text x="1044" y="235" text-anchor="end" font-family="DejaVu Sans" font-size="16" font-weight="800" fill="${colors.ink}">ISSUE #${escapeXml(issueNumber)}</text>
    <rect x="18" y="254" width="1044" height="64" fill="url(#club)"/>
    <text x="48" y="296" font-family="DejaVu Sans" font-size="29" font-weight="900" letter-spacing="4" fill="#F8FCFF">${escapeXml(clubStrip)}</text>
    <text x="1032" y="294" text-anchor="end" font-family="DejaVu Sans" font-size="15" font-weight="800" letter-spacing="2" fill="#06101A">${escapeXml(editionLabel)}</text>
    ${headline.wrapped.map((line, index) => `<text x="40" y="${headlineStart + index * headline.height}" font-family="DejaVu Sans" font-size="${headline.size}" font-weight="900" letter-spacing="-2" fill="${index === headline.wrapped.length - 1 && headline.wrapped.length > 1 ? colors.accent2 : colors.ink}">${escapeXml(line)}</text>`).join('')}
    <line x1="40" y1="${subheadlineY + 13}" x2="1040" y2="${subheadlineY + 13}" stroke="${colors.ink}" stroke-width="2"/>
    ${textLines(wrapLines(limitWords(story.subheadline, 24), 76, 2, { ellipsis: true }), 42, subheadlineY - 14, 25, `font-family="DejaVu Serif" font-size="21" font-weight="700" fill="${colors.muted}"`)}
    <rect x="40" y="${contentTop}" width="664" height="${heroHeight}" fill="#0C1722"/>
    <rect x="724" y="${contentTop}" width="316" height="${heroHeight}" fill="${colors.dark}"/>
    <rect x="724" y="${contentTop}" width="316" height="48" fill="${colors.accent2}"/>
    <text x="747" y="${contentTop + 32}" font-family="DejaVu Sans" font-size="18" font-weight="900" letter-spacing="3" fill="#F8FCFF">${sidebarTitle}</text>
    ${keyPoints.map((lines, index) => `<line x1="747" y1="${contentTop + 75 + index * 119}" x2="1015" y2="${contentTop + 75 + index * 119}" stroke="#476073" stroke-width="1"/>${textLines(lines, 747, contentTop + 105 + index * 119, 25, `font-family="DejaVu Sans" font-size="18" font-weight="600" fill="#F7F4EC"`)}`).join('')}
    <line x1="40" y1="1091" x2="1040" y2="1091" stroke="${colors.ink}" stroke-width="4"/>
    <text x="40" y="1122" font-family="DejaVu Serif" font-size="25" font-weight="900" fill="${colors.ink}">${escapeXml(team.reporter.toUpperCase())} REPORTS</text>
    <g clip-path="url(#storyClip)">${textLines(storyLines, 40, 1150, 21, `font-family="DejaVu Sans" font-size="16" font-weight="500" fill="${colors.muted}"`)}</g>
    <rect x="576" y="1110" width="464" height="171" fill="#F7F4EC" stroke="${colors.accent2}" stroke-width="3"/>
    <text x="602" y="1141" font-family="DejaVu Sans" font-size="15" font-weight="900" letter-spacing="3" fill="${colors.accent2}">FROM THE EDITORIAL DESK</text>
    <g clip-path="url(#quoteClip)">${textLines(wrapLines(quote, 42, 5, { ellipsis: true }), 602, 1174, 23, `font-family="DejaVu Serif" font-size="18" font-style="italic" font-weight="700" fill="${colors.ink}"`)}</g>
    <line x1="18" y1="1302" x2="1062" y2="1302" stroke="${colors.ink}" stroke-width="3"/>
    <text x="36" y="1330" font-family="DejaVu Sans" font-size="15" font-weight="800" fill="${colors.ink}">${escapeXml(team.outlet.toUpperCase())}</text>
    <text x="540" y="1330" text-anchor="middle" font-family="DejaVu Sans" font-size="15" font-weight="800" fill="${colors.ink}">CASTLE &amp; CROWN COLLECTIVE</text>
    <text x="1044" y="1330" text-anchor="end" font-family="DejaVu Sans" font-size="15" font-weight="800" fill="${colors.ink}">PAGE 1</text>
  </svg>`;

  const composites = [];
  if (heroBuffer) {
    const hero = await sharp(heroBuffer).rotate().resize(658, heroHeight - 6, { fit: 'cover', position: 'north' })
      .modulate({ brightness: 0.93, saturation: 0.92 }).png().toBuffer();
    composites.push({ input: hero, left: 43, top: contentTop + 3 });
  }
  const frame = `<svg width="${WIDTH}" height="${HEIGHT}" xmlns="http://www.w3.org/2000/svg"><rect x="40" y="${contentTop}" width="664" height="${heroHeight}" fill="none" stroke="${colors.ink}" stroke-width="4"/></svg>`;
  composites.push({ input: Buffer.from(frame), left: 0, top: 0 });
  if (brandBuffer) {
    const brand = await sharp(brandBuffer).rotate().resize(66, 58, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } }).png().toBuffer();
    composites.push({ input: brand, left: 956, top: 257 });
  }
  return sharp(Buffer.from(baseSvg)).composite(composites).png({ compressionLevel: 9 }).toBuffer();
}

module.exports = { renderNewspaper, palette, wrapLines, limitWords, headlineLayout, WIDTH, HEIGHT };
