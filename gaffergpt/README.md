## Current MVP: MPL and cup recaps

Pep’s active reporting workflows are `/weeklyreport` and `/cupreport`, plus the Friday 8 AM Eastern DM. Practice recap controls and the Session Planner are retired. The existing central database, historical records, RT Media masthead/fonts/photo layout, player links and notebook remain intact. Older sections below describe preserved implementation history; the Final recap MVP section describes current operation.

# Current Pep workflow — tactical coaching

Pep now coaches from PCT+ findings supplied by management. Automatic recap imports and
session classification DMs are paused; existing database records remain intact. The
Friday 8:00 AM America/New_York weekly recap DM remains enabled, including persisted
restart recovery and duplicate prevention. It asks for verified NACL results and PCT
findings; it does not fetch either website or publish an article automatically.

Use `/tacticaladvice analysis:<paste PCT findings> formation:<optional>` in the club
server for a private response, or paste written analysis into an owner DM to Pep.
Only the configured owner receives DM coaching; the server command follows existing
management permissions. Paste text, not just a link or screenshot. AI requests contain
only the supplied analysis/formation, not the central match database. Supplied findings
and suggested causes must stay distinct. Focus stays on club tactics, team movement,
one practice drill and what to check in the next session, not individual development.

`PEP_COACH_API_KEY` uses a Railway reference to the existing RT Media OpenAI key; no
secret is written into source control. `PEP_COACH_MODEL` defaults to `gpt-5-mini`.
Requests run only on demand (plus one deployment connection smoke test), with bounded
input/output and no provider response storage. These calls use the existing OpenAI API
balance. Timeouts, quota failures and missing keys fall back to a clearly labelled
practical coaching library; unsupported issues prompt for clearer written findings.
Coaching inputs/answers are saved in `coaching_notes` in the existing central database.
They do not alter scores, classifications, statistics or report selections.

The sections below document retained foundations and the earlier collection design;
automatic intake and session-review delivery are currently paused.

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

## Pep’s Notebook and backups

Owner-only `/notebook` downloads a ZIP of CSV snapshots for matches, team stats, players, links, tactics, reports, report selections and scheduling history. Open them in Excel or import into Google Sheets. This is not a live Google Sheet. Discord IDs must be imported as text. Untrusted text is protected against spreadsheet formula execution. No secrets/settings are exported.

Daily online SQLite snapshots are checked and retained for seven dates under `/data/backups`. `/backup` produces a fresh checked snapshot to download privately. Same-volume backups recover logical mistakes but do not protect against losing the Railway volume: keep a downloaded copy outside Railway. Restore only with the bot stopped, retain the current database first, verify the backup with `PRAGMA quick_check`, then copy it to the configured database path and restart; the automated restore tests use temporary files, not production.

## RT Media central connection

Pep hosts an authenticated, read-only API on private Railway networking, default port 8080. Configure `PEP_REPORTER_TOKEN` with a strong shared secret (never the Discord token), and `PEP_REPORTER_PORT` if needed. RT’s `PEP_CENTRAL_URL` points to Pep’s private host. RT uses `/pepreport report_id:N` to retrieve the current weekly article as a private owner-only download. It does not rewrite scores, add legacy match records, call paid AI, or publish. `/health` and `/reports/N` both require the secret. Only current draft/approved reports are accessible; changed classifications invalidate old drafts. Development-disabled reports exclude practice facts.

Existing RT JSON files still hold unrelated signing/schedule history; they are not migrated or deleted. New weekly match analysis and articles have one source: Pep’s SQLite database. RT is a read-only consumer. Older RT commands keep their legacy behavior and should not be used as the new weekly-report intake.

Club stats parsing now supports explicitly labeled counts and percentages within TEAM STATS, including the supplied direction, length, possession-third and shooting fields. It does not infer possession or pass accuracy from direction/length counts. A real automode recap format still requires live verification. No test fixtures are imported into production.

The listener checks readable message content and embed titles/descriptions/fields for a known club scoreline, supported match labels, or explicit recap/stat headings. Setup menus and generic bot replies do not create matches. Recognizable partial recaps remain Unknown with their original text. At startup, exact historical OurProClubs club-selection prompts in the configured channel are marked Ignored only when still Unknown and missing all opponent/score facts. Their raw records and classification history remain saved; old review DMs are updated and their controls removed. Other records and management classifications remain untouched. Image-only recaps and private “Only you can see this” replies cannot be imported by this listener. PCT recap parsing/source configuration is not implemented by this change.

An owner-requested, one-time compatibility check inspects only channels named `league-stats` or `league-game-stats` in the configured guild (decorative characters are ignored). It reads at most 30 recent messages per channel and captures up to three club bot recaps. Readable content, source IDs and text/attachment availability are saved under `league_stats_check:v1` in the central settings table and logged for deployment diagnostics. It does not add matches, change the listener, classify games or send messages; subsequent restarts skip a completed check. This diagnostic is not ongoing PCT intake.

