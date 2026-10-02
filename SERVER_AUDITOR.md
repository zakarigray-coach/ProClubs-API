# Castle & Crown server administration auditor

The auditor is part of the existing `reporterBot.js` client. It adds no second bot,
token, startup service, OpenAI call, or dependency. Reports are deterministic,
private Discord attachments. Channel names and topics are evidence, never instructions.

## Commands

| Command | Result |
| --- | --- |
| `/server-audit` | Structure, category/channel order, security, club workflows, onboarding and media review |
| `/permission-audit` | Effective role access, cached member combinations, overwrites, role hierarchy, club separation, bot capabilities |
| `/media-audit` | Raine/Teagan workflow, publishing permissions, guild-scoped tracked RT Media archive candidates |
| `/onboarding-audit` | Entry visibility, registration queue, native onboarding options and sensitive self-assigned roles |
| `/server-map` | Ordered text map plus JSON channel/role/overwrite inventory |
| `/cleanup-preview` | Audit plus one exact owner-requested action, before state, risks, preview ID and confirmation phrase |
| `/apply-changes` | Apply that exact unexpired preview and return a persisted change journal |

Every command checks `BOT_OWNER_ID`, falling back to the current guild owner.
Manage Server, Administrator and football operations roles do not bypass that check.
Commands are disabled by default for ordinary members (`default_member_permissions=0`)
and unavailable in DMs. Discord server owners retain access. If `BOT_OWNER_ID` is
not the guild owner/admin, allow that user to use these commands in Server Settings
→ Integrations; runtime checks still reject everyone else.

## Audit → preview → explicit owner confirmation → apply → journal

1. Run an audit and review its evidence and coverage limitations.
2. Request a precise change using `/cleanup-preview`. For example, choose `rename`,
   select a channel, and enter the new name as `value`. Review the attached JSON;
   it includes the exact target ID, previous state, requested action and risks.
3. Within 15 minutes run `/apply-changes`, copy the `preview_id`, and paste the
   complete `APPLY ...` phrase into `confirmation`. There is no generic Yes button.
4. The bot fetches the guild, roles, channels and its own membership again. Any
   change to the recorded server channels, owner, role hierarchy or permissions
   invalidates the preview. Bot capabilities and protected targets are rechecked.
5. The bot persists intent and consumes approval before its first Discord write.
   It records results and before/after state in the existing StateStore metadata
   and management log. Failure stops further actions; earlier successful actions
   remain applied. A crash/interruption never auto-replays a preview.

Audits generate review findings, not executable changes. There is no AI-to-action
path. No deletion operation exists. The auditor never creates channels, discards
messages, grants membership, or automatically moves stale content. Existing
`/archive-media` remains its own legacy owner approval workflow.

## Exact change options

- `rename`: `channel`, `value` (1–100 characters).
- `topic`: `channel`, `value` (at most 1024 characters).
- `position`: `channel`, integer `value`. Discord may shift sibling positions.
- `move`: `channel`, destination `category`. Existing overwrites are preserved;
  permissions are never automatically synced to the destination.
- `overwrite`: `channel`, `role`, comma-separated `allow` / `deny` permission names.
  This replaces that role's overwrite, resetting unspecified flags to inherit.
  Other role/member overwrites are preserved.
- `role-permissions`: `role`, comma-separated `value` of exact Discord permission
  names. This replaces the whole role permission bitfield for every role holder.

Use names such as `ViewChannel,SendMessages`, with exact spelling/case. Everyone,
integration-managed roles, the bot's roles, configured management roles, roles at
or above the bot, management/protected channels, and cross-club operational moves
are excluded from mutation. Their findings require manual Discord administration.
The bot cannot grant capabilities it does not possess. The owner must assess all
effects of permission replacement before approval.

## Configuration and evidence limits

Reuse `BOT_OWNER_ID`, `BIRMINGHAM_ROLE_ID`, `MLPC_ROLE_ID`, and `RT_DATA_DIR`.
Optional comma-separated ID lists are documented in `.env.example`:

- `AUDITOR_MANAGEMENT_ROLE_IDS`: explicitly authorized leadership roles.
- `AUDITOR_MANAGEMENT_CATEGORY_IDS`: management category IDs.
- `AUDITOR_BIRMINGHAM_CATEGORY_IDS` / `AUDITOR_CROWNFC_CATEGORY_IDS`: club category IDs.
- `AUDITOR_PROTECTED_CHANNEL_IDS`: channel/category IDs requiring manual changes.

Explicit category IDs take precedence over name-based review hints. Missing policy
is reported; display names alone cannot establish authorization. A channel named
like a private operational area is a review signal; public club media/results may
intentionally remain shared.

Audits fetch channel/role data, but use only cached members. A possibly unused role
is never asserted to be unused; multi-role combinations outside that cache remain
unassessed. Activity checks read the latest message from at most 50 text or
announcement channels. No visible message does not prove emptiness. Thread,
voice, archived forum and seasonal activity is not inferred. Media age candidates
come only from guild-scoped tracked RT Media state; age does not authorize archival
or prove that the post still exists. Native onboarding API failures are reported
as unavailable rather than silently passed. Naming checks do not prove that a
registration panel, lineup process or scheduling automation works end to end.
Reports retain at most 5000 findings and explicitly count any omitted findings
in coverage; a capped report is not a complete audit.

Full snapshots and evidence are attached to private audit replies. Do not share
these externally: they include internal channel/role IDs and permission policy.

## Deployment and recovery

Merge the reviewed change into the existing Railway-linked repository. The existing
command registration adds these seven commands; no second deployment is required.
Keep one active bot replica with a persistent Railway volume at `RT_DATA_DIR`.
The existing StateStore is a local JSON file; in-process guild locks do not provide
coordination across replicas. Do not run multiple writers against the same file.
Discord is not transactional: an administrator can change state after preflight,
and the API can partially apply a request. Use the journal to verify actual state.

Metadata keys are `serverAuditor:preview:<id>` and `serverAuditor:journal:<id>`.
If a plan remains `applying` after restart, inspect its journal and current Discord
state. Create a fresh preview for any desired correction; do not reuse approval.
Before snapshots support manual restoration, but rollback is not automatic and
there is no unreviewed rollback command. Audit results do not modify or replace
the existing `/audit-server`, `/streamline-server` or setup behavior.

## Validation

`node --test test/serverAuditor.test.js test/commandAudit.test.js` exercises command
registration, audit non-mutation, ownership, exact confirmation, expiry, drift,
cross-guild isolation, tampering, replay, concurrency, persistence failure,
overwrite preservation, native onboarding and partial failures using fake guilds.
These checks never log in to Discord or apply real server changes. Validate live
reports first in the target guild; no live audit or Railway deployment is implied
by passing local tests.
