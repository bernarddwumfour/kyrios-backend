# courses/registration.py

from django.db import transaction
from .models import CourseRegistration, CoursePurchase, Course, DIFFICULTY_HIERARCHY
from .prerequisites import get_all_prerequisites


def get_purchased_course_ids(user) -> set:
    """
    Returns IDs of all courses a user owns via purchase —
    including all prerequisites granted by those purchases.
    These are EXCLUDED from subscription limit counts.
    """
    direct_purchases = CoursePurchase.objects.filter(
        user=user,
        status=CoursePurchase.Status.ACTIVE,
    ).select_related("course").prefetch_related("course__prerequisites")

    all_owned_ids = set()

    for purchase in direct_purchases:
        all_owned_ids.add(purchase.course.id)
        # Prerequisites granted by purchase also don't count
        for prereq in get_all_prerequisites(purchase.course):
            all_owned_ids.add(prereq.id)

    return all_owned_ids


def validate_and_register(user, course, subscription) -> tuple:
    """
    Validates all package restrictions then creates a registration.
    Returns (registration, None) on success.
    Returns (None, error_message) on failure.

    Checks in order:
    1. Subscription is active
    2. Course is active
    3. Already registered or purchased
    4. Difficulty ceiling check
    5. Course limit at ceiling level (excluding purchased courses)
    6. Subject restriction
    """

    package = subscription.package

    # ── 1. Subscription active ────────────────────────────
    if not subscription.is_active:
        return None, "Your subscription is not active"

    # ── 2. Course active ──────────────────────────────────
    if course.status != Course.Status.ACTIVE:
        return None, "This course is not available"

    # ── 3. Already registered ─────────────────────────────
    already_registered = CourseRegistration.objects.filter(
        user=user,
        course=course,
        status=CourseRegistration.Status.ACTIVE,
    ).exists()

    if already_registered:
        return None, "You are already registered for this course"

    # ── 4. Difficulty ceiling check ───────────────────────
    if not package.is_unlimited:
        course_level   = DIFFICULTY_HIERARCHY.get(course.difficulty, 0)
        ceiling_level  = DIFFICULTY_HIERARCHY.get(package.max_difficulty, 0)

        if course_level > ceiling_level:
            # Above ceiling — no access
            return None, (
                f"Your '{package.name}' package only allows access up to "
                f"'{package.get_max_difficulty_display()}' courses. "
                f"This is an '{course.get_difficulty_display()}' course. "
                f"Upgrade your package to access this level."
            )

        elif course_level == ceiling_level:
            # ── 5. At ceiling — check limit ───────────────
            if package.max_courses_at_level is not None:

                # Get all purchased course IDs — these don't count toward limit
                purchased_ids = get_purchased_course_ids(user)

                # Count only subscription registrations at this level
                # that are not also purchased
                current_count = CourseRegistration.objects.filter(
                    user=user,
                    course__difficulty=course.difficulty,
                    status__in=[
                        CourseRegistration.Status.ACTIVE,
                        CourseRegistration.Status.COMPLETED,
                    ]
                ).exclude(
                    course_id__in=purchased_ids
                ).count()

                if current_count >= package.max_courses_at_level:
                    return None, (
                        f"You have reached your limit of "
                        f"{package.max_courses_at_level} "
                        f"'{course.get_difficulty_display()}' course(s) "
                        f"on the '{package.name}' plan. "
                        f"Drop a course or upgrade your package to add more."
                    )

        # course_level < ceiling_level → below ceiling → unlimited, no check

    # ── 6. Subject restriction ────────────────────────────
    if package.subjects.exists():
        allowed_subject_ids = package.subjects.values_list("id", flat=True)
        if course.subject_id not in allowed_subject_ids:
            return None, (
                f"Your '{package.name}' package does not include "
                f"the '{course.subject.name}' subject."
            )

    # ── All checks passed — create registration ───────────
    with transaction.atomic():
        registration = CourseRegistration.objects.create(
            user=user,
            course=course,
            subscription=subscription,
        )

    return registration, None