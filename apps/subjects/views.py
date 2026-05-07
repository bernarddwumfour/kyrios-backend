# views.py

import json

from apps.utils.decorators.auth import jwt_required, admin_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from apps.utils import bad_request, ok
from .models import Subject, Course
from django.core.paginator import Paginator
from .utils import serialize_course, serialize_subject
from django.utils.text import slugify
from django.db import transaction


# ─────────────────────────────────────────
# SUBJECTS
# ─────────────────────────────────────────

@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["POST"])
def create_subject(request):

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return bad_request("Invalid request body")

    name = data.get("name", "").strip()
    if not name:
        return bad_request("Name is required")

    status = data.get("status", Subject.Status.ACTIVE)
    if not isinstance(status, str):
        return bad_request(f"Status must be one of: {Subject.Status.values}")
    status = status.strip()
    if status not in Subject.Status.values:
        return bad_request(f"Status must be one of: {Subject.Status.values}")

    subject, created = Subject.objects.get_or_create(
        name=name,
        defaults={
            "status":      status,
            "description": data.get("description", "").strip(),
        }
    )

    if not created:
        return bad_request("A subject with this name already exists")

    return ok(data=serialize_subject(subject, is_admin=True), message="Subject created successfully")


@csrf_exempt
@jwt_required
@require_http_methods(["GET"])
def list_subjects(request):
    is_admin = request.user.is_staff_member or request.user.is_admin

    try:
        page_size   = max(1, min(int(request.GET.get("page_size", 10)), 100))
        page_number = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        return bad_request("page and page_size must be valid integers")

    queryset = Subject.objects.prefetch_related("courses").order_by("name")

    if is_admin:
        status_filter = request.GET.get("status", "all")
        if status_filter not in [*Subject.Status.values, "all"]:
            return bad_request(f"Invalid status. Must be one of: {Subject.Status.values}")
        if status_filter != "all":
            queryset = queryset.filter(status=status_filter)
    else:
        queryset = queryset.filter(status=Subject.Status.ACTIVE)

    paginator = Paginator(queryset, page_size)
    page      = paginator.get_page(page_number)

    return ok(
        data={
            "results": [serialize_subject(s, is_admin=is_admin) for s in page.object_list],
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
        message="Subjects listed successfully"
    )


@csrf_exempt
@jwt_required
@require_http_methods(["GET"])
def subject_detail(request, id):
    is_admin = request.user.is_staff_member or request.user.is_admin

    try:
        subject = Subject.objects.prefetch_related(
            "courses",
            "courses__modules",
        ).get(id=id)
    except Subject.DoesNotExist:
        return bad_request("Subject not found")
    except Exception:
        return bad_request("Invalid subject ID format")

    if not is_admin and subject.status != Subject.Status.ACTIVE:
        return bad_request("Subject not found")

    return ok(
        data=serialize_subject(subject, include_courses=True, is_admin=is_admin),
        message="Subject retrieved successfully"
    )


@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["PATCH"])
def update_subject(request, id):

    try:
        subject = Subject.objects.prefetch_related("courses").get(id=id)
    except Subject.DoesNotExist:
        return bad_request("Subject not found")
    except Exception:
        return bad_request("Invalid subject ID format")

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return bad_request("Invalid request body")

    allowed_fields  = {"name", "description", "status"}
    received_fields = set(data.keys())

    extra = received_fields - allowed_fields
    if extra:
        return bad_request(f"Unexpected fields not allowed: {', '.join(extra)}")

    if not data:
        return bad_request("No fields provided to update")

    if "name" in data:
        name = data["name"].strip()
        if not name:
            return bad_request("Name cannot be blank")
        if Subject.objects.exclude(id=id).filter(name=name).exists():
            return bad_request("A subject with this name already exists")
        subject.name = name
        subject.slug = slugify(name)

    if "description" in data:
        subject.description = data["description"].strip()

    if "status" in data:
        status = data["status"]
        if not isinstance(status, str) or status.strip() not in Subject.Status.values:
            return bad_request(f"Status must be one of: {Subject.Status.values}")
        subject.status = status.strip()

    subject.save()

    return ok(data=serialize_subject(subject, is_admin=True), message="Subject updated successfully")


