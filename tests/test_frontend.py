import asyncio
import re
from pathlib import Path

import pytest

from src import main as main_module
from src.main import create_app

PAGE = Path(main_module.__file__).resolve().parent / "static" / "index.html"

# The ids of the controls the page is built around.
MAIN_CONTROL_IDS = [
    # Slice 10: "error-area" (an inline box) became the "error-dialog" popup, and "group-status"
    # became "status-badge". Both new ids are in the list below.
    "start-screen",
    "display-name",
    "restaurant-select",
    "create-button",  # create a group order
    "share-code-input",
    "join-button",  # join with a code
    "group-screen",
    "share-code",  # the big code
    "delivery-fee",
    "menu-list",  # one add-item row per menu item
    "my-items",
    "summary-table",
    "summary-body",
    "refresh-button",
    "lock-button",
    "address-input",
    "checkout-button",
    "order-result",
    # --- added by the redesign (Slice 10)
    "error-dialog",
    "error-title",
    "error-ok",
    "receipt-dialog",
    "receipt-close",
    "receipt-order-id",
    "receipt-restaurant",
    "receipt-lines",
    "receipt-subtotal",
    "receipt-fee",
    "receipt-total",
    "receipt-group-total",
    "view-receipt-button",
    "toast-region",
    "status-badge",
    "copy-button",
    "restaurant-name",
    "summary-region",
    "summary-foot",
    "topbar",
    # --- added with leaving a group and removing a participant
    "leave-button",
    "people-list",
    "confirm-dialog",
    "confirm-title",
    "confirm-text",
    "confirm-ok",
    "confirm-cancel",
]

# CSS classes the script puts on the controls it creates for each menu item / own item.
DYNAMIC_CONTROL_CLASSES = [
    "add-item-button", "change-quantity-button", "remove-item-button",
    "quantity-stepper",  # Slice 10: the quantity <select> ("quantity-select") became a +/- stepper
]

ERROR_CODES = [
    "INVALID_SESSION", "RESTAURANT_NOT_FOUND", "INVALID_CODE", "GROUP_FULL", "ALREADY_JOINED", "ORDER_LOCKED",
    "ORDER_EXPIRED", "ORDER_CHECKED_OUT", "INVALID_QUANTITY", "ITEM_NOT_ON_MENU", "NOT_ALLOWED", "NOT_HOST",
    "EMPTY_PARTICIPANT", "NOT_LOCKED", "RESTAURANT_CLOSED", "INVALID_ADDRESS",
]


# A tiny ASGI client that also returns the headers (conftest's client does not).
def fetch(app, method: str, path: str):
    async def call():
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
            "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
            "headers": [(b"host", b"testserver")], "client": ("testclient", 50000), "server": ("testserver", 80),
        }
        sent = False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.disconnect"}

        status, headers, chunks = 500, {}, []

        async def send(message):
            nonlocal status, headers
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = {k.decode().lower(): v.decode() for k, v in message["headers"]}
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        await app(scope, receive, send)
        return status, headers, b"".join(chunks)

    return asyncio.run(call())


@pytest.fixture
def page_text() -> str:
    return PAGE.read_text(encoding="utf-8")


@pytest.fixture
def html(app) -> str:
    status, _, body = fetch(app, "GET", "/")
    assert status == 200
    return body.decode("utf-8")


# ------------------------------------------------------------------ the route


def test_get_root_returns_200_with_html(app):
    status, headers, body = fetch(app, "GET", "/")

    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert "charset=utf-8" in headers["content-type"].lower()
    assert body.startswith(b"<!DOCTYPE html>")


def test_the_response_is_the_content_of_the_page_file(app, page_text):
    _, _, body = fetch(app, "GET", "/")

    assert body.decode("utf-8") == page_text


def test_the_page_file_is_in_src_static(page_text):
    assert PAGE.parts[-3:] == ("src", "static", "index.html")
    assert page_text.strip()


def test_the_page_needs_no_session_token(app):
    status, _, _ = fetch(app, "GET", "/")  # no X-Session-Token header

    assert status == 200


def test_the_file_is_read_on_each_request(app, tmp_path, monkeypatch):
    other = tmp_path / "index.html"
    other.write_text("<!DOCTYPE html><html><body>first</body></html>", encoding="utf-8")
    monkeypatch.setattr(main_module, "INDEX_PATH", other)

    assert b"first" in fetch(app, "GET", "/")[2]
    other.write_text("<!DOCTYPE html><html><body>second</body></html>", encoding="utf-8")
    assert b"second" in fetch(app, "GET", "/")[2]


def test_non_ascii_text_in_the_file_is_served_as_utf8(app, tmp_path, monkeypatch):
    other = tmp_path / "index.html"
    other.write_text("<!DOCTYPE html><html><body>café – ✓</body></html>", encoding="utf-8")
    monkeypatch.setattr(main_module, "INDEX_PATH", other)

    assert "café – ✓" in fetch(app, "GET", "/")[2].decode("utf-8")


def test_only_get_is_allowed_on_root(app):
    assert fetch(app, "POST", "/")[0] == 405
    assert fetch(app, "DELETE", "/")[0] == 405


def test_the_root_route_is_not_listed_in_the_api_docs(app):
    assert "/" not in app.openapi()["paths"]


