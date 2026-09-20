# RT Football Media Discord Bot

A Discord sports desk for two FC 27 Pro Clubs teams:

- **Raine at St. Andrew’s** covers Birmingham City in MPL.
- **Teagan Behind the Crown** covers CrownFC in MLPC.

The bot publishes match reports, player signings, and departures as polished Discord news embeds. Upload an OurProClubs or match-stat graphic and the selected reporter reads the visible score and player stats, then turns them into a polished Discord news article. You can add optional context for anything the image does not show.

## Commands

- `/match` — required match graphic plus optional extra context
- `/signing` — player, position, details, and optional graphic
- `/release` — player and farewell details

## Discord setup

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and create an application named **RT Football Media**.
2. Open **Bot**, create the bot, and copy/reset its token.
3. Under **Bot → Privileged Gateway Intents**, enable **Message Content Intent**.
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
- `OPENAI_API_KEY` — optional; produces original AI-written articles
- `OPENAI_MODEL` — optional; defaults to `gpt-5-mini`

An OpenAI key is required for reading match graphics. Signing and release commands still have built-in fallback copy.

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

Post a graphic normally, or let another bot post it. RT Football Media reads image attachments and embedded images, then publishes the reporter post in the same channel. It ignores its own messages to prevent loops. The bot role needs View Channel, Read Message History, Send Messages, and Embed Links in each watched channel.

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