@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["DELETE"])
def delete_subject(request, id):

    # 1. Fetch subject
    try:
        subject = Subject.objects.prefetch_related("courses").get(id=id)
    except Subject.DoesNotExist:
        return bad_request("Subject not found")
    except Exception:
        return bad_request("Invalid subject ID format")

    # 2. Safety check — block deletion if subject has courses
    # Losing a subject should be a deliberate decision, not accidental
    course_count = subject.courses.count()
    if course_count > 0:
        return bad_request(
            f"Cannot delete subject with {course_count} course(s) attached. "
            f"Deactivate it instead, or reassign/delete its courses first."
        )

    # 3. Store name for response before deletion
    subject_name = subject.name
    subject.delete()

    return ok(data={"name": subject_name}, message="Subject deleted successfully")


@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["POST"])
def bulk_subject_action(request):
    """
    Perform a bulk action on multiple subjects.

    Expected body:
    {
        "action": "delete" | "activate" | "deactivate",
        "ids": ["uuid1", "uuid2", ...]
    }
    """

    # 1. Parse body
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return bad_request("Invalid request body")

    # 2. Validate action
    ALLOWED_ACTIONS = {"delete", "activate", "deactivate"}
    action = data.get("action", "").strip()
    if not action:
        return bad_request("action is required")
    if action not in ALLOWED_ACTIONS:
        return bad_request(f"Invalid action. Must be one of: {list(ALLOWED_ACTIONS)}")

    # 3. Validate ids
    ids = data.get("ids", [])
    if not ids:
        return bad_request("ids is required and must not be empty")
    if not isinstance(ids, list):
        return bad_request("ids must be a list")
    if len(ids) > 100:
        return bad_request("Cannot perform bulk action on more than 100 records at once")

    # 4. Fetch matching subjects
    queryset = Subject.objects.filter(id__in=ids)
    found_ids    = set(str(s.id) for s in queryset)
    missing_ids  = [i for i in ids if i not in found_ids]

    # 5. Warn about IDs that don't exist but continue with found ones
    warnings = []
    if missing_ids:
        warnings.append(f"Some IDs were not found and skipped: {missing_ids}")

    if not queryset.exists():
        return bad_request("None of the provided IDs were found")

    # 6. Execute action inside a transaction — all or nothing
    with transaction.atomic():

        if action == "delete":
            # Block deletion of subjects that still have courses
            subjects_with_courses = queryset.prefetch_related("courses").filter(
                courses__isnull=False
            ).distinct()

            if subjects_with_courses.exists():
                blocked = [s.name for s in subjects_with_courses]
                return bad_request(
                    f"Cannot delete subjects that still have courses: {blocked}. "
                    f"Deactivate them instead, or remove their courses first."
                )

            deleted_count, _ = queryset.delete()
            return ok(
                data={
                    "action":        action,
                    "affected":      deleted_count,
                    "warnings":      warnings,
                },
                message=f"{deleted_count} subject(s) deleted successfully"
            )

        elif action == "activate":
            # Only update the status column — nothing else
            updated_count = queryset.update(status=Subject.Status.ACTIVE)
            return ok(
                data={
                    "action":   action,
                    "affected": updated_count,
                    "warnings": warnings,
                },
                message=f"{updated_count} subject(s) activated successfully"
            )

        elif action == "deactivate":
            updated_count = queryset.update(status=Subject.Status.INACTIVE)
            return ok(
                data={
                    "action":   action,
                    "affected": updated_count,
                    "warnings": warnings,
                },
                message=f"{updated_count} subject(s) deactivated successfully"
            )


# ─────────────────────────────────────────
# COURSES
# ─────────────────────────────────────────

