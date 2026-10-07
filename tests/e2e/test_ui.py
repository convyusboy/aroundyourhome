import pytest

pytest.importorskip("playwright")
from playwright.sync_api import expect  # noqa: E402


def fill_and_search(page, lat="-6.9175", lng="107.6191", radius="1500"):
    page.fill("#lat", lat)
    page.fill("#lng", lng)
    page.fill("#radius", radius)
    page.click("#search-button")


def test_renders_category_checkboxes_all_checked(page, base_url, mock_api):
    page.goto(base_url)
    boxes = page.locator("#categories input[type=checkbox]")
    assert boxes.count() == 14
    assert page.locator("#categories input:checked").count() == 14


def test_select_none_and_all(page, base_url, mock_api):
    page.goto(base_url)
    page.click("#select-none")
    assert page.locator("#categories input:checked").count() == 0
    page.click("#select-all")
    assert page.locator("#categories input:checked").count() == 14


def test_search_lists_results_and_markers(page, base_url, mock_api):
    page.goto(base_url)
    fill_and_search(page)

    items = page.locator("#results li")
    expect(items).to_have_count(2)
    expect(items.first).to_contain_text("Apotek Sehat")
    expect(items.first).to_contain_text("120 m")
    expect(items.nth(1)).to_contain_text("1.4 km")
    expect(page.locator("#summary")).to_have_text("2 places within 1.5 km")
    expect(page.locator(".leaflet-marker-icon")).to_have_count(2)
    expect(page.locator("#status")).to_be_hidden()


def test_request_carries_form_values(page, base_url, mock_api):
    page.goto(base_url)
    page.click("#select-none")
    page.check("#categories input[value=cafe]")
    fill_and_search(page, radius="900")
    expect(page.locator("#results li").first).to_be_visible()

    url = mock_api["requests"][-1]
    assert "lat=-6.9175" in url and "radius=900" in url and "categories=cafe" in url


def test_shows_loading_state_and_disables_button_while_searching(page, base_url, mock_api):
    mock_api["delay"] = 1.0
    page.goto(base_url)
    fill_and_search(page)

    expect(page.locator("#status")).to_contain_text("Searching")
    expect(page.locator("#search-button")).to_be_disabled()
    expect(page.locator("#results li").first).to_be_visible()
    expect(page.locator("#search-button")).to_be_enabled()
    expect(page.locator("#status")).to_be_hidden()


def test_empty_results_message(page, base_url, mock_api):
    mock_api["body"] = {"query": {}, "partial": False, "results": []}
    page.goto(base_url)
    fill_and_search(page)

    expect(page.locator("#results li.empty")).to_contain_text("No places found")
    expect(page.locator("#summary")).to_have_text("0 places within 1.5 km")


def test_server_error_detail_is_shown(page, base_url, mock_api):
    mock_api["status"] = 400
    mock_api["body"] = {"detail": "radius must be between 100 and 10000 meters"}
    page.goto(base_url)
    fill_and_search(page, radius="150")

    expect(page.locator("#status")).to_have_text("radius must be between 100 and 10000 meters")
    expect(page.locator("#search-button")).to_be_enabled()


def test_partial_results_warning(page, base_url, mock_api):
    mock_api["body"] = {"query": {}, "partial": True, "results": []}
    page.goto(base_url)
    fill_and_search(page)

    expect(page.locator("#status")).to_contain_text("may be incomplete")


def test_requires_at_least_one_category(page, base_url, mock_api):
    page.goto(base_url)
    page.click("#select-none")
    fill_and_search(page)

    expect(page.locator("#status")).to_have_text("Select at least one category.")
    assert mock_api["requests"] == []


def test_clicking_a_result_opens_its_popup(page, base_url, mock_api):
    page.goto(base_url)
    fill_and_search(page)
    page.locator("#results li").first.click()

    expect(page.locator(".leaflet-popup-content")).to_contain_text("Apotek Sehat")
    expect(page.locator(".leaflet-popup-content")).to_contain_text("Hours: Mo-Su 08:00-21:00")


def test_shareable_link_prefills_and_runs_search(page, base_url, mock_api):
    page.goto(f"{base_url}/?lat=-6.9175&lng=107.6191&radius=1000&categories=cafe,clinic")

    expect(page.locator("#results li").first).to_be_visible()
    assert page.input_value("#radius") == "1000"
    checked = page.locator("#categories input:checked")
    assert sorted(el.get_attribute("value") for el in checked.all()) == ["cafe", "clinic"]
    assert "categories=cafe%2Cclinic" in mock_api["requests"][-1]


def test_successful_search_updates_url_for_sharing(page, base_url, mock_api):
    page.goto(base_url)
    fill_and_search(page)
    expect(page.locator("#results li").first).to_be_visible()

    assert "lat=-6.9175" in page.url and "lng=107.6191" in page.url


def test_result_text_is_not_interpreted_as_html(page, base_url, mock_api):
    mock_api["body"] = {"query": {}, "partial": False, "results": [{
        **{"category": "cafe", "distance_m": 5, "location": {"lat": -6.9, "lng": 107.6},
           "phone": None, "opening_hours": None, "rating": None, "gojek_link": None, "source": "osm"},
        "name": "<img src=x onerror=window.__xss=1>",
    }]}
    page.goto(base_url)
    fill_and_search(page)

    expect(page.locator("#results li .name")).to_have_text("<img src=x onerror=window.__xss=1>")
    assert page.evaluate("window.__xss") is None
