import json
from pathlib import Path
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.conf import settings
from core.models import Product, Customer


class Command(BaseCommand):
    help = "Seeds authentic FMCG products from seeds/catalog.json and demo customers."

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default=None,
            help='Path to catalog JSON file (defaults to seeds/catalog.json at workspace root)'
        )
        parser.add_argument(
            '--no-customers',
            action='store_true',
            help='Skip creating sample customer profiles'
        )

    def handle(self, *args, **options):
        # Locate catalog file
        file_arg = options.get('file')
        if file_arg:
            catalog_path = Path(file_arg)
        else:
            # Check relative to backend BASE_DIR or workspace root
            candidates = [
                settings.BASE_DIR.parent / 'seeds' / 'catalog.json',
                settings.BASE_DIR / 'seeds' / 'catalog.json',
                Path('seeds/catalog.json'),
            ]
            catalog_path = None
            for p in candidates:
                if p.exists():
                    catalog_path = p
                    break

        if not catalog_path or not catalog_path.exists():
            self.stderr.write(self.style.ERROR(f"Catalog file not found. Looked at: {candidates}"))
            return

        self.stdout.write(f"Loading catalog from: {catalog_path}")
        with open(catalog_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        created_count = 0
        updated_count = 0

        for item in data:
            sku = item.get('sku')
            if not sku:
                continue

            product, created = Product.objects.update_or_create(
                sku=sku,
                defaults={
                    'name': item.get('name', ''),
                    'brand': item.get('brand', ''),
                    'category': item.get('category', 'General'),
                    'wholesale_cost': Decimal(str(item.get('wholesale_cost', 0))),
                    'retail_price': Decimal(str(item.get('retail_price', 0))),
                    'stock_quantity': Decimal(str(item.get('stock_quantity', item.get('current_stock', 20)))),
                    'reorder_point': item.get('reorder_point', 10),
                    'pack_unit': item.get('pack_unit', 'pack'),
                    'tingi_unit': item.get('tingi_unit', 'piece'),
                    'barcode': item.get('barcode', None),
                    'is_active': True,
                }
            )

            # Ensure initial InventoryBatch and StockMovement exist for FIFO depletion
            if product.stock_quantity > Decimal('0.0000') and not product.batches.exists():
                from core.models import InventoryBatch, StockMovement
                InventoryBatch.objects.create(
                    product=product,
                    initial_tingi_quantity=product.stock_quantity,
                    remaining_tingi_quantity=product.stock_quantity,
                    unit_cost_basis=product.wholesale_cost,
                )
                StockMovement.objects.create(
                    product=product,
                    movement_type=StockMovement.MOVEMENT_AUDIT_ADJUSTMENT,
                    quantity_change=product.stock_quantity,
                    balance_after=product.stock_quantity,
                    reference_id="SEED_CATALOG"
                )

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Products catalog loaded successfully: {created_count} created, {updated_count} updated.")
        )

        # Create demo customers if requested
        if not options.get('no_customers'):
            demo_customers = [
                {
                    'name': 'Maria Santos',
                    'nickname': 'Aling Maria',
                    'phone': '09171234567',
                    'address': 'Blk 12 Lot 4, Riverside',
                    'debt_balance': Decimal("345.50"),
                    'credit_limit': Decimal("1500.00"),
                },
                {
                    'name': 'Kanor Dela Cruz',
                    'nickname': 'Mang Kanor',
                    'phone': '09189876543',
                    'address': 'House #22, Purok 3',
                    'debt_balance': Decimal("180.00"),
                    'credit_limit': Decimal("800.00"),
                },
                {
                    'name': 'Teresita Reyes',
                    'nickname': 'Nanay Tessie',
                    'phone': '09223344556',
                    'address': 'Corner St., Near Chapel',
                    'debt_balance': Decimal("0.00"),
                    'credit_limit': Decimal("1000.00"),
                },
                {
                    'name': 'Jun-Jun Bautista',
                    'nickname': 'Kuya Jun',
                    'phone': '09995551234',
                    'address': 'Brgy. Hall Compound',
                    'debt_balance': Decimal("520.00"),
                    'credit_limit': Decimal("1200.00"),
                },
            ]

            cust_created = 0
            for c_data in demo_customers:
                cust, created = Customer.objects.update_or_create(
                    name=c_data['name'],
                    defaults=c_data
                )
                if created:
                    cust_created += 1

            self.stdout.write(self.style.SUCCESS(f"Loaded {len(demo_customers)} demo customer profiles ({cust_created} newly created)."))
