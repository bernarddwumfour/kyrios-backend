import uuid
from django.db import models
from django.utils.text import slugify
from ..subjects.models import TimeStampedModel
from django.conf import settings


class Package(TimeStampedModel):

    class Status(models.TextChoices):
        ACTIVE   = "active",   "Active"
        INACTIVE = "inactive", "Inactive"

    class BillingCycle(models.TextChoices):
        MONTHLY  = "monthly",  "Monthly"
        YEARLY   = "yearly",   "Yearly"
        LIFETIME = "lifetime", "Lifetime"

    class MaxDifficulty(models.TextChoices):
        BEGINNER     = "beginner",     "Beginner Only"
        INTERMEDIATE = "intermediate", "Up to Intermediate"
        ADVANCED     = "advanced",     "All Levels"

    class VideoQuality(models.TextChoices):
        SD  = "sd",  "Standard Definition (480p)"
        HD  = "hd",  "High Definition (720p)"
        FHD = "fhd", "Full HD (1080p)"

    # ── Identity ──────────────────────────────────────────
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name        = models.CharField(max_length=100, unique=True)
    slug        = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True, default="")
    status      = models.CharField(
                    max_length=10,
                    choices=Status.choices,
                    default=Status.ACTIVE,
                    db_index=True,
                )

    # ── Pricing ───────────────────────────────────────────
    price          = models.DecimalField(max_digits=8, decimal_places=2)
    original_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    currency       = models.CharField(max_length=3, default="USD")
    billing_cycle  = models.CharField(
                        max_length=10,
                        choices=BillingCycle.choices,
                        default=BillingCycle.MONTHLY,
                        db_index=True,
                    )
    trial_days     = models.PositiveIntegerField(default=0)

    # ── Content Access ────────────────────────────────────
    is_unlimited = models.BooleanField(
                    default=False,
                    help_text="Grants unlimited access to ALL courses at ALL levels."
                )

    # ✅ The ceiling difficulty level for this package
    max_difficulty = models.CharField(
                        max_length=12,
                        choices=MaxDifficulty.choices,
                        default=MaxDifficulty.BEGINNER,
                        db_index=True,
                        help_text="The highest difficulty level this package can access."
                    )

    # ✅ Renamed from max_courses — limit only applies AT the ceiling level
    # Courses BELOW the ceiling are always unlimited
    # null = unlimited at ceiling level too (used for Unlimited plan)
    max_courses_at_level = models.PositiveIntegerField(
                            null=True,
                            blank=True,
                            help_text=(
                                "Maximum courses allowed AT the ceiling difficulty level. "
                                "Courses below the ceiling are always unlimited. "
                                "Null means unlimited at ceiling too."
                            )
                        )

    max_students = models.PositiveIntegerField(null=True, blank=True)

    # ── AI Features ───────────────────────────────────────
    ai_credits_per_month   = models.PositiveIntegerField(default=0)
    ai_question_generation = models.BooleanField(default=False)
    ai_explanations        = models.BooleanField(default=False)

    # ── Video & Audio ─────────────────────────────────────
    includes_video_lessons  = models.BooleanField(default=False)
    video_quality           = models.CharField(
                                max_length=5,
                                choices=VideoQuality.choices,
                                default=VideoQuality.SD,
                                blank=True,
                            )
    text_to_audio           = models.BooleanField(default=False)
    audio_to_text           = models.BooleanField(default=False)
    audio_minutes_per_month = models.PositiveIntegerField(default=0)

    # ── Features ──────────────────────────────────────────
    includes_certificate   = models.BooleanField(default=False)
    can_download_materials = models.BooleanField(default=False)

    # ── Marketing ─────────────────────────────────────────
    is_featured   = models.BooleanField(default=False)
    badge_text    = models.CharField(max_length=50, blank=True, default="")
    display_order = models.PositiveIntegerField(default=0)

    # ── Subjects restriction ──────────────────────────────
    subjects = models.ManyToManyField(
                "subjects.Subject",
                blank=True,
                related_name="packages",
            )

    class Meta:
        ordering        = ["display_order", "price"]
        verbose_name    = "package"
        verbose_name_plural = "packages"

    def __str__(self):
        return f"{self.name} ({self.get_billing_cycle_display()})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def has_discount(self) -> bool:
        return self.original_price is not None and self.original_price > self.price

    @property
    def discount_percentage(self) -> int | None:
        if not self.has_discount:
            return None
        return int(((self.original_price - self.price) / self.original_price) * 100)

    @property
    def has_trial(self) -> bool:
        return self.trial_days > 0

    @property
    def has_ai_access(self) -> bool:
        return self.ai_credits_per_month > 0  
    
    
    


