const fs = require('fs');
const path = require('path');

const archetypes = JSON.parse(fs.readFileSync(path.join(__dirname, 'data', 'archetypes.json'), 'utf8')).archetypes;
const costModels = JSON.parse(fs.readFileSync(path.join(__dirname, 'data', 'cost-models.json'), 'utf8'));

function getArchetype(id) {
  return archetypes.find(a => a.id.toLowerCase() === String(id || '').toLowerCase());
}

function normalizeInputs(body) {
  return {
    archetype: String(body.archetype || '').toLowerCase(),
    position: String(body.position || 'CAM').toUpperCase(),
    goal: String(body.goal || 'balanced').toLowerCase(),
    totalAP: Number(body.totalAP || 0),
    height: body.height || null,
    weight: body.weight || null,
    preferredFoot: body.preferredFoot || null,
    playstyle: body.playstyle || null,
    categoryCosts: body.categoryCosts || costModels.defaultCostPerPoint,
    categoryCaps: body.categoryCaps || {
      pace: 30,
      shooting: 30,
      passing: 30,
      dribbling: 30,
      physical: 25,
      defending: 20
    },
    lockedSpend: body.lockedSpend || {},
    minimumSpend: body.minimumSpend || {},
    categories: body.categories || ["pace", "shooting", "passing", "dribbling", "physical", "defending"]
  };
}

function allocateBudget(input, archetype) {
  const order = archetype.priority_weights[input.goal] || archetype.priority_weights.balanced;
  const budget = input.totalAP;
  const costs = input.categoryCosts;
  const caps = input.categoryCaps;
  const lockedSpend = input.lockedSpend;
  const minimumSpend = input.minimumSpend;

  let remaining = budget;
  const result = {};

  for (const category of input.categories) {
    const locked = Number(lockedSpend[category] || 0);
    result[category] = locked;
    remaining -= locked;
  }

  for (const category of Object.keys(minimumSpend)) {
    const min = Number(minimumSpend[category] || 0);
    if ((result[category] || 0) < min) {
      const needed = min - (result[category] || 0);
      result[category] = (result[category] || 0) + needed;
      remaining -= needed;
    }
  }

  if (remaining < 0) {
    throw new Error('Locked AP and minimum AP exceed total AP.');
  }

  for (const category of order) {
    if (!input.categories.includes(category)) continue;
    const maxPoints = Number(caps[category] || 0);
    const currentAP = Number(result[category] || 0);
    const cost = Number(costs[category] || costModels.defaultCostPerPoint[category] || 1);
    const currentPoints = Math.floor(currentAP / cost);
    const roomPoints = Math.max(maxPoints - currentPoints, 0);
    const spendable = Math.min(remaining, roomPoints * cost);
    result[category] += spendable;
    remaining -= spendable;
  }

  return { allocation: result, leftoverAP: remaining };
}

function buildCategorySummary(allocation, costs) {
  return Object.entries(allocation).map(([category, ap]) => ({
    category,
    apSpent: ap,
    estimatedPoints: Math.floor(ap / Number(costs[category] || 1)),
    costPerPoint: Number(costs[category] || 1)
  }));
}

function buildResponse(body) {
  const input = normalizeInputs(body);
  const archetype = getArchetype(input.archetype);
  if (!archetype) {
    return { error: `Unknown archetype: ${body.archetype}` };
  }
  if (!input.totalAP || input.totalAP <= 0) {
    return { error: 'totalAP must be greater than 0.' };
  }

  const { allocation, leftoverAP } = allocateBudget(input, archetype);
  const bodyRecommendation = archetype.recommended_body[input.position] || archetype.recommended_body[Object.keys(archetype.recommended_body)[0]];
  const playstyles = archetype.playstyles[input.position] || archetype.playstyles[Object.keys(archetype.playstyles)[0]] || [];

  return {
    summary: {
      archetype: archetype.name,
      position: input.position,
      goal: input.goal,
      totalAP: input.totalAP,
      leftoverAP
    },
    recommendation: {
      height: input.height || bodyRecommendation.height,
      weight: input.weight || bodyRecommendation.weight,
      preferredFoot: input.preferredFoot,
      playstyleFocus: input.playstyle,
      attributePriorityOrder: archetype.priority_weights[input.goal] || archetype.priority_weights.balanced,
      suggestedPlaystyles: playstyles
    },
    categoryDistribution: buildCategorySummary(allocation, input.categoryCosts),
    exactPointSpendMap: allocation,
    notes: [
      'This system uses your provided AP totals and the category cost model you pass in.',
      'For exact live-site precision, update categoryCosts or pass more detailed lockedSpend/minimumSpend values.',
      'Use lockedSpend to preserve sections you already know must stay fixed.'
    ]
  };
}

module.exports = { getArchetype, buildResponse, archetypes, costModels };
