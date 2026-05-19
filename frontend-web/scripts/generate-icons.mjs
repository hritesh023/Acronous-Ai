import sharp from 'sharp';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, '..');
const logoPath = join(root, '..', 'assets', 'logo.png');
const androidRes = join(root, 'android', 'app', 'src', 'main', 'res');

const densities = [
  { dir: 'mipmap-mdpi', size: 48 },
  { dir: 'mipmap-hdpi', size: 72 },
  { dir: 'mipmap-xhdpi', size: 96 },
  { dir: 'mipmap-xxhdpi', size: 144 },
  { dir: 'mipmap-xxxhdpi', size: 192 },
];

const logo = readFileSync(logoPath);

// Also resize foreground icons with padding (for adaptive icons)
const foregroundSizes = [
  { dir: 'mipmap-mdpi', size: 108 },
  { dir: 'mipmap-hdpi', size: 162 },
  { dir: 'mipmap-xhdpi', size: 216 },
  { dir: 'mipmap-xxhdpi', size: 324 },
  { dir: 'mipmap-xxxhdpi', size: 432 },
];

async function main() {
  for (const { dir, size } of densities) {
    const outDir = join(androidRes, dir);
    if (!existsSync(outDir)) mkdirSync(outDir, { recursive: true });

    const resized = await sharp(logo)
      .resize(size, size, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } })
      .png()
      .toBuffer();

    writeFileSync(join(outDir, 'ic_launcher.png'), resized);
    writeFileSync(join(outDir, 'ic_launcher_round.png'), resized);
    console.log(`Generated ${dir}/ic_launcher.png (${size}x${size})`);
  }

  // Generate foreground icons (larger for adaptive icon safe zone)
  for (const { dir, size } of foregroundSizes) {
    const outDir = join(androidRes, dir);
    const resized = await sharp(logo)
      .resize(size, size, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } })
      .png()
      .toBuffer();

    writeFileSync(join(outDir, 'ic_launcher_foreground.png'), resized);
    console.log(`Generated ${dir}/ic_launcher_foreground.png (${size}x${size})`);
  }

  console.log('All icons generated successfully!');
}

main().catch(console.error);