def test_the_existing_routes_still_work(app):
    assert fetch(app, "GET", "/restaurants")[0] == 200
    assert fetch(app, "GET", "/orders/999")[0] == 404
    assert fetch(app, "GET", "/docs")[0] == 200


# ------------------------------------------------------------- the main controls


def test_the_page_is_a_complete_html_document(html):
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert re.search(r"<html[^>]*lang=", html)
    assert "<title>" in html and "</html>" in html
    assert "<meta charset" in html.lower()


@pytest.mark.parametrize("element_id", MAIN_CONTROL_IDS)
def test_the_page_has_the_element_with_this_id(html, element_id):
    assert re.search(rf'\bid="{re.escape(element_id)}"', html), element_id


def test_element_ids_are_unique(html):
    ids = re.findall(r'\bid="([^"]+)"', html)

    assert len(ids) == len(set(ids))


# Slice 10: errors are shown in one modal <dialog> instead of an inline "error-area".
def test_there_is_exactly_one_error_dialog_and_it_announces_errors(html):
    assert html.count('id="error-dialog"') == 1
    assert re.search(r'<dialog\b[^>]*\bid="error-dialog"', html)
    assert re.search(r'<dialog\b[^>]*\bid="error-dialog"[^>]*role="alertdialog"', html)


@pytest.mark.parametrize(
    ("element_id", "tag"),
    [
        ("create-button", "button"), ("join-button", "button"), ("lock-button", "button"),
        ("checkout-button", "button"), ("refresh-button", "button"), ("display-name", "input"),
        ("share-code-input", "input"), ("address-input", "input"), ("restaurant-select", "select"),
        ("summary-table", "table"), ("summary-body", "tbody"),
    ],
)
def test_main_controls_are_the_right_kind_of_element(html, element_id, tag):
    assert re.search(rf'<{tag}\b[^>]*\bid="{element_id}"', html), (element_id, tag)


def test_the_summary_table_has_the_four_columns(html):
    table = re.search(r'<table[^>]*id="summary-table".*?</table>', html, re.S).group(0)

    for heading in ["Name", "Subtotal", "Fee share", "Total"]:
        assert re.search(rf"<th[^>]*>\s*{heading}\s*</th>", table), heading


def test_the_script_builds_the_per_item_controls(html):
    for css_class in DYNAMIC_CONTROL_CLASSES:
        assert css_class in html, css_class


# Slice 10 changed this: quantities are a +/- stepper now, not a 1-9 dropdown, so the limits are constants.
def test_the_page_offers_quantities_1_to_9(html):
    assert re.search(r"MIN_QUANTITY\s*=\s*1\b", html)
    assert re.search(r"MAX_QUANTITY\s*=\s*9\b", html)
    assert re.search(r"Math\.min\(\s*MAX_QUANTITY", html) and re.search(r"Math\.max\(\s*MIN_QUANTITY", html)


def test_the_group_screen_starts_hidden(html):
    assert re.search(r'id="group-screen"[^>]*\bhidden\b', html)


# --------------------------------------------------- self-contained, no extras


def test_no_external_resources(html):
    assert not re.search(r"https?://", html)
    assert not re.search(r"<script[^>]*\bsrc=", html, re.I)
    assert not re.search(r"<link\b", html, re.I)
    assert "@import" not in html
    assert "url(" not in html
    assert "@font-face" not in html
    assert "//cdn" not in html


def test_exactly_one_inline_script_and_one_inline_style(html):
    assert len(re.findall(r"<script\b", html)) == 1
    assert len(re.findall(r"<style\b", html)) == 1


def test_the_session_token_is_kept_per_tab(html):
    assert "sessionStorage" in html
    assert "localStorage" not in html
    assert "document.cookie" not in html


@pytest.mark.parametrize(
    "forbidden",
    ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "dangerouslySet"],
)
def test_user_text_is_never_inserted_as_html(html, forbidden):
    assert forbidden not in html


def test_text_is_inserted_with_textContent(html):
    assert "textContent" in html


# Slice 10 changed this rule: the page now polls every 4 seconds and uses short timers (see the polling
# tests below), so setInterval/setTimeout are allowed. Push connections and frame loops are still not.
@pytest.mark.parametrize("forbidden", ["requestAnimationFrame", "EventSource", "WebSocket"])
def test_the_page_uses_no_push_connections_or_frame_loops(html, forbidden):
    assert forbidden not in html


# Slice 10 changed this rule: transitions of 150-200ms and a CSS spinner are now required, and they
# must switch off for prefers-reduced-motion (see the motion tests below). Nothing else may animate.
def test_the_only_keyframes_are_for_the_loading_spinner(html):
    assert re.findall(r"@keyframes\s+([\w-]+)", html) == ["spin"]


@pytest.mark.parametrize("forbidden", ["toFixed", "parseFloat", "Math.round", "Intl.NumberFormat", "toLocaleString"])
def test_money_is_formatted_from_whole_cents_without_float_helpers(html, forbidden):
    assert forbidden not in html


def test_there_is_a_money_formatting_function_that_works_on_cents(html):
    assert re.search(r"function formatMoney\(cents\)", html)
    assert "% 100" in html


def test_the_page_has_no_unlock_and_no_remove_other_participant_controls(html):
    assert "unlock" not in html.lower()
    assert not re.search(r"remove[- ]participant", html, re.I)


