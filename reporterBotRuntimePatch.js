const fs = require('fs');
const path = require('path');
const Module = require('module');

/**
 * Loads reporterBot.js with small, fail-fast source patches that preserve the
 * original Discord image URL alongside the /data cached copy and keep the
 * signing workflow lightweight/reliable in production.
 *
 * Kept separate so production hotfixes are explicit and easy to fold directly
 * into reporterBot.js later.
 */
function loadReporterBot() {
  const filename = path.join(__dirname, 'reporterBot.js');
  let source = fs.readFileSync(filename, 'utf8');

  const replacements = [
    {
      name: 'fetchImage source-url fallback',
      from: `async function fetchImage(url) {\n  if (url && typeof url === 'object' && url.localPath && fs.existsSync(url.localPath)) {\n    return fs.readFileSync(url.localPath);\n  }\n  if (url && typeof url === 'object') url = url.url;\n  if (!url) return null;`,
      to: `async function fetchImage(url) {\n  if (url && typeof url === 'object' && url.localPath && fs.existsSync(url.localPath)) {\n    return fs.readFileSync(url.localPath);\n  }\n  if (url && typeof url === 'object') url = url.url || url.sourceUrl;\n  if (!url) return null;`,
    },
    {
      name: 'cacheGraphic source-url persistence',
      from: `async function cacheGraphic(id, graphic) {\n  if (!graphic || (!graphic.url && !graphic.localPath)) return null;\n  if (graphic.localPath && fs.existsSync(graphic.localPath)) return graphic;\n  const source = await fetchImage(graphic.url);\n  const localPath = storyPath(id, 'source.png');\n  await sharp(source).rotate().png().toFile(localPath);\n  return { contentType: 'image/png', localPath };\n}`,
      to: `async function cacheGraphic(id, graphic) {\n  if (!graphic) return null;\n  const sourceUrl = graphic.url || graphic.sourceUrl || '';\n  if (!sourceUrl && !graphic.localPath) return null;\n  if (graphic.localPath && fs.existsSync(graphic.localPath)) {\n    return { ...graphic, sourceUrl: sourceUrl || graphic.sourceUrl || '' };\n  }\n  if (!sourceUrl) return null;\n  const source = await fetchImage(sourceUrl);\n  if (!source || !source.length) throw new Error('The saved player/source image could not be recovered.');\n  const localPath = storyPath(id, 'source.png');\n  await sharp(source).rotate().png().toFile(localPath);\n  return { contentType: 'image/png', localPath, sourceUrl };\n}`,
    },
    {
      name: 'simple sign-batch command options',
      from: `const signBatch = clubOption(new SlashCommandBuilder().setName('sign-batch').setDescription('Prepare one unified announcement for 2–5 signings'))\n  .addUserOption(o => o.setName('marquee').setDescription('Optional marquee player; must also be selected in the signing class'))\n  .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild);`,
      to: `const signBatch = new SlashCommandBuilder().setName('sign-batch').setDescription('Collect individual signing packages for 2–5 players')\n  .addStringOption(o => o.setName('club').setDescription('Club(s)').setRequired(true)\n    .addChoices(\n      { name: 'Birmingham City (Raine)', value: 'birmingham' },\n      { name: 'CrownFC (Teagan)', value: 'crownfc' },\n      { name: 'Both — Birmingham City + CrownFC', value: 'both' },\n    ))\n  .addUserOption(o => o.setName('player1').setDescription('Player 1').setRequired(true))\n  .addUserOption(o => o.setName('player2').setDescription('Player 2').setRequired(true))\n  .addUserOption(o => o.setName('player3').setDescription('Player 3'))\n  .addUserOption(o => o.setName('player4').setDescription('Player 4'))\n  .addUserOption(o => o.setName('player5').setDescription('Player 5'))\n  .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild);`,
    },
    {
      name: 'startSignCommand accepts batch-selected user',
      from: `  async function startSignCommand(interaction, team, teamKey) {\n    const teamKeys = teamKey === 'both' ? ['birmingham', 'crownfc'] : [teamKey];`,
      to: `  async function startSignCommand(interaction, team, teamKey, selectedUserOverride = null, suppressReply = false) {\n    const teamKeys = teamKey === 'both' ? ['birmingham', 'crownfc'] : [teamKey];`,
    },
    {
      name: 'startSignCommand uses override user',
      from: `    const guild = interaction.guild;\n    const selectedUser = interaction.options.getUser('player');`,
      to: `    const guild = interaction.guild;\n    const selectedUser = selectedUserOverride || interaction.options.getUser('player');`,
    },
    {
      name: 'startSignCommand batch-safe completion',
      from: `    await interaction.editReply('Signing workflow started for **' + member.displayName + '** → **' + clubLabel + '**. The reporter has DMed the player for their signing package.' + roleNote);\n  }\n  async function startSignBatchCommand(interaction, team, teamKey) {`,
      to: `    const completion = 'Signing workflow started for **' + member.displayName + '** → **' + clubLabel + '**. The reporter has DMed the player for their signing package.' + roleNote;\n    if (suppressReply) return { memberName: member.displayName, clubLabel, completion };\n    await interaction.editReply(completion);\n    return { memberName: member.displayName, clubLabel, completion };\n  }\n  async function startSignBatchCommand(interaction, team, teamKey) {`,
    },
    {
      name: 'sign-batch launches individual manual packages',
      from: `    const team = TEAMS[selectedClub];\n    if (!team) return interaction.editReply('That club is not configured.');\n    if (interaction.commandName === 'sign-batch') {\n      const teamKey = interaction.options.getString('club');\n      await startSignBatchCommand(interaction, team, teamKey);\n      return;\n    }`,
      to: `    if (interaction.commandName === 'sign-batch') {\n      if (!['birmingham', 'crownfc', 'both'].includes(selectedClub)) return interaction.editReply('That club selection is not configured.');\n      const users = ['player1', 'player2', 'player3', 'player4', 'player5']\n        .map(name => interaction.options.getUser(name))\n        .filter(Boolean);\n      const uniqueUsers = [...new Map(users.map(user => [user.id, user])).values()];\n      if (uniqueUsers.length < 2) return interaction.editReply('Select at least two different players.');\n      const primaryTeam = selectedClub === 'both' ? TEAMS.birmingham : TEAMS[selectedClub];\n      const completed = [];\n      for (const user of uniqueUsers) {\n        completed.push(await startSignCommand(interaction, primaryTeam, selectedClub, user, true));\n      }\n      return interaction.editReply('Batch signing collection started for **' + uniqueUsers.length + ' players** → **' + (selectedClub === 'both' ? 'Birmingham City + CrownFC' : primaryTeam.label) + '**. Each player was DMed separately for their name, nickname, position, squad number and photo. RT Football Media will forward each completed package to you privately; no group signing graphic will be generated.');\n    }\n    const team = TEAMS[selectedClub];\n    if (!team) return interaction.editReply('That club is not configured.');`,
    },
  ];

  for (const replacement of replacements) {
    if (!source.includes(replacement.from)) {
      throw new Error(`RT Media runtime patch anchor missing: ${replacement.name}`);
    }
    source = source.replace(replacement.from, replacement.to);
  }

  const patched = new Module(filename, module.parent || module);
  patched.filename = filename;
  patched.paths = Module._nodeModulePaths(__dirname);
  patched._compile(source, filename);
  console.log('RT Football Media runtime patches loaded.');
  return patched.exports;
}

module.exports = { loadReporterBot };
