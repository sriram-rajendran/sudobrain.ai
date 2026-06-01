const API_BASE = "http://127.0.0.1:8420";

// Context menu: right-click selected text to capture
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "capture-task",
    title: "SudoBrain: Save as Task",
    contexts: ["selection"],
  });
  chrome.contextMenus.create({
    id: "capture-idea",
    title: "SudoBrain: Save as Idea",
    contexts: ["selection"],
  });
  chrome.contextMenus.create({
    id: "capture-decision",
    title: "SudoBrain: Save as Decision",
    contexts: ["selection"],
  });
  chrome.contextMenus.create({
    id: "capture-raw",
    title: "SudoBrain: Capture Text",
    contexts: ["selection"],
  });
  chrome.contextMenus.create({
    id: "capture-page",
    title: "SudoBrain: Capture Page",
    contexts: ["page"],
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const text = info.selectionText || tab?.title || tab?.url || "";
  if (!text) return;

  let captureText = text;
  switch (info.menuItemId) {
    case "capture-task":
      captureText = `todo: ${text}`;
      break;
    case "capture-idea":
      captureText = `idea: ${text}`;
      break;
    case "capture-decision":
      captureText = `decision: ${text}`;
      break;
    case "capture-raw":
      captureText = text;
      break;
    case "capture-page":
      captureText = `idea: ${tab?.title || "Web page"}\n${tab?.url || ""}`;
      break;
  }

  sendToSudoBrain(captureText, { sourceUrl: tab?.url || "", sourceTitle: tab?.title || "" });
});

async function sendToSudoBrain(text, meta = {}) {
  try {
    const response = await fetch(`${API_BASE}/capture`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: text,
        source_url: meta.sourceUrl || "",
        source_title: meta.sourceTitle || "",
        project: meta.project || "",
        person: meta.person || "",
      }),
    });

    if (response.ok) {
      const result = await response.json();
      rememberCapture(text, meta, result);
      console.log("[SudoBrain] Captured:", result);
    } else {
      console.error("[SudoBrain] Capture failed:", response.status);
    }
  } catch (error) {
    console.error("[SudoBrain] Cannot reach backend:", error.message);
  }
}

function rememberCapture(text, meta, result) {
  chrome.storage.local.get({ history: [] }, ({ history }) => {
    const next = [{
      text: text.slice(0, 160),
      type: result?.type || "capture",
      sourceUrl: meta.sourceUrl || "",
      sourceTitle: meta.sourceTitle || "",
      at: new Date().toISOString(),
    }, ...history].slice(0, 10);
    chrome.storage.local.set({ history: next });
  });
}

// Listen for messages from popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "capture") {
    sendToSudoBrain(message.text, message.meta || {});
    sendResponse({ status: "sent" });
  } else if (message.action === "health") {
    fetch(`${API_BASE}/health`)
      .then((r) => r.json())
      .then((data) => sendResponse(data))
      .catch((e) => sendResponse({ status: "offline", error: e.message }));
    return true; // async response
  } else if (message.action === "history") {
    chrome.storage.local.get({ history: [] }, (data) => sendResponse(data));
    return true;
  }
});