# ----------------------------------------------------- the API it talks to


def test_the_session_token_is_sent_in_the_x_session_token_header(html):
    assert "X-Session-Token" in html


@pytest.mark.parametrize(
    "fragment",
    [
        '"/restaurants"', "/menu", '"/sessions"', '"/group-orders"', "/join", "/participants/", "/items", "/summary",
        "/lock", "/checkout",
    ],
)
def test_the_page_calls_this_part_of_the_api(html, fragment):
    assert fragment in html, fragment


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE"])
def test_the_page_uses_this_http_method(html, method):
    assert re.search(rf'"{method}"', html), method


@pytest.mark.parametrize(
    "field",
    [
        "restaurant_id", "display_name", "participant_id", "menu_item_id", "quantity", "price_cents", "subtotal_cents",
        "fee_share_cents", "total_cents", "delivery_fee_cents", "order_id", "address", "token", "code",
    ],
)
def test_the_page_uses_this_api_field(html, field):
    assert field in html, field


def test_the_page_reads_the_error_code_of_the_shared_error_shape(html):
    assert "error.code" in html or ".error" in html


# ----------------------------------------------------------- error messages


@pytest.mark.parametrize("code", ERROR_CODES)
def test_every_listed_error_code_has_its_own_friendly_message(html, code):
    match = re.search(rf"\b{code}\s*:\s*(\"[^\"]{{15,}}\"|'[^']{{15,}}')", html)

    assert match, f"no message of at least 15 characters for {code}"


def test_unknown_codes_get_a_generic_message(html):
    assert re.search(r"Something went wrong", html)


def test_empty_participant_lists_the_names_from_the_error(html):
    assert "Missing: " in html  # the server's message names them after this text
    assert re.search(r"EMPTY_PARTICIPANT", html)


def test_a_network_failure_has_a_message(html):
    assert re.search(r"[Cc]ould not reach the server", html)


# ----------------------------------------------------------- after checkout


def test_after_checkout_the_order_id_is_shown_and_buttons_are_disabled(html):
    assert "order_id" in html
    assert re.search(r"\.disabled\s*=\s*true", html)
    assert 'id="order-result"' in html


def test_there_is_a_refresh_button_that_is_wired_up(html):  # renamed: the page polls now, see below
    assert 'id="refresh-button"' in html
    assert re.search(r"refresh-button.*?addEventListener|getElementById\(\"refresh-button\"\)", html, re.S)


# =====================================================================================
# Slice 10: professional redesign, error popups, receipt popup, live updates
# =====================================================================================

SPECIFIC_MESSAGES = {  # wording the spec asks for, word for word
    "ORDER_LOCKED": "The host has locked this order. Items can't be changed anymore.",
    "ORDER_CHECKED_OUT": "This order has already been placed.",
    "ORDER_EXPIRED": "This group order expired after 2 hours of inactivity.",
}


def block_after(text: str, opening: str) -> str:
    """The text between the braces that follow `opening` (handles nested braces)."""
    start = text.index(opening) + len(opening)
    depth, i = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[start : i - 1]


@pytest.fixture
def css(html) -> str:
    return re.search(r"<style>(.*?)</style>", html, re.S).group(1)


@pytest.fixture
def script(html) -> str:
    return re.search(r"<script>(.*?)</script>", html, re.S).group(1)


def tokens(block: str) -> dict:
    return {name: value.strip() for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block)}


@pytest.fixture
def light_tokens(css) -> dict:
    return tokens(block_after(css, ":root {"))


@pytest.fixture
def dark_tokens(css, light_tokens) -> dict:
    dark_media = block_after(css, "@media (prefers-color-scheme: dark) {")
    return {**light_tokens, **tokens(block_after(dark_media, ":root {"))}  # not overridden = same as light


def luminance(color: str) -> float:
    h = color.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# Every foreground/background pair the page uses for text. Names are CSS tokens.
TEXT_PAIRS = [
    ("--ink", "--bg"), ("--ink", "--surface"), ("--muted", "--bg"), ("--muted", "--surface"),
    ("--on-primary", "--primary"), ("--on-primary", "--primary-hover"),
    ("--open-fg", "--open-bg"), ("--locked-fg", "--locked-bg"), ("--expired-fg", "--expired-bg"),
    ("--done-fg", "--done-bg"), ("--success-fg", "--success-bg"), ("--danger-fg", "--danger-bg"),
    ("--toast-fg", "--toast-bg"), ("--ink", "--field-bg"), ("--muted", "--field-bg"),  # field text, placeholders
    ("--ink", "--highlight"),  # the row that is "you" in the summary
    ("--danger-fg", "--surface"), ("--danger-fg", "--highlight"),  # the Remove button, normal and on hover
]
# Focus rings, field borders and button edges only need 3:1 (WCAG non-text contrast).
EDGE_PAIRS = [("--focus", "--surface"), ("--focus", "--bg"), ("--field-border", "--field-bg"),
              ("--primary", "--surface"), ("--primary", "--bg")]


# ------------------------------------------------------------------ design tokens


def test_the_primary_color_is_c9331e_with_white_text(light_tokens):
    assert light_tokens["--primary"].upper() == "#C9331E"
    assert light_tokens["--on-primary"].upper() == "#FFFFFF"


