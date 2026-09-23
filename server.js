require('dotenv').config();
const express = require('express');
const cors = require('cors');
const { buildResponse, archetypes, costModels } = require('./optimizer');
const { startBot } = require('./reporterBot');

const app = express();
const PORT = process.env.PORT || 3000;
const botHealth = { status: 'starting', checkedAt: new Date().toISOString(), error: null };

app.use(cors());
app.use(express.json({ limit: '1mb' }));

app.get('/health', (req, res) => {
  const ok = botHealth.status !== 'error';
  res.status(ok ? 200 : 503).json({ ok, service: 'proclubs-custom-api', bot: botHealth.status, checkedAt: botHealth.checkedAt });
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

startBot().then(client => {
  botHealth.status = client ? 'ready' : 'disabled';
  botHealth.checkedAt = new Date().toISOString();
}).catch(err => {
  botHealth.status = 'error';
  botHealth.error = err.message;
  botHealth.checkedAt = new Date().toISOString();
  console.error('Discord bot failed to start:', err);
  process.exitCode = 1;
});