## Live Google Sheets notebook

Optional `PEP_GOOGLE_SERVICE_ACCOUNT_JSON` and `PEP_NOTEBOOK_SPREADSHEET_ID` enable a one-way mirror of the central database into the prepared Pep’s Notebook workbook. Enable Google Sheets API for the service account’s project and share only this workbook with the service account as Editor. Keep the JSON key only in Railway variables, never GitHub or chat. The bot uses only the Sheets scope; it cannot browse the rest of your Drive.

Every two minutes, a separate background worker checks for database changes and atomically refreshes the eight data tabs plus the Start Here status/timestamp. Unchanged records do not trigger writes. Restart forces a refresh; failures retry and cannot mark a sync successful. Discord ingestion, reviews and Friday DMs continue if Google is unavailable. IDs and recap text are explicit strings, so IDs retain their digits and text cannot execute formulas. Team statistics exclude individual metrics. Google’s cell limit requires text longer than 49,000 characters to be shortened with a notice; full text stays in SQLite.

The data tabs are viewing mirrors, not match intake or backup. Make match corrections and report selections in Discord. Data-tab cell edits are replaced on the next changed-data refresh, and tab names must remain unchanged. The sync clears stale rows in its managed data columns without changing formatting or touching other tabs. No settings, secrets or classification-history table are exported. The existing `/notebook` command still downloads a snapshot; `/backup` still provides a real database backup. If the workbook exceeds the safe sync payload limit, synchronization stops instead of sending partial records; the last-successful timestamp remains unchanged.

### Management player linking from Sheets

The separate `Link Players` input tab supports up to 100 rows (`A5:D104`). Column A is the exact OurProClubs player name; B is a Discord user ID stored as text; C/D are Pep-owned status/saved-at fields. Pep reads this tab every two minutes, including when the database has not changed. It checks new IDs against the configured Discord server with `fetch_member`, rejects bots, duplicate names/IDs, numeric or scientific-notation IDs, and existing-link conflicts. Only verified, unclaimed links are inserted atomically with the configured owner as actor. Existing links are never overwritten or deleted by this sheet; management corrects conflicts with `/setplayerlink` or `/unlinkplayer` in Discord. Clearing a cell does not unlink anyone. The bot writes only C/D and never overwrites manager input. Status updates are withheld if inputs changed during processing. The ordinary `Player_Links` tab reflects saved links after synchronization.

Keep workbook editor access limited to authorized management and the service account: writing this input tab authorizes linking requests. The initial eight names are from the supplied sample recap, not a verified complete club roster. Add further names and IDs only when their identities are known.


## Session reviews
Pep saves incoming matches immediately but sends one grouped review DM after 60 minutes
without a newly saved recap. This is an inactivity estimate, not proof the club stopped playing.
Management can use `/endsession` when finished to request the review immediately.
`PEP_SESSION_IDLE_MINUTES` optionally adjusts the quiet period (minimum 30, default 60).
`/reviewmatches` and `/match` remain available on demand. Classification does not change
until management chooses it; unclassified matches count in neither official nor practice analysis.
Session membership, delivery IDs and footer recovery markers live in the existing database.
Restarts preserve the quiet deadline and delivered batches. Menus paginate all session matches.

## NACL season source: planned, not connected
The intended season authority is NACL's confirmed MPL competition and season records;
PCT+/OurProClubs remain possible session-stat sources. No NACL importer or automatic
classification is enabled: approved API/feed/export access has not been verified.
VirtualArena's published terms require permission for automated collection/export.

Once approved access is available, verify team, competition and season IDs and import
completed results with stable NACL match IDs, recorded home/away and source provenance.
A verified result inside the configured MPL season can be classified Official without
asking Coach. A fixture without a final result cannot. Match-level data is required for
weekly selection; cumulative season totals alone cannot establish a weekly recap.
Preserve corrections/forfeits as official outcomes, without inventing on-field statistics.
Use only returned statistics and identify estimates separately.

Link Discord/EA/NACL records with shared external IDs where available; ambiguous matches
must go to review. Never merge the two fixtures against the same opponent by date or score.
An official game also appearing in a session recap must not be counted again as practice.
Absence from NACL does not establish practice: submissions may be delayed or missing.
Use management-confirmed practice sessions, with unresolved entries excluded from analysis.
All sources, match records and reporting selections must use the same central database.
Reporter consumes selected official matches and selected practice sections separately;
articles still require selection confirmation and approval before publication.


