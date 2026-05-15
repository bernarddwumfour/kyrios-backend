# views.py

import json

from apps.utils.decorators.auth import jwt_required, admin_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from apps.utils import bad_request, ok
from .models import Subject, Course,CourseRegistration,CoursePurchase,CourseProgress,DIFFICULTY_HIERARCHY
from django.core.paginator import Paginator
from .utils import serialize_course, serialize_subject
from django.utils.text import slugify
from django.db import transaction
from django.utils import timezone
from .utils import serialize_registration,serialize_purchase,serialize_progress
from apps.packages.models import Subscription
from .access import get_course_access
from .prerequisites import get_all_prerequisites
from .registration import validate_and_register
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
            f"Deactivate it instead, or delete its courses first."
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
# courses/views.py — create and update only

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

    # ✅ prerequisites and requirements added to allowed fields
    allowed_fields  = {
        "name", "description", "status", "difficulty",
        "subject", "duration", "price",
        "prerequisites", "requirements",
    }
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

    price = data.get("price")
    if price is not None:
        try:
            price = float(price)
            if price <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return bad_request("Price must be a positive number")

    # ✅ Validate requirements — must be a list of strings
    requirements = data.get("requirements", [])
    if not isinstance(requirements, list):
        return bad_request("requirements must be an array of strings")
    if not all(isinstance(r, str) for r in requirements):
        return bad_request("Each requirement must be a string")

    # ✅ Validate prerequisites — list of course IDs
    prerequisite_ids = data.get("prerequisites", [])
    if not isinstance(prerequisite_ids, list):
        return bad_request("prerequisites must be an array of course IDs")

    try:
        subject = Subject.objects.get(id=data["subject"])
    except Subject.DoesNotExist:
        return bad_request("Provided subject does not exist")
    except Exception:
        return bad_request("Invalid subject ID format")

    course, created = Course.objects.get_or_create(
        name=data["name"].strip(),
        defaults={
            "description":  data.get("description", "").strip(),
            "status":       status,
            "difficulty":   difficulty,
            "subject":      subject,
            "duration":     duration,
            "price":        price,
            "requirements": requirements,
        }
    )

    if not created:
        return bad_request("A course with this name already exists")

    # ✅ Set prerequisites after creation (M2M)
    if prerequisite_ids:
        valid_prereqs = Course.objects.filter(
            id__in=prerequisite_ids
        ).exclude(id=course.id)  # can't be its own prerequisite

        if valid_prereqs.count() != len(prerequisite_ids):
            # Some IDs were invalid — still save what we found
            pass

        course.prerequisites.set(valid_prereqs)

    course = Course.objects.select_related("subject").prefetch_related("prerequisites").get(id=course.id)

    return ok(data=serialize_course(course, is_admin=True), message="Course created successfully")


@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["PATCH"])
def update_course(request, id):

    try:
        course = Course.objects.select_related("subject").prefetch_related("prerequisites").get(id=id)
        
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

    allowed_fields = {
        "name", "description", "status", "difficulty",
        "subject", "duration", "price",
        "prerequisites", "requirements",
    }

    extra = set(data.keys()) - allowed_fields
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
        if data["status"] not in Course.Status.values:
            return bad_request(f"Status must be one of: {Course.Status.values}")
        course.status = data["status"]

    if "difficulty" in data:
        if data["difficulty"] not in Course.Difficulty.values:
            return bad_request(f"Difficulty must be one of: {Course.Difficulty.values}")
        course.difficulty = data["difficulty"]

    if "duration" in data:
        duration = data["duration"]
        if duration is not None:
            try:
                duration = int(duration)
                if duration <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                return bad_request("Duration must be a positive integer")
        course.duration = duration

    if "price" in data:
        price = data["price"]
        if price is None:
            course.price = None
        else:
            try:
                price = float(price)
                if price <= 0:
                    raise ValueError
                course.price = price
            except (ValueError, TypeError):
                return bad_request("Price must be a positive number")

    # ✅ Update requirements
    if "requirements" in data:
        requirements = data["requirements"]
        if not isinstance(requirements, list):
            return bad_request("requirements must be an array of strings")
        if not all(isinstance(r, str) for r in requirements):
            return bad_request("Each requirement must be a string")
        course.requirements = requirements

    if "subject" in data:
        try:
            course.subject = Subject.objects.get(id=data["subject"])
        except Subject.DoesNotExist:
            return bad_request("Provided subject does not exist")
        except Exception:
            return bad_request("Invalid subject ID format")

    course.save()

    # ✅ Update prerequisites (M2M — done after save)
    if "prerequisites" in data:
        prerequisite_ids = data["prerequisites"]
        if not isinstance(prerequisite_ids, list):
            return bad_request("prerequisites must be an array of course IDs")

        valid_prereqs = Course.objects.filter(
            id__in=prerequisite_ids
        ).exclude(id=id)  # can't be its own prerequisite

        course.prerequisites.set(valid_prereqs)

    course = Course.objects.select_related("subject").prefetch_related("prerequisites").get(id=course.id)

    return ok(data=serialize_course(course, is_admin=True), message="Course updated successfully")



