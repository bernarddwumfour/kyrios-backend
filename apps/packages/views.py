# apps/packages/views.py

import json
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
from django.core.paginator import Paginator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.text import slugify

from apps.utils import ok, bad_request
from apps.utils.decorators.auth import jwt_required, admin_required
from .models import Package, Subscription
from .utils import serialize_package, serialize_subscription


# ─────────────────────────────────────────
# PACKAGES
# ─────────────────────────────────────────

@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["POST"])
def create_package(request):

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return bad_request("Invalid request body")

    required_fields = {"name", "price", "billing_cycle"}
    missing = [f for f in required_fields if not str(data.get(f, "")).strip()]
    if missing:
        return bad_request(f"Missing required fields: {', '.join(missing)}")

    billing_cycle = data.get("billing_cycle", "")
    if billing_cycle not in Package.BillingCycle.values:
        return bad_request(f"Invalid billing_cycle. Must be one of: {Package.BillingCycle.values}")

    try:
        price = float(data["price"])
        if price < 0:
            raise ValueError
    except (ValueError, TypeError):
        return bad_request("Price must be a positive number e.g. 9.99")

    original_price = data.get("original_price")
    if original_price is not None:
        try:
            original_price = float(original_price)
            if original_price <= price:
                return bad_request("original_price must be greater than price")
        except (ValueError, TypeError):
            return bad_request("original_price must be a valid number")

    status = data.get("status", Package.Status.ACTIVE)
    if status not in Package.Status.values:
        return bad_request(f"Invalid status. Must be one of: {Package.Status.values}")
    
    max_difficulty = data.get("max_difficulty", Package.MaxDifficulty.ADVANCED)
    if max_difficulty not in Package.MaxDifficulty.values:
        return bad_request(f"Invalid max_difficulty. Must be one of: {Package.MaxDifficulty.values}")
    
  


    package, created = Package.objects.get_or_create(
        name=data["name"].strip(),
        defaults={
            "description":            data.get("description", "").strip(),
            "price":                  price,
            "original_price":         original_price,
            "currency":               data.get("currency", "USD").upper().strip(),
            "billing_cycle":          billing_cycle,
            "status":                 status,
            "trial_days":             int(data.get("trial_days", 0)),
            "is_unlimited":           bool(data.get("is_unlimited", False)),
            "max_courses":            data.get("max_courses"),
            "max_difficulty":         data.get("max_difficulty", Package.MaxDifficulty.ADVANCED),
            "max_students":           data.get("max_students"),
            "max_courses_at_level":   int (data.get("max_courses_at_level",3)),
            "includes_certificate":   bool(data.get("includes_certificate", False)),
            "can_download_materials": bool(data.get("can_download_materials", False)),
            "includes_video_lessons": bool(data.get("includes_video_lessons", False)),
            "video_quality":          data.get("video_quality", Package.VideoQuality.SD),
            "text_to_audio":          bool(data.get("text_to_audio", False)),
            "audio_to_text":          bool(data.get("audio_to_text", False)),
            "audio_minutes_per_month": int(data.get("audio_minutes_per_month", 0)),
            "ai_credits_per_month":   int(data.get("ai_credits_per_month", 0)),
            "ai_question_generation": bool(data.get("ai_question_generation", False)),
            "ai_explanations":        bool(data.get("ai_explanations", False)),
            "is_featured":            bool(data.get("is_featured", False)),
            "badge_text":             data.get("badge_text", "").strip(),
            "display_order":          int(data.get("display_order", 0)),
        }
    )

    if not created:
        return bad_request("A package with this name already exists")

    return ok(data=serialize_package(package, is_admin=True), message="Package created successfully")


@csrf_exempt
# @jwt_required
@require_http_methods(["GET"])
def list_packages(request):
    is_admin = request.user.is_staff

    try:
        page_size   = max(1, min(int(request.GET.get("page_size", 10)), 100))
        page_number = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        return bad_request("page and page_size must be valid integers")

    queryset = Package.objects.order_by("display_order", "price")

    if is_admin:
        status_filter = request.GET.get("status", "all")
        if status_filter not in [*Package.Status.values, "all"]:
            return bad_request(f"Invalid status. Must be one of: {Package.Status.values}")
        if status_filter != "all":
            queryset = queryset.filter(status=status_filter)
    else:
        # Students only see active packages
        queryset = queryset.filter(status=Package.Status.ACTIVE)

    paginator = Paginator(queryset, page_size)
    page      = paginator.get_page(page_number)
    
    print("here")
    

    return ok(
        data={
            "results": [serialize_package(p, is_admin=is_admin) for p in page.object_list],
            "pagination": {
                "total":         paginator.count,
                "total_pages":   paginator.num_pages,
                "current_page":  page.number,
                "page_size":     page_size,
                "has_next":      page.has_next(),
                "has_previous":  page.has_previous(),
                "next_page":     page.next_page_number() if page.has_next() else None,
                "previous_page": page.previous_page_number() if page.has_previous() else None,
            }
        },
        message="Packages listed successfully"
    )


