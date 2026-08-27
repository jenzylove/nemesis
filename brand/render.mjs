/**
 * Renders the X assets to PNG at the exact sizes the platform expects.
 * Run with: node brand/render.mjs
 */
import {chromium} from 'playwright';
import {fileURLToPath} from 'url';
import path from 'path';

const here = path.dirname(fileURLToPath(import.meta.url));

const TARGETS = [
  // X avatars display at 400x400 and are cropped to a circle. The 2x copy is
  // for anywhere that renders the mark larger.
  {file: 'pfp.html', out: 'nemesis-pfp-400.png', w: 400, h: 400, scale: 1},
  {file: 'pfp.html', out: 'nemesis-pfp-800.png', w: 400, h: 400, scale: 2},
  // 1500x500 is the X header size.
  {file: 'banner.html', out: 'nemesis-x-banner-1500x500.png', w: 1500, h: 500, scale: 1},
  {file: 'banner.html', out: 'nemesis-x-banner-3000x1000.png', w: 1500, h: 500, scale: 2},
  // A4 landscape in CSS pixels, so the screenshot matches the PDF page exactly.
  {file: 'architecture.html', out: 'nemesis-architecture.png', w: 1123, h: 794, scale: 2,
   pdf: {out: 'nemesis-architecture.pdf', width: '297mm', height: '210mm'}},
];

const browser = await chromium.launch();
for (const t of TARGETS) {
  const ctx = await browser.newContext({
    viewport: {width: t.w, height: t.h},
    deviceScaleFactor: t.scale,
  });
  const page = await ctx.newPage();
  await page.goto('file://' + path.join(here, t.file).replace(/\\/g, '/'), {waitUntil: 'networkidle'});
  // let webfonts settle so the wordmark never rasterises in a fallback face
  await page.evaluate(() => document.fonts ? document.fonts.ready : null);
  await page.waitForTimeout(400);
  await page.screenshot({path: path.join(here, t.out), omitBackground: false});
  console.log(`${t.out.padEnd(34)} ${t.w * t.scale}x${t.h * t.scale}`);
  if (t.pdf) {
    await page.pdf({path: path.join(here, t.pdf.out), width: t.pdf.width, height: t.pdf.height,
                    printBackground: true, pageRanges: '1'});
    console.log(`${t.pdf.out.padEnd(34)} ${t.pdf.width} x ${t.pdf.height}`);
  }
  await ctx.close();
}
await browser.close();
