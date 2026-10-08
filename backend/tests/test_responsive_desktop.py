import pytest
from decimal import Decimal
from playwright.sync_api import sync_playwright
from core.models import Product, Customer


@pytest.fixture
def setup_pos_products(db):
    Product.objects.all().delete()
    Customer.objects.all().delete()
    Customer.objects.create(
        name="Aling Susan",
        nickname="Susan",
        debt_balance=Decimal("50.00"),
        credit_limit=Decimal("500.00"),
        is_active=True
    )
    products = []
    for i in range(1, 10):
        products.append(
            Product.objects.create(
                sku=f"SKU-{i:03d}",
                name=f"Paninda Item {i}",
                wholesale_cost=Decimal("10.00"),
                retail_price=Decimal("15.00"),
                stock_quantity=Decimal("25.00"),
                reorder_point=5,
                category="General"
            )
        )
    return products


@pytest.mark.django_db(transaction=True)
def test_desktop_split_screen_layout_1920x1080(live_server, setup_pos_products):
    """
    Playwright test loading the POS UI in a 1920x1080 viewport.
    Verifies the desktop split-screen layout elements render side-by-side:
    Product selection / grid on the left and Cart on the right.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        page.goto(f"{live_server.url}/pos/")
        page.wait_for_selector("#pos-split-layout")
        page.wait_for_selector("#pos-catalog-column")
        page.wait_for_selector("#pos-cart-column")

        # 1. Bounding boxes verification for side-by-side split screen
        catalog_box = page.locator("#pos-catalog-column").bounding_box()
        cart_box = page.locator("#pos-cart-column").bounding_box()

        assert catalog_box is not None, "Catalog column must be rendered"
        assert cart_box is not None, "Cart column must be rendered"

        # Catalog must be on the left of cart
        assert catalog_box["x"] < cart_box["x"], (
            f"Catalog left ({catalog_box['x']}) must be to the left of Cart ({cart_box['x']})"
        )
        # Both rendered side-by-side across the 1920px canvas
        assert catalog_box["x"] + catalog_box["width"] <= cart_box["x"] + 60, (
            "Catalog column and Cart column must render side-by-side in 1920x1080"
        )

        # 2. Product grid presence and position
        grid_box = page.locator("#pos-product-grid").bounding_box()
        assert grid_box is not None, "Product grid must be visible"
        assert grid_box["x"] < cart_box["x"], "Product grid must be on the left pane"

        # 3. Interactivity check: Click quick-add button via HTMX
        first_btn = page.locator("button[id^='tingi-btn-']").first
        first_btn.click()

        # Wait for cart update
        page.wait_for_selector("#cart-total-display")
        content = page.content()
        assert "Paninda Item 1" in content or "15.00" in content

        # 4. Desktop vs Mobile navigation visibility
        desktop_nav = page.locator("#desktop-nav-menu")
        assert desktop_nav.is_visible(), "Desktop navigation menu must be visible on 1920x1080"

        mobile_nav = page.locator("#mobile-bottom-nav")
        assert not mobile_nav.is_visible(), "Mobile bottom nav must be hidden on 1920x1080 desktop"

        browser.close()


@pytest.mark.django_db(transaction=True)
def test_desktop_interactive_payment_and_tender_calculator(live_server, setup_pos_products):
    """
    Playwright test verifying cash/utang interactive toggling and tender calculator
    in desktop split-screen mode.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        page.goto(f"{live_server.url}/pos/")
        page.wait_for_selector("button[id^='tingi-btn-']")

        # 1. Add item to cart
        page.locator("button[id^='tingi-btn-']").first.click()
        page.wait_for_selector("#cart-total-display")

        # 2. Initially cash is selected; cash tender block visible, customer block hidden
        cash_block = page.locator("#cash-tender-block")
        customer_block = page.locator("#customer-select-block")
        assert cash_block.is_visible(), "Cash tender block must be visible initially"
        assert not customer_block.is_visible(), "Customer debt select block must be hidden initially"

        # 3. Switch to UTANG
        utang_radio = page.locator("input[name='payment_method'][value='UTANG']")
        utang_radio.click()
        page.wait_for_timeout(300)

        assert customer_block.is_visible(), "Customer select block must be visible when UTANG selected"
        assert not cash_block.is_visible(), "Cash tender block must be hidden when UTANG selected"

        # 4. Switch back to CASH
        cash_radio = page.locator("input[name='payment_method'][value='CASH']")
        cash_radio.click()
        page.wait_for_timeout(300)

        assert cash_block.is_visible(), "Cash block must re-appear when CASH selected"
        assert not customer_block.is_visible(), "Customer block must re-hide when CASH selected"

        # 5. Type tender and verify change calculation
        tender_input = page.locator("#cash-tender-input")
        tender_input.fill("50")
        page.wait_for_selector("#sukli-display")
        sukli_text = page.locator("#sukli-display").inner_text()
        assert "35.00" in sukli_text, f"Change for 50 - 15 must be 35.00, got: {sukli_text}"

        browser.close()


