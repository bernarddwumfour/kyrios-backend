# utils.py

def serialize_subject(subject, include_courses=False, is_admin=False) -> dict:
    data = {
        "id":           str(subject.id),
        "name":         subject.name,
        "slug":         subject.slug,
        "description":  subject.description,
        "status":       subject.status,
        "course_count": subject.courses.count(),
    }

    # Admins get extra metadata — students don't need it
    if is_admin:
        data["created_at"] = subject.created_at.isoformat()
        data["updated_at"] = subject.updated_at.isoformat()

    if include_courses:
        data["courses"] = [
            serialize_course(c, is_admin=is_admin)
            for c in subject.courses.all()
        ]

    return data


def serialize_course(course, include_modules=False, is_admin=False) -> dict:
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
        "difficulty":   course.difficulty,
        "duration":     course.duration,
        "status":       course.status,
        # "module_count": course.modules.count(),
    }

    if is_admin:
        data["created_at"] = course.created_at.isoformat()
        data["updated_at"] = course.updated_at.isoformat()

    if include_modules:
        data["modules"] = [
            {
                "id":          str(m.id),
                "name":        m.name,
                "slug":        m.slug,
                "description": m.description,
                "order":       m.order,
                # Only admins see status and timestamps
                **({"status":     m.status,
                    "created_at": m.created_at.isoformat(),
                    "updated_at": m.updated_at.isoformat(),
                    } if is_admin else {}),
            }
            for m in course.modules.all()
            # Students only see ACTIVE modules — admins see everything
            if is_admin or m.status == "active"
        ]

    return data