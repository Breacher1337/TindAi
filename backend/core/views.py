from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.db import transaction
from django.db.models import Sum, Q
from core.models import Product, Customer, CustomerPayment, Transaction as SaleTransaction, TransactionItem


def _get_cart(request):
    return request.session.get('cart', {})


def _save_cart(request, cart):
    request.session['cart'] = cart
    request.session.modified = True


def _calculate_cart_totals(cart):
    items = []
    total = Decimal('0.00')
    for product_id, data in cart.items():
        subtotal = Decimal(str(data['price'])) * int(data['qty'])
        items.append({
            'id': product_id,
            'name': data['name'],
            'price': data['price'],
            'unit': data['unit'],
            'qty': data['qty'],
            'subtotal': f"{subtotal:.2f}"
        })
        total += subtotal
    return items, f"{total:.2f}"


def pos_view(request):
    """Benta / Point of Sale mobile screen."""
    cart = _get_cart(request)
    cart_items, cart_total = _calculate_cart_totals(cart)
    
    # 6 popular tingi items for quick row
    tingi_products = Product.objects.filter(is_active=True)[:6]
    all_products = Product.objects.filter(is_active=True).order_by('name')
    customers = Customer.objects.filter(is_active=True).order_by('name')

    context = {
        'cart': cart_items,
        'cart_total': cart_total,
        'tingi_products': tingi_products,
        'all_products': all_products,
        'customers': customers,
    }
    return render(request, 'pos.html', context)


def cart_add(request, product_id):
    """Add item or increment quantity in cart."""
    product = get_object_or_404(Product, pk=product_id)
    cart = _get_cart(request)
    pid = str(product.id)

    if pid in cart:
        cart[pid]['qty'] += 1
    else:
        cart[pid] = {
            'name': product.name,
            'price': str(product.retail_price),
            'unit': product.tingi_unit,
            'qty': 1,
        }
    _save_cart(request, cart)

    if request.headers.get('HX-Request'):
        cart_items, cart_total = _calculate_cart_totals(cart)
        customers = Customer.objects.filter(is_active=True).order_by('name')
        return render(request, 'partials/cart.html', {
            'cart': cart_items,
            'cart_total': cart_total,
            'customers': customers,
        })
    return redirect('pos')


def cart_add_by_id(request):
    """Add item from dropdown selector."""
    product_id = request.POST.get('product_id')
    if product_id:
        return cart_add(request, int(product_id))
    return redirect('pos')


def cart_remove(request, product_id):
    """Decrement quantity or remove item from cart."""
    cart = _get_cart(request)
    pid = str(product_id)

    if pid in cart:
        if cart[pid]['qty'] > 1:
            cart[pid]['qty'] -= 1
        else:
            del cart[pid]
        _save_cart(request, cart)

    if request.headers.get('HX-Request'):
        cart_items, cart_total = _calculate_cart_totals(cart)
        customers = Customer.objects.filter(is_active=True).order_by('name')
        return render(request, 'partials/cart.html', {
            'cart': cart_items,
            'cart_total': cart_total,
            'customers': customers,
        })
    return redirect('pos')


def cart_clear(request):
    """Empty the current session cart."""
    _save_cart(request, {})
    if request.headers.get('HX-Request'):
        customers = Customer.objects.filter(is_active=True).order_by('name')
        return render(request, 'partials/cart.html', {
            'cart': [],
            'cart_total': '0.00',
            'customers': customers,
        })
    return redirect('pos')


@transaction.atomic
def checkout_action(request):
    """Finalize transaction as Cash or Utang."""
    if request.method != 'POST':
        return redirect('pos')

    cart = _get_cart(request)
    if not cart:
        return redirect('pos')

    payment_method = request.POST.get('payment_method', 'CASH')
    customer_id = request.POST.get('customer_id')

    customer = None
    if payment_method == 'UTANG':
        if not customer_id:
            return redirect('pos')
        customer = get_object_or_404(Customer, pk=customer_id)

    # Calculate total
    total_amount = Decimal('0.00')
    items_to_create = []

    for pid, data in cart.items():
        product = get_object_or_404(Product, pk=int(pid))
        qty = int(data['qty'])
        unit_price = Decimal(str(data['price']))
        subtotal = unit_price * qty
        total_amount += subtotal

        # Decrement stock
        product.stock_quantity = max(0, product.stock_quantity - qty)
        product.save(update_fields=['stock_quantity', 'updated_at'])

        items_to_create.append((product, qty, unit_price, subtotal))

    # Create transaction
    sale = SaleTransaction.objects.create(
        transaction_type=payment_method,
        customer=customer,
        total_amount=total_amount,
        payment_status='PAID' if payment_method == 'CASH' else 'PENDING',
    )

    for prod, qty, price, sub in items_to_create:
        TransactionItem.objects.create(
            transaction=sale,
            product=prod,
            quantity=qty,
            unit_price=price,
            subtotal=sub,
        )

    # If utang, update customer debt
    if payment_method == 'UTANG' and customer:
        customer.debt_balance += total_amount
        customer.save(update_fields=['debt_balance', 'updated_at'])

    # Clear cart
    _save_cart(request, {})
    return redirect('pos')


