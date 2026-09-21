# Castle & Crown Collective Bot

**Castle & Crown Collective** (short form **C&C Collective**) is the umbrella organization for Birmingham City in MPL League 1 and CrownFC in MLPC. **RT Football Media** is the official internal media division; it is not the server name.

A Discord sports desk for two FC 27 Pro Clubs teams:

- **Raine at St. Andrew’s** covers Birmingham City in Masters Premier League, League 1.
- **Teagan Behind the Crown** covers CrownFC in MLPC.

The bot publishes match reports, player signings, weekly recaps, Player Spotlights, awards, and departures as dated RT Football Media front pages. Each story receives fresh AI-generated hero artwork, while exact typography and the Eastern-Time publication date are rendered separately. Public posts contain the finished front page without repeating the full article as a long Discord embed.

## Commands

- `/match` — required match graphic plus optional extra context
- `/signing` — player, position, details, and optional graphic
- `/release` — player and farewell details
- `/correct-stats` — preview and approve a match-by-match correction
- `/award-shortlists` — evidence-based suggestions; the owner chooses every winner
- `/award-presentation` — owner-approved 10-second MP4 for a saved winner
- `/archive-media` — preview posts eligible for the copy → verify → delete archive
- `/run-schedules` — check due Eastern-Time jobs with restart-safe duplicate protection

## Discord setup

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and create an application named **RT Football Media**.
2. Open **Bot**, create the bot, and copy/reset its token.
3. Under **Bot → Privileged Gateway Intents**, enable **Message Content Intent** and **Server Members Intent**.
4. Open **OAuth2 → URL Generator**.
5. Select scopes `bot` and `applications.commands`.
6. Select permissions: **View Channels**, **Send Messages**, **Embed Links**, **Attach Files**, and **Read Message History**.
7. Use the generated URL to invite the bot to your server.
8. Turn on Discord Developer Mode, then copy your application ID and server ID.

## Environment variables

Copy `.env.example` to `.env` locally, or add the same values in your hosting service:

- `DISCORD_TOKEN` — bot token; never post this in Discord or commit it
- `DISCORD_CLIENT_ID` — application ID
- `DISCORD_GUILD_ID` — server ID; recommended during setup
- `OPENAI_API_KEY` — required for graphic reading, original writing, and fresh hero artwork
- `OPENAI_MODEL` — optional; defaults to `gpt-5-mini`
- `OPENAI_IMAGE_MODEL` — image model; defaults to `gpt-image-2.5-sunburst`
- `BOT_OWNER_ID` — Zak’s Discord user ID; all selections and approvals are sent here privately
- `TRU_USER_ID` — Tru’s Discord user ID; applies his saved #22 and “because I’m a baller” package without asking him again, while preserving owner approval
- `TRAP_USER_ID` — Trap’s Discord user ID; defaults to `764509653190180874` and displays his real Discord mention beside Coach Gray and Tru on stat-correction notices
- `FOOTBALL_OPS_ROLE_ID` — stable ID for the role titled `Vice President of Football Operations`
- `FC_SEASON` — season label for persistent match-by-match records; defaults to `FC27`
- `NEWS_TIMEZONE` — defaults to `America/New_York`
- `QUOTE_WAIT_HOURS` — defaults to 12 hours, with one reminder
- `RT_DATA_DIR` — persistent state/graphics directory; use `/data` with a Railway volume

The automatic graphic workflow intentionally stops and privately reports an error if AI writing or image generation fails. It never publishes an incomplete fallback story.

All publishing commands are owner-only and private. Every route—including the legacy `/match`, `/signing`, and `/release` commands—creates a DM preview with **Publish**, **Edit**, **Regenerate**, and **Cancel** instead of posting immediately.

Use `/season-calendar action:start` with a unique season name and official start date to begin a fresh team and player statistics period; the planned ending date is optional. Use `/season-calendar action:end` to record the actual Eastern-Time ending date and freeze totals without deleting match-by-match history. The correct reporter creates a private approval preview for either announcement, and the verified season window is printed in future newspaper reports for that club. Matches published while no season is active do not contaminate final totals.

