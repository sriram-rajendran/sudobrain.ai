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
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const text = info.selectionText;
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
      captureText = `idea: [Decision] ${text}`;
      break;
    case "capture-raw":
      captureText = text;
      break;
  }

  sendToSudoBrain(captureText, tab?.url || "");
});

async function sendToSudoBrain(text, sourceUrl) {
  try {
    const response = await fetch(`${API_BASE}/capture`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
    });

    if (response.ok) {
      const result = await response.json();
      console.log("[SudoBrain] Captured:", result);
    } else {
      console.error("[SudoBrain] Capture failed:", response.status);
    }
  } catch (error) {
    console.error("[SudoBrain] Cannot reach backend:", error.message);
  }
}

// Listen for messages from popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "capture") {
    sendToSudoBrain(message.text, message.url || "");
    sendResponse({ status: "sent" });
  } else if (message.action === "health") {
    fetch(`${API_BASE}/health`)
      .then((r) => r.json())
      .then((data) => sendResponse(data))
      .catch((e) => sendResponse({ status: "offline", error: e.message }));
    return true; // async response
  }
});
