# Rules for anyone changing this project, human or AI

Read this before making a change. These rules exist because the project was rebuilt once after it sprawled.

## The two jobs stay separate

- **Pep is the football brain.** Tactics, lineups, positions, Player of the Week recommendations. Pep never writes articles or publishes.
- **RT Football Media is the newsroom.** Cover, article, preview, approval, publishing. RT Media never makes a tactical call or picks an award.
- The only thing that passes from Pep to RT Media is a week Coach has approved.

If a new feature does not clearly belong to one of those two jobs, stop and ask Coach before building it.

## Hard rules

1. **Birmingham City and MPL only.** No second club.
2. **Nothing is published without Coach's approval.** No automatic public posts.
3. **A report is published once.** Keep the duplicate guard in `publisher.py`.
4. **AI runs only when Coach asks.** No AI calls at startup, on a timer, or when someone posts in a channel.
5. **No scraping and no new data feeds.** Coach supplies the match data.
6. **Never invent facts.** No made-up stats, quotes, injuries or match events. If data is missing, say so.
7. **No secrets in the repository.** Tokens and keys live in Railway variables only.
8. **Model and reasoning effort come from settings** (`ai_settings.py`), never written into a call.
9. **One service, one database.** Do not add a second service, a second database or a network link between bots.
10. **Do not delete match history.** Schema changes add to the database; they do not rebuild or wipe tables.

## How to make a change

1. Work on a branch, not the deployed one. Every push to the deployed branch goes live.
2. Run `python -m unittest discover -s gaffergpt/tests -q`. Add a test for the new behaviour.
3. Try it in the private staging channel before the real one.
4. Use `/backup` before anything that touches stored data.
5. When a feature is replaced, remove the old one in the same change. Do not leave both.
6. Keep `README.md` true. If a command or setting changes, update it in the same change.

## Before adding a feature, ask

- Is it in the two jobs above?
- Does Coach need it this season, or is it an idea?
- Can it be done without a new background job, a new service or a new AI call?

If any answer is no, write it down as a later idea and do not build it yet.
