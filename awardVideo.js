const { execFile } = require('child_process');
const fs = require('fs');
const path = require('path');
const sharp = require('sharp');

function escapeXml(value) {
  return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function run(command, args) {
  return new Promise((resolve, reject) => execFile(command, args, { timeout: 120000 }, (error, stdout, stderr) => {
    if (error) return reject(new Error(`Award video renderer failed: ${stderr || error.message}`));
    resolve(stdout);
  }));
}

async function createAwardVideo(options) {
  const { outputPath, playerName, awardName, clubName, teamKey, sourceImagePath, crestPath } = options;
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  const framePath = outputPath.replace(/\.mp4$/i, '-frame.png');
  const accent = teamKey === 'crownfc' ? '#65C7F2' : '#00A6E8';
  const background = sourceImagePath && fs.existsSync(sourceImagePath)
    ? await sharp(sourceImagePath).rotate().resize(1280, 720, { fit: 'cover' }).blur(1).modulate({ brightness: 0.45, saturation: 0.75 }).png().toBuffer()
    : await sharp({ create: { width: 1280, height: 720, channels: 4, background: '#07101B' } }).png().toBuffer();
  const svg = `<svg width="1280" height="720" xmlns="http://www.w3.org/2000/svg">
    <defs><linearGradient id="shade" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#07101B" stop-opacity=".94"/><stop offset=".58" stop-color="#07101B" stop-opacity=".55"/><stop offset="1" stop-color="#07101B" stop-opacity=".88"/></linearGradient></defs>
    <rect width="1280" height="720" fill="url(#shade)"/>
    <line x1="70" y1="90" x2="1210" y2="90" stroke="${accent}" stroke-width="5"/>
    <text x="70" y="145" font-family="DejaVu Sans" font-size="22" font-weight="700" letter-spacing="5" fill="${accent}">RT FOOTBALL MEDIA • AWARDS NIGHT</text>
    <text x="70" y="300" font-family="DejaVu Serif" font-size="72" font-weight="700" fill="#F7FBFF">${escapeXml(awardName.toUpperCase())}</text>
    <text x="70" y="408" font-family="DejaVu Serif" font-size="94" font-weight="700" fill="${accent}">${escapeXml(playerName.toUpperCase())}</text>
    <text x="74" y="463" font-family="DejaVu Sans" font-size="26" font-weight="700" letter-spacing="3" fill="#D5E1ED">${escapeXml(clubName.toUpperCase())}</text>
    <text x="70" y="628" font-family="DejaVu Sans" font-size="19" letter-spacing="3" fill="#B9C8D8">CASTLE &amp; CROWN COLLECTIVE • OWNER-APPROVED HONOR</text>
    <line x1="70" y1="658" x2="1210" y2="658" stroke="${accent}" stroke-width="3"/>
  </svg>`;
  const composites = [{ input: Buffer.from(svg) }];
  if (crestPath && fs.existsSync(crestPath)) {
    const crest = await sharp(crestPath).resize(150, 175, { fit: 'contain' }).png().toBuffer();
    composites.push({ input: crest, left: 1040, top: 120 });
  }
  await sharp(background).composite(composites).png().toFile(framePath);
  await run(process.env.FFMPEG_PATH || 'ffmpeg', [
    '-y', '-loop', '1', '-i', framePath, '-t', '10', '-r', '30',
    '-vf', 'scale=1280:720,fade=t=in:st=0:d=1,fade=t=out:st=9:d=1,format=yuv420p',
    '-c:v', 'libx264', '-preset', 'veryfast', '-movflags', '+faststart', outputPath,
  ]);
  return { outputPath, framePath, durationSeconds: 10 };
}

module.exports = { createAwardVideo };
