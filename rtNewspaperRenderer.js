const sharp = require('sharp');

const WIDTH = 1024;
const HEIGHT = 1536;

function escapeXml(value) {
  return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

function cleanText(value) {
  return String(value || '').replace(/\s+/g, ' ').replace(/\.{3}|…/g, '').trim();
}

function wrapLines(value, maxChars, maxLines) {
  const words = cleanText(value).split(' ').filter(Boolean);
  const lines = [];
  let line = '';
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (!line || next.length <= maxChars) line = next;
    else {
      lines.push(line);
      if (lines.length === maxLines) break;
      line = word;
    }
  }
  if (lines.length < maxLines && line) lines.push(line);
  return lines.slice(0, maxLines);
}

function limitWords(value, count) {
  return cleanText(value).split(' ').filter(Boolean).slice(0, count).join(' ');
}

function completeSentences(value, maxWords = 45) {
  const cleaned = cleanText(value);
  const sentences = cleaned.match(/[^.!?]+[.!?]+/g) || [];
  const kept = [];
  let used = 0;
  for (const sentence of sentences) {
    const text = sentence.trim();
    const words = text.split(/\s+/).length;
    if (used + words > maxWords) break;
    kept.push(text);
    used += words;
  }
  return kept.join(' ');
}

function textLines(lines, x, y, lineHeight, attrs) {
  return `<text x="${x}" y="${y}" ${attrs}>${lines.map((line, index) =>
    `<tspan x="${x}" dy="${index ? lineHeight : 0}">${escapeXml(line)}</tspan>`
  ).join('')}</text>`;
}

function palette(teamKey) {
  if (teamKey === 'crownfc') {
    return { accent: '#45C7F2', accent2: '#146AB3', ink: '#101216', dark: '#050C14', paper: '#EEE8DB' };
  }
  return { accent: '#12A9EA', accent2: '#155EAA', ink: '#101216', dark: '#050C14', paper: '#EEE8DB' };
}

function realQuote(value) {
  return value && !/^no .*comment/i.test(value) && !/not supplied/i.test(value);
}

function headlineLayout(value) {
  const clean = cleanText(value || 'CLUB NEWS').slice(0, 90).toUpperCase();
  for (const candidate of [
    { chars: 14, lines: 2, size: 90, height: 82 },
    { chars: 18, lines: 3, size: 72, height: 68 },
    { chars: 23, lines: 3, size: 58, height: 57 },
    { chars: 27, lines: 3, size: 50, height: 50 },
  ]) {
    const wrapped = wrapLines(clean, candidate.chars, candidate.lines);
    if (wrapped.join(' ').length >= clean.length) return { ...candidate, wrapped };
  }
  return { chars: 30, lines: 3, size: 45, height: 46, wrapped: wrapLines(clean, 30, 3) };
}

function displayDate(value) {
  const parsed = new Date(`${value} 12:00:00 UTC`);
  if (Number.isNaN(parsed.getTime())) return cleanText(value).toUpperCase();
  return parsed.toLocaleDateString('en-US', {
    timeZone: 'UTC', weekday: 'long', month: 'short', day: 'numeric', year: 'numeric',
  }).toUpperCase();
}

function shortLeague(team) {
  return cleanText(team.league).replace(/MASTERS PREMIER LEAGUE/i, 'MPL').toUpperCase();
}

function storyParagraphs(team, type, story) {
  const player = cleanText(story.playerName || 'The player');
  const number = cleanText(story.playerNumber);
  const position = cleanText(story.position);
  const previousClub = cleanText(story.previousClub);
  if (type === 'signing') {
    const paragraphs = [`${team.label} have signed ${player}.`];
    const details = [position ? `The new arrival joins as a ${position}.` : '', number ? `${player} will wear number ${number}.` : ''].filter(Boolean);
    paragraphs.push(...details);
    if (previousClub) paragraphs.push(`${player} arrives from ${previousClub}.`);
    else paragraphs.push(`The move is confirmed for the ${shortLeague(team)} campaign.`);
    return paragraphs.slice(0, 3);
  }
  if (type === 'spotlight') {
    return [
      `${player} is this week’s ${team.label} Player Spotlight.`,
      `The feature covers the player’s view of the club, the squad and the season ahead.`,
      realQuote(story.playerQuote) ? `Every quoted word comes from the player’s submitted interview.` : `No interview response was received, so no quote has been invented.`,
    ];
  }
  const complete = completeSentences(story.body || story.article, 52);
  if (complete) return complete.match(/[^.!?]+[.!?]+/g).map(value => value.trim()).slice(0, 3);
  return [`${team.label} are the subject of today’s verified club report.`, `Only confirmed details supplied to RT Football Media are included.`];
}