@csrf_exempt
@jwt_required
@require_http_methods(["GET"])
def package_detail(request, id):
    is_admin = request.user.is_staff

    try:
        package = Package.objects.get(id=id)
    except Package.DoesNotExist:
        return bad_request("Package not found")
    except Exception:
        return bad_request("Invalid package ID format")

    if not is_admin and package.status != Package.Status.ACTIVE:
        return bad_request("Package not found")

    return ok(data=serialize_package(package, is_admin=is_admin), message="Package retrieved successfully")


@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["PATCH"])
def update_package(request, id):

    try:
        package = Package.objects.get(id=id)
    except Package.DoesNotExist:
        return bad_request("Package not found")
    except Exception:
        return bad_request("Invalid package ID format")

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return bad_request("Invalid request body")

    if not data:
        return bad_request("No fields provided to update")

    # Simple string fields
    if "name" in data:
        name = data["name"].strip()
        if not name:
            return bad_request("Name cannot be blank")
        if Package.objects.exclude(id=id).filter(name=name).exists():
            return bad_request("A package with this name already exists")
        package.name = name
        package.slug = slugify(name)

    if "description" in data:
        package.description = data["description"].strip()

    if "badge_text" in data:
        package.badge_text = data["badge_text"].strip()

    if "currency" in data:
        package.currency = data["currency"].upper().strip()

    # Status
    if "status" in data:
        if data["status"] not in Package.Status.values:
            return bad_request(f"Invalid status. Must be one of: {Package.Status.values}")
        package.status = data["status"]

    # Billing cycle
    if "billing_cycle" in data:
        if data["billing_cycle"] not in Package.BillingCycle.values:
            return bad_request(f"Invalid billing_cycle. Must be one of: {Package.BillingCycle.values}")
        package.billing_cycle = data["billing_cycle"]

    # Pricing
    if "price" in data:
        try:
            price = float(data["price"])
            if price < 0:
                raise ValueError
            package.price = price
        except (ValueError, TypeError):
            return bad_request("Price must be a positive number")

    if "original_price" in data:
        original_price = data["original_price"]
        if original_price is None:
            package.original_price = None
        else:
            try:
                original_price = float(original_price)
                if original_price <= float(package.price):
                    return bad_request("original_price must be greater than current price")
                package.original_price = original_price
            except (ValueError, TypeError):
                return bad_request("original_price must be a valid number")
            

    if "max_difficulty" in data:
        if data["max_difficulty"] not in Package.MaxDifficulty.values:
            return bad_request(f"Invalid max_difficulty. Must be one of: {Package.MaxDifficulty.values}")
        package.max_difficulty = data["max_difficulty"]

    # Numeric fields
    for field in ["trial_days", "max_courses_at_level", "max_students",
                  "audio_minutes_per_month", "ai_credits_per_month", "display_order"]:
        if field in data:
            val = data[field]
            if val is None:
                setattr(package, field, None)
            else:
                try:
                    setattr(package, field, int(val))
                except (ValueError, TypeError):
                    return bad_request(f"{field} must be a valid integer")

    # Boolean fields
    for field in ["is_unlimited", "includes_certificate", "can_download_materials",
                  "includes_video_lessons", "text_to_audio", "audio_to_text",
                  "ai_question_generation", "ai_explanations", "is_featured", "auto_renew"]:
        if field in data:
            package.__setattr__(field, bool(data[field]))

    # Video quality
    if "video_quality" in data:
        if data["video_quality"] not in Package.VideoQuality.values:
            return bad_request(f"Invalid video_quality. Must be one of: {Package.VideoQuality.values}")
        package.video_quality = data["video_quality"]

    package.save()

    return ok(data=serialize_package(package, is_admin=True), message="Package updated successfully")


