import uuid
from django.db import models
from django.utils.text import slugify
from django.conf import settings


# ─────────────────────────────────────────
# ABSTRACT BASE
# ─────────────────────────────────────────

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ─────────────────────────────────────────
# SUBJECT
# ─────────────────────────────────────────

class Subject(TimeStampedModel):

    class Status(models.TextChoices):
        ACTIVE   = "active",   "Active"
        INACTIVE = "inactive", "Inactive"

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name        = models.CharField(max_length=100, unique=True, help_text="e.g. Mathematics, Physics, Web Development")
    slug        = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True, default="")
    status      = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )

    class Meta:
        ordering        = ["name"]
        verbose_name    = "subject"
        verbose_name_plural = "subjects"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


# ─────────────────────────────────────────
# COURSE
# ─────────────────────────────────────────
# courses/models.py

DIFFICULTY_HIERARCHY = {
    "beginner":     1,
    "intermediate": 2,
    "advanced":     3,
}


class Course(TimeStampedModel):

    class Status(models.TextChoices):
        ACTIVE   = "active",   "Active"
        INACTIVE = "inactive", "Inactive"

    class Difficulty(models.TextChoices):
        BEGINNER     = "beginner",     "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED     = "advanced",     "Advanced"

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject     = models.ForeignKey(Subject, on_delete=models.RESTRICT, related_name="courses")
    name        = models.CharField(max_length=100, unique=True)
    slug        = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True, default="")
    difficulty  = models.CharField(
                    max_length=12,
                    choices=Difficulty.choices,
                    default=Difficulty.BEGINNER,
                    db_index=True,
                )
    duration    = models.PositiveIntegerField(null=True, blank=True)
    price       = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    status      = models.CharField(
                    max_length=10,
                    choices=Status.choices,
                    default=Status.ACTIVE,
                    db_index=True,
                )

    prerequisites = models.ManyToManyField(
                        "self",
                        blank=True,
                        symmetrical=False,
                        related_name="unlocks",
                        help_text="Suggested courses to complete before this one."
                    )

    requirements = models.JSONField(
                        default=list,
                        blank=True,
                        help_text="Text list of requirements shown to student before enrolling."
                    )

    class Meta:
        ordering        = ["name"]
        verbose_name    = "course"
        verbose_name_plural = "courses"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def is_purchasable(self) -> bool:
        return self.price is not None and self.status == self.Status.ACTIVE

# courses/models.py



# Difficulty hierarchy used for package validation
DIFFICULTY_HIERARCHY = {
    "beginner":     1,
    "intermediate": 2,
    "advanced":     3,
}


class CourseRegistration(TimeStampedModel):

    class Status(models.TextChoices):
        ACTIVE    = "active",    "Active"
        DROPPED   = "dropped",   "Dropped"
        COMPLETED = "completed", "Completed"

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user         = models.ForeignKey(
                    settings.AUTH_USER_MODEL,
                    on_delete=models.RESTRICT,
                    related_name="registrations"
                )
    course       = models.ForeignKey(
                    Course,
                    on_delete=models.RESTRICT,
                    related_name="registrations"
                )
   
    subscription = models.ForeignKey(
                    "packages.Subscription",
                    on_delete=models.RESTRICT,
                    related_name="registrations",
                    help_text="The subscription that granted access to this course."
                )

    status       = models.CharField(
                    max_length=10,
                    choices=Status.choices,
                    default=Status.ACTIVE,
                    db_index=True,
                )


    # Timestamps for lifecycle events
    enrolled_at  = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    dropped_at   = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering     = ["-enrolled_at"]
        verbose_name = "course registration"
        verbose_name_plural = "course registrations"
        constraints  = [
            # A student can only register once per course
            models.UniqueConstraint(
                fields=["user", "course"],
                name="unique_user_course_registration"
            )
        ]

    def __str__(self):
        return f"{self.user} → {self.course.name} ({self.status})"

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE

    @property
    def is_completed(self) -> bool:
        return self.status == self.Status.COMPLETED
    
    
    
    price       = models.DecimalField(
                    max_digits=8,
                    decimal_places=2,
                    null=True,
                    blank=True,
                    help_text="One-time purchase price. Null means not available for purchase."
                )


