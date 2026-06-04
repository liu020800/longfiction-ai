#!/usr/bin/env node
// render-infographic.js — HTML template → PNG infographic
// Usage: node render-infographic.js "2026年4月29日" '["item1","item2",...]' output.png

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

async function main() {
  const date = process.argv[2] || new Date().toLocaleDateString('zh-CN');
  const itemsArg = process.argv[3] || '[]';
  const outputPath = process.argv[4] || '/tmp/infographic.png';

  let rawItems;
  try { rawItems = JSON.parse(itemsArg); } catch { rawItems = []; }

  // Format items
  // Items can be strings or {text, source, highlight?} objects
  const items = rawItems.map((item, i) => {
    if (typeof item === 'string') {
      return { text: item, source: '', highlight: false, featured: false };
    }
    return {
      text: item.text || item.title || '',
      source: item.source || '',
      highlight: item.highlight || false,
      featured: item.featured || (i === 0),
    };
  });

  // Read template
  const templatePath = path.join(__dirname, '..', 'templates', 'daily-brief.html');
  // Try alternative paths
  let templateFile = templatePath;
  if (!fs.existsSync(templateFile)) {
    // Try looking in /mnt/g/douyin/templates/
    const altPath = '/mnt/g/douyin/templates/daily-brief.html';
    if (fs.existsSync(altPath)) templateFile = altPath;
  }

  let html = fs.readFileSync(templateFile, 'utf-8');

  // Replace date
  html = html.replace('__DATE__', date);

  // Build items HTML
  const itemsHtml = items.slice(0, 12).map((item, i) => {
    const featuredClass = item.featured ? ' featured' : '';
    const num = (i + 1).toString().padStart(2, '0');

    // Highlight keywords in text
    let text = item.text;
    if (item.highlight) {
      const keywords = Array.isArray(item.highlight) ? item.highlight : [];
      keywords.forEach(kw => {
        text = text.replaceAll(kw, `<span class="highlight">${kw}</span>`);
      });
    }

    const sourceHtml = item.source ? `<div class="news-source">📰 ${item.source}</div>` : '';
    return `
    <div class="news-item${featuredClass}">
      <div class="news-index">${num}</div>
      <div class="news-body">
        <div class="news-text">${text}</div>
        ${sourceHtml}
      </div>
    </div>`;
  }).join('\n');

  html = html.replace('__ITEMS__', itemsHtml);

  // Render with Playwright
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 } });

  // Inject font preloading
  await page.setContent(html, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(1000);

  // Get actual height (content might be shorter than 1920px)
  const dimensions = await page.evaluate(() => {
    const body = document.body;
    return { height: body.scrollHeight, width: body.scrollWidth };
  });

  // Use a tighter crop if content is shorter
  const cropHeight = Math.min(dimensions.height, 1920);

  await page.screenshot({
    path: outputPath,
    fullPage: false,
    clip: { x: 0, y: 0, width: 1080, height: cropHeight },
  });

  await browser.close();
  console.log(`✅ 信息图已生成: ${outputPath} (${cropHeight}px)`);
}

main().catch(e => { console.error('❌', e.message); process.exit(1); });