def inventory_view(request):
    """Tira / Stock counts and low-inventory warnings."""
    query = request.GET.get('q', '').strip()
    selected_category = request.GET.get('category', '').strip()
    filter_status = request.GET.get('status', '').strip()

    all_active = Product.objects.filter(is_active=True)
    categories = sorted(list(set(all_active.values_list('category', flat=True))))

    products = all_active
    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(category__icontains=query) | Q(brand__icontains=query) | Q(sku__icontains=query)
        )
    if selected_category:
        products = products.filter(category=selected_category)
    if filter_status == 'low':
        products = [p for p in products if p.stock_quantity <= p.reorder_point]
    else:
        products = list(products.order_by('name'))

    low_stock_count = sum(1 for p in all_active if p.stock_quantity <= p.reorder_point)
    out_of_stock_count = sum(1 for p in all_active if p.stock_quantity <= 0)

    context = {
        'products': products,
        'query': query,
        'categories': categories,
        'selected_category': selected_category,
        'filter_status': filter_status,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'total_count': all_active.count(),
    }
    return render(request, 'inventory.html', context)


def utang_view(request):
    """Lista ng Utang / Debtor Directory."""
    query = request.GET.get('q', '').strip()
    customers_qs = Customer.objects.filter(is_active=True)

    if query:
        customers_qs = customers_qs.filter(
            Q(name__icontains=query) | Q(nickname__icontains=query) | Q(phone__icontains=query)
        )

    customers = customers_qs.order_by('-debt_balance', 'name')
    total_debt = Customer.objects.filter(is_active=True).aggregate(Sum('debt_balance'))['debt_balance__sum'] or Decimal('0.00')

    # Compute utilization ratio for display
    customer_list = []
    for c in customers:
        pct = 0
        if c.credit_limit and c.credit_limit > 0:
            pct = min(100, int((c.debt_balance / c.credit_limit) * 100))
        customer_list.append({
            'obj': c,
            'credit_pct': pct,
        })

    context = {
        'customer_list': customer_list,
        'customers': customers,
        'total_debt': f"{total_debt:.2f}",
        'query': query,
    }
    return render(request, 'utang.html', context)


@transaction.atomic
def utang_pay_action(request):
    """Record cash debt liquidation for customer."""
    if request.method == 'POST':
        customer_id = request.POST.get('customer_id')
        amount_str = request.POST.get('amount', '0')
        customer = get_object_or_404(Customer, pk=customer_id)
        amount = Decimal(amount_str)

        if amount > 0:
            CustomerPayment.objects.create(
                customer=customer,
                amount=amount,
                notes='Cash repayment at store counter',
            )
            customer.debt_balance = max(Decimal('0.00'), customer.debt_balance - amount)
            customer.save(update_fields=['debt_balance', 'updated_at'])

    return redirect('utang')


def restock_view(request):
    """Bili / Restock Budget Optimizer view."""
    return render(request, 'restock.html', {'budget': 5000})


def restock_calculate(request):
    """Calculate procurement shopping list within revolving cash budget."""
    budget = Decimal(request.POST.get('budget', '5000'))
    
    # Priority: items where stock is low or below ROP
    candidates = Product.objects.filter(is_active=True).order_by('stock_quantity')
    
    restock_items = []
    remaining_budget = budget
    total_spend = Decimal('0.00')

    for prod in candidates:
        pack_cost = prod.wholesale_cost
        if pack_cost <= 0:
            continue
        
        # Determine packs needed
        packs_to_buy = max(1, (prod.reorder_point * 2 - prod.stock_quantity) // 6)
        line_cost = pack_cost * packs_to_buy

        if line_cost <= remaining_budget:
            expected_profit = (prod.retail_price * 6 - pack_cost) * packs_to_buy
            restock_items.append({
                'name': prod.name,
                'category': prod.category,
                'packs': packs_to_buy,
                'pack_unit': prod.pack_unit,
                'unit_cost': f"{pack_cost:.2f}",
                'line_total': f"{line_cost:.2f}",
                'expected_profit': f"{max(Decimal('0.00'), expected_profit):.2f}",
            })
            remaining_budget -= line_cost
            total_spend += line_cost

        if remaining_budget < Decimal('100.00'):
            break

    total_profit = sum(Decimal(it['expected_profit']) for it in restock_items)

    context = {
        'budget': budget,
        'restock_items': restock_items,
        'total_spend': f"{total_spend:.2f}",
        'remaining_budget': f"{remaining_budget:.2f}",
        'total_profit': f"{total_profit:.2f}",
        'items_count': len(restock_items),
    }
    return render(request, 'restock.html', context)