@pytest.mark.django_db(transaction=True)
def test_desktop_language_switcher_toggle_in_browser(live_server, setup_pos_products):
    """
    Playwright test verifying clicking language switcher in header translates UI strings.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        page.goto(f"{live_server.url}/pos/")
        page.wait_for_selector("#lang-btn-fil")

        # Add item so cart items/total are shown
        page.locator("button[id^='tingi-btn-']").first.click()
        page.wait_for_selector("#cart-total-display")

        # Click FIL button
        page.locator("#lang-btn-fil").click()
        page.wait_for_selector("#cart-total-display")

        fil_content = page.content()
        assert "Kabuuan" in fil_content, "Total must be translated to Kabuuan under Filipino"

        # Click EN button
        page.locator("#lang-btn-en").click()
        page.wait_for_selector("#cart-total-display")

        en_content = page.content()
        assert "Total" in en_content, "Kabuuan must be translated back to Total under English"

        browser.close()


@pytest.mark.django_db(transaction=True)
def test_tablet_and_mobile_responsive_breakpoints(live_server, setup_pos_products):
    """
    Playwright test verifying layout adapts across tablet (768px) and mobile (375px) viewports
    without horizontal viewport overflow.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # 1. Tablet breakpoint: 768 x 1024
        tab_ctx = browser.new_context(viewport={"width": 768, "height": 1024})
        tab_page = tab_ctx.new_page()
        tab_page.goto(f"{live_server.url}/pos/")
        tab_page.wait_for_selector("#pos-catalog-column")

        # Ensure no horizontal scroll overflow
        has_horizontal_overflow = tab_page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
        assert not has_horizontal_overflow, "Tablet (768px) must not have horizontal scroll overflow"

        # 2. Mobile breakpoint: 375 x 667
        mob_ctx = browser.new_context(viewport={"width": 375, "height": 667})
        mob_page = mob_ctx.new_page()
        mob_page.goto(f"{live_server.url}/pos/")
        mob_page.wait_for_selector("#pos-catalog-column")

        # On mobile: mobile bottom nav is visible, desktop nav is hidden
        assert mob_page.locator("#mobile-bottom-nav").is_visible(), "Mobile bottom nav must be visible on 375px"
        assert not mob_page.locator("#desktop-nav-menu").is_visible(), "Desktop nav must be hidden on 375px"

        has_mob_overflow = mob_page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
        assert not has_mob_overflow, "Mobile (375px) must not have horizontal scroll overflow"

        browser.close()


