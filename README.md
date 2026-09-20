# RT Football Media Discord Bot

A Discord sports desk for two FC 27 Pro Clubs teams:

- **Raine at St. Andrew’s** covers Birmingham City in MPL.
- **Teagan Behind the Crown** covers CrownFC in MLPC.

The bot publishes match reports, player signings, and departures as polished Discord news embeds. An uploaded OurProClubs/result image can be attached to a match report. The image supplies the visual; enter the verified score and stats in the command so the reporter never guesses details from a graphic.

## Commands

- `/match` — score, opponent, match details, and optional graphic
- `/signing` — player, position, details, and optional graphic
- `/release` — player and farewell details

## Discord setup

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and create an application named **RT Football Media**.
2. Open **Bot**, create the bot, and copy/reset its token.
3. Open **OAuth2 → URL Generator**.
4. Select scopes `bot` and `applications.commands`.
5. Select permissions: **View Channels**, **Send Messages**, **Embed Links**, **Attach Files**, and **Read Message History**.
6. Use the generated URL to invite the bot to your server.
7. Turn on Discord Developer Mode, then copy your application ID and server ID.

## Environment variables

Copy `.env.example` to `.env` locally, or add the same values in your hosting service:

- `DISCORD_TOKEN` — bot token; never post this in Discord or commit it
- `DISCORD_CLIENT_ID` — application ID
- `DISCORD_GUILD_ID` — server ID; recommended during setup
- `OPENAI_API_KEY` — optional; produces original AI-written articles
- `OPENAI_MODEL` — optional; defaults to `gpt-5-mini`

Without an OpenAI key, all commands still work using built-in sports copy.

## Run

```bash
npm install
npm start
```

When `DISCORD_GUILD_ID` is set, commands normally appear in that server quickly. Remove it later if you want global commands available in every server that installs the bot.

## OurProClubs graphics

Use `/match`, enter the verified result and match details, then upload the OurProClubs result image in the `graphic` field. The bot adds it to the published recap.

## Hosting

The process must remain online for the bot to respond. It can run on Railway, Render, Fly.io, a VPS, or a home computer. Add secrets through the host’s environment-variable settings—never place them directly in GitHub.