The registration panel collects a player’s EA ID, positions, availability, league-verification information and notes. It sends a private management card with **Approve Birmingham**, **Approve CrownFC**, **Approve Both**, **Trialist** and **Reject** controls. Only the owner or the persisted Vice President of Football Operations role can decide; roster limits and Discord role hierarchy are checked before access is granted.

`/streamline-server` consolidates legacy sections into this top-to-bottom flow: Welcome; Club Info & Community; Management Office; Birmingham City; CrownFC; RT Football Media; The Grounds; active BYOT/External Competitions; Club Archive. Loose generic Standings Table, Team Stats and Player Stats channels are archived because each club has its own league center and combined live statistics board. Managers Only merges into Management Office and Matchday merges into The Grounds without deleting messages.

## Run

```bash
npm install
npm start
```

When `DISCORD_GUILD_ID` is set, commands normally appear in that server quickly. Remove it later if you want global commands available in every server that installs the bot.

## OurProClubs graphics

Use `/match`, select Birmingham City or CrownFC, and upload the OurProClubs image in `graphic`. The bot reads visible results and stats and writes the article in Raine’s or Teagan’s voice. Use `context` only for facts the image cannot show, such as a late comeback or a manager quote.

## Hosting

The process must remain online for the bot to respond. It can run on Railway, Render, Fly.io, a VPS, or a home computer. Add secrets through the host’s environment-variable settings—never place them directly in GitHub.

## Automatic channel watching

The bot automatically watches the existing league channels shown in your Discord layout:

- `mlpc-match-results` → Teagan reports for CrownFC
- `mlpc-signing-announcements` → Teagan posts for CrownFC
- `mpl-match-results` → Raine reports for Birmingham City
- `mpl-signing-announcements` → Raine posts for Birmingham City

Post an OurProClubs text recap, graphic recap, or both, or let another bot post it. Text is treated as the primary source for exact names and scores; the graphic is supporting evidence. RT Football Media caches available graphics and prevents duplicate processing.

Only matches explicitly labeled **Friendly/Friendlies**, **Cup**, or **Tournament** are eligible. Friendlies represent the clubs’ competitive league fixtures in this workflow, and Cup/Tournament games receive equal editorial importance. Playoff and unclassified games are ignored. If a recap contains multiple eligible games, the bot privately sends `BOT_OWNER_ID` a multi-select dropdown. The owner can choose one or several matches for a single article. After selection, the match edition is privately sent with **Publish**, **Edit**, **Regenerate**, and **Cancel** controls before anything appears publicly.

For signings, the owner privately selects a player from the correct club role or chooses **Player not listed** and supplies verified football facts—never the squad number. The player sees all squad numbers 1–99 across four selectors; taken numbers remain visible with the assigned player and `TAKEN`, and selecting one is rejected. The reporter collects the player’s genuine quote and optional photo. If no photo is supplied, the bot generates club-themed artwork without inventing a player likeness. Tru’s configured user ID applies his saved #22 and quote without contacting him again, but still sends the owner a private preview before publication.

Active roster limits are enforced from published squad-number assignments: Birmingham City/MPL allows 18 players and CrownFC/MLPC allows 16. A duplicate signing for an active player is blocked, and an approved release frees the player’s number and roster spot.

Approved match editions save each selected fixture as a separate season record. Supplied appearances, goals, assists, goalkeeper data, cards and MOTM values remain attached to that match. Running totals are calculated from those records so corrections can safely recalculate the season.

Each club’s read-only `stats` channel contains one pinned running board. After an approved recap or `/correct-stats` change, the bot updates team W-D-L, goals for/against, goal difference, clean sheets, recent form, individual appearances/goals/assists/cards/MOTM and goalkeeper saves/goals conceded/clean sheets. The board is visible only to that club’s authorized role and directs players to Coach Gray, Tru, or Trap if a figure looks incorrect.

## Scheduled media operations

The scheduler uses `America/New_York` and persistent run keys so a restart cannot duplicate a completed job:

