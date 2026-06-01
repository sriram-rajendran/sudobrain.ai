const api = "http://127.0.0.1:8420";

async function getJson(path) {
  const response = await fetch(`${api}${path}`);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function render(id, value) {
  document.getElementById(id).textContent = JSON.stringify(value, null, 2);
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

document.getElementById("refresh").addEventListener("click", refresh);
document.getElementById("search").addEventListener("click", search);
document.getElementById("query").addEventListener("keydown", event => {
  if (event.key === "Enter") search();
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./service-worker.js").catch(() => {});
}

refresh();
