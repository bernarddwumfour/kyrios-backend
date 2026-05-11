# courses/utils.py

def serialize_course(course, include_modules=False, is_admin=False, user=None) -> dict:
    data = {
        "id":           str(course.id),
        "name":         course.name,
        "slug":         course.slug,
        "description":  course.description,
        "subject": {
            "id":   str(course.subject.id),
            "name": course.subject.name,
            "slug": course.subject.slug,
        },
        "difficulty":      course.difficulty,
        "duration":        course.duration,
        "status":          course.status,

        "price":           str(course.price) if course.price is not None else None,
        "is_purchasable":  course.is_purchasable,
    }

    if is_admin:
        data["created_at"] = course.created_at.isoformat()
        data["updated_at"] = course.updated_at.isoformat()

    if user and user.is_authenticated:
        from .access import get_course_access
        from .models import CourseProgress

        access = get_course_access(user, course)

        # Get progress if it exists
        progress_record = CourseProgress.objects.filter(
            user=user, course=course
        ).first()

        data["user_access"] = {
            "has_access":    access["has_access"],
            "access_type":   access["access_type"],     # "purchase" | "subscription" | None
            "is_purchased":  access["is_purchased"],
            "is_registered": access["is_registered"],
            "progress":      progress_record.progress if progress_record else 0,
            "is_completed":  progress_record.is_completed if progress_record else False,
            "completed_at":  progress_record.completed_at.isoformat() if progress_record and progress_record.completed_at else None,
        }

    # if include_modules:
    #     data["modules"] = [
    #         {
    #             "id":          str(m.id),
    #             "name":        m.name,
    #             "slug":        m.slug,
    #             "description": m.description,
    #             "order":       m.order,
    #             **({"status":     m.status,
    #                 "created_at": m.created_at.isoformat(),
    #                 "updated_at": m.updated_at.isoformat(),
    #                 } if is_admin else {}),
    #         }
    #         for m in course.modules.all()
    #         if is_admin or m.status == "active"
    #     ]

    return data


def serialize_subject(subject, include_courses=False, is_admin=False) -> dict:
    # Unchanged
    data = {
        "id":           str(subject.id),
        "name":         subject.name,
        "slug":         subject.slug,
        "description":  subject.description,
        "status":       subject.status,
        "course_count": subject.courses.count(),
    }

    if is_admin:
        data["created_at"] = subject.created_at.isoformat()
        data["updated_at"] = subject.updated_at.isoformat()

    if include_courses:
        data["courses"] = [
            serialize_course(c, is_admin=is_admin)
            for c in subject.courses.all()
        ]

    return data


def serialize_registration(registration, is_admin=False) -> dict:
    from .models import CourseProgress

    progress_record = CourseProgress.objects.filter(
        user=registration.user,
        course=registration.course,
    ).first()

    data = {
        "id":          str(registration.id),
        "course": {
            "id":         str(registration.course.id),
            "name":       registration.course.name,
            "slug":       registration.course.slug,
            "difficulty": registration.course.difficulty,
            "duration":   registration.course.duration,
            "price":      str(registration.course.price) if registration.course.price else None,
            "subject": {
                "id":   str(registration.course.subject.id),
                "name": registration.course.subject.name,
            }
        },
        "status":      registration.status,

        "progress":    progress_record.progress if progress_record else 0,
        "is_completed": progress_record.is_completed if progress_record else False,
        "completed_at": progress_record.completed_at.isoformat() if progress_record and progress_record.completed_at else None,

        "enrolled_at": registration.enrolled_at.isoformat(),
        "dropped_at":  registration.dropped_at.isoformat() if registration.dropped_at else None,
    }

    if is_admin:
        data["user"] = {
            "id":    str(registration.user.id),
            "email": registration.user.email,
            "name":  registration.user.get_full_name(),
        }
        data["subscription"] = {
            "id":      str(registration.subscription.id),
            "package": registration.subscription.package.name,
        }
        data["created_at"] = registration.created_at.isoformat()
        data["updated_at"] = registration.updated_at.isoformat()

    return data


def serialize_purchase(purchase, is_admin=False) -> dict:
    from .models import CourseProgress

    progress_record = CourseProgress.objects.filter(
        user=purchase.user,
        course=purchase.course,
    ).first()

    data = {
        "id": str(purchase.id),
        "course": {
            "id":         str(purchase.course.id),
            "name":       purchase.course.name,
            "slug":       purchase.course.slug,
            "difficulty": purchase.course.difficulty,
            "duration":   purchase.course.duration,
            "subject": {
                "id":   str(purchase.course.subject.id),
                "name": purchase.course.subject.name,
            }
        },
        "price_paid":             str(purchase.price_paid),
        "status":                 purchase.status,
        "deactivated_by_student": purchase.deactivated_by_student,

        "progress":    progress_record.progress if progress_record else 0,
        "is_completed": progress_record.is_completed if progress_record else False,
        "completed_at": progress_record.completed_at.isoformat() if progress_record and progress_record.completed_at else None,

        "purchased_at": purchase.purchased_at.isoformat(),
    }

    if is_admin:
        data["user"] = {
            "id":    str(purchase.user.id),
            "email": purchase.user.email,
            "name":  purchase.user.get_full_name(),
        }
        data["payment_reference"]    = purchase.payment_reference
        data["deactivated_by_admin"] = purchase.deactivated_by_admin
        data["created_at"]           = purchase.created_at.isoformat()
        data["updated_at"]           = purchase.updated_at.isoformat()

    return data


def serialize_progress(progress) -> dict:
    return {
        "id":           str(progress.id),
        "course_id":    str(progress.course.id),
        "course_name":  progress.course.name,
        "progress":     progress.progress,
        "is_completed": progress.is_completed,
        "completed_at": progress.completed_at.isoformat() if progress.completed_at else None,
        "updated_at":   progress.updated_at.isoformat(),
    }