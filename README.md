# Pep + RT Football Media

Two Discord bots for Birmingham City (MPL), run as one service with one database.

- **Pep, Birmingham Tactical Coach** is the football brain. It reads the stats and screenshots Coach sends, gives tactical advice, and recommends Player of the Week. It never publishes.
- **RT Football Media** is the newsroom. It turns an approved week into a cover image and article, shows Coach a private draft, and publishes once after he approves. It makes no football decisions.

Nothing is published without Coach's approval, and AI runs only when Coach asks for something.

## Weekly flow

1. Coach DMs Pep `weekly recap` (or sends the PCT+ `.xlsx` export, recap text or screenshots) once the four league matches are played.
2. Pep shows the results it read and recommends Player of the Week, with a runner-up when the stats support one.
3. Coach corrects anything, optionally picks a different player or attaches a photo, then taps **Approve & Send to RT Media**.
4. RT Football Media DMs the private draft: cover image, article text, and controls.
5. Coach taps **Approve Draft**, then **Publish to RT Football Media**. The article goes up as its own post in the `rt-football-media` forum. A report can only be published once.

Cup and tournament matches never mix into the league recap. Start a cup edition with `/cupreport`.

## Live-match help

DM Pep a question, with up to four screenshots if useful. Pep answers in five parts: problem detected, immediate adjustment, formation or role change, passing sequence, what to watch next.

- Save the usual formation with `/tactic`; Pep uses the most recent one unless the message names a different one.
- A text message ending in `?` is always treated as a coaching question, even while a recap is open.
- Video clips are not read yet. Send a screenshot.

## Commands

All commands are for Coach or the configured management roles.

| Command | Purpose |
| --- | --- |
| `/tacticaladvice` | Ask a tactical question or paste match analysis |
| `/tactic` | Save the squad's formation and instructions |
| `/weeklyreport` | Choose the matches for a league recap |
| `/cupreport` | Start or reopen a cup or tournament edition |
| `/reportphoto` | Attach a player photo to a draft |
| `/matches`, `/match`, `/reviewmatches` | List, inspect and classify saved matches |
| `/matchdetails`, `/matchstat` | Correct a score or add a verified statistic |
| `/officialrecord`, `/development` | League record and team trends |
| `/status` | Check the bot is online |
| `/notebook`, `/backup` | Download the records as CSV, or a database backup |

## Settings

Set these as Railway variables. Never put a token or key in GitHub or Discord. `.env.example` lists them all.

| Variable | Purpose |
| --- | --- |
| `GAFFER_DISCORD_TOKEN` | Pep's bot token |
| `RT_MEDIA_DISCORD_TOKEN` | RT Football Media's bot token. Without it, Pep delivers drafts itself and publishing is off |
| `RT_MEDIA_PUBLISH_CHANNEL_ID` | Channel the approved article is posted to. A forum channel gets one post per article, titled with the headline; a text channel gets plain messages |
| `OWNER_DISCORD_USER_ID` | Coach's Discord user ID |
| `GAFFER_GUILD_ID` | The club server ID |
| `GAFFER_MANAGEMENT_ROLE_IDS` | Optional comma-separated role IDs allowed to use the commands |
| `GAFFER_DATABASE_PATH` | SQLite file, `/data/gaffergpt.db` on Railway |
| `PEP_COACH_API_KEY` | OpenAI API key |
| `PEP_AI_MODEL` | Model for every AI job. Default `gpt-6-luna` |
| `PEP_AI_EFFORT` | Reasoning effort for every AI job: `low`, `medium`, `high`, `xhigh` or `max`. Default `max` |
| `PEP_AI_MAX_OUTPUT_TOKENS` | Allowance for thinking plus the answer. Default `32000` |
| `PEP_AI_TIMEOUT_SECONDS` | Longest wait for one AI request. Default `300` |

One job can use a different model or effort: set `PEP_COACH_MODEL` / `PEP_COACH_EFFORT` (live advice), `PEP_RECAP_MODEL` / `PEP_RECAP_EFFORT` (reading submitted results) or `PEP_REPORTER_MODEL` / `PEP_REPORTER_EFFORT` (article writing). For example, `PEP_COACH_EFFORT=medium` makes mid-match replies faster.

## Run and test

```bash
pip install -r gaffergpt/requirements.txt
python -m unittest discover -s gaffergpt/tests -q
python -m gaffergpt.bot
```

GitHub runs the tests on every push that touches `gaffergpt/`.

## Hosting

One Railway service, built from `gaffergpt/Dockerfile` with root directory `/gaffergpt`, one replica, and a persistent volume mounted at `/data`. Every push to the deployed branch goes live, so try changes on another branch first.

## Data and backups

All matches, statistics, reports and settings live in one SQLite file on the `/data` volume. Pep saves a checked daily copy under `/data/backups` and keeps seven. Those copies are on the same volume, so use `/backup` now and then and keep the download somewhere else.

To restore: stop the service, copy a backup over `/data/gaffergpt.db`, start the service.

## Code map

Everything is in `gaffergpt/`.

| Area | Files |
| --- | --- |
| Pep: Discord commands, DMs and controls | `bot.py` |
| Pep: tactical advice | `coaching_ai.py`, `tactical_coach.py`, `analysis.py` |
| Pep: reading results and stats | `recap_intake.py`, `excel_intake.py`, `excel_stats.py`, `weekly_intake.py`, `parser.py` |
| RT Media: Discord identity and publishing | `rt_media.py`, `publisher.py` |
| RT Media: article writing and fact-checking | `reporter.py`, `article_writer.py`, `editorial.py`, `report_verification.py`, `report_audit.py`, `article_facts.py` |
| RT Media: cover and cup edition | `article_layout.py`, `cup_cover.py`, `recap_output.py`, `competitions.py`, `cup_verification.py` |
| Cup forum, event and availability | `cup_setup.py` |
| Shared | `database.py`, `config.py`, `ai_settings.py`, `notebook.py`, `scheduler.py` |

## Not built yet

- Lineup and position recommendations from a saved roster. Pep will suggest them only from information Coach types in.
- Heat-map analysis from video clips.
- Twitch live alerts into the match center.

`AGENTS.md` holds the rules to keep when adding any of these.
