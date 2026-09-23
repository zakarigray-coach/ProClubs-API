const fs = require('fs');
const path = require('path');
const Module = require('module');

/**
 * Loads reporterBot.js with small, fail-fast source patches that preserve the
 * original Discord image URL alongside the /data cached copy and attach the
 * CrownFC Virtualeagues schedule sync without destabilizing the main bot file.
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
      name: 'Virtualeagues schedule module import',
      from: `const { createAwardVideo } = require('./awardVideo');`,
      to: `const { createAwardVideo } = require('./awardVideo');\nconst { startVirtualeaguesSchedule } = require('./virtualeaguesSchedule');`,
    },
    {
      name: 'Virtualeagues schedule startup',
      from: `  client.once('clientReady', async () => {\n    console.log('RT Football Media logged in as ' + client.user.tag);\n    try {\n      await setupMplLeagueNewsFeed(client);`,
      to: `  client.once('clientReady', async () => {\n    console.log('RT Football Media logged in as ' + client.user.tag);\n    try {\n      await startVirtualeaguesSchedule(client, stateStore);\n    } catch (error) {\n      console.error('Virtualeagues CrownFC schedule setup failed:', error.message);\n    }\n    try {\n      await setupMplLeagueNewsFeed(client);`,
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
