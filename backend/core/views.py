from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, HttpResponseForbidden
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from core.models import Product, Customer, CustomerPayment, Transaction as SaleTransaction, TransactionItem, StoreConfig
from core.services.knapsack import solve_restock_knapsack
from core.services.analytics import get_financial_analytics, get_inventory_turnover_analytics
from core.services.inventory import deplete_product_inventory_fifo


def _get_cart(request):
    return request.session.get('cart', {})


def _save_cart(request, cart):
    request.session['cart'] = cart
    request.session.modified = True


def _calculate_cart_totals(cart):
    items = []
    total = Decimal('0.00')
    for product_id, data in cart.items():
        qty = Decimal(str(data['qty']))
        subtotal = Decimal(str(data['price'])) * qty
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
    
    # 9 popular tingi items for 3x3 quick tap grid
    tingi_products = Product.objects.filter(is_active=True).order_by('category', 'name')[:9]
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
        curr_qty = Decimal(str(cart[pid]['qty'])) + Decimal('1')
        cart[pid]['qty'] = int(curr_qty) if curr_qty == int(curr_qty) else float(curr_qty)
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
        return cart_add(request, product_id)
    return redirect('pos')


def cart_remove(request, product_id):
    """Decrement quantity or remove item from cart."""
    cart = _get_cart(request)
    pid = str(product_id)

    if pid in cart:
        curr_qty = Decimal(str(cart[pid]['qty']))
        if curr_qty > 1:
            new_qty = curr_qty - Decimal('1')
            cart[pid]['qty'] = int(new_qty) if new_qty == int(new_qty) else float(new_qty)
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
    """Finalize transaction as Cash or Utang with FIFO inventory depletion and ledger audit."""
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
            return HttpResponse("Customer is required for Utang transactions.", status=400)
        customer = get_object_or_404(Customer.objects.select_for_update(), pk=customer_id)
        if not customer:
            return HttpResponse("Customer is required for Utang transactions.", status=400)

    # Calculate total and validate stock
    total_amount = Decimal('0.00')
    items_to_process = []

    for pid, data in cart.items():
        product = get_object_or_404(Product.objects.select_for_update(), pk=pid)
        qty = Decimal(str(data['qty']))

        # Stock non-negativity guard: if stock < qty, block checkout
        if product.stock_quantity < qty:
            return redirect('pos')

        unit_price = Decimal(str(data['price']))
        subtotal = unit_price * qty
        total_amount += subtotal
        items_to_process.append((product, qty, unit_price, subtotal))

    # Check credit limit ceiling for UTANG
    if payment_method == 'UTANG':
        if customer.debt_balance + total_amount > customer.credit_limit:
            return HttpResponse("Lagpas sa Credit Limit!", status=400)
        customer.debt_balance += total_amount
        customer.save(update_fields=['debt_balance', 'updated_at'])

    # Create transaction
    sale = SaleTransaction.objects.create(
        transaction_type=payment_method,
        customer=customer,
        total_amount=total_amount,
        payment_status='PAID' if payment_method == 'CASH' else 'PENDING',
    )

    total_cogs = Decimal('0.00')
    for prod, qty, price, sub in items_to_process:
        item_cogs, effective_cost = deplete_product_inventory_fifo(prod, qty, reference_id=str(sale.id))
        total_cogs += item_cogs

        TransactionItem.objects.create(
            transaction=sale,
            product=prod,
            quantity=qty,
            unit_price=price,
            cost_price=effective_cost,
            subtotal=sub,
        )

    sale.total_cogs = total_cogs
    sale.gross_profit = sale.total_amount - total_cogs
    sale.save(update_fields=['total_cogs', 'gross_profit'])

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
    if request.method != 'POST':
        return redirect('utang')

    customer_id = request.POST.get('customer_id')
    if not customer_id:
        return HttpResponse("Customer ID is required.", status=400)

    customer = get_object_or_404(Customer.objects.select_for_update(), pk=customer_id)
    amount_str = request.POST.get('amount', '0')

    try:
        amount = Decimal(str(amount_str))
    except Exception:
        return HttpResponse("Invalid payment amount.", status=400)

    if amount <= Decimal('0.00'):
        return HttpResponse("Payment amount must be greater than zero.", status=400)

    balance_before = customer.debt_balance
    balance_after = max(Decimal('0.00'), customer.debt_balance - amount)
    CustomerPayment.objects.create(
        customer=customer,
        amount=amount,
        balance_before=balance_before,
        balance_after=balance_after,
        notes=request.POST.get('notes') or 'Cash repayment at store counter',
    )
    customer.debt_balance = balance_after
    customer.save(update_fields=['debt_balance', 'updated_at'])

    return redirect('utang')