class Subscription(TimeStampedModel):

    class Status(models.TextChoices):
        TRIAL     = "trial",     "Trial"
        ACTIVE    = "active",    "Active"
        GRACE     = "grace",     "Grace Period"  
        EXPIRED   = "expired",   "Expired"
        CANCELLED = "cancelled", "Cancelled"
        PAUSED    = "paused",    "Paused"


    class CancellationReason(models.TextChoices):
        TOO_EXPENSIVE  = "too_expensive",  "Too Expensive"
        NOT_USEFUL     = "not_useful",     "Not Useful"
        FOUND_BETTER   = "found_better",   "Found a Better Alternative"
        TECHNICAL      = "technical",      "Technical Issues"
        OTHER          = "other",          "Other"

    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user    = models.ForeignKey(
                settings.AUTH_USER_MODEL,
                on_delete=models.RESTRICT,      # never silently delete a paying user
                related_name="subscriptions"
              )
    package = models.ForeignKey(
                "Package",
                on_delete=models.RESTRICT,      # never delete a package with active subs
                related_name="subscriptions"
              )

    status       = models.CharField(
                    max_length=12,
                    choices=Status.choices,
                    default=Status.TRIAL,
                    db_index=True,
                )
    started_at   = models.DateTimeField(auto_now_add=True)
    expires_at   = models.DateTimeField(
                    null=True, blank=True,
                    help_text="Null means lifetime / never expires."
                )
    trial_ends_at = models.DateTimeField(
                    null=True, blank=True,
                    help_text="When the trial period ends."
                )
    cancelled_at  = models.DateTimeField(null=True, blank=True)
    paused_at     = models.DateTimeField(null=True, blank=True)

    auto_renew = models.BooleanField(
                    default=True,
                    help_text="Whether subscription renews automatically."
                )

    payment_reference = models.CharField(
                            max_length=200,
                            blank=True,
                            default="",
                            help_text="Payment gateway transaction reference."
                        )

    cancellation_reason = models.CharField(
                            max_length=20,
                            choices=CancellationReason.choices,
                            blank=True,
                            default="",
                        )
    cancellation_note   = models.TextField(
                            blank=True,
                            default="",
                            help_text="Optional note from student on cancellation."
                        )

    ai_credits_used           = models.PositiveIntegerField(default=0)
    audio_minutes_used        = models.PositiveIntegerField(default=0)
    usage_cycle_started_at    = models.DateTimeField(auto_now_add=True)
    
    current_period_ends_at = models.DateTimeField(
                                null=True, blank=True,
                                help_text="When the current billing cycle ends."
                            )

    grace_period_ends_at   = models.DateTimeField(
                                null=True, blank=True,
                                help_text="Grace period ends 3 days after billing cycle ends."
                            )

    class Meta:
        ordering     = ["-created_at"]
        verbose_name = "subscription"
        verbose_name_plural = "subscriptions"
        constraints  = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status__in=["trial", "active", "paused"]),
                name="unique_active_subscription_per_user"
            )
        ]

    def __str__(self):
        return f"{self.user} → {self.package.name} ({self.status})"

    @property
    def is_active(self) -> bool:
        """
        Active during trial, active status AND grace period.
        Student keeps full access throughout grace period.
        """
        from django.utils import timezone
        now = timezone.now()

        if self.status in [self.Status.TRIAL, self.Status.ACTIVE]:
            return True

        # Grace period — full access maintained
        if self.status == self.Status.GRACE:
            if self.grace_period_ends_at and now <= self.grace_period_ends_at:
                return True

        return False

    @property
    def is_in_grace_period(self) -> bool:
        from django.utils import timezone
        return (
            self.status == self.Status.GRACE and
            self.grace_period_ends_at is not None and
            timezone.now() <= self.grace_period_ends_at
        )

    @property
    def is_on_trial(self) -> bool:
        return self.status == self.Status.TRIAL

    @property
    def ai_credits_remaining(self) -> int:
        return max(0, self.package.ai_credits_per_month - self.ai_credits_used)

    @property
    def audio_minutes_remaining(self) -> int:
        return max(0, self.package.audio_minutes_per_month - self.audio_minutes_used)

    @property
    def has_video_access(self) -> bool:
        return self.is_active and self.package.includes_video_lessons

    @property
    def has_audio_access(self) -> bool:
        return self.is_active and (
            self.package.text_to_audio or self.package.audio_to_text
        )