@pytest.mark.parametrize("pair", TEXT_PAIRS, ids=lambda p: f"{p[0]}-on-{p[1]}")
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_text_and_background_pair_passes_wcag_aa(pair, theme, light_tokens, dark_tokens):
    palette = light_tokens if theme == "light" else dark_tokens
    foreground, background = palette[pair[0]], palette[pair[1]]

    assert contrast(foreground, background) >= 4.5, (theme, pair, foreground, background, contrast(foreground, background))


@pytest.mark.parametrize("pair", EDGE_PAIRS, ids=lambda p: f"{p[0]}-on-{p[1]}")
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_focus_rings_borders_and_button_edges_reach_3_to_1(pair, theme, light_tokens, dark_tokens):
    palette = light_tokens if theme == "light" else dark_tokens

    assert contrast(palette[pair[0]], palette[pair[1]]) >= 3.0, (theme, pair)


def test_white_text_on_the_primary_color_has_at_least_4_5_to_1(light_tokens):
    assert contrast("#FFFFFF", light_tokens["--primary"]) >= 4.5


def test_the_ink_is_near_black_and_cards_are_white_on_a_light_gray_page(light_tokens):
    assert luminance(light_tokens["--ink"]) < 0.02
    assert light_tokens["--surface"].upper() == "#FFFFFF"
    assert 0.85 < luminance(light_tokens["--bg"]) < 0.95


def test_there_is_a_dark_theme_with_its_own_tokens(css, light_tokens, dark_tokens):
    assert "@media (prefers-color-scheme: dark)" in css
    for name in ["--bg", "--surface", "--ink", "--muted", "--open-bg", "--locked-bg", "--danger-bg", "--toast-bg"]:
        assert dark_tokens[name] != light_tokens[name], name
    assert luminance(dark_tokens["--bg"]) < 0.05 < luminance(dark_tokens["--ink"])


@pytest.mark.parametrize(
    "name",
    ["--bg", "--surface", "--ink", "--muted", "--primary", "--primary-hover", "--on-primary", "--success-fg", "--success-bg",
     "--danger-fg", "--danger-bg", "--focus", "--border", "--field-border", "--field-bg", "--toast-fg", "--toast-bg",
     "--open-fg", "--open-bg", "--locked-fg", "--locked-bg", "--expired-fg", "--expired-bg", "--done-fg", "--done-bg",
     "--highlight", "--backdrop", "--font", "--tap", "--radius-sm", "--radius-md", "--radius-lg", "--shadow-sm", "--shadow-md", "--shadow-lg",
     "--text-xs", "--text-sm", "--text-base", "--text-lg", "--text-xl", "--text-2xl", "--text-code"],
)
def test_the_design_token_exists(light_tokens, name):
    assert name in light_tokens, name


def test_the_spacing_scale_is_in_steps_of_4_pixels(light_tokens):
    spacing = {k: v for k, v in light_tokens.items() if re.fullmatch(r"--space-\d+", k)}

    assert len(spacing) >= 6
    for name, value in spacing.items():
        assert re.fullmatch(r"\d+px", value), name
        assert int(value[:-2]) % 4 == 0, (name, value)
    assert "4px" in spacing.values() and "8px" in spacing.values()


def test_the_font_is_the_system_font_stack(light_tokens):
    font = light_tokens["--font"]

    assert font.startswith("system-ui")
    assert "sans-serif" in font


def test_no_color_is_written_outside_the_token_blocks(css):
    without_tokens = css.replace(block_after(css, ":root {"), "")
    dark_media = block_after(css, "@media (prefers-color-scheme: dark) {")
    without_tokens = without_tokens.replace(dark_media, "")

    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", without_tokens)
    assert not re.search(r"\b(rgb|rgba|hsl|hsla)\(", without_tokens)
    assert not re.search(r":\s*(white|black|red|green|blue|gray|grey)\b", without_tokens)


# ------------------------------------------------------- layout and responsiveness


def test_the_viewport_is_set_for_phones(html):
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html


def test_the_layout_goes_to_two_columns_from_about_900px(css):
    assert re.search(r"@media \(min-width: (8[5-9]\d|9\d\d)px\)", css)
    assert "grid-template-columns" in block_after(css, re.search(r"@media \(min-width: \d+px\) \{", css).group(0))


def test_the_default_layout_is_a_single_column(css):
    before_wide = css[: re.search(r"@media \(min-width: \d+px\)", css).start()]

    assert not re.search(r"\.layout\s*\{[^}]*grid-template-columns", before_wide)


def test_the_menu_is_on_the_left_and_the_summary_on_the_right(html):
    assert re.search(r'id="menu-column"', html) and re.search(r'id="summary-column"', html)
    assert html.index('id="menu-column"') < html.index('id="summary-column"')


def test_touch_targets_are_at_least_44px(css, light_tokens):
    assert light_tokens["--tap"] == "44px"
    for selector in ["button", "input", "select"]:
        assert re.search(rf"(^|[\s,}}]){selector}[^{{]*\{{[^}}]*min-height:\s*var\(--tap\)", css), selector
    assert re.search(r"\.stepper button[^{]*\{[^}]*min-width:\s*var\(--tap\)", css)


def test_the_page_cannot_scroll_sideways_on_a_phone(css):
    assert re.search(r"box-sizing:\s*border-box", css)
    assert re.search(r"overflow-wrap:\s*anywhere", css)
    assert re.search(r"max-width:\s*100%", css)
    assert "overflow-x: hidden" not in css  # hiding the overflow would only cover up a problem