def restock_view(request):
    """Bili / Restock Budget Optimizer view."""
    return render(request, 'restock.html', {'budget': 5000})


def restock_calculate(request):
    """Calculate procurement shopping list within revolving cash budget."""
    budget_raw = request.POST.get('budget', '5000')
    try:
        budget = Decimal(str(budget_raw))
        if budget <= Decimal('0.00'):
            budget = Decimal('5000.00')
    except Exception:
        budget = Decimal('5000.00')

    # Candidate products: active items where stock <= reorder_point * 2; fallback to all active
    products_qs = Product.objects.filter(is_active=True)
    candidates = [p for p in products_qs if p.stock_quantity <= p.reorder_point * 2]
    if not candidates:
        candidates = list(products_qs)

    knapsack_res = solve_restock_knapsack(candidates, budget)

    context = {
        'budget': f"{budget:.2f}",
        'restock_items': knapsack_res['items'],
        'categorized_items': knapsack_res['categorized_items'],
        'total_spend': f"{knapsack_res['total_spent']:.2f}",
        'remaining_budget': f"{knapsack_res['remaining_budget']:.2f}",
        'total_profit': f"{knapsack_res['expected_profit']:.2f}",
        'items_count': len(knapsack_res['items']),
        'solver_status': knapsack_res['solver_status'],
    }
    return render(request, 'restock.html', context)


def receipt_upload_view(request):
    """View to upload and scan wholesaler receipts."""
    return render(request, 'receipt_upload.html')


def analytics_view(request):
    """Real-time financial dashboard displaying profit, margins, strict cash vs utang liquidity, and inventory turnover."""
    period = request.GET.get('period', 'all')
    analytics = get_financial_analytics(period=period)
    turnover = get_inventory_turnover_analytics()
    context = {
        'period': period,
        'analytics': analytics,
        'turnover': turnover,
        'fast_moving': turnover['fast_moving'],
        'dead_stock': turnover['dead_stock'],
        'all_items': turnover['all_items'],
        'all_skus': turnover['all_skus'],
        'fast_moving_count': turnover['fast_moving_count'],
        'dead_stock_count': turnover['dead_stock_count'],
        'dead_stock_tied_capital': f"{turnover['dead_stock_tied_capital']:.2f}",
        'gross_revenue': f"{analytics['gross_revenue']:.2f}",
        'cogs': f"{analytics['cogs']:.2f}",
        'net_profit': f"{analytics['net_profit']:.2f}",
        'profit_margin_pct': f"{analytics['profit_margin_pct']:.1f}",
        'cash_on_hand': f"{analytics['cash_on_hand']:.2f}",
        'uncollected_utang': f"{analytics['uncollected_utang']:.2f}",
        'cash_sales_total': f"{analytics['cash_sales_total']:.2f}",
        'utang_sales_total': f"{analytics['utang_sales_total']:.2f}",
        'repayments_total': f"{analytics['repayments_total']:.2f}",
        'total_transactions_count': analytics['total_transactions_count'],
    }
    return render(request, 'analytics.html', context)