- Thursday: each reporter selects a player from the correct club role, never repeating a previous selection, and DMs 4–5 rotating questions.
- Friday: one weekly recap draft per club summarizes only verified saved results and statistics.
- Saturday at 10:00 AM Eastern: a Player Spotlight draft uses the saved signing photo only as an identity reference for a fresh scene. If the player did not respond, the cover clearly says so and invents no quote.
- Daily: RT-managed posts at least 30 days old are offered to the owner for approval. The original is deleted only after its archive copy succeeds.

## Private staging suite

Run `/staging-suite` for an owner-only preview. After approval, the bot creates or reuses a hidden `PRIVATE STAGING` category, runs the full 27-point checklist against a separate TEST namespace, posts the private pass/fail report and clears only TEST data. It never sends real player DMs, publishes publicly, changes production squad numbers, deletes production articles or contaminates real statistics.

## MPL Romano Times follower

The Birmingham section includes read-only `romano-times-news` for the MPL Romano Times / Around the League announcement channel `1547269808909979729`. If the bot can access the source announcement channel it creates the follower connection. Otherwise, use Discord’s source-channel **Follow** button once and choose Castle & Crown Collective → `romano-times-news`. Discord then forwards future announcements automatically without the RT bot rewriting them.

Squad numbers are normalized to 1–99 and locked separately for each club after publication. A duplicate is rejected with the name of the player who already owns it. Pending signing drafts also block their selected number, and Tru’s existing number 22 is protected for him on both Birmingham City and CrownFC. Publishing `/release` for a player frees that player's stored number for that club.

Every final publication is rebuilt with the actual publication date in Eastern Time. Regenerating a draft creates new writing and new hero artwork; it does not lock in an old date.

## One-command media setup

After the bot is online and invited with **Manage Channels**, run:

`/setup-server`

It safely creates or reuses:

- `𓊆 📰 𓊇 RT FOOTBALL MEDIA`
- `🔵・raine-reports` for Birmingham City/MPL
- `👑・teagan-reports` for CrownFC/MLPC
- `🗄️・media-archives` for verified 30-day archive copies

Running the command again does not duplicate the category or channels. Automatic posts from MPL source channels are routed to Raine, and MLPC source channels are routed to Teagan. You may remove **Manage Channels** from the bot after setup; retain View Channel, Read Message History, Send Messages, Embed Links, and Attach Files.

## Approval-gated server cleanup audit

Run `/audit-server` to receive a private report covering empty categories, inactive text channels, uncategorized channels, duplicate channel names, role cleanup candidates, and roles with Administrator permission.

The audit makes no changes by itself. It provides **Approve Safe Cleanup** and **Cancel** buttons. Approval is tied to the person who ran the command, expires after 15 minutes, and deletes only categories that are still empty at approval time. It never automatically deletes channels, messages, or roles.

## Genuine player comments

Signing posts use genuine supplied comments only. You may provide a club-leadership comment in the facts form or the caption accompanying the graphic:

```text
Player: Tru
Player Comment: I want to earn my place and help the group compete every match.
Club Comment: His composure and willingness to do the work fit the standards we are building.
```

The bot never invents or simulates a quote. Missing comments are shown as no-comment notes.

## Railway persistence

Pending selections, quote requests, approvals, cached source graphics, statistics, schedules, spotlights, archive metadata, awards, and duplicate-message records survive restarts. Add a Railway persistent volume mounted at `/data` and set `RT_DATA_DIR=/data`; Railway deployments also default to `/data`. `nixpacks.toml` installs FFmpeg and Fontconfig for award videos and reliable newspaper typography.

The exact owner-supplied CrownFC identity artwork is stored in `assets/crownfc-brand.jpg` with its production crest crop in `assets/crownfc-crest.png`. CrownFC media uses Carolina/cyan blue, deep navy, royal blue, white and silver—never gold.

## Targeted role alerts

Reporter posts can notify only the relevant club role instead of using `@everyone`. Add `BIRMINGHAM_ROLE_ID` and `MLPC_ROLE_ID` in Railway. Raine’s posts mention only the Birmingham role; Teagan’s posts mention only the MLPC role. The role must be mentionable, or the bot must have permission to mention roles.
The approved setup gives only the RT bot permission to mention non-mentionable club roles inside the controlled club/media channels, so players cannot use those roles themselves.
