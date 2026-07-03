// Simplified image editing approach - removing HuggingFace dependencies and using web search
async function llmGuidedEdit(imageBase64, editDesc, mimeType, approach) {
  if (!OPENROUTER_API_KEY) return null;

  try {
    // Step 1: Use vision model to understand the original image content
    const visionPrompt = `Analyze this image with MAXIMUM precision. Describe: (1) Main subject appearance (face, body, clothing, expression, pose), (2) Background/setting, (3) Colors and lighting, (4) Composition and style. Focus on details needed to accurately recreate this image. Format as concise bullet points.`;
    const visionContent = buildMultimodalContent(visionPrompt, imageBase64, mimeType);
    const visionMsgs = [
      { role: 'system', content: 'You are a precise image analyst. Describe images in concise, factual bullet points.' },
      { role: 'user', content: visionContent },
    ];
    const visionResp = await callOpenRouter(visionMsgs, { model: VISION_MODEL, stream: false, max_tokens: 512, temperature: 0.1 });
    const visionData = await visionResp.json();
    const imageAnalysis = sanitizeText(visionData?.choices?.[0]?.message?.content || '');
    if (!imageAnalysis || imageAnalysis.length < 20) return null;

    // Step 2: Use LLM to craft a precise edit instruction based on actual image content
    const editPromptMsgs = [
      { role: 'system', content: approach === 'inpaint'
        ? 'You are an expert image inpainting prompt engineer. Given the original image analysis and an edit request, create a prompt describing ONLY the edited result. Focus on what the image looks like AFTER the edit. Keep the prompt under 300 characters.'
        : 'You are an expert image editing prompt engineer. Given the original image analysis and an edit request, create a concise instruction for editing the image. Describe only the changes to apply. Keep under 300 characters.' },
      { role: 'user', content: `Original image analysis:\n${imageAnalysis}\n\nEdit request: ${editDesc}\n\nCreate a precise, detailed prompt for the edited image. Return ONLY the prompt.` },
    ];
    const editPromptResp = await callOpenRouter(editPromptMsgs, { model: FAST_MODEL, stream: false, max_tokens: 300, temperature: 0.2 });
    const editPromptData = await editPromptResp.json();
    let guidedPrompt = sanitizeText(editPromptData?.choices?.[0]?.message?.content || '');
    if (!guidedPrompt || guidedPrompt.length < 10) guidedPrompt = editDesc;

    // Step 3: Try web search for enhanced editing context (new power of internet)
    let enhancedPrompt = guidedPrompt;
    const searchTerms = extractEditSearchTerms(editDesc);
    if (searchTerms && searchTerms.length > 0) {
      try {
        const searchResults = await searchWeb(`${editDesc} ${imageAnalysis} ${searchTerms}`);
        if (searchResults) {
          // Incorporate web search results into the edit prompt
          enhancedPrompt = `${guidedPrompt}\n\nWeb search context for enhanced editing: ${searchResults.slice(0, 500)}`;
        }
      } catch {}
    }

    // Step 4: Try gen.pollinations.ai POST first (no URL limits, best quality)
    if (typeof POLLINATIONS_API_KEY !== 'undefined' && POLLINATIONS_API_KEY) {
      const pollBody = JSON.stringify({
        prompt: enhancedPrompt.substring(0, 500),
        model: 'flux',
        image: `data:${mimeType || 'image/jpeg'};base64,${imageBase64}`,
        width: 1024,
        height: 1024,
        seed: Math.floor(Math.random() * 1000000),
      });
      const pollResp = await fetch('https://gen.pollinations.ai/image', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${POLLINATIONS_API_KEY}`,
        },
        body: pollBody,
        signal: AbortSignal.timeout(90000),
      });
      if (pollResp.ok) {
        const ct = pollResp.headers.get('content-type') || '';
        if (ct.startsWith('image/')) {
          const buf = await pollResp.arrayBuffer();
          if (buf && buf.byteLength > 500) return buf;
        }
      }
    }

    // Step 5: Try CF Workers AI (free, reliable within plan)
    if (globalThis.AI) {
      const workerResult = await callWorkersAIImageEdit(base64ToArrayBuffer(imageBase64), enhancedPrompt, mimeType);
      if (workerResult && workerResult.byteLength > 500) return workerResult;
    }

    // Step 6: Use enhanced Pollinations img2img with preserved identity
    const preservePrompt = enhancedPrompt + ' PRESERVE IDENTITY: Keep the exact same subject, face, body, pose, expression, background, lighting, and composition. Only apply the described change. No text, no words, no letters.';
    const pollResult = await pollinationsImg2img(imageBase64, preservePrompt, mimeType);
    if (pollResult && pollResult.byteLength > 500) return pollResult;

  } catch (e) {}

  return null;
}

function extractEditSearchTerms(editDesc) {
  const searchTerms = [];
  const lower = editDesc.toLowerCase();
  
  const keywords = [
    'background', 'style', 'color', 'lighting', 'expression', 'pose',
    'clothing', 'hair', 'eyes', 'face', 'body', 'skin', 'fabric',
    'art', 'painting', 'sketch', 'cartoon', 'anime', 'chibi',
    'photo', 'picture', 'image', 'filter', 'effect', 'enhance'
  ];
  
  for (const kw of keywords) {
    if (lower.includes(kw)) searchTerms.push(kw);
  }
  
  return searchTerms.join(' ');
}

async function tryVisionEdit(imageBase64, editDesc, mimeType) {
  if (!OPENROUTER_API_KEY) return null;
  try {
    // Step 1: Analyze the original image with vision model
    const visionPrompt = `Describe this image in detail. Focus on: main subject, colors, composition, setting, lighting, style, and key visual elements. Be specific about what can be seen.`;
    const visionContent = buildMultimodalContent(visionPrompt, imageBase64, mimeType);
    const visionMsgs = [
      { role: 'system', content: 'You are an expert image analyst. Describe images in precise detail.' },
      { role: 'user', content: visionContent },
    ];
    const visionResp = await callOpenRouter(visionMsgs, { model: VISION_MODEL, stream: false, max_tokens: 512, temperature: 0.2 });
    const visionData = await visionResp.json();
    const imageDescription = sanitizeText(visionData?.choices?.[0]?.message?.content || '');
    if (!imageDescription || imageDescription.length < 20) return null;

    // Step 2: Use web search for enhancement context
    let enhancedDescription = imageDescription;
    const searchTerms = extractEditSearchTerms(editDesc);
    if (searchTerms) {
      try {
        const searchResults = await searchWeb(`${editDesc} ${searchTerms}`);
        if (searchResults) {
          enhancedDescription = `${imageDescription}\n\nEnhanced with web context: ${searchResults.slice(0, 300)}`;
        }
      } catch {}
    }

    // Step 3: Generate an edit prompt with web-enriched context
    const editPromptMsgs = [
      { role: 'system', content: 'You are an expert image editing prompt engineer. Given an original image description and an edit request, create a detailed text-to-image prompt that produces the edited version. Focus on visual details. NEVER include text, words, letters, or typography in the prompt. Return ONLY the prompt, no explanations.' },
      { role: 'user', content: `Original image: ${enhancedDescription}\n\nEdit request: ${editDesc}\n\nCreate a detailed image generation prompt that shows the image after this edit is applied. Describe ONLY the resulting edited scene.` },
    ];
    const editPromptResp = await callOpenRouter(editPromptMsgs, { model: OPENROUTER_MODEL, stream: false, max_tokens: 500, temperature: 0.4 });
    const editPromptData = await editPromptResp.json();
    let generatedPrompt = sanitizeText(editPromptData?.choices?.[0]?.message?.content || '');
    if (!generatedPrompt || generatedPrompt.length < 20) return null;
    generatedPrompt = generatedPrompt
      .replace(/\b(Acronous|acronous|ACRONOUS)\b/gi, '')
      .replace(/\b(text\b(?:\s+\w+){0,3}|words|letters|symbols|characters|font|typography)\s*[,.]*/gi, '')
      .replace(/\s+/g, ' ').trim();

    // Step 4: Add web search for final enhancement and generate via Pollinations
    let finalPrompt = generatedPrompt;
    const finalSearchTerms = extractEditSearchTerms(editDesc);
    if (finalSearchTerms) {
      try {
        const finalSearchResults = await searchWeb(`${editDesc} style ${finalSearchTerms}`);
        if (finalSearchResults) {
          finalPrompt = `${generatedPrompt}\n\nFinal enhancement context: ${finalSearchResults.slice(0, 300)}`;
        }
      } catch {}
    }

    const imageBuffer = await pollinationsImage(finalPrompt, { retries: 3 });
    if (imageBuffer && imageBuffer.byteLength > 500) return imageBuffer;
  } catch {}
  return null;
}

const copy = require('clipboardy');

if (typeof globalThis !== 'undefined') {
  globalThis.console = console;
  globalThis.fetch = fetch;
}

function base64ToArrayBuffer(base64) {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
  const str = base64.replace(/-/g, '+').replace(/_/g, '/');
  const ignored = str.length % 4;
  if (ignored) {
    throw new Error('str length is not divisible by 4');
  }
  const values = [];
  const index = str.length - 1;
  for (let i = 0; i <= index; i += 4) {
    const a = chars.indexOf(str.charAt(i));
    const b = chars.indexOf(str.charAt(i + 1));
    const c = chars.indexOf(str.charAt(i + 2));
    const d = chars.indexOf(str.charAt(i + 3));
    const combined = (a * 64 + b) * 64 + (c * 4 + d);
    values.push((combined >> 16) & 0xff, (combined >> 8) & 0xff, combined & 0xff);
  }
  return new Uint8Array(values);
}

async function searchWeb(query) {
  if (!ENABLE_WEB) return null;
  const searchProviders = [
    () => `https://www.googleapis.com/customsearch/v1?q=${encodeURIComponent(query)}&key=${GOOGLE_CUSTOM_SEARCH_KEY}`,
    () => `https://api.duckduckgo.com/?q=${encodeURIComponent(query)}&format=json&pretty=1`,
    () => `https://www.googleapis.com/customsearch/v1?q=${encodeURIComponent(query)}&key=${GOOGLE_CUSTOM_SEARCH_API_KEY}`,
  ];
  
  const promises = searchProviders.map((provider) => {
    try {
      const url = provider();
      return fetch(url, {
        headers: {'user-agent': 'Mozilla/5.0'},
        signal: AbortSignal.timeout(5000),
      })
        .then((resp) => resp.ok && resp.json())
        .then((data) => {
          if (data && Array.isArray(data.items)) return data.items.slice(0, 3).map((item) => item.snippet || item.title).join(' ');
          if (data && data.Abstract) return data.Abstract;
          return null;
        })
        .catch(() => null);
    } catch (e) {
      return null;
    }
  });

  const results = await Promise.all(promises);
  for (const result of results) {
    if (result && result.length > 30) return result;
  }

  return null;
}

async function callOpenRouter(messages, options = {}) {
  if (!OPENROUTER_API_KEY) throw new Error('OPENROUTER_API_KEY not set');
  const defaultOptions = {
    model: OPENROUTER_MODEL,
    stream: false,
    max_tokens: 500,
    temperature: 0.1,
    timeout: 30000,
  };
  const config = { ...defaultOptions, ...options };
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), config.timeout);

  const headers = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${OPENROUTER_API_KEY}`,
    'HTTP-Referer': 'https://ai.acronous.com',
    'X-Title': 'Acronous AI',
  }

  const response = await fetch(`${OPENROUTER_BASE_URL}/chat/completions`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      messages,
      model: config.model,
      stream: config.stream,
      max_tokens: config.max_tokens,
      temperature: config.temperature,
    }),
    signal: controller.signal,
  });
  clearTimeout(timeoutId);

  if (!response.ok) throw new Error(`OpenRouter API error: ${response.status}`);
  const data = await response.json();

  if (!data || !data.choices || data.choices.length === 0) throw new Error('Invalid response from OpenRouter');
  return data;
}

function sanitizeText(text) {
  if (!text) return '';
  return text
    .replace(/\\u003cthinking\\u003e.*?\\u003c\\u002fthinking\\u003e/gi, '')
    .replace(/\\[.*?\\]/gi, '')
    .replace(/\\u003c.*?\\u003e/gi, '')
    .trim();
}

function buildMultimodalContent(text, base64Image, mimeType) {
  const base = encodeURIComponent(text);
  const imageData = base64Image.replace(/\\n/g, '');
  return `data:image/${mimeType};base64,${imageData},${base}`;
}

async function pollinationsImage(prompt, options = {}) {
  try {
    const retries = options.retries || 1;
    for (let attempt = 0; attempt < retries; attempt++) {
      const encoded = encodeURIComponent(prompt);
      const url = `https://image.pollinations.ai/prompt/${encoded}`;
      const resp = await fetch(url, {
        headers: {
          'User-Agent': 'Mozilla/5.0',
          'Accept': 'image/png,image/jpeg,image/webp,image/*',
        },
        signal: AbortSignal.timeout(30000),
      });
      if (resp.ok) {
        const ct = resp.headers.get('content-type') || '';
        if (ct.startsWith('image/')) {
          const blob = await resp.blob();
          return await blob.arrayBuffer();
        }
      }
    }
    return null;
  } catch (e) {
    return null;
  }
}

