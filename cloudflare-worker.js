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