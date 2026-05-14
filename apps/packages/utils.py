# apps/packages/utils.py

def serialize_package(package, is_admin=False) -> dict:
    data = {
        "id":           str(package.id),
        "name":         package.name,
        "slug":         package.slug,
        "description":  package.description,
        "price":        str(package.price),
        "original_price": str(package.original_price) if package.original_price else None,
        "currency":     package.currency,
        "billing_cycle": package.billing_cycle,
        "trial_days":   package.trial_days,
        "has_trial":    package.has_trial,
        "has_discount": package.has_discount,
        "discount_percentage": package.discount_percentage,
        "is_featured":  package.is_featured,
        "badge_text":   package.badge_text,
        "display_order": package.display_order,

        # ✅ Renamed and explained
        "is_unlimited":          package.is_unlimited,
        "max_difficulty":        package.max_difficulty,
        "max_difficulty_label":  package.get_max_difficulty_display(),
        "max_courses_at_level":  package.max_courses_at_level,

        # ✅ UI-friendly access summary
        # Tells frontend exactly what to display on the pricing card
        "access_summary": _build_access_summary(package),

        "includes_certificate":   package.includes_certificate,
        "can_download_materials": package.can_download_materials,
        "includes_video_lessons": package.includes_video_lessons,
        "video_quality":          package.video_quality if package.includes_video_lessons else None,
        "text_to_audio":          package.text_to_audio,
        "audio_to_text":          package.audio_to_text,
        "audio_minutes_per_month": package.audio_minutes_per_month,
        "ai_credits_per_month":   package.ai_credits_per_month,
        "ai_question_generation": package.ai_question_generation,
        "ai_explanations":        package.ai_explanations,
        "has_ai_access":          package.has_ai_access,
        "max_students":           package.max_students,
    }

    if is_admin:
        data["status"]     = package.status
        data["created_at"] = package.created_at.isoformat()
        data["updated_at"] = package.updated_at.isoformat()

    return data



def _build_access_summary(package) -> list:
    """
    Builds the feature bullet points shown on the pricing card.
    Maps directly to the UI checkmark list in the image.

    e.g. Free    → ["5 Beginner courses included",
                     "Enroll in courses up to beginner"]
         Basic   → ["Unlimited Beginner courses",
                     "20 Intermediate courses included",
                     "Enroll in courses up to intermediate"]
         Pro     → ["Unlimited Beginner courses",
                     "Unlimited Intermediate courses",
                     "50 Advanced courses included",
                     "Certificate of Completion",
                     "Download Materials"]
         Unlimited → ["Enroll in courses up to expert",
                       "Certificate of Completion", ...]
    """
    summary = []

    HIERARCHY = {"beginner": 1, "intermediate": 2, "advanced": 3}
    ceiling   = package.max_difficulty
    ceiling_level = HIERARCHY.get(ceiling, 0)
    

    if package.is_unlimited:
        summary.append("Unlimited access to all courses at all levels")
    else:
        # Levels below ceiling — unlimited
        for level, level_num in HIERARCHY.items():
            if level_num < ceiling_level:
                summary.append(f"Unlimited {level.capitalize()} courses")

        # At ceiling — limited
        if package.max_courses_at_level is not None:
            summary.append(
                f"Enroll in up to {package.max_courses_at_level} "
                f"{ceiling.capitalize()} courses "
            )
        else:
            summary.append(f"Unlimited {ceiling.capitalize()} courses")

        # summary.append(f"Enroll in courses up to {ceiling}")

    if package.includes_certificate:
        summary.append("Certificate of Completion")
    if package.can_download_materials:
        summary.append("Download Materials")
    if package.includes_video_lessons:
        summary.append(f"{package.video_quality.upper()} Video Lessons")
    if package.ai_credits_per_month > 0:
        summary.append(f"{package.ai_credits_per_month} AI Credits/Month")
    if package.ai_explanations or package.ai_question_generation:
        summary.append("AI-Powered Learning")

    return summary




def serialize_subscription(subscription, is_admin=False) -> dict:
    data = {
        "id":                   str(subscription.id),
        "package":              serialize_package(subscription.package),
        "status":               subscription.status,
        "started_at":           subscription.started_at.isoformat(),
        "expires_at":           subscription.expires_at.isoformat() if subscription.expires_at else None,
        "trial_ends_at":        subscription.trial_ends_at.isoformat() if subscription.trial_ends_at else None,
        "auto_renew":           subscription.auto_renew,
        "is_active":            subscription.is_active,
        "is_on_trial":          subscription.is_on_trial,
        "has_video_access":     subscription.has_video_access,
        "has_audio_access":     subscription.has_audio_access,

        # Usage
        "ai_credits_used":      subscription.ai_credits_used,
        "ai_credits_remaining": subscription.ai_credits_remaining,
        "audio_minutes_used":   subscription.audio_minutes_used,
        "audio_minutes_remaining": subscription.audio_minutes_remaining,
        "created_at"             : subscription.created_at.isoformat(),
        "cancelled_at"           : subscription.cancelled_at.isoformat() if subscription.cancelled_at else None
    }

    if is_admin:
        data["user"] = {
            "id":    str(subscription.user.id),
            "email": subscription.user.email,
            "name":  subscription.user.get_full_name(),
        }
        data["payment_reference"]   = subscription.payment_reference
        data["cancellation_reason"] = subscription.cancellation_reason
        data["cancellation_note"]   = subscription.cancellation_note
        
        data["updated_at"]          = subscription.updated_at.isoformat()

    return data