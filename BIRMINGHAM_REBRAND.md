# Birmingham MPL cleanup — 11 October 2026

The owner requested removal of CrownFC from server/channel descriptions and renaming
ML1 channel names to MPL. RT runs this bounded cleanup once on startup, only for the
configured Birmingham server (1524828767426707587).

Only description, topic and name fields are edited. Existing channel IDs, messages,
categories, membership and permissions are retained. Original descriptions and names
are saved before changes in the RT data volume's `birmingham-rebrand-journal.json`.
Permission failures remain visible in deployment logs and cannot mark the job complete.
Successful restarts do not repeat the edits.

The active RT channel lookup/template names and Birmingham auditor prefix now use MPL.
Old Match Center aliases remain supported by the existing Match Center setup module.

RT also reads recent and pinned posts in the live club-directory channel and records
their text, fields and buttons in private Railway logs. The directory post itself is
not changed until the owner supplies the desired replacement sections.
