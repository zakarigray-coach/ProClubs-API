# Pep — Birmingham Tactical Coach

Gaffer is Birmingham City's assistant coach. Reporter is the writing service.
Both use the same `GAFFER_DATABASE_PATH` SQLite file. No API key is needed for
the initial factual reports.

## What is ready

- Player registration and named tactics.
- Text recap import from one explicitly configured OurProClubs bot/channel.
- Each game is a separate record, including multiple scorelines in one message.
- Unknown queue; management classification and correction controls.
- Flexible team/player metrics, official record and measured comparisons.
- Paged match selection, separate official/practice menus and development toggle.
- Private article drafts and approval that saves only, never publishes.
- Friday 08:00 America/New_York scheduler with persisted jobs, leases, retries,
  restart catch-up, skip and one-hour reminder controls.
- A one-minute private live scheduler test; production schedule defaults OFF.

## Existing project preservation

The root JavaScript RT Football Media bot remains unchanged. Its JSON history,
publication system, server tools and current Railway deployment are preserved.
This Python package adds Gaffer and a new factual Reporter foundation; it does
not yet connect the legacy JavaScript journalist to SQLite or migrate its old
records. Do not copy the live RT Discord token into Gaffer: two clients using
one application would conflict, including their `/match` commands.

The new Gaffer/Reporter feature set has ONE central database, not one database
per feature. Keep Reporter in the same process/storage boundary for now.
A separate Railway service cannot simply mount another service's SQLite volume.
If the legacy journalist is connected later, use a controlled service boundary
or a deliberately planned shared-database migration.

## Run and test

From the repository root:

```bash
pip install -r gaffergpt/requirements.txt
python -m unittest discover -s gaffergpt/tests -v
python -m gaffergpt.init_db
python -m gaffergpt.bot
```

Environment settings are listed in `.env.example`. Settings are read from the
process environment; this package does not automatically load `.env` files.
The default database path is the repository's existing `gaffergpt.db`, preserving
the original Phase 1 players/tactics. Railway must set a persistent `/data` path.
Initialization creates missing tables and records migration version 1 without
wiping tables. Future structural changes should use numbered migrations, not
rewrite the production file. Back up the SQLite file before future migrations.

## Deploy safely on Railway

Use a **new GafferGPT service** in the existing Railway project. Do not replace
`proclubs-custom-api` or `club-websites-preview`.

- Repository: `zakarigray-coach/ProClubs-API`, branch `feat/gaffergpt-foundation`.
- Root directory: `/gaffergpt`; build using the supplied Dockerfile.
- Single replica. Attach a persistent volume at `/data`.
- `GAFFER_DATABASE_PATH=/data/gaffergpt.db`.
- Set `GAFFER_DISCORD_TOKEN`, `OWNER_DISCORD_USER_ID`, `GAFFER_GUILD_ID`.
- Optional management role IDs in `GAFFER_MANAGEMENT_ROLE_IDS` (comma-separated).
- Keep `PEP_FRIDAY_RECAP=false` initially.

Create a separate Discord application named GafferGPT, enable **Message Content
Intent**, and invite it with `bot` and `applications.commands`. Give it View
Channels, Read Message History, Send Messages and Attach Files where needed.
The owner must permit DMs from the bot/server. Administrator is unnecessary.

Once connected, use `/configurepep` to choose the recap channel and actual
OurProClubs bot. Then run `/testweeklydm`: a persisted job should send a DM
within 60–90 seconds. Verify its menus, restart behavior and private delivery
before setting `PEP_FRIDAY_RECAP=true`.

A token is never printed, committed, or hardcoded. Add it through Railway's
secret/environment editor, never into a PR, Discord message or chat transcript.

## Commands

- `/status`: connectivity and review queue count.
- `/configurepep`: owner chooses one recap channel and source bot.
- `/matches`: recent entries.
- `/reviewmatches`: next ten Unknown entries.
- `/match match_id`: details and classification correction.
- `/matchdetails`: management supplies verified opponent, scores and competition.
- `/matchstat`: management supplies one verified metric; use consistent subject
  names, metric names and units when comparing matches.
- `/officialrecord`: classified official games with known scores only.
- `/tactic`: save/update a named tactic.
- `/weeklyreport`: current week or custom YYYY-MM-DD start/end (end exclusive).
- `/testweeklydm`: one-minute owner-only delivery test.

Players can write: `Pep, register me as a Striker with Advanced Forward role`.
They can append `with Attack focus`. This is a small language pattern, not an
unrestricted AI conversation engine. Role/focus names are stored as supplied;
no unverified FC 27 role list is hardcoded.

## How match handling works

Every nonempty text message from the configured source bot in the chosen
channel is stored as an Unknown recap. The initial parser confidently extracts
plain scorelines such as `Birmingham City 3–1 Chelsea` or the reverse order, and
explicit `Opponent:`, `Birmingham score:` and `Opponent score:` fields.
Unsupported/partial formats retain raw text and null unknown values for review.
Send a real OurProClubs recap sample before expanding automatic extraction.
Statistics currently come from verified management input; the foundation does
not invent or guess them from unsupported text.

Source message/channel/guild plus scoreline index prevent duplicate imports.
Opponent, date and score are never deduplication keys. Offline recovery reads
messages after the stored channel cursor. Initial channel configuration starts
with future messages rather than importing unrelated historical messages.
Message edits are not automatically reparsed; management can correct facts.
A single unsupported message containing several games must be manually reviewed;
the parser needs real examples to split that format confidently.