def test_the_top_bar_is_sticky_and_holds_the_name_the_code_and_the_copy_button(html, css):
    assert re.search(r"#topbar\s*\{[^}]*position:\s*sticky", css)
    topbar = re.search(r'<header[^>]*id="topbar".*?</header>', html, re.S).group(0)
    assert "MiniDash" in topbar
    assert 'id="share-code"' in topbar and 'id="copy-button"' in topbar


def test_there_is_a_restaurant_header_card_with_the_status_badge(html):
    card = re.search(r'<section[^>]*id="restaurant-card".*?</section>', html, re.S).group(0)

    assert 'id="restaurant-name"' in card and 'id="status-badge"' in card and 'id="delivery-fee"' in card


def test_menu_items_are_cards_with_a_stepper_and_an_add_button(script):
    assert "menu-card" in script
    assert "quantity-stepper" in script and "add-item-button" in script
    assert re.search(r"MIN_QUANTITY", script) and re.search(r"MAX_QUANTITY", script)


def test_the_summary_table_has_a_bold_total_row(html, css):
    assert re.search(r'<tfoot[^>]*id="summary-foot"', html)
    assert re.search(r"tfoot[^{]*\{[^}]*font-weight:\s*(700|bold)", css)


# ----------------------------------------------------------- status badge, empty states


@pytest.mark.parametrize("label", ["Open", "Locked", "Expired", "Checked out"])
def test_the_status_badge_has_a_text_label_for_each_status(script, label):
    assert f'"{label}"' in script


@pytest.mark.parametrize("status", ["open", "locked", "expired", "done"])
def test_each_status_has_its_own_badge_color_class(css, status):
    assert f".badge-{status}" in css


def test_the_status_badge_is_never_color_only(script):
    # every status has a symbol next to its label
    assert re.search(r"OPEN:\s*\{[^}]*symbol", script) and re.search(r"CHECKED_OUT:\s*\{[^}]*symbol", script)


@pytest.mark.parametrize("empty_text", ["No items yet", "Nobody has joined", "menu"])
def test_empty_states_have_short_helpful_text(html, empty_text):
    assert empty_text.lower() in html.lower()


def test_loading_buttons_get_a_spinner_and_are_disabled_while_the_request_runs(css, script):
    assert ".is-loading::after" in css
    assert re.search(r"@keyframes spin", css)
    assert "is-loading" in script and "aria-busy" in script
    assert re.search(r"\.disabled\s*=\s*true", script)


# ------------------------------------------------------------------------- motion


def test_every_transition_lasts_150_to_200_ms(css):
    durations = [int(ms) for decl in re.findall(r"transition:([^;]+);", css) for ms in re.findall(r"(\d+)ms", decl)]

    assert durations, "no transitions found"
    assert all(150 <= ms <= 200 for ms in durations), durations


def test_there_is_no_transition_all(css):
    assert not re.search(r"transition:\s*all\b", css)


def test_reduced_motion_switches_off_transitions_and_animations(css):
    reduced = block_after(css, "@media (prefers-reduced-motion: reduce) {")

    assert re.search(r"transition:\s*none", reduced)
    assert re.search(r"animation:\s*none", reduced)


def test_the_toast_timer_also_respects_reduced_motion(script):
    assert "prefers-reduced-motion" in script  # skips the fade-out wait when motion is reduced


# -------------------------------------------------------------------- accessibility


def test_the_page_uses_semantic_landmarks(html):
    for landmark in ["<header", "<main", "<footer", "<nav" if False else "<section", "<h1", "<h2"]:
        assert landmark in html, landmark


def test_sections_are_labelled_by_their_headings(html):
    assert len(re.findall(r'<section[^>]*aria-labelledby="[\w-]+"', html)) >= 5


def test_every_input_and_select_has_a_label(html):
    controls = re.findall(r'<(?:input|select)\b[^>]*\bid="([\w-]+)"', html)

    assert len(controls) >= 4
    for control_id in controls:
        assert re.search(rf'<label[^>]*for="{control_id}"', html), control_id


def test_the_script_labels_the_controls_it_creates(script):
    assert script.count("aria-label") >= 3  # steppers and per-item buttons say which item they are for


def test_buttons_are_real_buttons_without_inline_handlers(html):
    assert not re.search(r'role="button"', html)
    assert not re.search(r"\bon(click|change|input|submit|load|error)\s*=", html)
    for button in re.findall(r"<button\b[^>]*>", html):
        assert 'type="button"' in button, button


def test_buttons_made_by_the_script_are_real_buttons_too(script):
    assert 'createElement("button")' in script and 'type = "button"' in script


def test_focus_is_always_visible(css):
    assert re.search(r":focus-visible\s*\{[^}]*outline:\s*3px solid var\(--focus\)", css)
    assert not re.search(r"outline:\s*(none|0)\b", css)


def test_the_summary_and_status_regions_are_polite_live_regions(html):
    assert re.search(r'id="summary-region"[^>]*aria-live="polite"|aria-live="polite"[^>]*id="summary-region"', html)
    assert re.search(r'id="status-region"[^>]*aria-live="polite"|aria-live="polite"[^>]*id="status-region"', html)
    assert re.search(r'id="toast-region"[^>]*aria-live="polite"|aria-live="polite"[^>]*id="toast-region"', html)