class CoursePurchase(TimeStampedModel):
    """
    One-time course purchase.
    Gives permanent access independent of subscription.
    Does NOT count toward subscription course limit.
    If purchased while accessing via subscription,
    the subscription slot is automatically freed.
    """

    class Status(models.TextChoices):
        ACTIVE      = "active",      "Active"
        DEACTIVATED = "deactivated", "Deactivated"

    id                   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user                 = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, related_name="course_purchases")
    course               = models.ForeignKey(Course, on_delete=models.RESTRICT, related_name="purchases")

    # Snapshot price at time of purchase — never changes even if course price changes
    price_paid           = models.DecimalField(max_digits=8, decimal_places=2)
    payment_reference    = models.CharField(max_length=200, blank=True, default="")

    status               = models.CharField(
                            max_length=12,
                            choices=Status.choices,
                            default=Status.ACTIVE,
                            db_index=True,
                        )

    # Student can deactivate for themselves
    # Excluded from completion rate, progress stats, dashboard
    deactivated_by_student = models.BooleanField(default=False)

    # Admin can deactivate independently
    deactivated_by_admin   = models.BooleanField(default=False)

    purchased_at         = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering     = ["-purchased_at"]
        verbose_name = "course purchase"
        verbose_name_plural = "course purchases"
        constraints  = [
            # A student can only purchase a course once
            models.UniqueConstraint(
                fields=["user", "course"],
                name="unique_user_course_purchase"
            )
        ]

    def __str__(self):
        return f"{self.user} purchased {self.course.name}"

    @property
    def is_accessible(self) -> bool:
        """Purchase grants access unless BOTH admin and student deactivate."""
        return self.status == self.Status.ACTIVE


class CourseProgress(TimeStampedModel):
    """
    Unified progress tracking — shared across subscription access
    AND purchased access. Progress always carries over regardless
    of how the student is accessing the course.
    """

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, related_name="progress")
    course       = models.ForeignKey(Course, on_delete=models.RESTRICT, related_name="progress")

    # 0-100 percentage
    progress     = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "course progress"
        verbose_name_plural = "course progress"
        constraints  = [
            # One progress record per user per course — always
            models.UniqueConstraint(
                fields=["user", "course"],
                name="unique_user_course_progress"
            )
        ]

    def __str__(self):
        return f"{self.user} — {self.course.name} ({self.progress}%)"

    @property
    def is_completed(self) -> bool:
        return self.completed_at is not None


# ─────────────────────────────────────────
# MODULE
# ─────────────────────────────────────────

# class Module(TimeStampedModel):

#     class Status(models.TextChoices):
#         DRAFT    = "draft",    "Draft"      # just created / AI generated, not reviewed
#         ACTIVE   = "active",   "Active"     # reviewed and published
#         INACTIVE = "inactive", "Inactive"   # hidden from students

#     id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     course      = models.ForeignKey(Course, on_delete=models.RESTRICT, related_name="modules")
#     name        = models.CharField(max_length=100, help_text="e.g. Introduction to Quadratic Equations")
#     slug        = models.SlugField(max_length=120, blank=True)
#     description = models.TextField(blank=True, default="")
#     order       = models.PositiveIntegerField(default=0, help_text="Position of this module within the course")
#     status      = models.CharField(
#         max_length=10,
#         choices=Status.choices,
#         default=Status.DRAFT,   # ← AI-generated content starts as DRAFT always
#         db_index=True,
#     )

#     class Meta:
#         ordering        = ["order"]
#         verbose_name    = "module"
#         verbose_name_plural = "modules"
#         constraints     = [
#             models.UniqueConstraint(fields=["course", "slug"],  name="unique_module_slug_per_course"),
#             models.UniqueConstraint(fields=["course", "order"], name="unique_module_order_per_course"),
#         ]

#     def __str__(self):
#         return f"{self.course.name} — {self.name}"

#     def save(self, *args, **kwargs):
#         if not self.slug:
#             self.slug = slugify(self.name)
#         super().save(*args, **kwargs)


# ─────────────────────────────────────────
# CONTENT BLOCK
# ─────────────────────────────────────────

# class ContentBlock(TimeStampedModel):

#     class BlockType(models.TextChoices):
#         TEXT       = "text",       "Text / Explanation"
#         MATH       = "math",       "Mathematical Expression"
#         CODE       = "code",       "Code Example"
#         IMAGE      = "image",      "Image"
#         VIDEO      = "video",      "Video"
#         EXAMPLE    = "example",    "Worked Example"
#         EXPERIMENT = "experiment", "Experiment / Lab"
#         CALLOUT    = "callout",    "Callout / Key Note"