@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["POST"])
def create_course(request):

    if request.content_type != "application/json":
        return bad_request("Content-Type must be application/json")

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return bad_request("Invalid JSON body")

    allowed_fields  = {"name", "description", "status", "difficulty", "subject", "duration"}
    required_fields = {"name", "difficulty", "subject"}
    received_fields = set(data.keys())

    extra = received_fields - allowed_fields
    if extra:
        return bad_request(f"Unexpected fields not allowed: {', '.join(extra)}")

    missing = [f for f in required_fields if not str(data.get(f, "")).strip()]
    if missing:
        return bad_request(f"Missing required fields: {', '.join(missing)}")

    difficulty = data["difficulty"]
    if difficulty not in Course.Difficulty.values:
        return bad_request(f"Invalid difficulty. Must be one of: {Course.Difficulty.values}")

    status = data.get("status", Course.Status.ACTIVE)
    if status not in Course.Status.values:
        return bad_request(f"Invalid status. Must be one of: {Course.Status.values}")

    duration = data.get("duration")
    if duration is not None:
        try:
            duration = int(duration)
            if duration <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return bad_request("Duration must be a positive integer (minutes)")

    try:
        subject = Subject.objects.get(id=data["subject"])
    except Subject.DoesNotExist:
        return bad_request("Provided subject does not exist")
    except Exception:
        return bad_request("Invalid subject ID format")

    course, created = Course.objects.get_or_create(
        name=data["name"].strip(),
        defaults={
            "description": data.get("description", "").strip(),
            "status":      status,
            "difficulty":  difficulty,
            "subject":     subject,
            "duration":    duration,
        }
    )

    if not created:
        return bad_request("A course with this name already exists")

    course = Course.objects.select_related("subject").get(id=course.id)

    # course = Course.objects.select_related("subject").prefetch_related("modules").get(id=course.id)

    return ok(data=serialize_course(course, is_admin=True), message="Course created successfully")


@csrf_exempt
@jwt_required
@require_http_methods(["GET"])
def list_courses(request):
    is_admin = request.user.is_staff_member or request.user.is_admin

    try:
        page_size   = max(1, min(int(request.GET.get("page_size", 10)), 100))
        page_number = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        return bad_request("page and page_size must be valid integers")

    # queryset = Course.objects.select_related("subject").prefetch_related("modules").order_by("name")
    queryset = Course.objects.select_related("subject").order_by("name")


    if is_admin:
        status_filter = request.GET.get("status", "all")
        if status_filter not in [*Course.Status.values, "all"]:
            return bad_request(f"Invalid status. Must be one of: {Course.Status.values}")
        if status_filter != "all":
            queryset = queryset.filter(status=status_filter)
    else:
        queryset = queryset.filter(
            status=Course.Status.ACTIVE,
            subject__status=Subject.Status.ACTIVE,
        )

    paginator = Paginator(queryset, page_size)
    page      = paginator.get_page(page_number)

    return ok(
        data={
            "results": [serialize_course(c, is_admin=is_admin) for c in page.object_list],
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
        message="Courses listed successfully"
    )


@csrf_exempt
@jwt_required
@require_http_methods(["GET"])
def course_detail(request, id):
    is_admin = request.user.is_staff_member or request.user.is_admin

    try:
        course = Course.objects.select_related("subject") \
                               .prefetch_related("modules") \
                               .get(id=id)
    except Course.DoesNotExist:
        return bad_request("Course not found")
    except Exception:
        return bad_request("Invalid course ID format")

    if not is_admin:
        if course.status != Course.Status.ACTIVE:
            return bad_request("Course not found")
        if course.subject.status != Subject.Status.ACTIVE:
            return bad_request("Course not found")

    return ok(
        data=serialize_course(course, include_modules=True, is_admin=is_admin),
        message="Course retrieved successfully"
    )


@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["PATCH"])
def update_course(request, id):

    try:
        # course = Course.objects.select_related("subject").prefetch_related("modules").get(id=id)
        course = Course.objects.select_related("subject").get(id=id)

    except Course.DoesNotExist:
        return bad_request("Course not found")
    except Exception:
        return bad_request("Invalid course ID format")

    if request.content_type != "application/json":
        return bad_request("Content-Type must be application/json")

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return bad_request("Invalid request body")

    allowed_fields  = {"name", "description", "status", "difficulty", "subject", "duration"}
    received_fields = set(data.keys())

    extra = received_fields - allowed_fields
    if extra:
        return bad_request(f"Unexpected fields not allowed: {', '.join(extra)}")

    if not data:
        return bad_request("No fields provided to update")

    if "name" in data:
        name = data["name"].strip()
        if not name:
            return bad_request("Name cannot be blank")
        if Course.objects.exclude(id=id).filter(name=name).exists():
            return bad_request("A course with this name already exists")
        course.name = name
        course.slug = slugify(name)

    if "description" in data:
        course.description = data["description"].strip()

    if "status" in data:
        status = data["status"]
        if not isinstance(status, str) or status.strip() not in Course.Status.values:
            return bad_request(f"Status must be one of: {Course.Status.values}")
        course.status = status.strip()

    if "difficulty" in data:
        difficulty = data["difficulty"]
        if difficulty not in Course.Difficulty.values:
            return bad_request(f"Difficulty must be one of: {Course.Difficulty.values}")
        course.difficulty = difficulty

    if "duration" in data:
        duration = data["duration"]
        if duration is not None:
            try:
                duration = int(duration)
                if duration <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                return bad_request("Duration must be a positive integer (minutes)")
        course.duration = duration

    if "subject" in data:
        try:
            new_subject = Subject.objects.get(id=data["subject"])
        except Subject.DoesNotExist:
            return bad_request("Provided subject does not exist")
        except Exception:
            return bad_request("Invalid subject ID format")
        course.subject = new_subject

    course.save()

    # course = Course.objects.select_related("subject").prefetch_related("modules").get(id=course.id)
    course = Course.objects.select_related("subject").get(id=course.id)


    return ok(data=serialize_course(course, is_admin=True), message="Course updated successfully")


