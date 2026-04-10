const express = require('express');
const cors = require('cors');
const { buildResponse, archetypes, costModels } = require('./optimizer');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json({ limit: '1mb' }));

app.get('/health', (req, res) => {
  res.json({ ok: true, service: 'proclubs-custom-api' });
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