@csrf_exempt
# @jwt_required
@require_http_methods(["GET"])
def list_courses(request):
    is_admin =False   
    if request.user.is_authenticated:
        is_admin = request.user.is_staff_member or request.user.is_admin
        
    try:
        page_size   = max(1, min(int(request.GET.get("page_size", 10)), 100))
        page_number = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        return bad_request("page and page_size must be valid integers")

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
        
    
    

    is_purchasable = request.GET.get("is_purchasable", "").lower()
    if is_purchasable == "true":
        queryset = queryset.filter(price__isnull=False)
    elif is_purchasable == "false":
        queryset = queryset.filter(price__isnull=True)

    difficulty = request.GET.get("difficulty", "").strip()
    if difficulty:
        if difficulty not in Course.Difficulty.values:
            return bad_request(f"Invalid difficulty. Must be one of: {Course.Difficulty.values}")
        queryset = queryset.filter(difficulty=difficulty)

    paginator = Paginator(queryset, page_size)
    page      = paginator.get_page(page_number)
    
    print("hereeee")
    

    return ok(
        data={
            "results": [
                serialize_course(c, is_admin=is_admin) for c in page.object_list
            ],
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
# @jwt_required
@require_http_methods(["GET"])
def course_detail(request, id):
    print("Here")
    is_admin = request.user.is_staff
    

    try:
        course = Course.objects.select_related("subject").get(id=id)
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
        data=serialize_course(
            course,
            include_modules=False,
            is_admin=is_admin,
            user=request.user,
        ),
        message="Course retrieved successfully"
    )


@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["DELETE"])
def delete_course(request, id):

    try:
        course = Course.objects.prefetch_related("modules", "registrations", "purchases").get(id=id)
    except Course.DoesNotExist:
        return bad_request("Course not found")
    except Exception:
        return bad_request("Invalid course ID format")

    if course.modules.count() > 0:
        return bad_request(
            f"Cannot delete course with {course.modules.count()} module(s). "
            f"Delete its modules first."
        )

    purchase_count = course.purchases.count()
    if purchase_count > 0:
        return bad_request(
            f"Cannot delete course with {purchase_count} purchase(s). "
            f"Deactivate the course instead."
        )

    active_registrations = course.registrations.filter(
        status=CourseRegistration.Status.ACTIVE
    ).count()
    if active_registrations > 0:
        return bad_request(
            f"Cannot delete course with {active_registrations} active registration(s). "
            f"Deactivate the course instead."
        )

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
            
        


@csrf_exempt
@jwt_required
@require_http_methods(["POST"])
def register_for_course(request):

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return bad_request("Invalid request body")

    course_id = data.get("course_id", "").strip()
    if not course_id:
        return bad_request("course_id is required")

    try:
        course = Course.objects.select_related("subject").get(id=course_id)
    except Course.DoesNotExist:
        return bad_request("Course not found")
    except Exception:
        return bad_request("Invalid course ID format")

    already_purchased = CoursePurchase.objects.filter(
        user=request.user,
        course=course,
        status=CoursePurchase.Status.ACTIVE,
    ).exists()

    if already_purchased:
        return bad_request(
            "You have already purchased this course. "
            "You have permanent access — no need to register."
        )

    try:
        subscription = Subscription.objects.select_related("package") \
                                           .prefetch_related("package__subjects") \
                                           .get(
                                               user=request.user,
                                               status__in=["active", "trial", "grace"]
                                           )
    except Subscription.DoesNotExist:
        return bad_request("You need an active subscription to register for courses.")

    registration, error = validate_and_register(
        user=request.user,
        course=course,
        subscription=subscription,
    )

    if error:
        return bad_request(error)

    CourseProgress.objects.get_or_create(
        user=request.user,
        course=course,
        defaults={"progress": 0}
    )

    return ok(
        data=serialize_registration(registration),
        message=f"Successfully registered for '{course.name}'"
    )


