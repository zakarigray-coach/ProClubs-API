# RT Football Media Discord Bot

A Discord sports desk for two FC 27 Pro Clubs teams:

- **Raine at St. Andrew’s** covers Birmingham City in Masters Premier League, League 1.
- **Teagan Behind the Crown** covers CrownFC in MLPC.

The bot publishes match reports, player signings, and departures as dated RT Football News front pages. Each story receives fresh AI-generated hero artwork, while the newspaper text and exact Eastern-Time publication date are rendered separately for accuracy. Public posts contain the finished newspaper cover (plus the configured role ping) without repeating the full article in a Discord embed.

## Commands

- `/match` — required match graphic plus optional extra context
- `/signing` — player, position, details, and optional graphic
- `/release` — player and farewell details

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
- `TRU_USER_ID` — Tru’s Discord user ID; applies “Because I’m a baller.” and bypasses the quote wait
- `NEWS_TIMEZONE` — defaults to `America/New_York`
- `QUOTE_WAIT_HOURS` — defaults to 12 hours, with one reminder
- `RT_DATA_DIR` — persistent state/graphics directory; use `/data` with a Railway volume

The automatic graphic workflow intentionally stops and privately reports an error if AI writing or image generation fails. It never publishes an incomplete fallback story.

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

For signings, the owner privately selects a player from the correct club role or chooses **Player not listed**, supplies verified facts, and then the correct reporter requests a genuine quote by DM. The player can submit a quote or decline. A 12-hour timeout sends the owner options to continue without a quote, enter one manually, or cancel. Tru’s configured user ID uses his saved quote and publishes without waiting.

Every final publication is rebuilt with the actual publication date in Eastern Time. Regenerating a draft creates new writing and new hero artwork; it does not lock in an old date.

## One-command media setup

After the bot is online and invited with **Manage Channels**, run:

`/setup-server`

It safely creates or reuses:

- `𓊆 📰 𓊇 RT FOOTBALL MEDIA`
- `🔵・raine-reports` for Birmingham City/MPL
- `👑・teagan-reports` for CrownFC/MLPC

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

Pending selections, quote requests, approvals, cached source graphics, and duplicate-message records must survive restarts. Add a Railway persistent volume mounted at `/data`, then set `RT_DATA_DIR=/data`. Without a volume, state survives a normal process restart only while the local filesystem remains available; a redeploy may erase it.

## Targeted role alerts

Reporter posts can notify only the relevant club role instead of using `@everyone`. Add `BIRMINGHAM_ROLE_ID` and `MLPC_ROLE_ID` in Railway. Raine’s posts mention only the Birmingham role; Teagan’s posts mention only the MLPC role. The role must be mentionable, or the bot must have permission to mention roles.