@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["DELETE"])
def delete_course(request, id):

    # 1. Fetch course
    try:
        course = Course.objects.get(id=id)
    except Course.DoesNotExist:
        return bad_request("Course not found")
    except Exception:
        return bad_request("Invalid course ID format")

    # 2. Safety check — block deletion if course has modules
    # module_count = course.modules.count()
    # if module_count > 0:
    #     return bad_request(
    #         f"Cannot delete course with {module_count} module(s) attached. "
    #         f"Deactivate it instead, or delete its modules first."
    #     )

    # 3. Store name before deletion
    course_name = course.name
    course.delete()

    return ok(data={"name": course_name}, message="Course deleted successfully")


@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["POST"])
def bulk_course_action(request):
    """
    Perform a bulk action on multiple courses.

    Expected body:
    {
        "action": "delete" | "activate" | "deactivate",
        "ids": ["uuid1", "uuid2", ...]
    }
    """

    # 1. Parse body
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return bad_request("Invalid request body")

    # 2. Validate action
    ALLOWED_ACTIONS = {"delete", "activate", "deactivate"}
    action = data.get("action", "").strip()
    if not action:
        return bad_request("action is required")
    if action not in ALLOWED_ACTIONS:
        return bad_request(f"Invalid action. Must be one of: {list(ALLOWED_ACTIONS)}")

    # 3. Validate ids
    ids = data.get("ids", [])
    if not ids:
        return bad_request("ids is required and must not be empty")
    if not isinstance(ids, list):
        return bad_request("ids must be a list")
    if len(ids) > 100:
        return bad_request("Cannot perform bulk action on more than 100 records at once")

    # 4. Fetch matching courses
    queryset    = Course.objects.filter(id__in=ids)
    found_ids   = set(str(c.id) for c in queryset)
    missing_ids = [i for i in ids if i not in found_ids]

    warnings = []
    if missing_ids:
        warnings.append(f"Some IDs were not found and skipped: {missing_ids}")

    if not queryset.exists():
        return bad_request("None of the provided IDs were found")

    # 5. Execute inside a transaction — all or nothing
    with transaction.atomic():

        if action == "delete":
            # Block deletion of courses that still have modules
            courses_with_modules = queryset.prefetch_related("modules").filter(
                modules__isnull=False
            ).distinct()

            if courses_with_modules.exists():
                blocked = [c.name for c in courses_with_modules]
                return bad_request(
                    f"Cannot delete courses that still have modules: {blocked}. "
                    f"Deactivate them instead, or delete their modules first."
                )

            deleted_count, _ = queryset.delete()
            return ok(
                data={
                    "action":   action,
                    "affected": deleted_count,
                    "warnings": warnings,
                },
                message=f"{deleted_count} course(s) deleted successfully"
            )

        elif action == "activate":
            updated_count = queryset.update(status=Course.Status.ACTIVE)
            return ok(
                data={
                    "action":   action,
                    "affected": updated_count,
                    "warnings": warnings,
                },
                message=f"{updated_count} course(s) activated successfully"
            )

        elif action == "deactivate":
            updated_count = queryset.update(status=Course.Status.INACTIVE)
            return ok(
                data={
                    "action":   action,
                    "affected": updated_count,
                    "warnings": warnings,
                },
                message=f"{updated_count} course(s) deactivated successfully"
            )