function sidebarRows(team, type, story) {
  if (type === 'signing') return [
    ['OFFICIAL MOVE', 'Club confirmation received.'],
    ['SQUAD FILE', 'Position and shirt number verified.'],
    ['PLAYER’S WORD', realQuote(story.playerQuote) ? 'Genuine comment included below.' : 'No quote has been invented.'],
    ['LEAGUE DESK', shortLeague(team)],
  ];
  if (type === 'spotlight') return [
    ['WEEKLY FEATURE', 'One player. One fresh interview scene.'],
    ['PLAYER’S WORD', realQuote(story.playerQuote) ? 'Submitted answers included.' : 'No response. No invented quote.'],
    ['CLUB DESK', team.label],
    ['EDITION', 'Player Spotlight'],
  ];
  if (type === 'match') return [
    ['FINAL SCORE', 'Verified from the match recap.'],
    ['PLAYER STATS', 'Saved match by match.'],
    ['SEASON TOTALS', 'Updated after approval.'],
    ['LEAGUE DESK', shortLeague(team)],
  ];
  return [
    ['CLUB DESK', team.label],
    ['VERIFIED COPY', 'No invented facts or quotes.'],
    ['COMPETITION', shortLeague(team)],
    ['EDITION', 'RT Football Media report.'],
  ];
}

function safeReporterNote(team, story) {
  const complete = completeSentences(story.reporterNote, 22);
  return complete || `${team.reporter} reports only the verified details supplied to RT Football Media.`;
}

function lowerSidebarRows(team, type, story) {
  if (type === 'signing') return [
    ['STATUS', 'Official club signing.'],
    ['ARRIVES FROM', cleanText(story.previousClub || 'Not supplied.')],
    ['REPORTER', team.reporter],
  ];
  if (type === 'spotlight') return [
    ['FEATURE', 'Weekly player interview.'],
    ['RESPONSE', realQuote(story.playerQuote) ? 'Player submitted.' : 'No response received.'],
    ['REPORTER', team.reporter],
  ];
  return [
    ['EDITION', type === 'match' ? 'Matchday report.' : 'Club report.'],
    ['VERIFICATION', 'Owner approved.'],
    ['REPORTER', team.reporter],
  ];
}

function lowerFeatureCopy(team, type, story) {
  const player = cleanText(story.playerName || 'The player');
  if (type === 'signing') {
    return completeSentences(
      `${player} is now part of the ${team.label} squad. The move adds another option as the club prepares for the ${shortLeague(team)} campaign.`,
      32,
    );
  }
  if (type === 'spotlight') {
    return realQuote(story.playerQuote)
      ? `${player} shares a personal view of life inside ${team.label}.`
      : `${player} is profiled using verified club information; no interview quote has been invented.`;
  }
  return completeSentences(story.reporterNote, 32)
    || `${team.reporter} brings the verified story from inside ${team.label}.`;
}