## Friday article workflow
Pep continues to DM Coach Fridays at 8 AM America/New_York, with persisted missed-job recovery.
RT's independent 6 PM draft and scheduled player interviews are retired.
1. Open **Add Results / Notes** in the Friday DM (or use `/weeklyreport`).
2. Enter one result per line: `2026-10-15 | Official Home | Chelsea | 3-1`.
   Types: `Official Home`, `Official Away`, `Practice`. Score is always Birmingham first.
   Dates must be within the displayed reporting week. Results are explicitly management-classified;
   they are not inferred from EA's Friendly/League label. Repeated identical submissions are deduplicated.
   To correct an existing imported score, use `/matchdetails`; do not resubmit a changed score as a new fixture.
3. Optionally add verified PCT findings and a Player of the Week name/Discord mention plus factual achievement.
   These are attributed management notes, not independently verified statistics. No player interview is sent.
4. Select only the matches to include and press **Generate Report**.
5. Optionally run `/reportphoto` with the report ID and a PNG/JPEG/WebP up to 8 MB, then generate again.
   Photos are stored in the same persistent database and attached to Coach's draft DM. No public mention pings.
6. Review the private article and photo. **Approve Draft** saves approval only; nothing publishes automatically.

Raine and Teagan rotate with persisted opening history. Draft length follows the available facts;
350–550 words is the default for a full match week, not a reason to invent detail or pad a sparse week.
Automatic recap collection remains paused. Owner DMs outside the results form remain tactical advice requests.


### Reply directly to the Friday DM
No results command is required. Reply with your weekly recap text or up to four PNG/JPEG/WebP
photos (8 MB each). Pep reads them with the existing configured AI provider, asks for missing
facts, and shows a result preview. **Confirm Results & Draft** saves only those results,
selects them, and generates a private draft. No facts import before confirmation and no auto-publication.
The pending conversation and confirmation buttons survive restarts. Send `weekly recap`
in a private DM to start early. While waiting for recap replies, prefix tactical requests with `Tactics:`.
Photos submitted as recaps are source material, not automatically featured player photos.
NACL and PCT are not scraped. Dates, venue and scores must be present or supplied by Coach.

If weekly player statistics support a comparison, Pep proposes Player of the Week with its supplied-stat
reason in the result preview. Coach confirms the suggestion. Missing player statistics produce no award
suggestion. The **Attach Player Photo** button on the preview or draft lets Coach send the image in DM,
without a slash command. Recap screenshots and featured player photos are handled separately.


### Excel recap uploads
Send the original PCT+ `.xlsx` export to Pep's private DM (8 MB maximum).
An Excel attachment can start the weekly intake without typing `weekly recap` first.
Pep reads cell values from all worksheets, including player-week totals and player-match details;
formulas/macros/external links are not executed. `.xls` and `.xlsm` are not supported.
If the export lacks official/practice classification or venue, reply with those details;
Pep keeps the uploaded values and clarification context, so reuploading is unnecessary.
For example: **All these matches were practices.** EA's `league` label never establishes MPL status.
Large match lists include a complete text preview attachment before confirmation.
Player-week aggregates may cover practices and official games together; suggestions must state that scope.


Excel player stats now carry through confirmation into `match_statistics` in the central database.
The preview includes all exported player totals; the draft computes player performances only from
selected, unambiguously matched player-match records, separately for Official and Practice.
The match identity check uses Eastern date, opponent and both scores. Ambiguous identical fixtures
receive no guessed stats. Missing metrics stay missing, zero-minute rows do not count as appearances,
and passing percentages are weighted by recorded attempts, not averaged across games.
This is factual reporting, not individual development advice. The club-only coaching policy is unchanged.

Weekly articles now use the configured Pep AI provider for a story-led sports feature: original headline, rotating reporter voice, selective statistics and separate practice coverage. Weekly articles default to 350–550 words and remain shorter when evidence is thin. Recent drafts inform wording variation. Provider failures keep confirmed facts available for retry; articles remain private drafts.

Sports desk quality: concrete leads, restrained reporter voices, evidence-only descriptions, rounded readable figures and explicit confirmed Player of the Week recognition. Legacy outfield conceded-goal totals are stripped before AI writing; new Excel imports retain individual conceded goals/clean sheets only for goalkeeper appearances.

Article generation builds a frozen fact sheet from the selected database matches and raw statistic rows. Python computes separate Official and Practice totals, tracks sample coverage, and keeps individual fixture figures distinct. Incomplete aggregate metrics are omitted from prose. Material source conflicts hold the draft and return the precise conflict to Coach.

The existing reporter voices and configured `PEP_REPORTER_MODEL` remain unchanged. The sports desk drafts and edits complete prose, then runs an independent editorial review and final claim-location pass. Python checks the final claims against the frozen facts, including player attribution, score/result consistency, scope, exact names, unavailable quotations/narrative events, unselected opponent leakage, repeated statistics and banned language. These gates do not turn model judgement into proof of every possible natural-language inference; unsupported material is held, rather than labelled verified.

