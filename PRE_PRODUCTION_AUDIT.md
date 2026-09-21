# Castle & Crown Collective — Production Readiness Audit

Audit date: 2026-09-21  
Scope: local release candidate  
Live production changed: **NO**

## Result

The previously identified code blockers are fixed. The release candidate is ready for the private Discord/Railway integration test. It must not be called live-verified until that credentialed test succeeds against the real server and `/data` volume.

## Fixed

- Directly imported dark navy/cyan RT Media front-page renderer; no runtime monkey patch.
- `PRO CLUBS NEWS NETWORK`, approved slogan, club strip, issue number, Eastern-Time date, hero image, key storylines and editorial panel.
- Exact owner-supplied CrownFC brand/crest assets; no substitute crest and no gold palette.
- Fresh signing, match, recap and spotlight scenes; signing reference photos preserve identity while requesting a different composition.
- Owner-only approval gates on automatic posts and every slash-command publication route.
- Thursday no-repeat spotlight selection, reporter DM, rotating questions, response capture and Saturday 10:00 AM Eastern draft.
- Friday weekly recap draft for each club using verified saved records only.
- Match-by-match persistence, calculated season totals and owner-approved `/correct-stats` corrections.
- One pinned running stats board per club with team record, recent form, player totals, goalkeeper totals and tagged correction contacts.
- Raine and Teagan posts reliably mention only their respective configured club role; ordinary members cannot use those protected role mentions.
- Evidence-based `/award-shortlists`; the bot never chooses a winner.
- Owner-approved 10-second MP4 `/award-presentation`; Railway FFmpeg dependency declared.
- Approval-gated 30-day copy → verify → delete → log archive workflow.
- Production/TEST data separation and the hidden 27-point `/staging-suite`.
- Persistent idempotency keys and restart recovery for scheduled jobs, signings and spotlight responses.
- Tru package (#22 and `because I’m a baller`), all 99 visible squad numbers, taken-number rejection and no-photo club artwork.
- App-style four-button Welcome screen plus detailed Club Directory.
- Management Office is private to ownership, the bot and Vice President of Football Operations.
- Castle & Crown branding, stable leadership role-ID migration, club permission separation and native Romano Times follower setup.
- Health endpoint reports bot readiness/error state instead of only HTTP process health.

## Automated evidence

- JavaScript syntax: PASS
- Automated tests: 21 PASS / 0 FAIL
- Isolated workflow checklist: 27 PASS / 0 FAIL
- Rendered RT Media PNG: PASS, 1080×1350
- Rendered award MP4: PASS, 10.0 seconds
- Production dependency vulnerabilities: 0
- Git whitespace validation: PASS

## Credentialed integration gate

The following can only be verified after deploying the candidate with the real Railway secrets:

1. Discord login and command registration.
2. Real owner/player DMs and owner interaction buttons.
3. Current bot/Auto Role Bot/club-role hierarchy and channel permissions.
4. OpenAI article, image-edit and image-generation calls under the production account.
5. Native follower access to external MPL announcement channel `1547269808909979729`; otherwise Discord’s one-time manual Follow action is required.
6. Railway `/data` mount persistence across an actual redeploy/restart.
7. A hidden `/staging-suite` run in the real Discord server, followed by one controlled owner-approved test publication.

Production records must remain untouched until the hidden staging report passes. A failed archive copy never deletes its original, and a failed publication remains private and is logged.