@csrf_exempt
@jwt_required
@require_http_methods(["POST"])
def drop_course(request, id):

    try:
        registration = CourseRegistration.objects.select_related("course").get(
            id=id, user=request.user
        )
    except CourseRegistration.DoesNotExist:
        return bad_request("Registration not found")
    except Exception:
        return bad_request("Invalid registration ID format")

    if registration.status != CourseRegistration.Status.ACTIVE:
        return bad_request(f"Cannot drop a course with status '{registration.status}'")

    registration.status    = CourseRegistration.Status.DROPPED
    registration.dropped_at = timezone.now()
    registration.save(update_fields=["status", "dropped_at"])

    return ok(
        data=serialize_registration(registration),
        message=f"Successfully dropped '{registration.course.name}'"
    )


@csrf_exempt
@jwt_required
@require_http_methods(["GET"])
def my_registrations(request):

    try:
        page_size   = max(1, min(int(request.GET.get("page_size", 10)), 100))
        page_number = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        return bad_request("page and page_size must be valid integers")

    status_filter = request.GET.get("status", "all")
    if status_filter not in [*CourseRegistration.Status.values, "all"]:
        return bad_request(f"Invalid status. Must be one of: {CourseRegistration.Status.values}")

    queryset = CourseRegistration.objects.select_related(
        "course", "course__subject",
    ).filter(user=request.user).order_by("-enrolled_at")

    if status_filter != "all":
        queryset = queryset.filter(status=status_filter)

    paginator = Paginator(queryset, page_size)
    page      = paginator.get_page(page_number)

    return ok(
        data={
            "results": [serialize_registration(r) for r in page.object_list],
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
        message="Registrations retrieved successfully"
    )


@csrf_exempt
@jwt_required
@admin_required
@require_http_methods(["GET"])
def admin_list_registrations(request):

    try:
        page_size   = max(1, min(int(request.GET.get("page_size", 10)), 100))
        page_number = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        return bad_request("page and page_size must be valid integers")

    queryset = CourseRegistration.objects.select_related(
        "user", "course", "course__subject", "subscription__package"
    ).order_by("-enrolled_at")

    status_filter = request.GET.get("status", "all")
    if status_filter not in [*CourseRegistration.Status.values, "all"]:
        return bad_request(f"Invalid status. Must be one of: {CourseRegistration.Status.values}")
    if status_filter != "all":
        queryset = queryset.filter(status=status_filter)

    course_id = request.GET.get("course")
    if course_id:
        queryset = queryset.filter(course__id=course_id)

    paginator = Paginator(queryset, page_size)
    page      = paginator.get_page(page_number)

    return ok(
        data={
            "results": [serialize_registration(r, is_admin=True) for r in page.object_list],
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
        message="Registrations listed successfully"
    )
    


@csrf_exempt
@jwt_required
@require_http_methods(["POST"])
def purchase_course(request):
    """
    Two modes via 'confirm' flag:

    confirm=false (default):
        → Validate the purchase
        → Return upsell options if available
        → Don't charge yet

    confirm=true:
        → User has seen upsell and decided to proceed
        → Complete the purchase
    """

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return bad_request("Invalid request body")

    course_id = data.get("course_id", "").strip()
    if not course_id:
        return bad_request("course_id is required")

    try:
        course = Course.objects.select_related("subject").prefetch_related(
                                   "prerequisites",
                                   "prerequisites__subject",
                                   "prerequisites__prerequisites",
                                   "unlocks",
                                   "unlocks__prerequisites",
                                   "unlocks__subject",
                               ).get(id=course_id)
    except Course.DoesNotExist:
        return bad_request("Course not found")
    except Exception:
        return bad_request("Invalid course ID format")

    if not course.is_purchasable:
        return bad_request("This course is not available for purchase")

    already_purchased = CoursePurchase.objects.filter(
        user=request.user,
        course=course,
    ).exists()

    if already_purchased:
        return bad_request("You have already purchased this course")

    # ── Step 1: Check upsell options ──────────────────────
    # If confirm=false (default), return upsell info before charging
    confirm = str(data.get("confirm", "false")).lower() == "true"

    from .upsell import get_upsell_options
    upsell_options = get_upsell_options(course, request.user)

    if not confirm and upsell_options:
        # Return upsell options — let user decide before proceeding
        return ok(
            data={
                "course": {
                    "id":         str(course.id),
                    "name":       course.name,
                    "price":      str(course.price),
                    "difficulty": course.difficulty,
                },
                "upsell_options":  upsell_options,
                "confirm_required": True,
                "message": (
                    f"Before purchasing '{course.name}', you may want to consider "
                    f"one of these options that include it."
                ),
            },
            message=f"'{course.name}' is included in other courses. Review your options below."
        )

    # ── Step 2: Validate payment reference ────────────────
    payment_reference = data.get("payment_reference", "").strip()
    if not payment_reference:
        return bad_request("payment_reference is required")

    # ── Step 3: Complete purchase ─────────────────────────
    with transaction.atomic():

        purchase = CoursePurchase.objects.create(
            user=request.user,
            course=course,
            price_paid=course.price,
            payment_reference=payment_reference,
        )

        freed_slot = False
        existing_registration = CourseRegistration.objects.filter(
            user=request.user,
            course=course,
            status=CourseRegistration.Status.ACTIVE,
        ).first()

        if existing_registration:
            existing_registration.delete()
            freed_slot = True

        CourseProgress.objects.get_or_create(
            user=request.user,
            course=course,
            defaults={"progress": 0}
        )

        all_prerequisites = get_all_prerequisites(course)
        newly_granted     = []
        already_owned     = []

        for prereq in all_prerequisites:

            prereq_purchase, prereq_created = CoursePurchase.objects.get_or_create(
                user=request.user,
                course=prereq,
                defaults={
                    "price_paid":        0,
                    "payment_reference": f"prereq-of-{str(purchase.id)}",
                }
            )

            if prereq_created:
                CourseRegistration.objects.filter(
                    user=request.user,
                    course=prereq,
                    status=CourseRegistration.Status.ACTIVE,
                ).delete()

                CourseProgress.objects.get_or_create(
                    user=request.user,
                    course=prereq,
                    defaults={"progress": 0}
                )

                newly_granted.append({
                    "id":          str(prereq.id),
                    "name":        prereq.name,
                    "slug":        prereq.slug,
                    "difficulty":  prereq.difficulty,
                    "subject":     prereq.subject.name,
                    "purchase_id": str(prereq_purchase.id),
                    "price_paid":  "0.00",
                    "granted_by":  str(purchase.id),
                })
            else:
                already_owned.append({
                    "id":          str(prereq.id),
                    "name":        prereq.name,
                    "slug":        prereq.slug,
                    "difficulty":  prereq.difficulty,
                    "purchase_id": str(prereq_purchase.id),
                })

    # ── Build response message ────────────────────────────
    message_parts = [f"Successfully purchased '{course.name}'."]

    if newly_granted:
        names = ", ".join(f"'{p['name']}'" for p in newly_granted)
        message_parts.append(
            f"Access to {len(newly_granted)} prerequisite(s) granted: {names}."
        )

    if already_owned:
        names = ", ".join(f"'{p['name']}'" for p in already_owned)
        message_parts.append(
            f"You already owned {len(already_owned)} prerequisite(s): {names}."
        )

    if freed_slot:
        message_parts.append("A subscription slot has been freed.")

    return ok(
        data={
            "purchase":     serialize_purchase(purchase),
            "slot_freed":   freed_slot,
            "prerequisites": {
                "newly_granted": newly_granted,
                "already_owned": already_owned,
                "total_count":   len(all_prerequisites),
            },
          
            "other_options": upsell_options if upsell_options else [],
        },
        message=" ".join(message_parts)
    )


@csrf_exempt
@jwt_required
@require_http_methods(["PATCH"])
def deactivate_purchase(request, id):
    """
    Student deactivates a purchased course from their dashboard.
    Course is still owned — just excluded from stats.
    """

    try:
        purchase = CoursePurchase.objects.select_related("course").get(
            id=id,
            user=request.user,
        )
    except CoursePurchase.DoesNotExist:
        return bad_request("Purchase not found")
    except Exception:
        return bad_request("Invalid purchase ID format")

    if purchase.status == CoursePurchase.Status.DEACTIVATED:
        return bad_request("This course is already deactivated")

    purchase.deactivated_by_student = True
    purchase.status                 = CoursePurchase.Status.DEACTIVATED
    purchase.save(update_fields=["deactivated_by_student", "status"])

    return ok(
        data=serialize_purchase(purchase),
        message=f"'{purchase.course.name}' has been removed from your dashboard"
    )


@csrf_exempt
@jwt_required
@require_http_methods(["PATCH"])
def reactivate_purchase(request, id):
    """Student reactivates a previously deactivated purchase."""

    try:
        purchase = CoursePurchase.objects.select_related("course").get(
            id=id,
            user=request.user,
        )
    except CoursePurchase.DoesNotExist:
        return bad_request("Purchase not found")
    except Exception:
        return bad_request("Invalid purchase ID format")

    if purchase.status == CoursePurchase.Status.ACTIVE:
        return bad_request("This course is already active")

    # Admin deactivation takes priority —
    # student cannot reactivate an admin-deactivated purchase
    if purchase.deactivated_by_admin:
        return bad_request("This course has been deactivated by an administrator")

    purchase.deactivated_by_student = False
    purchase.status                 = CoursePurchase.Status.ACTIVE
    purchase.save(update_fields=["deactivated_by_student", "status"])

    return ok(
        data=serialize_purchase(purchase),
        message=f"'{purchase.course.name}' has been restored to your dashboard"
    )


@csrf_exempt
@jwt_required
@require_http_methods(["GET"])
def my_purchases(request):
    """Returns all courses the current user has purchased."""

    try:
        page_size   = max(1, min(int(request.GET.get("page_size", 10)), 100))
        page_number = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        return bad_request("page and page_size must be valid integers")

    # Default to active only — students see active purchases on dashboard
    include_deactivated = request.GET.get("include_deactivated", "false").lower() == "true"

    queryset = CoursePurchase.objects.select_related(
        "course", "course__subject"
    ).filter(user=request.user).order_by("-purchased_at")

    if not include_deactivated:
        queryset = queryset.filter(status=CoursePurchase.Status.ACTIVE)

    paginator = Paginator(queryset, page_size)
    page      = paginator.get_page(page_number)

    return ok(
        data={
            "results": [serialize_purchase(p) for p in page.object_list],
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
        message="Purchased courses retrieved successfully"
    )


@csrf_exempt
@jwt_required
@require_http_methods(["PATCH"])
def update_progress(request, course_id):
    """
    Update student's progress on a course.
    Works for both subscription and purchased access.
    """

    # 1. Verify student has access
    try:
        course = Course.objects.get(id=course_id)
    except Course.DoesNotExist:
        return bad_request("Course not found")

    access = get_course_access(request.user, course)
    if not access["has_access"]:
        return bad_request("You do not have access to this course")

    # 2. Parse and validate progress value
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return bad_request("Invalid request body")

    try:
        progress = int(data.get("progress", -1))
        if not (0 <= progress <= 100):
            raise ValueError
    except (ValueError, TypeError):
        return bad_request("progress must be an integer between 0 and 100")

    # 3. Update or create progress record
    course_progress, _ = CourseProgress.objects.get_or_create(
        user=request.user,
        course=course,
        defaults={"progress": 0}
    )

    # Progress can only go forward — never backward
    if progress <= course_progress.progress:
        return bad_request(
            f"Progress cannot go backward. "
            f"Current progress is {course_progress.progress}%"
        )

    course_progress.progress = progress

    # Mark completed
    if progress == 100 and not course_progress.completed_at:
        course_progress.completed_at = timezone.now()

    course_progress.save(update_fields=["progress", "completed_at"])

    return ok(
        data=serialize_progress(course_progress),
        message="Progress updated successfully"
    )