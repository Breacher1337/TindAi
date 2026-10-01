"""Acceptance and unit test suite for StoreConfig Singleton Model (FR-05).

Verifies singleton semantics, default attributes, alias properties, idempotency,
multi-layer second-row blocking (ORM create/save, form clean, raw SQL CHECK constraint),
sequence drift prevention on deletion/recreation, and Unfold admin permission enforcement.
"""

from decimal import Decimal
import pytest
from django.contrib.admin.sites import site
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import Client, RequestFactory
from django.urls import reverse

from core.models import StoreConfig


@pytest.fixture
def admin_superuser(db):
    """Superuser fixture for StoreConfig admin testing."""
    return User.objects.create_superuser(
        username="store_admin",
        email="store_admin@tindai.local",
        password="supersecretadminpassword123"
    )


@pytest.mark.django_db
class TestStoreConfigSingleton:
    """Test suite for StoreConfig singleton creation, defaults, and properties."""

    def test_default_attributes_and_properties(self):
        """Verify default configuration values, alias properties, and __str__."""
        StoreConfig.objects.all().delete()
        config = StoreConfig.get_solo()

        # Primary key must be 1
        assert config.pk == 1
        assert config.id == 1

        # Default attribute values
        assert config.store_name == "TindAI Sari-Sari Store"
        assert config.caretaker_identity == "Tindero / Tindera"
        assert config.default_retail_markup_percentage == Decimal("15.00")

        # Computed / alias properties
        assert config.caretaker_name == "Tindero / Tindera"
        assert config.default_markup_percentage == Decimal("15.00")

        # String representation
        assert str(config) == "TindAI Sari-Sari Store (Tindero / Tindera)"

        # Timestamps populated
        assert config.created_at is not None
        assert config.updated_at is not None

    def test_get_solo_idempotency_and_update_persistence(self):
        """Verify get_solo() idempotently returns the same row and persists updates."""
        StoreConfig.objects.all().delete()
        config1 = StoreConfig.get_solo()
        assert config1.pk == 1

        # Update attributes on singleton
        config1.store_name = "Aling Nena Sari-Sari Store"
        config1.caretaker_identity = "Aling Nena"
        config1.default_retail_markup_percentage = Decimal("20.00")
        config1.save()

        # Retrieve again via get_solo()
        config2 = StoreConfig.get_solo()
        assert config2.pk == 1
        assert config2.store_name == "Aling Nena Sari-Sari Store"
        assert config2.caretaker_name == "Aling Nena"
        assert config2.default_markup_percentage == Decimal("20.00")

        # Exactly 1 row in database
        assert StoreConfig.objects.count() == 1