#     id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     module     = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="content_blocks")
#     block_type = models.CharField(max_length=20, choices=BlockType.choices, db_index=True)
#     title      = models.CharField(max_length=200, blank=True, default="")
#     order      = models.PositiveIntegerField(default=0)

#     # Text / Explanation / Callout / Example — supports markdown
#     body       = models.TextField(blank=True, default="")

#     # Maths — raw LaTeX e.g. "x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}"
#     latex      = models.TextField(blank=True, default="")

#     # Code
#     code       = models.TextField(blank=True, default="")
#     language   = models.CharField(max_length=50, blank=True, default="",
#                                   help_text="e.g. python, javascript, html, sql")

#     # Media
#     media_url  = models.URLField(blank=True, default="")
#     caption    = models.CharField(max_length=300, blank=True, default="")

#     class Meta:
#         ordering     = ["order"]
#         verbose_name = "content block"
#         verbose_name_plural = "content blocks"
#         constraints  = [
#             models.UniqueConstraint(
#                 fields=["module", "order"],
#                 name="unique_content_block_order_per_module"
#             )
#         ]

#     def __str__(self):
#         return f"{self.module.name} | Block {self.order} ({self.block_type})"


# ─────────────────────────────────────────
# QUESTION
# ─────────────────────────────────────────

# class Question(TimeStampedModel):

#     class QuestionType(models.TextChoices):
#         MCQ        = "mcq",        "Multiple Choice"
#         TRUE_FALSE = "true_false", "True / False"
#         SHORT      = "short",      "Short Answer"
#         CODE       = "code",       "Code Challenge"
#         MATH       = "math",       "Math Problem"
#         FILL_BLANK = "fill_blank", "Fill in the Blank"

#     id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     module        = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="questions")
#     question_type = models.CharField(max_length=20, choices=QuestionType.choices, db_index=True)

#     # Supports markdown
#     text          = models.TextField(help_text="The question text. Supports markdown.")

#     # For math questions
#     latex         = models.TextField(blank=True, default="")

#     # For code challenges
#     starter_code  = models.TextField(blank=True, default="",
#                                      help_text="Starter code shown to the student")
#     language      = models.CharField(max_length=50, blank=True, default="")

#     hint          = models.TextField(blank=True, default="")
#     order         = models.PositiveIntegerField(default=0)
#     marks         = models.PositiveIntegerField(default=1)

#     class Meta:
#         ordering     = ["order"]
#         verbose_name = "question"
#         verbose_name_plural = "questions"

#     def __str__(self):
#         return f"Q{self.order}: {self.text[:80]}"


# ─────────────────────────────────────────
# ANSWER CHOICE  (MCQ / True-False options)
# ─────────────────────────────────────────

# class AnswerChoice(TimeStampedModel):

#     id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     question   = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")
#     text       = models.TextField()
#     latex      = models.TextField(blank=True, default="")  # for math-based answer options
#     is_correct = models.BooleanField(default=False)
#     order      = models.PositiveIntegerField(default=0)

#     class Meta:
#         ordering     = ["order"]
#         verbose_name = "answer choice"
#         verbose_name_plural = "answer choices"

#     def __str__(self):
#         return f"{'✓' if self.is_correct else '✗'} {self.text[:60]}"


# ─────────────────────────────────────────
# SOLUTION
# ─────────────────────────────────────────

# class Solution(TimeStampedModel):

#     id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     question        = models.OneToOneField(Question, on_delete=models.CASCADE, related_name="solution")

#     # Plain text answer
#     text            = models.TextField()

#     # Math solutions
#     latex           = models.TextField(blank=True, default="")

#     # Step-by-step workings — JSONField is justified here:
#     # always loaded with parent, no relationships needed, bounded size
#     # e.g. [{"step": 1, "explanation": "Expand brackets", "latex": "x^2 + 2x"}]
#     steps           = models.JSONField(default=list, blank=True)

#     # Code solutions
#     code            = models.TextField(blank=True, default="")
#     expected_output = models.TextField(blank=True, default="")

#     explanation     = models.TextField(blank=True, default="",
#                                        help_text="Why this answer is correct.")

#     class Meta:
#         verbose_name = "solution"
#         verbose_name_plural = "solutions"

#     def __str__(self):
#         return f"Solution: {self.question}"