def settings_view(request):
    """Store configuration frontend editor. Protected: only logged-in Admins/Staff can access."""
    if not request.user.is_authenticated:
        return redirect(f"/admin/login/?next={request.path}")
    if not (request.user.is_staff or request.user.is_superuser):
        return HttpResponseForbidden("Access Denied: Admin or Staff privileges required.")

    config = StoreConfig.get_solo()
    errors = []
    success_message = None

    form_values = {
        'store_name': config.store_name,
        'caretaker_identity': config.caretaker_identity,
        'default_retail_markup_percentage': config.default_retail_markup_percentage,
    }

    if request.method == 'POST':
        store_name = request.POST.get('store_name', '').strip()
        caretaker_identity = request.POST.get('caretaker_identity', '').strip()
        markup_raw = request.POST.get('default_retail_markup_percentage', '').strip()

        form_values['store_name'] = store_name
        form_values['caretaker_identity'] = caretaker_identity
        form_values['default_retail_markup_percentage'] = markup_raw

        if not store_name:
            errors.append(_("Store name cannot be empty."))
        elif len(store_name) > 255:
            errors.append(_("Store name cannot exceed 255 characters."))

        if not caretaker_identity:
            errors.append(_("Caretaker identity cannot be empty."))
        elif len(caretaker_identity) > 255:
            errors.append(_("Caretaker identity cannot exceed 255 characters."))

        markup = None
        try:
            markup = Decimal(markup_raw)
            if markup < Decimal('0.00') or markup > Decimal('999.99'):
                errors.append(_("Retail markup percentage must be between 0.00% and 999.99%."))
        except Exception:
            errors.append(_("Invalid markup percentage value."))

        if not errors:
            config.store_name = store_name
            config.caretaker_identity = caretaker_identity
            config.default_retail_markup_percentage = markup
            try:
                config.full_clean()
                config.save()
                success_message = _("Store configuration successfully updated.")
                form_values['store_name'] = config.store_name
                form_values['caretaker_identity'] = config.caretaker_identity
                form_values['default_retail_markup_percentage'] = config.default_retail_markup_percentage
            except ValidationError as ve:
                if hasattr(ve, 'message_dict'):
                    for msgs in ve.message_dict.values():
                        errors.extend(msgs)
                else:
                    errors.extend(ve.messages)

    context = {
        'config': form_values,
        'errors': errors,
        'success_message': success_message,
    }
    status = 400 if (request.method == 'POST' and errors) else 200
    return render(request, 'settings.html', context, status=status)


def switch_language_view(request, lang_code):
    """Direct helper to switch language and redirect back."""
    next_url = request.GET.get('next') or request.META.get('HTTP_REFERER') or '/'
    if not url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = '/'

    lang_code_lower = (lang_code or '').strip().lower()
    if lang_code_lower in ('filipino', 'pilipino'):
        lang_code_lower = 'fil'
    elif lang_code_lower in ('tagalog',):
        lang_code_lower = 'tl'
    elif lang_code_lower in ('english',):
        lang_code_lower = 'en'

    supported = dict(settings.LANGUAGES)
    if lang_code_lower in supported:
        translation.activate(lang_code_lower)
        response = redirect(next_url)
        response.set_cookie(
            settings.LANGUAGE_COOKIE_NAME,
            lang_code_lower,
            max_age=settings.LANGUAGE_COOKIE_AGE,
            path=settings.LANGUAGE_COOKIE_PATH,
            domain=settings.LANGUAGE_COOKIE_DOMAIN,
            secure=settings.LANGUAGE_COOKIE_SECURE,
            httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
            samesite=settings.LANGUAGE_COOKIE_SAMESITE,
        )
        if hasattr(request, 'session'):
            request.session['_language'] = lang_code_lower
        return response
    return redirect(next_url)


def service_worker_view(request):
    """Serve root-scoped service worker file with Service-Worker-Allowed: / header."""
    sw_file = settings.BASE_DIR / 'static' / 'sw.js'
    if sw_file.exists():
        with open(sw_file, 'r', encoding='utf-8') as f:
            content = f.read()
        response = HttpResponse(content, content_type='application/javascript')
        response['Service-Worker-Allowed'] = '/'
        return response
    return HttpResponse("// sw.js not found", content_type='application/javascript', status=404)


def manifest_view(request):
    """Serve PWA web app manifest at root /manifest.json."""
    manifest_file = settings.BASE_DIR / 'static' / 'manifest.json'
    if manifest_file.exists():
        with open(manifest_file, 'r', encoding='utf-8') as f:
            content = f.read()
        return HttpResponse(content, content_type='application/json')
    return HttpResponse("{}", content_type='application/json', status=404)


