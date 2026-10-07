const CATEGORIES = [
  "hospital", "restaurant", "pharmacy", "school", "bank_atm",
  "place_of_worship", "supermarket", "gas_station", "police", "gym", "park",
];

const categoriesFieldset = document.getElementById("categories");
for (const category of CATEGORIES) {
  const label = document.createElement("label");
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.value = category;
  checkbox.checked = true;
  label.appendChild(checkbox);
  label.append(" " + category);
  categoriesFieldset.appendChild(label);
}

const map = L.map("map").setView([-6.2, 106.8], 14);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

let markers = [];
const statusEl = document.getElementById("status");

document.getElementById("use-location").addEventListener("click", () => {
  if (!("geolocation" in navigator)) {
    statusEl.textContent = "Geolocation is not available in this browser.";
    statusEl.hidden = false;
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (position) => {
      document.getElementById("lat").value = position.coords.latitude;
      document.getElementById("lng").value = position.coords.longitude;
    },
    () => {
      statusEl.textContent = "Could not get your location.";
      statusEl.hidden = false;
    }
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

  const submitButton = event.submitter || document.querySelector("#search-form [type=submit]");
  submitButton.disabled = true;
  statusEl.className = "loading";
  statusEl.textContent = "Searching… first searches in a new area can take up to 30 seconds.";
  statusEl.hidden = false;
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
    statusEl.className = "";
    statusEl.textContent = err.message;
    statusEl.hidden = false;
    return;
  } finally {
    submitButton.disabled = false;
  }

  statusEl.className = "";
  statusEl.hidden = true;

  markers.forEach((marker) => map.removeLayer(marker));
  markers = [];

  const resultsList = document.getElementById("results");
  resultsList.innerHTML = "";

  for (const place of data.results) {
    const item = document.createElement("li");
    item.textContent = `${place.name} (${place.category}) - ${place.distance_m}m` +
      (place.phone ? ` - ${place.phone}` : "");
    const source = document.createElement("span");
    source.className = "source";
    source.textContent = ` [${place.source}]`;
    item.appendChild(source);
    resultsList.appendChild(item);

    const marker = L.marker([place.location.lat, place.location.lng])
      .addTo(map)
      .bindPopup(place.name);
    markers.push(marker);
  }

  if (data.partial) {
    statusEl.textContent = "Some categories could not be freshly fetched — results may be incomplete.";
    statusEl.hidden = false;
  }

  map.setView([parseFloat(lat), parseFloat(lng)], 14);
});