@pytest.mark.django_db
class TestStoreConfigConstraints:
    """Acceptance criteria verification: second row creation must be strictly blocked."""

    def test_block_second_row_objects_create(self):
        """StoreConfig.objects.create(...) must raise IntegrityError when row exists."""
        StoreConfig.objects.all().delete()
        StoreConfig.get_solo()
        assert StoreConfig.objects.count() == 1

        with pytest.raises(IntegrityError) as exc_info:
            StoreConfig.objects.create(
                store_name="Illegitimate Second Store",
                caretaker_identity="Intruder",
                default_retail_markup_percentage=Decimal("25.00")
            )
        assert "Only one StoreConfig instance is permitted" in str(exc_info.value)
        assert StoreConfig.objects.count() == 1

    def test_block_second_row_model_save(self):
        """StoreConfig(...).save() must raise IntegrityError when row exists."""
        StoreConfig.objects.all().delete()
        StoreConfig.get_solo()
        assert StoreConfig.objects.count() == 1

        new_instance = StoreConfig(
            store_name="Another Store Instance",
            caretaker_identity="Impostor"
        )
        with pytest.raises(IntegrityError) as exc_info:
            new_instance.save()
        assert "Only one StoreConfig instance is permitted" in str(exc_info.value)
        assert StoreConfig.objects.count() == 1

    def test_block_second_row_model_clean(self):
        """StoreConfig(...).clean() must raise ValidationError when row exists."""
        StoreConfig.objects.all().delete()
        StoreConfig.get_solo()
        assert StoreConfig.objects.count() == 1

        unpersisted = StoreConfig(
            store_name="Unsaved Duplicate Store",
            caretaker_identity="Form User"
        )
        with pytest.raises(ValidationError) as exc_info:
            unpersisted.clean()
        assert "Only one StoreConfig instance is permitted" in str(exc_info.value)

    def test_block_explicit_non_1_id_model_clean(self):
        """StoreConfig(id=2).clean() must raise ValidationError with permitted message."""
        StoreConfig.objects.all().delete()
        StoreConfig.get_solo()

        rogue = StoreConfig(id=2, store_name="Malicious Config")
        with pytest.raises(ValidationError) as exc_info:
            rogue.clean()
        assert "Only one StoreConfig instance is permitted" in str(exc_info.value)

    def test_block_explicit_non_1_id_model_save(self):
        """StoreConfig(id=2).save() must raise IntegrityError."""
        StoreConfig.objects.all().delete()
        StoreConfig.get_solo()

        rogue = StoreConfig(id=2, store_name="Malicious Config")
        with pytest.raises(IntegrityError) as exc_info:
            rogue.save()
        assert "Only one StoreConfig instance is permitted" in str(exc_info.value)
        assert StoreConfig.objects.count() == 1

    def test_block_explicit_non_1_id_model_save_force_update(self):
        """StoreConfig(id=2).save(force_update=True) must raise IntegrityError without overwriting row 1."""
        StoreConfig.objects.all().delete()
        original = StoreConfig.get_solo()
        assert original.store_name == "TindAI Sari-Sari Store"

        rogue = StoreConfig(id=2, store_name="Malicious Config")
        with pytest.raises(IntegrityError) as exc_info:
            rogue.save(force_update=True)
        assert "Only one StoreConfig instance is permitted" in str(exc_info.value)

        original.refresh_from_db()
        assert original.store_name == "TindAI Sari-Sari Store"
        assert StoreConfig.objects.count() == 1

    def test_database_level_check_constraint_direct_sql_insert(self):
        """Direct raw SQL insert with id=2 must fail with SQLite CHECK constraint failure."""
        StoreConfig.objects.all().delete()
        StoreConfig.get_solo()

        # Attempt raw SQL insert with id=2
        with pytest.raises(IntegrityError) as exc_info:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO core_storeconfig "
                        "(id, store_name, caretaker_identity, default_retail_markup_percentage, created_at, updated_at) "
                        "VALUES (2, 'SQL Second Store', 'Tindero', 15.00, '2026-10-01 00:00:00', '2026-10-01 00:00:00')"
                    )

        err_msg = str(exc_info.value).lower()
        assert "check constraint failed" in err_msg or "single_store_config_record" in err_msg
        assert StoreConfig.objects.count() == 1

    def test_database_level_check_constraint_arbitrary_ids(self):
        """Direct raw SQL insert with arbitrary non-1 IDs (0, 99) must also fail."""
        StoreConfig.objects.all().delete()
        StoreConfig.get_solo()

        for invalid_id in [0, 99]:
            with pytest.raises(IntegrityError) as exc_info:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "INSERT INTO core_storeconfig "
                            "(id, store_name, caretaker_identity, default_retail_markup_percentage, created_at, updated_at) "
                            f"VALUES ({invalid_id}, 'Invalid ID Store', 'Tindero', 15.00, '2026-10-01 00:00:00', '2026-10-01 00:00:00')"
                        )
            err_msg = str(exc_info.value).lower()
            assert "check constraint failed" in err_msg or "single_store_config_record" in err_msg

    def test_delete_and_recreate_maintains_pk_1_without_sequence_drift(self):
        """Deleting the instance and recreating maintains pk=1 without sequence drift."""
        StoreConfig.objects.all().delete()
        config = StoreConfig.get_solo()
        assert config.pk == 1

        # Delete the instance
        config.delete()
        assert StoreConfig.objects.count() == 0

        # Recreate via get_solo()
        recreated = StoreConfig.get_solo()
        assert recreated.pk == 1
        assert StoreConfig.objects.count() == 1

        # Recreate via direct save() after deletion
        recreated.delete()
        assert StoreConfig.objects.count() == 0

        manual_new = StoreConfig(
            store_name="Fresh Store Post Delete",
            caretaker_identity="Ate Rose"
        )
        manual_new.save()
        assert manual_new.pk == 1
        assert StoreConfig.objects.count() == 1


@pytest.mark.django_db
class TestStoreConfigAdmin:
    """Test suite for StoreConfigAdmin permissions and Unfold changelist/changeform views."""

    def test_admin_permissions_with_and_without_instance(self, admin_superuser):
        """Admin has_add_permission is False when row exists, True when empty. has_delete_permission is always False."""
        StoreConfig.objects.all().delete()
        admin_obj = site._registry[StoreConfig]
        rf = RequestFactory()
        req = rf.get("/admin/core/storeconfig/")
        req.user = admin_superuser

        # When no config exists:
        assert admin_obj.has_add_permission(req) is True
        assert admin_obj.has_delete_permission(req, obj=None) is False

        # When config exists:
        config = StoreConfig.get_solo()
        assert admin_obj.has_add_permission(req) is False
        assert admin_obj.has_delete_permission(req, obj=config) is False

    def test_admin_views_http_render(self, admin_superuser):
        """Verify changelist and changeform render properly for StoreConfig."""
        StoreConfig.objects.all().delete()
        config = StoreConfig.get_solo()

        client = Client()
        client.force_login(admin_superuser)

        # Changelist view
        cl_url = reverse("admin:core_storeconfig_changelist")
        cl_resp = client.get(cl_url)
        assert cl_resp.status_code == 200
        assert b"TindAI Sari-Sari Store" in cl_resp.content

        # Changeform view
        change_url = reverse("admin:core_storeconfig_change", args=[config.pk])
        ch_resp = client.get(change_url)
        assert ch_resp.status_code == 200
        assert b"TindAI Sari-Sari Store" in ch_resp.content
        assert b"Tindero / Tindera" in ch_resp.content
