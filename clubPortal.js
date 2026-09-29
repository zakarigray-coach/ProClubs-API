const crypto = require('node:crypto');
const path = require('node:path');
const express = require('express');

const CLUBS = Object.freeze({
  birmingham: {
    name: 'Birmingham City', league: 'MPL LEAGUE 1',
    roleEnv: 'BIRMINGHAM_ROLE_ID', hero: '/club-assets/birmingham-hero.webp',
    crest: '/club-assets/birmingham-crest.png', capacity: 18,
    story: 'Pride. People. Progress. A new chapter for the Blues in MPL League 1.',
    practice: 'Tuesday & Thursday · 10:00 / 10:30 PM ET',
  },
  crownfc: {
    name: 'CrownFC', league: 'MLPC',
    roleEnv: 'MLPC_ROLE_ID', hero: '/club-assets/crownfc-brand.jpg',
    crest: '/club-assets/crownfc-crest.png', capacity: 16,
    story: 'Behind the Crown. Built together, ready for the next challenge.',
    practice: 'Monday & Wednesday · 8:00 / 8:30 PM ET',
  },
});

const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const base64url = value => Buffer.from(value).toString('base64url');
const seconds = () => Math.floor(Date.now() / 1000);

function sign(value, secret) {
  return crypto.createHmac('sha256', secret).update(value).digest('base64url');
}
function encodeToken(value, secret) {
  const body = base64url(JSON.stringify(value));
  return body + '.' + sign(body, secret);
}
function decodeToken(token, secret) {
  if (!token || typeof token !== 'string') return null;
  const [body, signature, extra] = token.split('.');
  if (!body || !signature || extra) return null;
  const expected = sign(body, secret);
  const a = Buffer.from(signature);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  try {
    const parsed = JSON.parse(Buffer.from(body, 'base64url').toString('utf8'));
    return Number.isSafeInteger(parsed.exp) && parsed.exp > seconds() ? parsed : null;
  } catch { return null; }
}
function cookies(req) {
  return Object.fromEntries(String(req.headers.cookie || '').split(';').map(part => {
    const at = part.indexOf('=');
    return at < 0 ? [] : [part.slice(0, at).trim(), part.slice(at + 1).trim()];
  }).filter(pair => pair.length === 2));
}
function cookieOptions(maxAge) {
  return { httpOnly: true, secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax', path: '/', maxAge };
}
function safeReturnTo(value) {
  return /^\/(?:birmingham|crownfc)(?:\/members)?$/.test(value || '') ? value : '/clubs';
}
function sessionSecret() {
  // The bot token is already a protected server secret. A dedicated secret is preferred.
  return process.env.CLUB_SITE_SESSION_SECRET || process.env.DISCORD_TOKEN || '';
}
function loginReady() {
  return Boolean(process.env.DISCORD_CLIENT_ID && process.env.DISCORD_CLIENT_SECRET &&
    process.env.DISCORD_GUILD_ID && process.env.CLUB_SITE_BASE_URL && sessionSecret());
}
function layout(title, content, clubKey = '') {
  const club = CLUBS[clubKey];
  const theme = clubKey === 'crownfc' ? 'crown' : clubKey === 'birmingham' ? 'blues' : 'collective';
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="${theme === 'blues' ? '#0057ff' : '#071729'}">
<meta name="description" content="${escapeHtml(club?.story || 'Birmingham City and CrownFC · Castle & Crown Collective')}">
<title>${escapeHtml(title)} · Castle & Crown Collective</title>
<link rel="icon" href="/club-assets/crown-crest.png"><link rel="stylesheet" href="/club-assets/site.css">
</head><body class="${theme}"><a class="skip" href="#main">Skip to content</a>
<header class="topbar"><a class="collective-mark" href="/clubs">C<span>&</span>C <small>COLLECTIVE</small></a>
<nav aria-label="Club websites"><a href="/birmingham" ${clubKey === 'birmingham' ? 'aria-current="page"' : ''}>Birmingham City</a><a href="/crownfc" ${clubKey === 'crownfc' ? 'aria-current="page"' : ''}>CrownFC</a><a href="/clubs">My clubs</a></nav></header>
<main id="main">${content}</main><footer><span>CASTLE & CROWN COLLECTIVE</span><span>One server · two clubs · your place on the roster</span></footer>
</body></html>`;
}
function sendHtml(res, title, content, clubKey, status = 200) {
  res.status(status).type('html').send(layout(title, content, clubKey));
}
function loginLink(next, label = 'Sign in with Discord') {
  return `<a class="button" href="/auth/discord?next=${encodeURIComponent(next)}">${escapeHtml(label)}</a>`;
}

async function membership(getClient, userId) {
  const client = getClient();
  if (!client?.isReady?.()) throw new Error('The Discord connection is not ready.');
  const guild = await client.guilds.fetch(process.env.DISCORD_GUILD_ID);
  const member = await guild.members.fetch({ user: userId, force: true });
  const owner = userId === process.env.BOT_OWNER_ID;
  const allowed = Object.fromEntries(Object.entries(CLUBS).map(([key, club]) =>
    [key, owner || Boolean(process.env[club.roleEnv] && member.roles.cache.has(process.env[club.roleEnv]))]));
  return { guild, member, allowed, owner };
}
async function roster(guild, key) {
  const roleId = process.env[CLUBS[key].roleEnv];
  if (!roleId) return [];
  // GuildMembers intent is already used by the existing bot. Read the live approved role.
  const members = await guild.members.fetch();
  return [...members.values()].filter(member => !member.user.bot && member.roles.cache.has(roleId))
    .sort((a, b) => a.displayName.localeCompare(b.displayName))
    .map(member => ({ name: member.displayName, avatar: member.displayAvatarURL({ size: 96 }) }));
}

function mountClubPortal(app, { getClient }) {
  app.use('/club-assets', express.static(path.join(__dirname, 'club-site-assets'), {
    maxAge: '1h',
  }));
  app.use('/club-assets', express.static(path.join(__dirname, 'assets'), {
    maxAge: '1h', fallthrough: false,
  }));

  app.get('/clubs', (req, res) => {
    const session = decodeToken(cookies(req).cc_session, sessionSecret());
    const cards = Object.entries(CLUBS).map(([key, club]) =>
      `<a class="club-choice ${key}" href="/${key}"><img src="${club.crest}" alt="" />
      <span><small>${club.league}</small><strong>${club.name}</strong><em>Open club website</em></span></a>`).join('');
    sendHtml(res, 'Choose your club', `<section class="chooser"><p class="eyebrow">CASTLE & CROWN COLLECTIVE</p>
      <h1>One home. Two clubs.</h1><p>Choose a club to explore. Your Discord roster decides which member area you can enter.</p>
      <div class="choice-grid">${cards}</div><div class="chooser-signin">${session ?
      '<a class="button" href="/my-clubs">View my roster access</a>' : loginLink('/clubs')}</div></section>`);
  });
  app.get('/', (req, res) => res.redirect(302, '/clubs'));

  for (const [key, club] of Object.entries(CLUBS)) {
    app.get('/' + key, (req, res) => {
      sendHtml(res, club.name, `<section class="club-hero" style="--hero:url('${club.hero}')">
        <div class="hero-shade"></div><div class="hero-content"><div class="hero-brand"><img src="${club.crest}" alt="${club.name} crest"><span>${club.league}<small>2026 / 27</small></span></div>
        <p class="eyebrow">${key === 'birmingham' ? 'THE BLUES' : 'BEHIND THE CROWN'}</p>
        <h1>${club.name}</h1><p class="hero-story">${club.story}</p>
        <div class="hero-actions">${loginLink('/' + key + '/members', 'Enter member area')}<a class="ghost-button" href="/clubs">Explore both clubs</a></div></div></section>
        <section class="club-facts"><div><small>COMPETITION</small><strong>${club.league}</strong></div>
        <div><small>TRAINING</small><strong>${club.practice}</strong></div>
        <div><small>ROSTER LIMIT</small><strong>${club.capacity} players</strong></div></section>
        <section class="club-intro"><p class="eyebrow">THE CLUB</p><h2>${key === 'birmingham' ? 'Pride. People. Progress.' : 'Built behind the Crown.'}</h2>
        <p>${key === 'birmingham' ?
          'We represent Birmingham City with purpose in MPL League 1. Every player earns their place through commitment, communication and the work we put in together.' :
          'CrownFC competes in MLPC with its own squad, schedule and identity. The badge belongs to the people who show up for each other.'}</p></section>`, key);
    });
    app.get('/' + key + '/members', async (req, res) => {
      const session = decodeToken(cookies(req).cc_session, sessionSecret());
      if (!session?.id) return res.redirect(302, '/auth/discord?next=/' + key + '/members');
      try {
        const access = await membership(getClient, session.id);
        if (!access.allowed[key]) {
          return sendHtml(res, 'Roster access', `<section class="member-state"><p class="eyebrow">${club.name}</p><h1>This club is not on your roster yet.</h1>
          <p>Your manager needs to approve your ${club.name} Discord role. Choosing a club here cannot add you to the roster.</p>
          <a class="button" href="/my-clubs">See my clubs</a></section>`, key, 403);
        }
        let players;
        try { players = await roster(access.guild, key); }
        catch { players = null; }
        const list = players === null ? '<p>Roster is temporarily unavailable. Please check back shortly.</p>' :
          players.length ? `<ul class="roster">${players.map(player =>
            `<li><img src="${escapeHtml(player.avatar)}" alt=""><span>${escapeHtml(player.name)}</span></li>`).join('')}</ul>` :
          '<p>No approved player roles are showing yet.</p>';
        sendHtml(res, club.name + ' members', `<section class="member-head"><div><p class="eyebrow">MEMBER AREA · ${club.league}</p>
        <h1>${club.name}</h1><p>Signed in as ${escapeHtml(access.member.displayName)}. Your club access is checked against Discord each time.</p></div>
        <a class="quiet-link" href="/my-clubs">Switch club</a></section><section class="member-grid">
        <article class="panel"><small>TRAINING TIMES</small><h2>${club.practice}</h2><p>Times shown in Eastern Time.</p></article>
        <article class="panel"><small>YOUR STATUS</small><h2>Approved roster access</h2><p>Only members with this club's approved Discord role can view this page.</p></article></section>
        <section class="roster-section"><div class="section-heading"><p class="eyebrow">2026 / 27</p><h2>Club roster</h2></div>${list}</section>`, key);
      } catch (error) {
        if (error.code === 10007 || error.status === 404) {
          res.clearCookie('cc_session', cookieOptions(0));
          return sendHtml(res, 'Server access', `<section class="member-state"><h1>Join the Castle & Crown server first.</h1>
          <p>Your Discord account must be in our server and approved for this club.</p><a class="button" href="/clubs">Back to clubs</a></section>`, key, 403);
        }
        console.error('Club portal membership check failed:', error);
        sendHtml(res, 'Temporarily unavailable', `<section class="member-state"><h1>We cannot verify your roster right now.</h1>
        <p>Please try again shortly. Your access has not been changed.</p></section>`, key, 503);
      }
    });
  }

  app.get('/my-clubs', async (req, res) => {
    const session = decodeToken(cookies(req).cc_session, sessionSecret());
    if (!session?.id) return res.redirect(302, '/auth/discord?next=/clubs');
    try {
      const access = await membership(getClient, session.id);
      const entries = Object.entries(CLUBS).filter(([key]) => access.allowed[key]);
      const content = entries.length ? entries.map(([key, club]) =>
        `<a class="club-choice ${key}" href="/${key}/members"><img src="${club.crest}" alt=""><span>
        <small>${club.league}</small><strong>${club.name}</strong><em>Enter member area</em></span></a>`).join('') :
        '<p>No club roster has been approved for your Discord account yet. Ask management to confirm your club role.</p>';
      sendHtml(res, 'My clubs', `<section class="chooser"><p class="eyebrow">YOUR ROSTER ACCESS</p><h1>Welcome, ${escapeHtml(access.member.displayName)}.</h1>
      <p>These are the clubs your Discord account can enter.</p><div class="choice-grid">${content}</div>
      <a class="quiet-link" href="/auth/logout">Sign out</a></section>`);
    } catch (error) {
      console.error('Club portal access check failed:', error);
      sendHtml(res, 'Temporarily unavailable', '<section class="member-state"><h1>We cannot verify your clubs right now.</h1><p>Please try again shortly.</p></section>', '', 503);
    }
  });

  app.get('/auth/discord', (req, res) => {
    if (!loginReady()) return sendHtml(res, 'Sign-in setup', `<section class="member-state"><h1>Discord sign-in is being connected.</h1>
      <p>The club websites are ready. Member sign-in will open after the Discord app owner finishes its connection settings.</p>
      <a class="button" href="/clubs">Explore club pages</a></section>`, '', 503);
    const next = safeReturnTo(req.query.next);
    const state = crypto.randomBytes(24).toString('base64url');
    res.cookie('cc_oauth', encodeToken({ state, next, exp: seconds() + 600 }, sessionSecret()), cookieOptions(600000));
    const params = new URLSearchParams({ client_id: process.env.DISCORD_CLIENT_ID,
      redirect_uri: process.env.CLUB_SITE_BASE_URL.replace(/\/$/, '') + '/auth/discord/callback',
      response_type: 'code', scope: 'identify', state });
    res.redirect(302, 'https://discord.com/oauth2/authorize?' + params);
  });
  app.get('/auth/discord/callback', async (req, res) => {
    const state = decodeToken(cookies(req).cc_oauth, sessionSecret());
    res.clearCookie('cc_oauth', cookieOptions(0));
    if (!state || !req.query.code || req.query.state !== state.state) {
      return sendHtml(res, 'Sign-in failed', '<section class="member-state"><h1>Sign-in expired.</h1><p>Please start again from your club page.</p><a class="button" href="/clubs">Choose club</a></section>', '', 400);
    }
    try {
      const callback = process.env.CLUB_SITE_BASE_URL.replace(/\/$/, '') + '/auth/discord/callback';
      const response = await fetch('https://discord.com/api/v10/oauth2/token', {
        method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ client_id: process.env.DISCORD_CLIENT_ID,
          client_secret: process.env.DISCORD_CLIENT_SECRET, grant_type: 'authorization_code',
          code: String(req.query.code), redirect_uri: callback }),
      });
      if (!response.ok) throw new Error('Discord token exchange returned ' + response.status);
      const token = await response.json();
      const identityResponse = await fetch('https://discord.com/api/v10/users/@me', {
        headers: { Authorization: 'Bearer ' + token.access_token },
      });
      if (!identityResponse.ok) throw new Error('Discord identity returned ' + identityResponse.status);
      const identity = await identityResponse.json();
      if (!/^\d{16,22}$/.test(identity.id)) throw new Error('Invalid Discord identity');
      res.cookie('cc_session', encodeToken({ id: identity.id, exp: seconds() + 8 * 3600 },
        sessionSecret()), cookieOptions(8 * 3600000));
      return res.redirect(302, safeReturnTo(state.next));
    } catch (error) {
      console.error('Club portal sign-in failed:', error);
      sendHtml(res, 'Sign-in failed', '<section class="member-state"><h1>Discord sign-in did not finish.</h1><p>Please try again later.</p><a class="button" href="/clubs">Choose club</a></section>', '', 502);
    }
  });
  app.get('/auth/logout', (req, res) => {
    res.clearCookie('cc_session', cookieOptions(0));
    res.redirect(302, '/clubs');
  });
}

module.exports = { mountClubPortal, CLUBS, decodeToken, encodeToken, safeReturnTo };
