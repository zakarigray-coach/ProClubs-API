require('dotenv').config();
const express = require('express');
const cors = require('cors');
const { buildResponse, archetypes, costModels } = require('./optimizer');
require('./rtReporterVoicePatch');
require('./rtNewspaperPatch');
const { startBot } = require('./reporterBot');

const app = express();
const PORT = process.env.PORT || 3000;
const SERVER_BRAND_NAME = process.env.SERVER_BRAND_NAME || 'Castle & Crown Collective';

app.use(cors());
app.use(express.json({ limit: '1mb' }));

app.get('/health', (req, res) => {
  res.json({ ok: true, service: 'proclubs-custom-api', serverBrandName: SERVER_BRAND_NAME });
});

app.get('/archetypes', (req, res) => {
  res.json({ archetypes });
});

app.get('/cost-models/default', (req, res) => {
  res.json(costModels);
});

app.post('/optimize-build', (req, res) => {
  try {
    const result = buildResponse(req.body || {});
    if (result.error) return res.status(400).json(result);
    res.json(result);
  } catch (err) {
    res.status(400).json({ error: err.message || 'Unable to optimize build.' });
  }
});

app.post('/calculate-build', (req, res) => {
  try {
    const result = buildResponse(req.body || {});
    if (result.error) return res.status(400).json(result);
    res.json(result);
  } catch (err) {
    res.status(400).json({ error: err.message || 'Unable to calculate build.' });
  }
});

app.listen(PORT, () => {
  console.log(`proclubs-custom-api running on port ${PORT}`);
});

(async () => {
  try {
    const client = await startBot();
    if (!client) return;
    const guild = process.env.DISCORD_GUILD_ID
      ? await client.guilds.fetch(process.env.DISCORD_GUILD_ID).catch(() => null)
      : client.guilds.cache.first();
    if (!guild) return;
    if (guild.name !== SERVER_BRAND_NAME) {
      await guild.setName(SERVER_BRAND_NAME, 'Approved Castle & Crown Collective server rebrand');
      console.log('Discord server renamed to ' + SERVER_BRAND_NAME);
    }
  } catch (err) {
    console.error('Discord bot failed to start:', err);
    process.exitCode = 1;
  }
})();
