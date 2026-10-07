const CATEGORIES = [
  "hospital", "restaurant", "pharmacy", "school", "bank_atm",
  "place_of_worship", "supermarket", "gas_station", "police", "gym", "park",
  "cafe", "clinic", "convenience_store",
];

const LABELS = {
  bank_atm: "Bank / ATM",
  place_of_worship: "Place of worship",
  gas_station: "Gas station",
  convenience_store: "Convenience store",
};

function labelFor(category) {
  if (LABELS[category]) return LABELS[category];
  return category.charAt(0).toUpperCase() + category.slice(1);
}

function formatDistance(meters) {
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${meters} m`;
}

const categoriesFieldset = document.getElementById("categories");
for (const category of CATEGORIES) {
  const label = document.createElement("label");
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.value = category;
  checkbox.checked = true;
  label.appendChild(checkbox);
  label.append(" " + labelFor(category));
  categoriesFieldset.appendChild(label);
}

function setAllCategories(checked) {
  categoriesFieldset
    .querySelectorAll("input[type=checkbox]")
    .forEach((input) => { input.checked = checked; });
}
document.getElementById("select-all").addEventListener("click", () => setAllCategories(true));
document.getElementById("select-none").addEventListener("click", () => setAllCategories(false));

const map = L.map("map").setView([-6.2, 106.8], 14);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

let markers = [];
let originLayer = null;
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");

function showStatus(message, loading = false) {
  statusEl.className = loading ? "loading" : "";
  statusEl.textContent = message;
  statusEl.hidden = false;
}

function hideStatus() {
  statusEl.className = "";
  statusEl.hidden = true;
}

function popupContent(place) {
  const root = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = place.name;
  root.appendChild(title);
  const lines = [
    `${labelFor(place.category)} · ${formatDistance(place.distance_m)}`,
    place.phone,
    place.opening_hours && `Hours: ${place.opening_hours}`,
    place.rating != null && `Rating: ${place.rating}`,
  ].filter(Boolean);
  for (const line of lines) {
    root.appendChild(document.createElement("br"));
    root.append(line);
  }
  return root;
}

document.getElementById("use-location").addEventListener("click", () => {
  if (!("geolocation" in navigator)) {
    showStatus("Geolocation is not available in this browser.");
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (position) => {
      document.getElementById("lat").value = position.coords.latitude.toFixed(6);
      document.getElementById("lng").value = position.coords.longitude.toFixed(6);
      hideStatus();
    },
    () => showStatus("Could not get your location.")
  );
});

document.getElementById("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();

  const lat = document.getElementById("lat").value;
  const lng = document.getElementById("lng").value;
  const radius = document.getElementById("radius").value;
  const selected = Array.from(
    categoriesFieldset.querySelectorAll("input:checked")
  ).map((input) => input.value);

  if (selected.length === 0) {
    showStatus("Select at least one category.");
    return;
  }

  const submitButton = event.submitter || document.getElementById("search-button");
  submitButton.disabled = true;
  showStatus("Searching… first searches in a new area can take up to 30 seconds.", true);
  const params = new URLSearchParams({ lat, lng, radius, categories: selected.join(",") });

  let data;
  try {
    const response = await fetch(`/api/places?${params}`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${response.status})`);
    }
    data = await response.json();
  } catch (err) {
    showStatus(err.message);
    return;
  } finally {
    submitButton.disabled = false;
  }

  hideStatus();
  history.replaceState(null, "", `?${params}`);

  markers.forEach((marker) => map.removeLayer(marker));
  markers = [];
  if (originLayer) map.removeLayer(originLayer);

  const center = [parseFloat(lat), parseFloat(lng)];
  const radiusMeters = parseInt(radius, 10) || 1500;
  originLayer = L.circle(center, {
    radius: radiusMeters,
    color: "#2563eb",
    weight: 1,
    fillOpacity: 0.05,
  }).addTo(map);

  const resultsList = document.getElementById("results");
  resultsList.innerHTML = "";

  if (data.results.length === 0) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "No places found in this radius for the selected categories.";
    resultsList.appendChild(empty);
  }

  for (const place of data.results) {
    const marker = L.marker([place.location.lat, place.location.lng])
      .addTo(map)
      .bindPopup(popupContent(place));
    markers.push(marker);

    const item = document.createElement("li");
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = place.name;
    const meta = document.createElement("div");
    meta.className = "meta";
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = labelFor(place.category);
    meta.appendChild(tag);
    meta.append(formatDistance(place.distance_m) + (place.phone ? ` · ${place.phone}` : ""));
    item.append(name, meta);
    item.addEventListener("click", () => {
      map.flyTo([place.location.lat, place.location.lng], Math.max(map.getZoom(), 16));
      marker.openPopup();
    });
    resultsList.appendChild(item);
  }

  const count = data.results.length;
  summaryEl.textContent =
    `${count} place${count === 1 ? "" : "s"} within ${formatDistance(radiusMeters)}`;
  summaryEl.hidden = false;

  if (data.partial) {
    showStatus("Some categories could not be freshly fetched — results may be incomplete.");
  }

  map.fitBounds(originLayer.getBounds());
});

// Shareable links: ?lat=..&lng=..[&radius=..][&categories=a,b] pre-fills and runs a search.
const initial = new URLSearchParams(window.location.search);
if (initial.has("lat") && initial.has("lng")) {
  document.getElementById("lat").value = initial.get("lat");
  document.getElementById("lng").value = initial.get("lng");
  if (initial.has("radius")) document.getElementById("radius").value = initial.get("radius");
  if (initial.has("categories")) {
    const wanted = new Set(initial.get("categories").split(","));
    categoriesFieldset.querySelectorAll("input[type=checkbox]").forEach((input) => {
      input.checked = wanted.has(input.value);
    });
  }
  document.getElementById("search-form").requestSubmit();
}