async function pollinationsImg2img(base64Image, prompt, mimeType) {
  try {
    const encodedImage = encodeURIComponent(base64Image);
    const encodedPrompt = encodeURIComponent(prompt);
    const width = prompt.toLowerCase().includes('square') ? 1024 : 768;
    const height = prompt.toLowerCase().includes('square') ? 1024 : 768;
    
    const url = `https://image.pollinations.ai/prompt/${encodedPrompt}&model=flux&width=${width}&height=${height}&img=data:image/${mimeType};base64,${encodedImage}`;
    
    const resp = await fetch(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'image/png,image/jpeg,image/webp,image/*',
      },
      signal: AbortSignal.timeout(60000),
    });
    
    if (resp.ok) {
      const ct = resp.headers.get('content-type') || '';
      if (ct.startsWith('image/')) {
        const blob = await resp.blob();
        return await blob.arrayBuffer();
      }
    }
    return null;
  } catch (e) {
    return null;
  }
}

async function callWorkersAIImageEdit(imageBuffer, prompt, mimeType) {
  try {
    const formData = new FormData();
    const blob = new Blob([imageBuffer], { type: `image/${mimeType || 'png'}` });
    formData.append('file', blob, `image.${mimeType || 'png'}`);
    formData.append('prompt', prompt);

    const resp = await fetch('https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/stable-diffusion-xl-1024-test', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${CLOUDFLARE_API_KEY}`,
      },
      body: formData,
      signal: AbortSignal.timeout(120000),
    });

    if (resp.ok) {
      const data = await resp.json();
      if (data && data.result) {
        const base64Result = data.result.split(',')[1];
        if (base64Result) {
          return base64ToArrayBuffer(base64Result);
        }
      }
    }
    return null;
  } catch (e) {
    return null;
  }
}