Revision is bounded: one initial draft and at most three edit/review/source-location attempts. One additional reference-mapping repair may fix an invalid citation without rewriting the checked article (at most eleven provider requests). Article requests have a 180-second timeout; the coaching timeout remains 60 seconds. A retry can resume the saved edited draft and precise correction notes only when its frozen source hash still matches; all checks run again. Failures retain selections and source data; no intermediate article is delivered or automatically published. Public approval remains required. Approval also checks that the audited text and selected source rows have not changed. `report_generation_audit` stores source references, hashes, fact sheets, individual checks, failures and revisions in the shared SQLite database. The private View Statistics control keeps the complete recap separate from the article.

`PEP_REPORT_REWRITE_REQUEST` remains a one-time owner test control. A marker ending `:preview` generates through the normal pipeline and logs the final article and checks privately for inspection. `:deliver` delivers only a stored draft whose text hash matches a passed audit. The former copy-edit bypass is retired; a changed article must go through the checks again. No token values are logged.

Calendar-day fixture references and daily counts come from trusted match dates, never a fallback message timestamp. Leading-scorer comparisons are emitted only when the recorded goal coverage rules out an unseen higher scorer. The source fingerprint covers the underlying records; adding a derived check cannot masquerade as new source data. The claim locator distinguishes supported football interpretation from new factual assertions, while concrete events, quotations and statistics still require evidence.

## Cup / tournament editions

Use `/weeklyreport`, then **Competition / Report Type**. Choose **Cup / Tournament** to open the separate event report. The seeded **The Minglewood Cup** runs October 13–15, 2026; selecting it opens that date range automatically. Its supplied announcement confirms single elimination, possible rounds 1–3 on October 13, semifinals/final October 15, and the bracket draw October 12. The notice's “10 PM EST” is stored verbatim with timezone ambiguity; it does not schedule kickoff notifications. Opponents, Birmingham participation, prizes and outcome are not invented.

**Cup Competition Details** supports other names/date ranges and confirmed format/outcome. Add results as `2026-10-13 | Cup | Opponent | 2-1`, or send the recap/Excel after selecting the cup report. Coach still confirms extracted results. **Classify / Edit Cup Match** assigns existing entries explicitly and accepts optional stage/group, tie ID/leg, extra-time final score and separate shootout score. Unknown fields may stay blank. Final match scores include extra time but exclude shootout kicks. Two selected legs with the same tie ID yield a calculated aggregate; one leg never invents an aggregate. Cup records cannot enter `/officialrecord` (MPL league totals).

The default recognition is **Cup Standout**. Choose the player and verified achievement in Add Results / Notes. **Cup Award Scope** permits Player of the Tournament only with explicit confirmation of who awarded it and its scope. Photo attachment remains optional. A passed private draft includes a fixed CUP EDITION PNG using the original masthead and existing DejaVu font system (fonts-dejavu-core in the container); long headings move to an additional card without reducing readable type. The authenticated RT bridge retrieves those same covers and article, not another copy of the match database. No public publishing is triggered.

Migration 3 backs up a legacy SQLite file to `.pre-cup.bak`, then replaces constrained tables atomically while retaining IDs, statistics, selections, audits and scheduled jobs. New league/cup/practice reports can share a reporting period without colliding. Existing historical practice reports and Friday 8 AM America/New_York scheduling remain intact.

Cup regression tests run with the existing command: `python -m unittest discover -s gaffergpt/tests -q`. Pillow is the single added dependency for deterministic covers; it is not an AI service. Sample data must use a temporary database, never the production store.


### Final recap MVP

Pep focuses on Friday MPL league recaps and manually triggered cup/tournament recaps. Use `/weeklyreport` for MPL selection or `/cupreport` for the relevant tournament. There is no recap-type menu, practice reporting control or `/session` planner. Historical practice data, older drafts, player records and statistics remain stored; existing tactical advice and notebook integrations are preserved.

Friday reminders still run at 8 AM America/New_York with persisted delivery markers, leases and restart catch-up. Articles require explicit match confirmation and remain private drafts until Coach approves. Cup reports are keyed by competition and date range; repeated triggers reopen the same report. Stage, aggregate and shootout evidence remain separate from league/player totals.

Verified articles now feed the approved RT brushstroke masthead, fixed fonts, blue/navy weekly presentation and optional right-hand player-photo panel. Cup editions retain their existing gold cover. Measured continuation cards keep the complete article readable without clipping, alongside an optional text download. RT's existing `/pepreport` bridge retrieves the same media and central data; there is no second database or paid image generation.

Changing an optional photo re-renders the media without calling the article writer again. Results, award selection or statistics changes still require a fresh fact check. Generation failures preserve selections. Production bot controls exclude practices/scrims/test classifications; manager-confirmed official MPL and cup records are the only new article sources. Source EA “league”/“friendly” labels never determine competition classification automatically.
