'use strict';

// Read current reports from Pep; never maintain a second match store.
async function centralRequest(path, { url = process.env.PEP_CENTRAL_URL, token = process.env.PEP_REPORTER_TOKEN, fetchImpl = fetch } = {}) {
  if (!url || !token) throw new Error('Pep connection is not configured.');
  const response = await fetchImpl(new URL(path, url), {
    headers: { Authorization: `Bearer ${token}` },
    signal: AbortSignal.timeout(10000), redirect: 'error',
  });
  if (!response.ok) throw new Error(`Pep returned ${response.status}; the report may need review.`);
  return response.json();
}

async function fetchReport(reportId, options) {
  if (!Number.isSafeInteger(reportId) || reportId < 1) throw new Error('Use a valid report ID.');
  const report = await centralRequest(`/reports/${reportId}`, options);
  if (report.version !== 1 || report.report_id !== reportId || !['draft', 'approved'].includes(report.status) || typeof report.article !== 'string' || !Array.isArray(report.matches)) {
    throw new Error('Pep report format is unavailable.');
  }
  return report;
}

async function sendReview(interaction, reportId, ownerId, options) {
  if (interaction.user.id !== ownerId) {
    return interaction.editReply('Only Coach can retrieve Pep’s weekly drafts.');
  }
  const report = await fetchReport(reportId, options);
  const bytes = Buffer.from(report.article, 'utf8');
  if (bytes.length > 7500000) throw new Error('This draft is too large for Discord.');
  // Ephemeral download only; no public post and no legacy statistics writes.
  return interaction.editReply({
    content: `RT Football Media — Pep draft #${reportId}. Private review copy; nothing has been published.`,
    files: [{ attachment: bytes, name: `RT_Pep_Report_${reportId}.txt` }],
    allowedMentions: { parse: [] },
  });
}

async function checkConnection(options) {
  const data = await centralRequest('/health', options);
  if (!data.ok || data.service !== 'pep-central-store') throw new Error('Pep central store is not healthy.');
  return true;
}

module.exports = { fetchReport, sendReview, checkConnection };