def test_the_page_never_uses_alert_confirm_or_prompt(html):
    for call in ["alert(", "confirm(", "prompt("]:
        assert call not in html, call


# ------------------------------------------------------------------- error popups


def test_the_error_dialog_has_a_title_a_message_and_an_ok_button(html):
    dialog = re.search(r'<dialog\b[^>]*id="error-dialog".*?</dialog>', html, re.S).group(0)

    assert 'aria-labelledby="error-title"' in dialog and 'aria-describedby="error-text"' in dialog
    assert re.search(r'<h2[^>]*id="error-title"', dialog) and re.search(r'id="error-text"', dialog)
    assert re.search(r'<button[^>]*id="error-ok"[^>]*>\s*OK\s*</button>', dialog)


def test_modals_use_the_native_dialog_element_with_showModal(script):
    assert script.count("showModal()") >= 3  # the error, receipt and confirm dialogs
    assert "dialog.open" in script or ".open" in script


def test_there_is_only_one_error_modal_and_it_is_reused(html, script):
    # error, receipt and (new) confirm: three dialogs in all, and only one of them shows errors
    assert html.count("<dialog") == 3
    assert html.count('id="error-dialog"') == 1
    assert re.search(r"if \(!\w+\.open\)", script)


def test_escape_and_ok_both_close_the_dialog_and_focus_goes_back(script):
    assert re.search(r'addEventListener\("close"', script)  # Esc and OK both end in the close event
    assert "focusKey" in script and ".focus()" in script


def test_focus_returns_to_a_stable_control_even_if_the_page_was_redrawn(script):
    assert "data-focus-key" in script or "dataset.focusKey" in script


@pytest.mark.parametrize("code", ERROR_CODES)
def test_every_error_code_has_a_title_and_a_message_of_its_own(script, code):
    titles = re.search(r"var TITLES = \{(.*?)\};", script, re.S).group(1)
    messages = re.search(r"var MESSAGES = \{(.*?)\};", script, re.S).group(1)

    assert re.search(rf'\b{code}\s*:\s*"[^"]{{3,}}"', titles), f"title for {code}"
    assert re.search(rf'\b{code}\s*:\s*"[^"]{{20,}}"', messages), f"message for {code}"


def test_every_error_message_is_different(script):
    messages = re.search(r"var MESSAGES = \{(.*?)\};", script, re.S).group(1)
    texts = re.findall(r':\s*"([^"]{20,})"', messages)

    assert len(texts) >= 16 and len(texts) == len(set(texts))


@pytest.mark.parametrize(("code", "wording"), SPECIFIC_MESSAGES.items())
def test_the_error_wording_asked_for_is_used_word_for_word(script, code, wording):
    assert re.search(rf'\b{code}\s*:\s*"{re.escape(wording)}"', script)


def test_the_connection_error_is_titled_cant_reach_the_server(script):
    assert re.search(r'NETWORK\s*:\s*"Can\'t reach the server"', script)


def test_unknown_codes_get_a_generic_title_and_message(script):
    assert re.search(r'GENERIC_TITLE\s*=\s*"Something went wrong"', script)


def test_empty_participant_lists_the_names_in_the_dialog(script):
    assert "Missing: " in script and "Still waiting on" in script


def test_only_one_error_modal_shows_at_a_time_and_poll_errors_do_not_repeat(script):
    assert "lastPollError" in script  # the same background error is not shown again every 4 seconds


# ---------------------------------------------------------------------------- toasts


def test_the_toast_region_is_fixed_and_toasts_disappear_after_about_3_seconds(html, css, script):
    assert re.search(r"#toast-region\s*\{[^}]*position:\s*fixed", css)
    assert re.search(r"var TOAST_MS = 3000;", script)
    assert re.search(r"setTimeout\([^;]*TOAST_MS", script)


@pytest.mark.parametrize("message", ["Item added", "Copied", "The host locked the order"])
def test_small_successes_use_a_toast(script, message):
    assert message in script


def test_the_copy_button_confirms_with_copied(script):
    assert "navigator.clipboard" in script
    assert re.search(r'"Copied"', script)


# ------------------------------------------------------------------------- live updates


def test_the_page_re_fetches_the_summary_every_4_seconds(script):
    assert re.search(r"var POLL_MS = 4000;", script)
    assert re.search(r"setTimeout\([^;]*POLL_MS", script) or re.search(r"setInterval\([^;]*POLL_MS", script)


def test_polling_pauses_while_the_tab_is_hidden_and_refreshes_when_it_is_visible_again(script):
    assert "document.hidden" in script
    assert re.search(r'addEventListener\("visibilitychange"', script)


def test_polling_stops_once_the_order_is_checked_out_or_expired(script):
    assert re.search(r"CHECKED_OUT", script) and re.search(r"EXPIRED", script)
    assert "TERMINAL" in script or "isFinal" in script


def test_polling_only_runs_while_the_group_screen_is_showing(script):
    assert re.search(r"group-screen", script) and "stopPolling" in script and "startPolling" in script


def test_a_poll_never_overlaps_a_user_action_or_another_poll(script):
    assert "polling" in script and "busy" in script


