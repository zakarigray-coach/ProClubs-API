const Module = require('module');
const fs = require('fs');
const path = require('path');

function newspaperGraphicV2(team, type, story, graphic, options = {}) {
  const width = 1080;
  const height = 1350;
  const isCrown = team === TEAMS.crownfc;
  const teamColor = isCrown ? '#7BAFD4' : '#0057B8';
  const teamColorDeep = isCrown ? '#15253A' : '#003B7A';
  const paper = '#F1EEE7';
  const ink = '#111111';
  const date = publicationDate(options.publishedAt);
  const issue = String((Number(options.editionSeed || 8) % 90) + 10).padStart(2, '0');
  const headlineLines = wrapLines(story.headline, 18, 3);
  const longestHeadline = Math.max(...headlineLines.map(line => line.length), 1);
  const headlineSize = headlineLines.length >= 3 ? 58 : longestHeadline > 17 ? 66 : longestHeadline > 14 ? 74 : 84;
  const summary = safePublicText(story.body || excerptWords(story.article, 90), 900);
  const articleCopy = safePublicText(story.article || summary, 3500);
  const playerQuoteIsReal = story.playerQuote && !/^no .*comment/i.test(story.playerQuote) && !/not supplied/i.test(story.playerQuote);
  const leadershipQuoteIsReal = story.leadershipQuote && !/^no .*comment/i.test(story.leadershipQuote) && !/not supplied/i.test(story.leadershipQuote);
  const quote = playerQuoteIsReal
    ? '“' + story.playerQuote + '” — ' + (story.playerName || 'Player')
    : leadershipQuoteIsReal
      ? '“' + story.leadershipQuote + '” — ' + story.leadershipRole
      : (story.reporterNote || 'RT Media will continue following the story as it develops.');

  const sideTitles = type === 'match'
    ? ['FINAL WHISTLE', 'KEY PERFORMERS', 'TACTICAL READ', 'NEXT UP']
    : ['NEW SIGNING', 'SQUAD UPDATE', 'WHAT IT MEANS', 'NEXT UP'];
  const sideCopies = type === 'match'
    ? [story.subheadline, summary, story.reporterNote || summary, team.label + ' continue their ' + team.league + ' campaign.']
    : [story.playerName ? story.playerName + ' joins ' + team.label + '.' : story.subheadline,
       safePublicText(story.subheadline, 180),
       safePublicText(story.reporterNote || summary, 220),
       team.label + ' continue building for ' + team.league + '.'];

  const articleLines = wrapLines(articleCopy, 38, 12);
  const quoteLines = wrapLines(quote, 44, 4);
  const teamStripText = team.label.toUpperCase();
  const leagueText = team.league.toUpperCase();
  const footerStory = type === 'match' ? 'MATCHDAY, RETOLD.' : 'A NEW ARRIVAL. A FRESH CHALLENGE.';

  const masthead = `
    <rect x="18" y="18" width="1044" height="215" rx="2" fill="#07111E"/>
    <defs>
      <linearGradient id="topGlow" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#07111E"/><stop offset="0.56" stop-color="#132A45"/><stop offset="1" stop-color="#07111E"/>
      </linearGradient>
      <linearGradient id="heroShade" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#000" stop-opacity=".04"/><stop offset="1" stop-color="#000" stop-opacity=".36"/>
      </linearGradient>
      <filter id="paper"><feTurbulence baseFrequency="0.65" numOctaves="2" seed="${escapeXml(options.editionSeed || 8)}" type="fractalNoise"/><feColorMatrix values="0 0 0 0 0.73 0 0 0 0 0.72 0 0 0 0 0.69 0 0 0 .11 0"/></filter>
    </defs>
    <rect x="18" y="18" width="1044" height="215" fill="url(#topGlow)"/>
    <path d="M20 184 C150 120, 260 210, 390 150 S650 180, 780 115 S950 155,1060 110" fill="none" stroke="#FFFFFF" stroke-opacity=".10" stroke-width="3"/>
    <path d="M20 207 C180 142, 305 222, 430 170 S700 205, 840 135 S960 165,1060 138" fill="none" stroke="${teamColor}" stroke-opacity=".35" stroke-width="5"/>
    <text x="58" y="123" font-family="DejaVu Sans" font-size="88" font-style="italic" font-weight="700" fill="#FFFFFF" letter-spacing="-5">RT</text>
    <text x="208" y="132" font-family="DejaVu Sans" font-size="98" font-weight="800" fill="#FFFFFF" letter-spacing="-4">MEDIA</text>
    <rect x="203" y="154" width="436" height="8" fill="${teamColor}" transform="rotate(-2 203 154)"/>
    <text x="212" y="199" font-family="DejaVu Sans" font-size="16" letter-spacing="8" fill="#E8EEF6">PRO CLUBS NEWS NETWORK</text>
    <line x1="760" y1="46" x2="760" y2="205" stroke="#FFFFFF" stroke-opacity=".42" stroke-width="2"/>
    <text x="786" y="83" font-family="DejaVu Sans" font-size="22" font-weight="700" fill="#FFFFFF">REAL CLUBS.</text>
    <text x="786" y="113" font-family="DejaVu Sans" font-size="22" font-weight="700" fill="#FFFFFF">REAL STORIES.</text>
    <text x="786" y="143" font-family="DejaVu Sans" font-size="22" font-weight="700" fill="#FFFFFF">ALL FOOTBALL</text>
    <text x="786" y="173" font-family="DejaVu Sans" font-size="22" font-weight="700" fill="#FFFFFF">THAT MATTERS.</text>`;

  const headlineSvg = headlineLines.map((line, index) => {
    const y = 420 + index * (headlineSize + 6);
    const fill = index === headlineLines.length - 1 && headlineLines.length > 1 ? teamColor : ink;
    return `<text x="43" y="${y}" font-family="DejaVu Sans" font-size="${headlineSize}" font-weight="900" letter-spacing="-3" fill="${fill}">${escapeXml(line)}</text>`;
  }).join('');
  const headlineBottom = 420 + (headlineLines.length - 1) * (headlineSize + 6);
  const subY = headlineBottom + 52;
  const heroY = Math.max(610, subY + 88);
  const heroH = 405;

  const sideBlocks = sideTitles.map((title, index) => {
    const y = heroY + 26 + index * 95;
    return `
      <text x="807" y="${y}" font-family="DejaVu Sans" font-size="20" font-weight="800" fill="#FFFFFF">${escapeXml(title)}</text>
      ${tspans(wrapLines(sideCopies[index] || '', 23, 3), 807, y + 27, 19, 'font-family="DejaVu Sans" font-size="15" fill="#E9EEF5"')}
      ${index < sideTitles.length - 1 ? `<line x1="798" y1="${y + 70}" x2="1038" y2="${y + 70}" stroke="${teamColor}" stroke-width="2" opacity=".9"/>` : ''}`;
  }).join('');

  const svg = `<svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
    <rect width="1080" height="1350" fill="${paper}"/>
    <rect width="1080" height="1350" filter="url(#paper)" opacity=".20"/>
    <rect x="14" y="14" width="1052" height="1322" fill="none" stroke="#171717" stroke-width="2"/>
    ${masthead}

    <rect x="18" y="238" width="1044" height="41" fill="#F8F6F0"/>
    <text x="35" y="266" font-family="DejaVu Sans" font-size="17" font-weight="700" fill="#1B1B1B">${escapeXml(date)}</text>
    <text x="540" y="266" text-anchor="middle" font-family="DejaVu Sans" font-size="15" font-weight="700" letter-spacing="2" fill="#1B1B1B">TRANSFER NEWS  |  MATCHDAY  |  CLUB UPDATES  |  COMMUNITY</text>
    <text x="1042" y="266" text-anchor="end" font-family="DejaVu Sans" font-size="17" font-weight="700" fill="#1B1B1B">ISSUE #${issue}</text>

    <rect x="18" y="286" width="1044" height="74" fill="${teamColorDeep}"/>
    <rect x="18" y="286" width="1044" height="74" fill="${teamColor}" opacity=".23"/>
    <text x="55" y="335" font-family="DejaVu Sans" font-size="44" font-weight="900" fill="#FFFFFF">${escapeXml(teamStripText)}</text>
    <line x1="760" y1="302" x2="760" y2="345" stroke="#FFFFFF" stroke-opacity=".55" stroke-width="2"/>
    <text x="786" y="320" font-family="DejaVu Sans" font-size="16" font-weight="800" fill="#FFFFFF">${escapeXml(leagueText)}</text>
    <text x="786" y="341" font-family="DejaVu Sans" font-size="14" fill="#DCE6F3">RT MEDIA COVERAGE</text>

    ${headlineSvg}
    ${tspans(wrapLines(story.subheadline || '', 74, 2), 43, subY, 26, 'font-family="DejaVu Serif" font-size="22" font-weight="700" fill="#202020"')}
    <line x1="42" y1="${subY + 55}" x2="1038" y2="${subY + 55}" stroke="#202020" stroke-width="2"/>

    <rect x="40" y="${heroY}" width="190" height="${heroH}" fill="#F6F2EA" stroke="#222" stroke-width="2"/>
    <text x="56" y="${heroY + 34}" font-family="DejaVu Serif" font-size="24" font-weight="800" fill="#111">THE STORY</text>
    ${tspans(articleLines.slice(0, 12), 56, heroY + 67, 25, 'font-family="DejaVu Serif" font-size="17" fill="#191919"')}

    <rect x="247" y="${heroY}" width="520" height="${heroH}" fill="#122033" stroke="#202020" stroke-width="2"/>
    <rect x="247" y="${heroY}" width="520" height="${heroH}" fill="url(#heroShade)"/>

    <rect x="782" y="${heroY}" width="266" height="${heroH}" fill="#08111C"/>
    <rect x="782" y="${heroY}" width="266" height="50" fill="${teamColorDeep}"/>
    <text x="915" y="${heroY + 34}" text-anchor="middle" font-family="DejaVu Sans" font-size="24" font-weight="900" fill="#FFFFFF">KEY STORYLINES</text>
    ${sideBlocks}

    <rect x="40" y="${heroY + heroH + 18}" width="1008" height="218" fill="#08111C"/>
    <rect x="40" y="${heroY + heroH + 18}" width="8" height="218" fill="${teamColor}"/>
    <text x="72" y="${heroY + heroH + 62}" font-family="DejaVu Sans" font-size="22" font-weight="800" fill="${teamColor}">${escapeXml(team.outlet.toUpperCase())}</text>
    <text x="72" y="${heroY + heroH + 102}" font-family="DejaVu Sans" font-size="42" font-weight="900" fill="#FFFFFF">${escapeXml(type === 'match' ? 'THE STORY OF THE NIGHT' : 'BUILDING FOR A BIG SEASON')}</text>
    ${tspans(quoteLines, 72, heroY + heroH + 137, 24, 'font-family="DejaVu Serif" font-size="18" font-style="italic" fill="#E9EEF5"')}
    <text x="1022" y="${heroY + heroH + 190}" text-anchor="end" font-family="DejaVu Sans" font-size="14" font-weight="700" letter-spacing="2" fill="#FFFFFF">${escapeXml(footerStory)}</text>

    <rect x="18" y="1300" width="1044" height="36" fill="#07111E"/>
    <text x="540" y="1324" text-anchor="middle" font-family="DejaVu Sans" font-size="14" letter-spacing="4" fill="#FFFFFF">RT MEDIA  •  REAL CLUBS. REAL STORIES. ALL FOOTBALL THAT MATTERS.</text>
  </svg>`;

  const composites = [];
  const heroSource = options.heroBuffer || (options.heroPath && fs.existsSync(options.heroPath) ? fs.readFileSync(options.heroPath) : null);
  return (async () => {
    if (heroSource || graphic) {
      const source = heroSource || await fetchImage(graphic);
      const photo = await sharp(source).rotate().resize(516, heroH - 4, { fit: 'cover', position: 'north' }).modulate({ brightness: 0.96, saturation: 0.9 }).png().toBuffer();
      composites.push({ input: photo, left: 249, top: heroY + 2 });
    }
    if (isCrown) {
      const brandPath = path.join(__dirname, 'assets', 'crownfc-logo-small.b64');
      if (fs.existsSync(brandPath)) {
        try {
          const brandSource = Buffer.from(fs.readFileSync(brandPath, 'utf8').trim(), 'base64');
          const brand = await sharp(brandSource).resize(94, 94, { fit: 'contain', background: { r: 8, g: 17, b: 28, alpha: 1 } }).png().toBuffer();
          composites.push({ input: brand, left: 650, top: 276 });
        } catch (error) {
          console.warn('CrownFC brand asset could not be rendered:', error.message);
        }
      }
    }
    return sharp(Buffer.from(svg)).composite(composites).png({ compressionLevel: 9 }).toBuffer();
  })();
}

const originalJsLoader = Module._extensions['.js'];
let active = true;

Module._extensions['.js'] = function rtMediaNewspaperLoader(module, filename) {
  if (active && path.basename(filename) === 'reporterBot.js') {
    active = false;
    try {
      let source = fs.readFileSync(filename, 'utf8');
      const pattern = /async function newspaperGraphic\(team, type, story, graphic, options = \{\}\) \{[\s\S]*?\n\}\n\nfunction newspaperAttachment/;
      const replacement = newspaperGraphicV2.toString().replace('newspaperGraphicV2', 'newspaperGraphic');
      if (!pattern.test(source)) throw new Error('Could not locate the RT Media newspaper renderer to patch.');
      source = source.replace(pattern, replacement + '\n\nfunction newspaperAttachment');
      module._compile(source, filename);
    } finally {
      Module._extensions['.js'] = originalJsLoader;
    }
    return;
  }
  return originalJsLoader(module, filename);
};
