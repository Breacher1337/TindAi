import pytest
from decimal import Decimal
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import translation
from core.models import StoreConfig, Product


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="admin_user",
        email="admin@tindai.local",
        password="supersecretpassword123"
    )


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username="suki_user",
        email="suki@tindai.local",
        password="regularpassword123"
    )


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="tindero_staff",
        email="staff@tindai.local",
        password="staffpassword123",
        is_staff=True
    )


@pytest.fixture
def sample_product_in_cart(db):
    return Product.objects.create(
        sku="TEST-SKU-I18N",
        name="Lucky Me Pancit Canton",
        wholesale_cost=Decimal("12.00"),
        retail_price=Decimal("15.00"),
        stock_quantity=Decimal("50.00"),
        reorder_point=10,
        category="Noodles"
    )


@pytest.mark.django_db
class TestStoreSettingsAccessAndEditing:
    """Acceptance tests for /settings/ access control and StoreConfig singleton editing."""

    def test_settings_strictly_rejects_anonymous_users(self, client):
        """Anonymous GET and POST to /settings/ must be rejected with redirect to login."""
        get_resp = client.get(reverse('settings'))
        assert get_resp.status_code in (302, 401, 403)
        if get_resp.status_code == 302:
            assert "/admin/login/" in get_resp.url

        post_resp = client.post(reverse('settings'), {
            'store_name': 'Hacked Store',
            'caretaker_identity': 'Intruder',
            'default_retail_markup_percentage': '25.00'
        })
        assert post_resp.status_code in (302, 401, 403)

    def test_settings_strictly_rejects_non_staff_users(self, client, regular_user):
        """Authenticated non-staff users must receive 403 Forbidden."""
        client.force_login(regular_user)
        get_resp = client.get(reverse('settings'))
        assert get_resp.status_code == 403

        post_resp = client.post(reverse('settings'), {
            'store_name': 'Unauthorized Store',
            'caretaker_identity': 'NonStaff',
            'default_retail_markup_percentage': '20.00'
        })
        assert post_resp.status_code == 403

    def test_settings_allows_staff_users(self, client, staff_user):
        """Staff members (is_staff=True, is_superuser=False) can access and edit settings."""
        client.force_login(staff_user)
        resp = client.get(reverse('settings'))
        assert resp.status_code == 200

        update_resp = client.post(reverse('settings'), {
            'store_name': 'Staff Managed Store',
            'caretaker_identity': 'Kuya Tindero',
            'default_retail_markup_percentage': '12.50'
        })
        assert update_resp.status_code in (200, 302)
        cfg = StoreConfig.get_solo()
        assert cfg.store_name == 'Staff Managed Store'
        assert cfg.caretaker_identity == 'Kuya Tindero'
        assert cfg.default_retail_markup_percentage == Decimal('12.50')

    def test_settings_allows_admins_and_renders_config(self, client, admin_user):
        """Admins can view /settings/ and edit StoreConfig singleton."""
        client.force_login(admin_user)
        StoreConfig.objects.all().delete()
        config = StoreConfig.get_solo()

        resp = client.get(reverse('settings'))
        assert resp.status_code == 200
        assert config.store_name.encode('utf-8') in resp.content
        assert config.caretaker_identity.encode('utf-8') in resp.content

    def test_settings_admin_can_update_store_config(self, client, admin_user):
        """Admins can update store_name, caretaker_identity, and markup percentage."""
        client.force_login(admin_user)
        StoreConfig.objects.all().delete()
        StoreConfig.get_solo()

        update_resp = client.post(reverse('settings'), {
            'store_name': 'Aling Nena Super Sari-Sari Store',
            'caretaker_identity': 'Aling Nena',
            'default_retail_markup_percentage': '18.50'
        })
        assert update_resp.status_code in (200, 302)

        updated_config = StoreConfig.get_solo()
        assert updated_config.store_name == 'Aling Nena Super Sari-Sari Store'
        assert updated_config.caretaker_identity == 'Aling Nena'
        assert updated_config.default_retail_markup_percentage == Decimal('18.50')

    def test_settings_validation_blocks_invalid_markup_and_empty_fields(self, client, admin_user):
        """Form rejects negative markup and blank store name."""
        client.force_login(admin_user)
        StoreConfig.objects.all().delete()
        StoreConfig.get_solo()

        # Negative markup
        resp_neg = client.post(reverse('settings'), {
            'store_name': 'Valid Name',
            'caretaker_identity': 'Valid Caretaker',
            'default_retail_markup_percentage': '-5.00'
        })
        assert resp_neg.status_code == 400
        assert b"0.00" in resp_neg.content or b"Errors" in resp_neg.content or b"negative" in resp_neg.content

        # Empty store name
        resp_empty = client.post(reverse('settings'), {
            'store_name': '',
            'caretaker_identity': 'Valid Caretaker',
            'default_retail_markup_percentage': '15.00'
        })
        assert resp_empty.status_code == 400

    def test_settings_validation_blocks_overflow_markup_without_corrupting_database(self, client, admin_user):
        """Form rejects markup >= 1000.00 to prevent DecimalField overflow and db row corruption."""
        client.force_login(admin_user)
        StoreConfig.objects.all().delete()
        cfg_before = StoreConfig.get_solo()

        # Attempt to save 1000.00 markup
        resp_overflow = client.post(reverse('settings'), {
            'store_name': 'Valid Store',
            'caretaker_identity': 'Valid Caretaker',
            'default_retail_markup_percentage': '1000.00'
        })
        assert resp_overflow.status_code == 400

        # Attempt to save 99999.99 markup
        resp_huge = client.post(reverse('settings'), {
            'store_name': 'Valid Store',
            'caretaker_identity': 'Valid Caretaker',
            'default_retail_markup_percentage': '99999.99'
        })
        assert resp_huge.status_code == 400

        # Critical: StoreConfig.get_solo() must NOT raise decimal.InvalidOperation
        cfg_after = StoreConfig.get_solo()
        assert cfg_after.default_retail_markup_percentage == cfg_before.default_retail_markup_percentage

    def test_settings_validation_preserves_form_input_on_failure(self, client, admin_user):
        """When form has validation errors, user's typed store_name and caretaker are preserved in the form."""
        client.force_login(admin_user)
        resp = client.post(reverse('settings'), {
            'store_name': 'Preserved Custom Store Name',
            'caretaker_identity': 'Preserved Custom Caretaker',
            'default_retail_markup_percentage': '-10.00'  # invalid
        })
        assert resp.status_code == 400
        assert b"Preserved Custom Store Name" in resp.content
        assert b"Preserved Custom Caretaker" in resp.content

    def test_settings_legal_boundary_values(self, client, admin_user):
        """0.00% and 999.99% are exact legal boundaries and must be accepted."""
        client.force_login(admin_user)
        # 0.00%
        resp_zero = client.post(reverse('settings'), {
            'store_name': 'Zero Markup Store',
            'caretaker_identity': 'Zero Tindero',
            'default_retail_markup_percentage': '0.00'
        })
        assert resp_zero.status_code in (200, 302)
        assert StoreConfig.get_solo().default_retail_markup_percentage == Decimal('0.00')

        # 999.99%
        resp_max = client.post(reverse('settings'), {
            'store_name': 'Max Markup Store',
            'caretaker_identity': 'Max Tindero',
            'default_retail_markup_percentage': '999.99'
        })
        assert resp_max.status_code in (200, 302)
        assert StoreConfig.get_solo().default_retail_markup_percentage == Decimal('999.99')

    def test_settings_rejects_strings_exceeding_max_length(self, client, admin_user):
        """Store name and caretaker identity longer than 255 chars must be rejected."""
        client.force_login(admin_user)
        resp = client.post(reverse('settings'), {
            'store_name': 'X' * 256,
            'caretaker_identity': 'Y' * 256,
            'default_retail_markup_percentage': '15.00'
        })
        assert resp.status_code == 400

    def test_settings_rejects_whitespace_only_fields(self, client, admin_user):
        """Submitting whitespace-only store name or caretaker must be rejected with 400."""
        client.force_login(admin_user)
        resp = client.post(reverse('settings'), {
            'store_name': '    ',
            'caretaker_identity': '   \t\n  ',
            'default_retail_markup_percentage': '15.00'
        })
        assert resp.status_code == 400

    def test_settings_rejects_excessive_decimal_places(self, client, admin_user):
        """Markup with more than 2 decimal places (e.g. 15.123) is rejected with 400."""
        client.force_login(admin_user)
        resp = client.post(reverse('settings'), {
            'store_name': 'Valid Store',
            'caretaker_identity': 'Valid Caretaker',
            'default_retail_markup_percentage': '15.125'
        })
        assert resp.status_code == 400