@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["DELETE"])
def delete_package(request, id):

    try:
        package = Package.objects.prefetch_related("subscriptions").get(id=id)
    except Package.DoesNotExist:
        return bad_request("Package not found")
    except Exception:
        return bad_request("Invalid package ID format")

    # Block deletion if active subscriptions exist
    active_subs = package.subscriptions.filter(
        status__in=[Subscription.Status.ACTIVE, Subscription.Status.TRIAL]
    ).count()

    if active_subs > 0:
        return bad_request(
            f"Cannot delete package with {active_subs} active subscription(s). "
            f"Deactivate the package instead."
        )

    package_name = package.name
    package.delete()

    return ok(data={"name": package_name}, message="Package deleted successfully")


# ─────────────────────────────────────────
# SUBSCRIPTIONS
# ─────────────────────────────────────────

@csrf_exempt
@jwt_required
@require_http_methods(["POST"])
def subscribe(request):
    """
    Student subscribes to a package.
    One active subscription per user at a time.
    """

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return bad_request("Invalid request body")

    # 1. Validate package
    package_id = data.get("package_id", "").strip()
    if not package_id:
        return bad_request("package_id is required")

    try:
        package = Package.objects.get(id=package_id, status=Package.Status.ACTIVE)
    except Package.DoesNotExist:
        return bad_request("Package not found or unavailable")
    except Exception:
        return bad_request("Invalid package ID format")

    # 2. Check for existing active subscription
    existing = Subscription.objects.filter(
        user=request.user,
        status__in=[Subscription.Status.ACTIVE, Subscription.Status.TRIAL]
    ).first()

    if existing:
        return bad_request(
            f"You already have an active subscription to '{existing.package.name}'. "
            f"Cancel it before subscribing to a new package."
        )

    # 3. Create subscription inside a transaction
    with transaction.atomic():
        now = timezone.now()

        # Determine if trial applies
        is_trial    = package.has_trial
        trial_ends  = now + timedelta(days=package.trial_days) if is_trial else None

        # Calculate expiry based on billing cycle
        if package.billing_cycle == Package.BillingCycle.MONTHLY:
            expires_at = now + timedelta(days=30)
        elif package.billing_cycle == Package.BillingCycle.YEARLY:
            expires_at = now + timedelta(days=365)
        else:
            # Lifetime — never expires
            expires_at = None

        subscription = Subscription.objects.create(
            user=request.user,
            package=package,
            status=Subscription.Status.TRIAL if is_trial else Subscription.Status.ACTIVE,
            trial_ends_at=trial_ends,
            expires_at=trial_ends if is_trial else expires_at,
            payment_reference=data.get("payment_reference", "").strip(),
        )

    return ok(
        data=serialize_subscription(subscription),
        message=f"Successfully subscribed to {package.name}"
    )


@csrf_exempt
@jwt_required
@require_http_methods(["GET"])
def my_subscription(request):
    """Returns the current user's active subscription."""

    try:
        subscription = Subscription.objects.select_related("package").get(
            user=request.user,
            status__in=[Subscription.Status.ACTIVE, Subscription.Status.TRIAL]
        )
    except Subscription.DoesNotExist:
        return bad_request("You do not have an active subscription")

    return ok(data=serialize_subscription(subscription), message="Subscription retrieved successfully")


@csrf_exempt
@jwt_required
@require_http_methods(["POST"])
def cancel_subscription(request):
    """Student cancels their own active subscription."""

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return bad_request("Invalid request body")

    # 1. Get active subscription
    try:
        subscription = Subscription.objects.select_related("package").get(
            user=request.user,
            status__in=[Subscription.Status.ACTIVE, Subscription.Status.TRIAL]
        )
    except Subscription.DoesNotExist:
        return bad_request("You do not have an active subscription to cancel")

    # 2. Validate cancellation reason if provided
    reason = data.get("reason", "").strip()
    if reason and reason not in Subscription.CancellationReason.values:
        return bad_request(f"Invalid reason. Must be one of: {Subscription.CancellationReason.values}")

    # 3. Cancel
    subscription.status              = Subscription.Status.CANCELLED
    subscription.cancelled_at        = timezone.now()
    subscription.auto_renew          = False
    subscription.cancellation_reason = reason
    subscription.cancellation_note   = data.get("note", "").strip()
    subscription.save(update_fields=[
        "status", "cancelled_at", "auto_renew",
        "cancellation_reason", "cancellation_note"
    ])

    return ok(
        data=serialize_subscription(subscription),
        message="Subscription cancelled successfully"
    )