`played_at` initially uses the Discord message timestamp and `date_source` is
`message`; it is not represented as a verified kickoff time. Date parsing and a
match-date correction control are follow-up work for real-source validation.
Unknown and Ignored records are never report-eligible. Practice records are
report-eligible but never official. Corrections invalidate affected article drafts.

## Reporting and Friday timing

The default reporting week is Monday 00:00 to the next Monday 00:00 Eastern,
end exclusive. Friday's menu contains eligible records stored by delivery time;
late Friday/weekend matches can be added with `/weeklyreport` in that same week.
Drafts count only selected official games, not every stored match.

Selections persist across pages and restarts. Unknown matches block confirmation
until reviewed. Generate Report is explicit confirmation; it creates a factual
private text draft. Approve Draft saves approval and publishes nothing. Player of
the Week, quotes, injuries and Looking Ahead are omitted when evidence is absent.
Comparisons use selected matches against the same opponent and the same metric,
subject and unit; descriptive changes are not claimed as proof of tactical cause.

The first installed week seeds jobs from that Monday forward. Missed prompts
for weeks after installation are delivered after restart, including multiple
missed weeks. Weeks before first installation are not retrospectively spammed.
A completed/Skipped week stays completed/Skipped. Reminder jobs reuse the same
report; they never create a second weekly report.

Delivery uses a database lease and a unique marker in the DM footer. If Discord
accepted a message before the process crashed, restart recovery searches DM
history for that marker instead of sending it again. If history access fails,
the bot retries rather than blindly sending. Exactly-once network delivery
cannot be mathematically guaranteed if Discord history is deleted or unavailable;
this design prevents ordinary retries/restarts from duplicating messages.

## Known live checks still required

Automated tests use a temporary database and simulated Discord delivery. Real
Discord login, command synchronization, OurProClubs source access, real sample
parsing, private DMs, a Railway build, and volume restart persistence require the
new application's token and owner/server IDs. No live deployment or real Friday
schedule is claimed until those checks succeed.

The legacy RT bot has its own Friday scheduler and recap listener. After Gaffer
is live and verified, explicitly transfer Birmingham recap ownership so both
bots do not prompt Coach for the same workflow. CrownFC and other media features
must remain untouched. Twitch/Zapier is outside this implementation.

## Player linking

Players run `/linkplayer player_name:ExactName` in the club server, then `/myplayer` to check their link. Names are self-reported, not proof of ownership. Each stats name can link to only one Discord account; case and extra spaces do not create duplicate identities. `/unlinkplayer` removes only the link, never match data. Management uses `/setplayerlink member:@Player player_name:ExactName` to correct links, or leaves the name empty to remove one. Remove an incorrect existing claim before assigning that name to the right player. These commands grant no Discord roles.

Links live in the same persistent SQLite database as matches and reports, separately from position/role registration, so linking does not overwrite player preferences. Migration 2 adds the link table safely to existing databases. Stats ingestion and personalized feedback are separate follow-up features; linking alone does not parse new stats.

## Player stats and private feedback

`/myfeedback` gives a linked player measured feedback from their latest ten classified matches in each category, separating Official and Practice. Unknown/Ignored matches never contribute. Missing values are excluded, not zero-filled. The feedback is a factual training guide, not an AI diagnosis or a player ranking.

Supported text sample: a `Birmingham City` or `MPL Birmingham` scoreline, followed by `PLAYER STATS`, name — archetype headers and pipe-separated labeled cells (`RAT`, `GLS`, `SHT`, `AST`, `2AST`, `DRI`, `PAS`, `POS`, `TKL`, `INT`, `BLK`, `CLR`, `SVS`). Parsing ends at `TEAM STATS`/`FINAL SCORE`. PAS and TKL pairs are stored as completed/attempted and won/attempted; POS pair meanings remain uninterpreted. Dashes remain missing. Several scorelines in one message prevent automatic assignment of player stats. Unsupported layouts stay raw for review. A recap saying League Match still starts Unknown. The user-supplied example is a supported test format, not proof of the actual automode layout; check the first real text recap. Existing imports are not silently rewritten. Team-stat sections and cards are not parsed in this version.

## Development tracking and richer drafts

Management runs `/development days:30` (1–90 days) for a private text review of classified matches. The same analysis is used in weekly drafts, limited to confirmed selected matches. Three or more samples against the same opponent, within the same category and units, produce a measured trend: improving/declining for understood metrics, mixed/steady, or increasing/decreasing where more is not necessarily better. Two samples provide only a comparison. Missing observations do not become zeroes. Pass completion, tackle success and finishing percentages need valid recorded numerators and nonzero denominators. Rates describe recorded outcomes, not causes.

Practice-to-later-official comparisons remain labeled separately. Two selected official Home/Away fixtures against the same opponent, on the same Eastern calendar date and in the same competition, can be presented together while retaining both match IDs. This uses stored timestamps; message-derived times are not proof of kickoff times and management should verify them.

Drafts now include a fact-based headline, result paragraphs, W/D/L and goal totals, two-fixture coverage when applicable, Gaffer observations and optional training/development sections. With development disabled, practice data cannot influence analysis or prose. Incomplete scores stay out of result totals. There are no invented player awards, quotes, injuries, highlights or upcoming fixtures. Approval still does not auto-publish. This is deterministic writing; an external AI provider is not required. The legacy RT bot connection remains a separate task.

Development scope: club/team only. The analyst ignores individual-player metrics for trends, practice-to-official comparisons and weekly development sections. Player links, saved stats and basic `/myfeedback` remain available, but individual rating progression is removed. Existing drafts are not automatically rewritten; regenerate a draft to apply this scope.