@pytest.mark.django_db
class TestLanguageSwitcherAndI18n:
    """Acceptance tests for Django server-side gettext i18n translation framework."""

    def test_gettext_translates_total_to_kabuuan_unit(self):
        """Django gettext translates known string 'Total' to 'Kabuuan' under Filipino / Tagalog."""
        # English
        translation.activate('en')
        assert translation.gettext('Total') == 'Total'

        # Filipino (fil)
        translation.activate('fil')
        assert translation.gettext('Total') == 'Kabuuan'

        # Tagalog alias (tl)
        translation.activate('tl')
        assert translation.gettext('Total') == 'Kabuuan'

        # Reset back
        translation.deactivate()

    def test_pos_cart_translates_total_in_templates(self, client, sample_product_in_cart):
        """
        Verify template rendering translates 'Total:' to 'Kabuuan:' based on active language.
        Add an item to the session cart first to show the Grand Total line.
        """
        # Add item to session cart
        client.post(reverse('cart_add', args=[sample_product_in_cart.id]))

        # 1. Fetch under English
        resp_en = client.get(reverse('pos'), HTTP_ACCEPT_LANGUAGE='en')
        assert resp_en.status_code == 200
        content_en = resp_en.content.decode('utf-8')
        assert 'Total:' in content_en or 'Total' in content_en

        # 2. Switch to Filipino via language switch endpoint
        setlang_resp = client.post(reverse('set_language'), {
            'language': 'fil',
            'next': reverse('pos')
        })
        assert setlang_resp.status_code == 302

        # 3. Fetch under Filipino
        resp_fil = client.get(reverse('pos'))
        assert resp_fil.status_code == 200
        content_fil = resp_fil.content.decode('utf-8')
        assert 'Kabuuan:' in content_fil or 'Kabuuan' in content_fil

    def test_switch_language_helper_endpoint(self, client):
        """Verify GET /set-language/<lang_code>/ activates requested language."""
        from django.conf import settings
        resp = client.get(reverse('switch_language', args=['fil']), HTTP_REFERER='/pos/')
        assert resp.status_code == 302
        assert client.cookies[settings.LANGUAGE_COOKIE_NAME].value == 'fil'
        assert client.session.get('_language') == 'fil'

        resp_en = client.get(reverse('switch_language', args=['en']), HTTP_REFERER='/pos/')
        assert resp_en.status_code == 302
        assert client.cookies[settings.LANGUAGE_COOKIE_NAME].value == 'en'
        assert client.session.get('_language') == 'en'

    def test_switch_language_open_redirect_protection(self, client):
        """Adversarial test: /set-language/<lang>/ must NOT redirect to external malicious targets."""
        # 1. External HTTPS URL
        resp_ext = client.get(reverse('switch_language', args=['fil']) + '?next=https://malicious.example.com')
        assert resp_ext.status_code == 302
        assert resp_ext.url == '/'

        # 2. Scheme-relative URL
        resp_rel = client.get(reverse('switch_language', args=['fil']) + '?next=//attacker.example.com/steal')
        assert resp_rel.status_code == 302
        assert resp_rel.url == '/'

        # 3. Legitimate internal path is preserved
        resp_safe = client.get(reverse('switch_language', args=['en']) + '?next=/inventory/')
        assert resp_safe.status_code == 302
        assert resp_safe.url == '/inventory/'

    def test_language_cookie_persistence_setting(self):
        """Verify LANGUAGE_COOKIE_AGE is configured for 1-year persistence."""
        from django.conf import settings
        assert settings.LANGUAGE_COOKIE_AGE == 60 * 60 * 24 * 365

    def test_i18n_context_processor_registered(self):
        """Verify django.template.context_processors.i18n is in context_processors."""
        from django.conf import settings
        processors = settings.TEMPLATES[0]['OPTIONS']['context_processors']
        assert 'django.template.context_processors.i18n' in processors

    def test_switch_language_case_insensitivity_and_aliases(self, client):
        """Adversarial test: Uppercase codes ('FIL', 'EN') and aliases ('Tagalog') must activate proper language."""
        from django.conf import settings
        # 1. Uppercase FIL
        resp_fil_upper = client.get(reverse('switch_language', args=['FIL']), HTTP_REFERER='/pos/')
        assert resp_fil_upper.status_code == 302
        assert client.cookies[settings.LANGUAGE_COOKIE_NAME].value == 'fil'
        assert client.session.get('_language') == 'fil'

        # 2. Tagalog alias
        resp_tl = client.get(reverse('switch_language', args=['Tagalog']), HTTP_REFERER='/pos/')
        assert resp_tl.status_code == 302
        assert client.cookies[settings.LANGUAGE_COOKIE_NAME].value == 'tl'
        assert client.session.get('_language') == 'tl'

        # 3. Uppercase EN
        resp_en = client.get(reverse('switch_language', args=['EN']), HTTP_REFERER='/pos/')
        assert resp_en.status_code == 302
        assert client.cookies[settings.LANGUAGE_COOKIE_NAME].value == 'en'
        assert client.session.get('_language') == 'en'

    def test_all_settings_and_cart_strings_translated_under_filipino(self):
        """Verify all critical UI strings translate properly under gettext in Filipino."""
        translation.activate('fil')
        try:
            assert translation.gettext('Total') == 'Kabuuan'
            assert translation.gettext('Cancel') == 'Kanselahin'
            assert translation.gettext('Admin View') == 'Tingnan sa Admin'
            assert translation.gettext('Store Configuration') == 'Konpigurasyon ng Tindahan'
            assert translation.gettext('Store Name') == 'Pangalan ng Tindahan'
            assert translation.gettext('Caretaker Identity') == 'Tagapangalaga'
            assert translation.gettext('Tap a tingi item above or snap a photo of the counter.') == 'Pumindot ng tingi sa itaas o kumuha ng litrato ng counter.'
            assert translation.gettext("The total amount will be recorded to the chosen suki's ledger.") == 'Dadalhin ang kabuuang halaga sa talaan ng napiling suki.'
        finally:
            translation.deactivate()

    def test_settings_prevents_stored_xss_in_templates(self, client, admin_user):
        """Adversarial test: Submitting XSS script payloads in store_name is safely auto-escaped in HTML."""
        client.force_login(admin_user)
        xss_payload = "<script>alert('XSS-TINDAI')</script>"
        resp = client.post(reverse('settings'), {
            'store_name': xss_payload,
            'caretaker_identity': 'Safe Caretaker',
            'default_retail_markup_percentage': '15.00'
        })
        assert resp.status_code in (200, 302)

        get_resp = client.get(reverse('settings'))
        content = get_resp.content.decode('utf-8')
        assert "<script>alert('XSS-TINDAI')</script>" not in content
        assert "&lt;script&gt;alert(&#x27;XSS-TINDAI&#x27;)&lt;/script&gt;" in content or "&lt;script&gt;" in content

    def test_switch_language_unsupported_code_falls_back_safely(self, client):
        """Adversarial test: Unsupported language codes redirect safely without setting invalid cookie."""
        from django.conf import settings
        resp = client.get(reverse('switch_language', args=['fr']), HTTP_REFERER='/pos/')
        assert resp.status_code == 302
        assert resp.url == '/pos/'
        assert settings.LANGUAGE_COOKIE_NAME not in client.cookies or client.cookies[settings.LANGUAGE_COOKIE_NAME].value != 'fr'