@pytest.mark.django_db(transaction=True)
def test_4k_and_ultrawide_desktop_layouts(live_server, setup_pos_products):
    """
    Playwright test verifying 4K UHD (3840x2160) and 2560x1440 ultra-wide desktop viewports:
    - Side-by-side catalog and cart split layout maintained without breakdown
    - Zero horizontal viewport overflow
    - Quick-add interactivity and reactive cart updates
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for width, height in [(3840, 2160), (2560, 1440)]:
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()

            page.goto(f"{live_server.url}/pos/")
            page.wait_for_selector("#pos-split-layout")
            page.wait_for_selector("#pos-catalog-column")
            page.wait_for_selector("#pos-cart-column")

            # 1. Split-screen layout positioning
            catalog_box = page.locator("#pos-catalog-column").bounding_box()
            cart_box = page.locator("#pos-cart-column").bounding_box()

            assert catalog_box is not None, f"Catalog must render in {width}x{height}"
            assert cart_box is not None, f"Cart must render in {width}x{height}"
            assert catalog_box["x"] < cart_box["x"], f"Catalog must be to the left of Cart in {width}x{height}"

            # 2. No horizontal scroll overflow
            has_overflow = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
            assert not has_overflow, f"Viewport {width}x{height} must not have horizontal overflow"

            # 3. Interactivity
            first_btn = page.locator("button[id^='tingi-btn-']").first
            first_btn.click()
            page.wait_for_selector("#cart-total-display")

            content = page.content()
            assert "Paninda Item 1" in content or "15.00" in content

            # 4. Desktop nav is visible, mobile nav hidden
            assert page.locator("#desktop-nav-menu").is_visible()
            assert not page.locator("#mobile-bottom-nav").is_visible()

            context.close()

        browser.close()


@pytest.mark.django_db(transaction=True)
def test_htmx_outerhtml_swap_prevents_duplicate_cart_container_nesting(live_server, setup_pos_products):
    """
    Adversarial test: Repeated HTMX cart mutations (quick-add, steppers +, -, clear)
    must NOT nest multiple #cart-container DOM elements (maintains single valid ID).
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        page.goto(f"{live_server.url}/pos/")
        page.wait_for_selector("button[id^='tingi-btn-']")

        # Initial check: exactly 1 cart container
        initial_containers = page.evaluate("() => document.querySelectorAll('#cart-container').length")
        assert initial_containers == 1, f"Expected exactly 1 cart container initially, got {initial_containers}"

        # 1. Add item 1
        page.locator("button[id^='tingi-btn-']").first.click()
        page.wait_for_selector("#cart-total-display")
        count_after_first = page.evaluate("() => document.querySelectorAll('#cart-container').length")
        assert count_after_first == 1, f"Expected 1 cart container after 1st add, got {count_after_first}"

        # 2. Add item 2
        page.locator("button[id^='tingi-btn-']").nth(1).click()
        page.wait_for_timeout(300)
        count_after_second = page.evaluate("() => document.querySelectorAll('#cart-container').length")
        assert count_after_second == 1, f"Expected 1 cart container after 2nd add, got {count_after_second}"

        # 3. Click stepper + on first item
        plus_btn = page.locator("button:has-text('+')").first
        plus_btn.click()
        page.wait_for_timeout(300)
        count_after_plus = page.evaluate("() => document.querySelectorAll('#cart-container').length")
        assert count_after_plus == 1, f"Expected 1 cart container after stepper +, got {count_after_plus}"

        # 4. Click stepper -
        minus_btn = page.locator("button:has-text('-')").first
        minus_btn.click()
        page.wait_for_timeout(300)
        count_after_minus = page.evaluate("() => document.querySelectorAll('#cart-container').length")
        assert count_after_minus == 1, f"Expected 1 cart container after stepper -, got {count_after_minus}"

        # 5. Clear cart
        clear_btn = page.locator("button:has-text('Clear Cart'), button:has-text('Burahin')").first
        clear_btn.click()
        page.wait_for_timeout(300)
        count_after_clear = page.evaluate("() => document.querySelectorAll('#cart-container').length")
        assert count_after_clear == 1, f"Expected 1 cart container after clear, got {count_after_clear}"

        # 6. Re-add item to verify recovery from empty state
        page.locator("button[id^='tingi-btn-']").first.click()
        page.wait_for_selector("#cart-total-display")
        count_final = page.evaluate("() => document.querySelectorAll('#cart-container').length")
        assert count_final == 1, f"Expected 1 cart container after re-add, got {count_final}"

        browser.close()


