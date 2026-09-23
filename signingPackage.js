const fs = require('fs');

function signingTeamKeys(record) {
  return Array.isArray(record?.signingTeamKeys) && record.signingTeamKeys.length
    ? [...new Set(record.signingTeamKeys)]
    : record?.teamKey ? [record.teamKey] : [];
}

function packageMissingFields(record, fileExists = fs.existsSync) {
  const missing = [];
  if (!String(record?.selectedPlayerName || '').trim()) missing.push('name');
  if (!String(record?.announcementName || '').trim()) missing.push('nickname');
  if (!String(record?.position || '').trim()) missing.push('position');
  const photoPath = record?.graphic?.localPath;
  if (!photoPath || !fileExists(photoPath)) missing.push('photo');
  const numbers = record?.signingNumbers || {};
  for (const key of signingTeamKeys(record)) {
    const number = numbers[key] || (key === record.teamKey ? record.playerNumber : '');
    if (!/^([1-9]|[1-9]\d)$/.test(String(number || ''))) missing.push(`${key}Number`);
  }
  return missing;
}

function packageComplete(record, fileExists) {
  return packageMissingFields(record, fileExists).length === 0;
}

async function runIndependentBatch(users, starter) {
  const started = [];
  const failed = [];
  for (const user of users) {
    try {
      const result = await starter(user);
      if (result?.contacted) started.push(result);
      else failed.push({ user, error: 'DMs disabled or unavailable', result });
    } catch (error) {
      failed.push({ user, error: error.message || String(error) });
    }
  }
  return { started, failed };
}

module.exports = { signingTeamKeys, packageMissingFields, packageComplete, runIndependentBatch };
