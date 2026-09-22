'use strict';

// RT Football Media newspaper renderer intentionally disabled.
// All previous newspaper template/layout/design code was removed on 2026-09-22.
// Do not add a fallback or legacy layout here.
// A new Birmingham City SVG and CrownFC SVG will be installed when approved templates are supplied.

const RT_NEWSPAPER_RENDERER_VERSION = 'template-removed-awaiting-new-svg';

async function renderNewspaper() {
  throw new Error('RT Football Media newspaper rendering is temporarily disabled: approved Birmingham City and CrownFC SVG templates have not been installed yet.');
}

module.exports = { renderNewspaper, RT_NEWSPAPER_RENDERER_VERSION };
