'use strict';

// Read current reports from Pep; never maintain a second match store.
async function centralRequest(path, { url = process.env.PEP_CENTRAL_URL, token = process.env.PEP_REPORTER_TOKEN, fetchImpl = fetch, binary = false } = {}) {
  if (!url || !token) throw new Error('Pep connection is not configured.');
  const response = await fetchImpl(new URL(path, url), {
    headers: { Authorization: `Bearer ${token}` },
    signal: AbortSignal.timeout(10000), redirect: 'error',
  });
  if (!response.ok) throw new Error(`Pep returned ${response.status}; the report may need review.`);
  if (binary) {
    const bytes = Buffer.from(await response.arrayBuffer());
    if (bytes.length > 8 * 1024 * 1024) throw new Error('Featured photo exceeds Discord size limit.');
    return bytes;
  }
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
  const files = [{ attachment: bytes, name: `RT_Pep_Report_${reportId}.txt` }];
  if (['png', 'jpg', 'webp'].includes(report.photo_extension)) {
    const photo = await centralRequest(`/reports/${reportId}/photo`, { ...options, binary: true });
    files.push({ attachment: photo, name: `Featured_Player_${reportId}.${report.photo_extension}` });
  }
  if (Number.isInteger(report.cover_count) && report.cover_count > 0 && report.cover_count <= 8) {
    for (let i = 0; i < report.cover_count; i++) {
      const cover = await centralRequest(`/reports/${reportId}/covers/${i}`, { ...options, binary: true });
      files.push({ attachment: cover, name: `${report.competition_context?.event?.report_type === 'Cup' ? 'RT_Cup' : 'RT_Media'}_${reportId}_${i + 1}.png` });
    }
  }
  // Ephemeral download only; no public post and no legacy statistics writes.
  return interaction.editReply({
    content: `RT Football Media — Pep draft #${reportId}. Private review copy; nothing has been published.`,
    files,
    allowedMentions: { parse: [] },
  });
}

async function checkConnection(options) {
  const data = await centralRequest('/health', options);
  if (!data.ok || data.service !== 'pep-central-store') throw new Error('Pep central store is not healthy.');
  return true;
}

module.exports = { fetchReport, sendReview, checkConnection };