async function renderNewspaper(options) {
  const { team, teamKey, type, story, date, issueNumber, heroBuffer, brandBuffer, mastheadBuffer, editionSeed } = options;
  const colors = palette(teamKey);
  const headline = headlineLayout(story.headline);
  const headlineStart = 426;
  const headlineBottom = headlineStart + ((headline.wrapped.length - 1) * headline.height);
  const subY = headlineBottom + 48;
  const mainTop = Math.max(650, subY + 62);
  const mainHeight = 455;
  const rows = sidebarRows(team, type, story);
  const lowerRows = lowerSidebarRows(team, type, story);
  const paragraphs = storyParagraphs(team, type, story);
  const lowerCopy = lowerFeatureCopy(team, type, story);
  const quote = realQuote(story.playerQuote)
    ? `“${cleanText(story.playerQuote)}”`
    : realQuote(story.leadershipQuote)
      ? `“${cleanText(story.leadershipQuote)}”`
      : 'THE STORY CONTINUES ON THE PITCH.';
  const quoteAttribution = realQuote(story.playerQuote)
    ? `— ${cleanText(story.playerName || 'PLAYER')}`
    : realQuote(story.leadershipQuote)
      ? `— ${cleanText(story.leadershipRole || 'CLUB REPRESENTATIVE')}`
      : '';
  const editionLabel = type === 'match' ? 'MATCHDAY' : type === 'spotlight' ? 'PLAYER SPOTLIGHT' : type === 'weekly_recap' ? 'WEEK IN REVIEW' : type === 'signing' ? 'NEW SIGNING' : 'CLUB EXCLUSIVE';

  const svg = `<svg width="${WIDTH}" height="${HEIGHT}" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <filter id="paper"><feTurbulence baseFrequency=".5" numOctaves="4" seed="${escapeXml(editionSeed || 7)}"/><feColorMatrix values=".5 0 0 0 .45 0 .5 0 0 .42 0 0 .5 0 .36 0 0 0 .13 0"/></filter>
      <filter id="rough"><feTurbulence baseFrequency=".025 .7" numOctaves="2" seed="${escapeXml((editionSeed || 7) + 3)}"/><feDisplacementMap in="SourceGraphic" scale="3"/></filter>
      <linearGradient id="club" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#0A3767"/><stop offset=".5" stop-color="${colors.accent2}"/><stop offset="1" stop-color="#071D35"/></linearGradient>
    </defs>
    <rect width="1024" height="1536" fill="${colors.paper}"/>
    <rect width="1024" height="1536" filter="url(#paper)" opacity=".7"/>
    <rect x="16" y="238" width="992" height="34" fill="#F7F3EA" stroke="${colors.ink}" stroke-width="2"/>
    <text x="26" y="261" font-family="Nimbus Sans Narrow" font-size="17" font-weight="900" letter-spacing="1" fill="${colors.ink}">${escapeXml(displayDate(date))}</text>
    <text x="548" y="261" text-anchor="middle" font-family="Nimbus Sans Narrow" font-size="12" font-weight="800" letter-spacing="1" fill="${colors.ink}">TRANSFERS  |  MATCHDAY  |  CLUB UPDATES  |  COMMUNITY</text>
    <text x="996" y="261" text-anchor="end" font-family="Nimbus Sans Narrow" font-size="18" font-weight="900" fill="${colors.ink}">ISSUE #${escapeXml(String(issueNumber).replace(/^0+/, '') || '1')}</text>
    <rect x="16" y="281" width="992" height="79" fill="url(#club)"/>
    <text x="${brandBuffer ? 124 : 42}" y="334" font-family="Nimbus Sans Narrow" font-size="48" font-weight="900" letter-spacing="1" fill="#F7F3EA">${escapeXml(team.label.toUpperCase())}</text>
    ${textLines(wrapLines(team.league.toUpperCase(), 20, 2), 760, 312, 23, `font-family="Nimbus Sans Narrow" font-size="18" font-weight="800" letter-spacing=".5" fill="#F7F3EA"`)}
    ${headline.wrapped.map((line, index) => `<text x="34" y="${headlineStart + index * headline.height}" font-family="Nimbus Sans Narrow" font-size="${headline.size}" font-weight="900" letter-spacing="-3" filter="url(#rough)" fill="${index === headline.wrapped.length - 1 && headline.wrapped.length > 1 ? colors.accent2 : colors.ink}">${escapeXml(line)}</text>`).join('')}
    ${textLines(wrapLines(story.subheadline, 58, 2), 36, subY, 28, `font-family="Nimbus Sans Narrow" font-size="23" font-weight="900" letter-spacing=".2" fill="${colors.ink}"`)}
    <line x1="30" y1="${subY + 40}" x2="994" y2="${subY + 40}" stroke="${colors.ink}" stroke-width="3"/>

    <rect x="30" y="${mainTop}" width="211" height="${mainHeight}" fill="#EEE8DB"/>
    <text x="42" y="${mainTop + 28}" font-family="Nimbus Sans Narrow" font-size="18" font-weight="900" letter-spacing="2" fill="${colors.accent2}">${escapeXml(editionLabel)}</text>
    <line x1="42" y1="${mainTop + 40}" x2="222" y2="${mainTop + 40}" stroke="${colors.ink}" stroke-width="2"/>
    ${paragraphs.map((paragraph, index) => textLines(wrapLines(paragraph, 19, 5), 42, mainTop + 75 + index * 118, 21, `font-family="DejaVu Serif" font-size="18" font-weight="600" fill="${colors.ink}"`)).join('')}
    <line x1="42" y1="${mainTop + 176}" x2="98" y2="${mainTop + 176}" stroke="${colors.accent2}" stroke-width="3"/>
    <line x1="42" y1="${mainTop + 294}" x2="98" y2="${mainTop + 294}" stroke="${colors.accent2}" stroke-width="3"/>
    <rect x="254" y="${mainTop}" width="488" height="${mainHeight}" fill="#07111B"/>
    <rect x="756" y="${mainTop}" width="238" height="${mainHeight}" fill="${colors.dark}"/>
    <rect x="756" y="${mainTop}" width="238" height="46" fill="${colors.accent2}"/>
    <text x="775" y="${mainTop + 31}" font-family="Nimbus Sans Narrow" font-size="21" font-weight="900" letter-spacing="2" fill="#F7F3EA">INSIDE TODAY</text>
    ${rows.map(([label, value], index) => {
      const y = mainTop + 72 + index * 92;
      return `<line x1="775" y1="${y}" x2="976" y2="${y}" stroke="${colors.accent}" stroke-width="1" opacity=".65"/>
        <circle cx="793" cy="${y + 35}" r="18" fill="none" stroke="#F7F3EA" stroke-width="3"/>
        <text x="793" y="${y + 42}" text-anchor="middle" font-family="Nimbus Sans Narrow" font-size="18" font-weight="900" fill="#F7F3EA">${index + 1}</text>
        <text x="821" y="${y + 26}" font-family="Nimbus Sans Narrow" font-size="18" font-weight="900" fill="#F7F3EA">${escapeXml(label)}</text>
        ${textLines(wrapLines(value, 18, 2), 821, y + 49, 18, `font-family="Nimbus Sans Narrow" font-size="15" font-weight="600" fill="#DDE8F0"`)}`;
    }).join('')}

    <rect x="24" y="1124" width="718" height="308" fill="${colors.dark}" stroke="${colors.ink}" stroke-width="4"/>
    <path d="M24 1124 L742 1124 L742 1180 L24 1180 Z" fill="url(#club)"/>
    <path d="M205 1180 L742 1180 L742 1432 L150 1432 Z" fill="#071421" opacity=".9"/>
    <path d="M220 1191 L730 1191" stroke="${colors.accent}" stroke-width="4" opacity=".85"/>
    <text x="220" y="1228" font-family="Nimbus Sans Narrow" font-size="18" font-weight="900" letter-spacing="3" fill="#F7F3EA">${escapeXml(editionLabel)}</text>
    <text x="220" y="1281" font-family="Nimbus Sans Narrow" font-size="55" font-weight="900" font-style="italic" fill="${colors.accent}" filter="url(#rough)">${escapeXml(cleanText(story.playerName || team.label).toUpperCase())}</text>
    <text x="220" y="1318" font-family="Nimbus Sans Narrow" font-size="24" font-weight="900" letter-spacing="2" fill="#F7F3EA">${escapeXml(story.playerNumber ? `NUMBER ${cleanText(story.playerNumber)}` : shortLeague(team))}${escapeXml(story.position ? `  •  ${cleanText(story.position).toUpperCase()}` : '')}</text>
    ${textLines(wrapLines(lowerCopy, 48, 2), 220, 1352, 20, `font-family="DejaVu Serif" font-size="15" font-weight="600" fill="#F7F3EA"`)}
    ${textLines(wrapLines(quote, 42, 2), 220, 1408, 22, `font-family="DejaVu Serif" font-size="18" font-weight="700" font-style="italic" fill="${colors.accent}"`)}
    <rect x="756" y="1124" width="238" height="308" fill="${colors.dark}"/>
    <rect x="756" y="1124" width="238" height="46" fill="${colors.accent2}"/>
    <text x="775" y="1155" font-family="Nimbus Sans Narrow" font-size="19" font-weight="900" letter-spacing="2" fill="#F7F3EA">KEY STORYLINES</text>
    ${lowerRows.map(([label, value], index) => {
      const y = 1190 + index * 76;
      return `<line x1="775" y1="${y}" x2="976" y2="${y}" stroke="${colors.accent}" stroke-width="1" opacity=".7"/>
        <text x="775" y="${y + 24}" font-family="Nimbus Sans Narrow" font-size="17" font-weight="900" fill="#F7F3EA">${escapeXml(label)}</text>
        ${textLines(wrapLines(value, 22, 2), 775, y + 46, 18, `font-family="Nimbus Sans Narrow" font-size="15" font-weight="600" fill="#DDE8F0"`)}`;
    }).join('')}
    <line x1="24" y1="1460" x2="1000" y2="1460" stroke="${colors.ink}" stroke-width="3"/>
    <text x="38" y="1494" font-family="Nimbus Sans Narrow" font-size="18" font-weight="900" fill="${colors.ink}">RT FOOTBALL MEDIA</text>
    <text x="512" y="1494" text-anchor="middle" font-family="Nimbus Sans Narrow" font-size="18" font-weight="900" fill="${colors.ink}">CASTLE &amp; CROWN COLLECTIVE</text>
    <text x="986" y="1494" text-anchor="end" font-family="Nimbus Sans Narrow" font-size="18" font-weight="900" fill="${colors.ink}">PAGE 1</text>
  </svg>`;

  const composites = [];
  if (mastheadBuffer) {
    const masthead = await sharp(mastheadBuffer).resize(WIDTH, 232, { fit: 'fill' }).png().toBuffer();
    composites.push({ input: masthead, left: 0, top: 0 });
  }
  if (heroBuffer) {
    const hero = await sharp(heroBuffer).rotate().resize(480, mainHeight - 8, { fit: 'cover', position: 'north' })
      .modulate({ brightness: 0.94, saturation: 0.94 }).png().toBuffer();
    composites.push({ input: hero, left: 258, top: mainTop + 4 });
  }
  const frame = `<svg width="${WIDTH}" height="${HEIGHT}" xmlns="http://www.w3.org/2000/svg"><rect x="254" y="${mainTop}" width="488" height="${mainHeight}" fill="none" stroke="${colors.ink}" stroke-width="4"/></svg>`;
  composites.push({ input: Buffer.from(frame), left: 0, top: 0 });
  if (brandBuffer) {
    const brand = await sharp(brandBuffer).rotate().resize(70, 68, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } }).png().toBuffer();
    composites.push({ input: brand, left: 38, top: 286 });
    const lowerBrand = await sharp(brandBuffer).rotate().resize(150, 190, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } }).png().toBuffer();
    composites.push({ input: lowerBrand, left: 43, top: 1192 });
  }
  return sharp(Buffer.from(svg)).composite(composites).png({ compressionLevel: 9 }).toBuffer();
}

module.exports = {
  renderNewspaper, palette, wrapLines, limitWords, completeSentences, headlineLayout,
  storyParagraphs, sidebarRows, lowerSidebarRows, lowerFeatureCopy, WIDTH, HEIGHT,
};