def test_the_page_is_read_only_when_the_order_is_not_open(script):
    assert re.search(r'status\s*!==\s*"OPEN"|isOpen', script)
    assert re.search(r"\.disabled\s*=", script)


def test_when_the_host_locks_other_pages_get_a_toast(script):
    assert "The host locked the order" in script


def test_the_expired_dialog_is_shown_once(script):
    assert "expiredShown" in script


# ----------------------------------------------------------------- host-only controls


def test_lock_and_checkout_are_hidden_for_people_who_are_not_the_host(html, script):
    assert "is_host" in script and "you" in script
    assert re.search(r'id="host-controls"[^>]*\bhidden\b|id="host-controls"', html)
    assert re.search(r"host-controls", script)


def test_the_page_knows_which_participant_is_me_from_the_summary(script):
    assert "summary.you" in script or ".you." in script


# ----------------------------------------------------------------------------- receipt


def test_the_receipt_dialog_has_the_order_id_restaurant_lines_and_totals(html):
    dialog = re.search(r'<dialog\b[^>]*id="receipt-dialog".*?</dialog>', html, re.S).group(0)

    for element_id in ["receipt-order-id", "receipt-restaurant", "receipt-lines", "receipt-subtotal", "receipt-fee",
                       "receipt-total", "receipt-group-total", "receipt-close"]:
        assert f'id="{element_id}"' in dialog, element_id
    assert "Order placed" in dialog and "Group total" in dialog
    assert re.search(r"Delivery fee share|Your delivery fee", dialog)


def test_the_receipt_total_is_large_and_bold_and_the_group_total_is_smaller(css):
    total = re.search(r"#receipt-total\s*\{([^}]*)\}", css).group(1)
    group = re.search(r"#receipt-group-total\s*\{([^}]*)\}", css).group(1)

    assert re.search(r"font-weight:\s*(700|800|bold)", total)
    assert "var(--text-2xl)" in total
    assert "var(--text-sm)" in group or "var(--text-xs)" in group


def test_the_receipt_is_shown_once_per_order_per_tab(script):
    assert "sessionStorage" in script and "minidash.receipt" in script
    assert "receiptShown" in script or "receiptKey" in script


def test_the_receipt_appears_for_everyone_not_only_the_one_who_clicked_checkout(script):
    assert re.search(r"CHECKED_OUT", script) and "showReceipt" in script
    assert script.count("showReceipt(") >= 2  # from the status check and from the View receipt button


def test_the_receipt_uses_the_order_id_and_names_from_the_summary(script):
    for field in ["summary.order_id", "summary.restaurant_name", "line_total_cents", "fee_share_cents", "subtotal_cents"]:
        assert field in script, field


def test_the_receipt_can_be_opened_again_after_it_was_closed(html, script):
    assert re.search(r'<button[^>]*id="view-receipt-button"[^>]*>\s*View receipt\s*</button>', html)
    assert "view-receipt-button" in script


def test_after_checkout_the_page_stays_read_only_with_the_badge_checked_out(script):
    assert "Checked out" in script and re.search(r'status\s*!==\s*"OPEN"|isOpen', script)


# ----------------------------------------------------------------------- size and data


# Slice 10 asked for "under about 900 lines". Leaving a group and removing people added the people list, a
# confirm dialog and their code, so the limit is now 1000.
def test_the_page_is_under_1000_lines(page_text):
    assert len(page_text.splitlines()) <= 1000


@pytest.mark.parametrize(
    "field",
    ["restaurant_name", "line_total_cents", "order_id", "you", "is_host", "name"],
)
def test_the_page_reads_the_new_summary_fields(script, field):
    assert field in script, field


def test_money_is_still_formatted_with_whole_cents_only(script):
    assert re.search(r"function formatMoney\(cents\)", script)
    assert "Number.isInteger(cents)" in script and "% 100" in script


# =====================================================================================
# Leaving a group, and the host removing a participant
# =====================================================================================

NEW_CODES = ["HOST_CANNOT_LEAVE", "PARTICIPANT_NOT_FOUND", "REMOVED_FROM_GROUP"]


@pytest.mark.parametrize("code", NEW_CODES)
def test_the_new_error_codes_have_a_title_and_a_message_of_their_own(script, code):
    titles = re.search(r"var TITLES = \{(.*?)\};", script, re.S).group(1)
    messages = re.search(r"var MESSAGES = \{(.*?)\};", script, re.S).group(1)

    assert re.search(rf'\b{code}\s*:\s*"[^"]{{3,}}"', titles), f"title for {code}"
    assert re.search(rf'\b{code}\s*:\s*"[^"]{{20,}}"', messages), f"message for {code}"


def test_the_removed_message_says_they_cannot_come_back(script):
    assert re.search(r'REMOVED_FROM_GROUP\s*:\s*"[^"]*can\'t join it again[^"]*"', script)


def test_there_is_a_leave_button_that_is_a_real_danger_styled_button(html):
    assert re.search(r'<button\b[^>]*\bid="leave-button"[^>]*type="button"[^>]*>\s*Leave group\s*</button>', html) or re.search(
        r'<button\b[^>]*\bid="leave-button"[^>]*>\s*Leave group\s*</button>', html
    )
    assert re.search(r'id="leave-button"[^>]*class="[^"]*btn-danger', html)


