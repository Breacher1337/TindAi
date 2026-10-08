from decimal import Decimal
from typing import Tuple, Optional
from datetime import datetime
from django.utils import timezone
from core.models import Product, InventoryBatch, StockMovement, RestockInvoiceItem


def deplete_product_inventory_fifo(
    product: Product,
    quantity: Decimal,
    reference_id: str,
    timestamp: Optional[datetime] = None
) -> Tuple[Decimal, Decimal]:
    """
    Deduct inventory from active InventoryBatch records in FIFO order (received_at ASC),
    update remaining batches, decrement product.stock_quantity, and log a StockMovement audit record.

    Returns:
        (item_cogs, effective_unit_cost)
    """
    needed = Decimal(str(quantity))
    total_cogs = Decimal('0.00')

    batches = list(
        InventoryBatch.objects.select_for_update().filter(
            product=product,
            remaining_tingi_quantity__gt=Decimal('0.0000')
        ).order_by('received_at')
    )

    for batch in batches:
        if needed <= Decimal('0.0000'):
            break
        take = min(needed, batch.remaining_tingi_quantity)
        total_cogs += (take * batch.unit_cost_basis)
        batch.remaining_tingi_quantity -= take
        batch.save(update_fields=['remaining_tingi_quantity'])
        needed -= take

    # If any remainder was unbatched, fall back to product.wholesale_cost
    if needed > Decimal('0.0000'):
        total_cogs += (needed * product.wholesale_cost)

    product.stock_quantity = product.stock_quantity - quantity
    product.save(update_fields=['stock_quantity', 'updated_at'])

    movement_timestamp = timestamp if timestamp is not None else timezone.now()
    StockMovement.objects.create(
        product=product,
        movement_type=StockMovement.MOVEMENT_SALE,
        quantity_change=-quantity,
        balance_after=product.stock_quantity,
        reference_id=str(reference_id),
        timestamp=movement_timestamp
    )

    effective_unit_cost = (total_cogs / quantity) if quantity > Decimal('0.0000') else product.wholesale_cost
    return total_cogs, effective_unit_cost


def record_restock_batch(
    product: Product,
    quantity: Decimal,
    unit_cost: Decimal,
    invoice_item: Optional[RestockInvoiceItem] = None,
    reference_id: str = "",
    timestamp: Optional[datetime] = None
) -> InventoryBatch:
    """
    Record inbound stock: creates an InventoryBatch, increments product stock_quantity,
    updates product wholesale cost, and logs a RESTOCK StockMovement audit record.
    """
    received_timestamp = timestamp if timestamp is not None else timezone.now()
    batch = InventoryBatch.objects.create(
        product=product,
        invoice_item=invoice_item,
        initial_tingi_quantity=quantity,
        remaining_tingi_quantity=quantity,
        unit_cost_basis=unit_cost,
        received_at=received_timestamp
    )

    product.stock_quantity = product.stock_quantity + quantity
    product.wholesale_cost = unit_cost
    product.save(update_fields=['stock_quantity', 'wholesale_cost', 'updated_at'])

    StockMovement.objects.create(
        product=product,
        movement_type=StockMovement.MOVEMENT_RESTOCK,
        quantity_change=quantity,
        balance_after=product.stock_quantity,
        reference_id=str(reference_id),
        timestamp=received_timestamp
    )

    return batch
