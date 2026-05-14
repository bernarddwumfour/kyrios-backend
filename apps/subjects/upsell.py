# courses/upsell.py

from .models import Course, CoursePurchase
from .access import get_course_access


def get_upsell_options(course, user=None) -> list:
    """
    Returns courses that directly list this course as a prerequisite
    (1 level up ONLY — no grandparents).

    For each parent course, shows:
    - Its price and purchasability
    - All its other prerequisites (so user sees full value)
    - Whether it's better value than buying this course alone

    Filters out:
    - Courses the user already owns/has access to
    - Courses not available for purchase
    - Inactive courses
    """

    # Direct parents only — 1 level up
    parent_courses = course.unlocks.filter(
        status=Course.Status.ACTIVE,
    ).prefetch_related(
        "prerequisites",
        "prerequisites__subject",
        "subject",
    )

    options = []

    for parent in parent_courses:

        # Skip if user already has access to the parent
        if user and user.is_authenticated:
            access = get_course_access(user, parent)
            if access["has_access"]:
                continue

        # Build the list of ALL prerequisites for the parent
        # So user sees the full value of buying the parent
        all_prereqs = parent.prerequisites.all()

        # Separate the current course from other prerequisites
        # so UI can highlight "includes this course + these others"
        other_prereqs = [
            {
                "id":         str(p.id),
                "name":       p.name,
                "slug":       p.slug,
                "difficulty": p.difficulty,
                "subject":    p.subject.name,
            }
            for p in all_prereqs
            if p.id != course.id
        ]

        # Value comparison — is buying the parent cheaper than
        # or equal to buying this course + its siblings separately?
        sibling_total = None
        if parent.is_purchasable:
            purchasable_siblings = [
                p for p in all_prereqs
                if p.id != course.id and p.price is not None
            ]
            if purchasable_siblings:
                sibling_total = sum(
                    float(p.price) for p in purchasable_siblings
                ) + float(course.price or 0)

        is_better_value = (
            parent.is_purchasable and
            sibling_total is not None and
            float(parent.price) <= sibling_total
        )

        options.append({
            "id":            str(parent.id),
            "name":          parent.name,
            "slug":          parent.slug,
            "difficulty":    parent.difficulty,
            "subject": {
                "id":   str(parent.subject.id),
                "name": parent.subject.name,
            },
            "price":         str(parent.price) if parent.price else None,
            "is_purchasable": parent.is_purchasable,

            # The current course is included in this parent
            "includes_this_course": True,

            # Other courses also included via prerequisites
            "also_includes": other_prereqs,

            # Total prerequisites count
            "total_prerequisites": len(all_prereqs),

            # Whether buying parent is better value than buying separately
            "is_better_value": is_better_value,

            # UI-friendly message
            "offer_message": _build_offer_message(
                parent, course, other_prereqs, is_better_value
            ),
        })

    return options


def _build_offer_message(parent, current_course, other_prereqs, is_better_value) -> str:
    """
    Builds a human-readable message for the upsell option.

    e.g. "'{current}' is included in '{parent}'. 
          Buying '{parent}' also grants you access to: CSS Basics, JavaScript Intro."
    """
    message = (
        f"'{current_course.name}' is included in "
        f"'{parent.name}'"
    )

    if other_prereqs:
        other_names = ", ".join(f"'{p['name']}'" for p in other_prereqs[:3])
        if len(other_prereqs) > 3:
            other_names += f" and {len(other_prereqs) - 3} more"
        message += f". Buying '{parent.name}' also grants you access to: {other_names}."
    else:
        message += "."

    if is_better_value:
        message += " This is better value than purchasing the courses individually."

    return message