def test_the_host_does_not_see_the_leave_button(script):
    assert re.search(r'byId\("leave-button"\)\.hidden\s*=\s*summary\.you\.is_host', script)


def test_the_leave_button_is_disabled_unless_the_order_is_open(script):
    assert re.search(r'byId\("leave-button"\)\.disabled\s*=\s*!state\.isOpen', script)


def test_leaving_calls_the_leave_endpoint(script):
    assert re.search(r'api\("POST",\s*groupPath\(\)\s*\+\s*"/leave"\)', script)


def test_removing_a_person_calls_the_delete_participant_endpoint(script):
    assert re.search(r'api\("DELETE",\s*groupPath\(\)\s*\+\s*"/participants/"\s*\+\s*\w+(\.\w+)?\)', script)


def test_the_host_has_a_people_list_with_a_remove_button_for_everyone_else(html, script):
    assert re.search(r'<ul\b[^>]*\bid="people-list"', html)
    host_controls = re.search(r'<section[^>]*id="host-controls".*?</section>', html, re.S).group(0)
    assert 'id="people-list"' in host_controls  # so only the host sees it
    assert "remove-person-button" in script
    assert re.search(r"participant_id\s*!==\s*summary\.you\.participant_id", script)  # not a button for yourself


def test_the_remove_person_buttons_are_disabled_when_the_order_is_not_open(script):
    assert re.search(r'remove-person-button[^;]*js-mutating|js-mutating[^;]*remove-person-button', script)


def test_each_remove_button_says_who_it_removes(script):
    assert re.search(r'"Remove "\s*\+\s*\w+(\.\w+)?\s*\+\s*" from the group"', script)


def test_remove_buttons_use_a_stable_focus_key_per_person(script):
    assert re.search(r'"kick-"\s*\+', script)


def test_the_people_list_has_an_empty_state(html, script):
    assert "Nobody else has joined yet" in html


# ----------------------------------------------------------------- the confirm dialog


def test_leaving_and_removing_ask_first_in_a_native_dialog(html, script):
    dialog = re.search(r'<dialog\b[^>]*id="confirm-dialog".*?</dialog>', html, re.S).group(0)

    assert 'aria-labelledby="confirm-title"' in dialog and 'aria-describedby="confirm-text"' in dialog
    assert re.search(r'<button[^>]*id="confirm-cancel"[^>]*>\s*Cancel\s*</button>', dialog)
    assert 'id="confirm-ok"' in dialog
    assert "askConfirm" in script and "confirmDialog.showModal()" in script


def test_cancel_is_the_default_choice_in_the_confirm_dialog(html):
    dialog = re.search(r'<dialog\b[^>]*id="confirm-dialog".*?</dialog>', html, re.S).group(0)

    assert re.search(r'<button[^>]*id="confirm-cancel"[^>]*\bautofocus\b', dialog)  # focus starts on Cancel
    assert dialog.index('id="confirm-cancel"') < dialog.index('id="confirm-ok"')


def test_nothing_is_sent_until_the_person_confirms(script):
    # both flows return early unless the answer is yes, and only then reach the API call
    for flow, call in (("leaveFlow", '"/leave"'), ("removePerson", '"/participants/"')):
        body = re.search(rf"async function {flow}\(.*?\n\}}", script, re.S).group(0)
        assert re.search(r"if \(!\(await askConfirm\(", body), flow
        assert body.index("askConfirm(") < body.index("return;") < body.index(call), flow


def test_leaving_and_removing_say_what_will_happen_and_that_removed_people_cannot_return(script):
    assert "Leave this group order?" in script
    assert "Your items will be removed" in script
    assert re.search(r"won't be able to join (this group order )?again", script)


def test_closing_the_confirm_dialog_returns_focus_and_answers_no(script):
    assert re.search(r'confirmDialog\.addEventListener\("close"', script)
    assert "confirmReturnKey" in script


def test_the_confirm_dialog_uses_text_content_for_names(script):
    assert re.search(r'byId\("confirm-title"\)\.textContent', script) and re.search(r'byId\("confirm-text"\)\.textContent', script)


# ---------------------------------------------------- what happens on the page afterwards


def test_after_leaving_the_page_goes_back_to_the_start_screen(script):
    assert "resetToStart" in script
    reset = re.search(r"function resetToStart\(.*?\n\}", script, re.S).group(0)
    assert 'byId("start-screen").hidden = false' in reset and 'byId("group-screen").hidden = true' in reset
    assert "stopPolling()" in reset and "GROUP_KEY" in reset
    assert "You left the group order" in script


def test_a_removed_person_is_sent_back_to_the_start_screen_with_a_message(script):
    assert re.search(r'REMOVED_FROM_GROUP', script)
    assert re.search(r'code === "REMOVED_FROM_GROUP"', script)


def test_a_removal_found_by_polling_is_always_shown_even_if_another_popup_is_open(script):
    assert re.search(r'code === "REMOVED_FROM_GROUP"[^}]*handleError', script, re.S) or re.search(
        r'REMOVED_FROM_GROUP[^;]*;[^}]*handleError', script, re.S
    )


def test_the_host_gets_a_toast_when_someone_is_removed(script):
    assert re.search(r'display_name\s*\+\s*" was removed"', script)


def test_the_page_does_not_use_the_browser_confirm(html):
    assert "confirm(" not in html.replace("askConfirm(", "").replace("confirmed", "")
