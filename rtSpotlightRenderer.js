'use strict';

// RT Football Media Player Spotlight renderer intentionally disabled.
// All previous Spotlight template/layout/design code was removed on 2026-09-22.
// Do not add a fallback, alternate, or legacy cover here.
// New Birmingham City and CrownFC Spotlight templates will be installed when approved files are supplied.

const RT_SPOTLIGHT_RENDERER_VERSION = 'template-removed-awaiting-new-design';
const LAYOUTS = [];

function selectSpotlightLayout() {
  return 'template-removed-awaiting-new-design';
}

async function renderSpotlight() {
  throw new Error('RT Football Media Player Spotlight rendering is temporarily disabled: approved Birmingham City and CrownFC templates have not been installed yet.');
}

module.exports = { renderSpotlight, selectSpotlightLayout, LAYOUTS, RT_SPOTLIGHT_RENDERER_VERSION };