@csrf_exempt
@jwt_required
@require_http_methods(["GET"])
def subscription_history(request):
    """Returns all of the current user's subscriptions — including past ones."""

    try:
        page_size   = max(1, min(int(request.GET.get("page_size", 10)), 100))
        page_number = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        return bad_request("page and page_size must be valid integers")

    queryset = Subscription.objects.select_related("package") \
                                   .filter(user=request.user) \
                                   .order_by("-created_at")

    paginator = Paginator(queryset, page_size)
    page      = paginator.get_page(page_number)

    return ok(
        data={
            "results": [serialize_subscription(s) for s in page.object_list],
            "pagination": {
                "total":         paginator.count,
                "total_pages":   paginator.num_pages,
                "current_page":  page.number,
                "page_size":     page_size,
                "has_next":      page.has_next(),
                "has_previous":  page.has_previous(),
                "next_page":     page.next_page_number() if page.has_next() else None,
                "previous_page": page.previous_page_number() if page.has_previous() else None,
            }
        },
        message="Subscription history retrieved successfully"
    )


# ── Admin Subscription Views ──────────────────────────────

@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["GET"])
def admin_list_subscriptions(request):
    """Admin view — all subscriptions across all users."""

    print("Here")
    try:
        page_size   = max(1, min(int(request.GET.get("page_size", 10)), 100))
        page_number = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        return bad_request("page and page_size must be valid integers")

    queryset = Subscription.objects.select_related("user", "package").order_by("-created_at")
    
                                   
                                
    # Filter by status
    status_filter = request.GET.get("status", "all")
    if status_filter not in [*Subscription.Status.values, "all"]:
        return bad_request(f"Invalid status. Must be one of: {Subscription.Status.values}")
    if status_filter != "all":
        queryset = queryset.filter(status=status_filter)

    # Filter by package
    package_id = request.GET.get("package")
    if package_id:
        queryset = queryset.filter(package__id=package_id)

    paginator = Paginator(queryset, page_size)
    page      = paginator.get_page(page_number)

    return ok(
        data={
            "results": [serialize_subscription(s, is_admin=True) for s in page.object_list],
            "pagination": {
                "total":         paginator.count,
                "total_pages":   paginator.num_pages,
                "current_page":  page.number,
                "page_size":     page_size,
                "has_next":      page.has_next(),
                "has_previous":  page.has_previous(),
                "next_page":     page.next_page_number() if page.has_next() else None,
                "previous_page": page.previous_page_number() if page.has_previous() else None,
            }
        },
        message="Subscriptions listed successfully"
    )


@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["PATCH"])
def admin_update_subscription(request, id):
    """Admin can manually adjust a subscription — extend, pause, activate."""

    try:
        subscription = Subscription.objects.select_related("package").get(id=id)
    except Subscription.DoesNotExist:
        return bad_request("Subscription not found")
    except Exception:
        return bad_request("Invalid subscription ID format")

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return bad_request("Invalid request body")

    if not data:
        return bad_request("No fields provided to update")

    if "status" in data:
        if data["status"] not in Subscription.Status.values:
            return bad_request(f"Invalid status. Must be one of: {Subscription.Status.values}")
        subscription.status = data["status"]

    if "expires_at" in data:
        try:
            from django.utils.dateparse import parse_datetime
            expires_at = parse_datetime(data["expires_at"])
            if not expires_at:
                raise ValueError
            subscription.expires_at = expires_at
        except (ValueError, TypeError):
            return bad_request("Invalid expires_at format. Use ISO 8601 e.g. 2025-12-31T00:00:00Z")

    if "auto_renew" in data:
        subscription.auto_renew = bool(data["auto_renew"])

    if "ai_credits_used" in data:
        try:
            subscription.ai_credits_used = int(data["ai_credits_used"])
        except (ValueError, TypeError):
            return bad_request("ai_credits_used must be a valid integer")

    if "audio_minutes_used" in data:
        try:
            subscription.audio_minutes_used = int(data["audio_minutes_used"])
        except (ValueError, TypeError):
            return bad_request("audio_minutes_used must be a valid integer")

    subscription.save()

    return ok(
        data=serialize_subscription(subscription, is_admin=True),
        message="Subscription updated successfully"
    )