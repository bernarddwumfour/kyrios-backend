
from .models import CourseRegistration, CoursePurchase
from apps.packages.models import Subscription


def get_course_access(user, course):
    """
    Checks how a user can access a course.

    Returns a dict:
    {
        "has_access": bool,
        "access_type": "purchase" | "subscription" | None,
        "is_purchased": bool,
        "is_registered": bool,
        "purchase": CoursePurchase | None,
        "registration": CourseRegistration | None,
    }

    Priority: purchase > subscription
    """

    result = {
        "has_access":    False,
        "access_type":   None,
        "is_purchased":  False,
        "is_registered": False,
        "purchase":      None,
        "registration":  None,
    }

    # ── 1. Check purchase first — permanent access wins ───
    purchase = CoursePurchase.objects.filter(
        user=user,
        course=course,
        status=CoursePurchase.Status.ACTIVE,
    ).first()

    if purchase:
        result["has_access"]   = True
        result["access_type"]  = "purchase"
        result["is_purchased"] = True
        result["purchase"]     = purchase
        return result

    # ── 2. Check subscription registration ───────────────
    registration = CourseRegistration.objects.filter(
        user=user,
        course=course,
        status=CourseRegistration.Status.ACTIVE,
    ).select_related("subscription").first()

    if registration and registration.subscription.is_active:
        result["has_access"]    = True
        result["access_type"]   = "subscription"
        result["is_registered"] = True
        result["registration"]  = registration
        return result

    return result


def get_ai_access(user) -> bool:
    """
    AI features are ALWAYS tied to subscription only.
    Never granted by course purchase.
    """
    try:
        subscription = Subscription.objects.get(
            user=user,
            status__in=["active", "trial", "grace"]
        )
        return (
            subscription.is_active and
            subscription.package.ai_credits_per_month > 0 and
            subscription.ai_credits_remaining > 0
        )
    except Subscription.DoesNotExist:
        return False