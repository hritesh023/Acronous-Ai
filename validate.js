const fs = require('fs');
const code = fs.readFileSync('cloudflare-worker.js','utf8');
let depth = 0;
let inString = false, inTemplate = false, stringChar = '';
for (let i = 0; i < code.length; i++) {
  const ch = code[i];
  const prev = i > 0 ? code[i-1] : '';
  if (!inString && !inTemplate) {
    if (ch === '{' || ch === '(' || ch === '[') depth++;
    if (ch === '}' || ch === ')' || ch === ']') depth--;
    if (ch === "'" || ch === '"') { inString = true; stringChar = ch; }
    if (ch === '`') { inTemplate = true; }
  } else if (inString) {
    if (ch === '\\') i++;
    else if (ch === stringChar) inString = false;
  } else if (inTemplate) {
    if (ch === '\\') i++;
    else if (ch === '`' && prev !== '\\') inTemplate = false;
  }
}
console.log('Balance:', depth, '(should be 0)');
console.log('Size:', (code.length/1024).toFixed(1) + 'KB');
console.log('Lines:', code.split('\n').length);
console.log('generateRealPDF:', code.includes('function generateRealPDF'));
console.log('PHOTOREALISTIC:', code.includes('PHOTOREALISTIC photography'));
console.log('Seed random:', code.includes('Math.random() * 1000000'));
console.log('PDF generateRealPDF call:', code.includes('generateRealPDF(cleanedContent'));