@pytest.mark.django_db(transaction=True)
def test_language_cookie_persistence_across_browser_context_reset(live_server, setup_pos_products):
    """
    Adversarial test: Setting language to Filipino stores a 1-year persistent cookie.
    When a browser session/context is recreated with stored cookies, the language
    preference remains active (rendering 'Kabuuan').
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Context 1: Switch language
        ctx1 = browser.new_context(viewport={"width": 1920, "height": 1080})
        page1 = ctx1.new_page()
        page1.goto(f"{live_server.url}/pos/")
        page1.wait_for_selector("#lang-btn-fil")

        # Add item so total label is rendered
        page1.locator("button[id^='tingi-btn-']").first.click()
        page1.wait_for_selector("#cart-total-display")

        # Click FIL toggle
        page1.locator("#lang-btn-fil").click()
        page1.wait_for_selector("#cart-total-display")
        assert "Kabuuan" in page1.content()

        # Capture cookies
        cookies = ctx1.cookies()
        lang_cookies = [c for c in cookies if c["name"] == "django_language"]
        assert len(lang_cookies) == 1, "django_language cookie must be set"
        assert lang_cookies[0]["value"] == "fil"
        # Verify 1-year max age / expiration
        assert lang_cookies[0]["expires"] > 0, "Cookie must have an expiration timestamp (not a session-only cookie)"

        ctx1.close()

        # Context 2: Recreate browser context with stored cookies (simulates browser restart)
        ctx2 = browser.new_context(viewport={"width": 1920, "height": 1080})
        ctx2.add_cookies(cookies)
        page2 = ctx2.new_page()

        page2.goto(f"{live_server.url}/pos/")
        page2.wait_for_selector("#pos-catalog-column")

        # Add item
        page2.locator("button[id^='tingi-btn-']").first.click()
        page2.wait_for_selector("#cart-total-display")

        # Must still render Kabuuan in new browser session
        assert "Kabuuan" in page2.content(), "Language preference must persist across browser context recreations"

        ctx2.close()
        browser.close()


@pytest.mark.django_db(transaction=True)
def test_utang_desktop_grid_dom_structure_with_multiple_customers(live_server):
    """
    Adversarial test: Multiple customers rendered on /utang/ desktop view must ALL be
    contained inside the grid container without premature closing div tags or DOM breakdown.
    """
    Customer.objects.all().delete()
    for i in range(1, 5):
        Customer.objects.create(
            name=f"Suki Debtor {i}",
            nickname=f"Suki{i}",
            debt_balance=Decimal(str(i * 100)),
            credit_limit=Decimal("1000.00"),
            is_active=True
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        page.goto(f"{live_server.url}/utang/")
        page.wait_for_selector(".grid.grid-cols-1.md\\:grid-cols-2")

        # Verify all 4 customer cards are direct child nodes within the grid
        card_count = page.evaluate("() => document.querySelectorAll('.grid.grid-cols-1.md\\\\:grid-cols-2 > div.bg-white').length")
        assert card_count == 4, f"All 4 customer cards must be direct children of the 2-column grid, got {card_count}"

        # Verify desktop side-by-side positioning of card 1 and card 2
        cards = page.locator(".grid.grid-cols-1.md\\:grid-cols-2 > div.bg-white")
        box1 = cards.nth(0).bounding_box()
        box2 = cards.nth(1).bounding_box()

        assert box1 is not None and box2 is not None
        assert abs(box1["y"] - box2["y"]) < 50, "Cards 1 and 2 in a 2-column grid must sit on the same horizontal row"
        assert box1["x"] < box2["x"], "Card 1 must be in left column and Card 2 in right column"

        browser.close()


