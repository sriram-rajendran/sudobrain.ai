const api = "http://127.0.0.1:8420";

async function getJson(path) {
  const response = await fetch(`${api}${path}`);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

async function postJson(path, payload = {}) {
  const response = await fetch(`${api}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : response.text();
}

function render(id, value) {
  document.getElementById(id).textContent = JSON.stringify(value, null, 2);
}

function renderText(id, value) {
  document.getElementById(id).textContent = value;
}

async function refresh() {
  try {
    render("health", await getJson("/health"));
    render("briefing", await getJson("/briefing/morning"));
    render("sources", await getJson("/sources/freshness"));
  } catch (error) {
    render("health", { error: error.message });
  }
}

async function search() {
  const query = document.getElementById("query").value.trim();
  if (!query) return;
  try {
    render("results", await getJson(`/search?q=${encodeURIComponent(query)}`));
  } catch (error) {
    render("results", { error: error.message });
  }
}

async function capture() {
  const text = document.getElementById("captureText").value.trim();
  const source = document.getElementById("captureSource").value;
  if (!text) return;
  try {
    const path = source === "mobile" || source === "web" ? "/capture/mobile" : `/capture/channel/${encodeURIComponent(source)}`;
    const payload = source === "mobile" || source === "web"
      ? { text, source }
      : { text, sender: "web-companion" };
    render("captureResult", await postJson(path, payload));
    document.getElementById("captureText").value = "";
  } catch (error) {
    render("captureResult", { error: error.message });
  }
}

async function ask() {
  const query = document.getElementById("chatQuery").value.trim();
  const mode = document.getElementById("chatMode").value;
  if (!query) return;
  renderText("chatAnswer", "");
  render("chatSources", []);
  try {
    if (mode === "offline") {
      const result = await postJson("/chat", { query, offline: true, collection: "web-companion" });
      renderText("chatAnswer", result.answer || "");
      render("chatSources", result.sources || []);
      return;
    }

    const response = await fetch(`${api}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, collection: "web-companion" })
    });
    if (!response.ok || !response.body) throw new Error(`${response.status} ${response.statusText}`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop();
      for (const event of events) {
        const line = event.split("\n").find(item => item.startsWith("data: "));
        if (!line) continue;
        const payload = JSON.parse(line.slice(6));
        if (payload.type === "metadata") render("chatSources", payload.sources || []);
        if (payload.type === "token") {
          document.getElementById("chatAnswer").textContent += payload.text;
        }
      }
    }
  } catch (error) {
    renderText("chatAnswer", `Error: ${error.message}`);
  }
}

async function exportWeeklyReport() {
  try {
    render("actionResult", await postJson("/reports/weekly/share"));
  } catch (error) {
    render("actionResult", { error: error.message });
  }
}

async function exportVault() {
  try {
    render("actionResult", await postJson("/knowledge/vault/export"));
  } catch (error) {
    render("actionResult", { error: error.message });
  }
}

document.getElementById("refresh").addEventListener("click", refresh);
document.getElementById("search").addEventListener("click", search);
document.getElementById("capture").addEventListener("click", capture);
document.getElementById("ask").addEventListener("click", ask);
document.getElementById("weeklyReport").addEventListener("click", exportWeeklyReport);
document.getElementById("vaultExport").addEventListener("click", exportVault);
document.getElementById("query").addEventListener("keydown", event => {
  if (event.key === "Enter") search();
});
document.getElementById("chatQuery").addEventListener("keydown", event => {
  if (event.key === "Enter") ask();
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./service-worker.js").catch(() => {});
}

refresh();
