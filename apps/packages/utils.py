# apps/packages/utils.py

def serialize_package(package, is_admin=False) -> dict:
    data = {
        "id":                    str(package.id),
        "name":                  package.name,
        "slug":                  package.slug,
        "description":           package.description,
        "price":                 str(package.price),
        "original_price":        str(package.original_price) if package.original_price else None,
        "currency":              package.currency,
        "billing_cycle":         package.billing_cycle,
        "trial_days":            package.trial_days,
        "has_trial":             package.has_trial,
        "has_discount":          package.has_discount,
        "discount_percentage":   package.discount_percentage,
        "is_featured":           package.is_featured,
        "badge_text":            package.badge_text,
        "display_order":         package.display_order,
        "max_difficulty":         package.max_difficulty,

        # Content access
        "is_unlimited":          package.is_unlimited,
        "max_courses":           package.max_courses,
        "max_students":          package.max_students,

        # Features
        "includes_certificate":   package.includes_certificate,
        "can_download_materials": package.can_download_materials,

        # Video
        "includes_video_lessons": package.includes_video_lessons,
        "video_quality":          package.video_quality if package.includes_video_lessons else None,

        # Audio
        "text_to_audio":          package.text_to_audio,
        "audio_to_text":          package.audio_to_text,
        "audio_minutes_per_month": package.audio_minutes_per_month,

        # AI
        "ai_credits_per_month":    package.ai_credits_per_month,
        "ai_question_generation":  package.ai_question_generation,
        "ai_explanations":         package.ai_explanations,
        "has_ai_access":           package.has_ai_access,
    }

    if is_admin:
        data["status"]     = package.status
        data["created_at"] = package.created_at.isoformat()
        data["updated_at"] = package.updated_at.isoformat()

    return data


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