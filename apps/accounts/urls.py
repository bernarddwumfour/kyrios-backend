from django.urls import path
from . import views

urlpatterns = [
    # Public endpoints
    path('register/', views.register, name='register'),
    path('login/', views.login, name='login'),
    path('google/', views.google_login, name='google-login'),
    path('token/refresh/', views.token_refresh, name='token-refresh'),
    
      # Email verification endpoints
    path('email/verify/', views.verify_email, name='verify-email'),
    path('email/resend-verification/', views.resend_verification_email, name='resend-verification'),
    path('email/status/', views.verification_status, name='verification-status'),
    
    # Protected endpoints (require JWT)
    path('logout/', views.logout, name='logout'),
    path('me/', views.me, name='me'),
    path('me/update/', views.update_profile, name='update-profile'),
    
    # NEW: Avatar endpoints
    path('me/avatar/update/', views.update_avatar, name='update-avatar'),  # POST - Update avatar
    path('me/avatar/reset/', views.reset_avatar, name='reset-avatar'),     # DELETE - Reset avatar
    
    path('password/change/', views.change_password, name='change-password'),
    path('password/forgot/', views.forgot_password, name='forgot-password'),
    path('password/reset/', views.reset_password, name='reset-password'),
    path('password/resend/', views.resend_reset_email, name='resend-reset-email'),
    
    # Admin endpoints
    path('admin/users/', views.admin_users, name='admin-users'),
    path('admin/users/<int:user_id>/', views.admin_user_detail, name='admin-user-detail'),
    path('admin/users/<int:user_id>/update/', views.admin_update_user, name='admin-user-update'),
    
    path('admin/users/<int:user_id>/activate/', views.admin_activate_user, name='admin_activate_user'),
    path('admin/users/<int:user_id>/deactivate/', views.admin_deactivate_user, name='admin_deactivate_user'),
    path('admin/users/bulk-status/', views.admin_bulk_activate_deactivate, name='admin_bulk_status'),
    
    # Admin endpoints - Change Role
    path('admin/users/<int:user_id>/change-role/', views.admin_change_user_role, name='admin_change_user_role'),
    path('admin/users/bulk-change-role/', views.admin_bulk_change_role, name='admin_bulk_change_role'),
    
    
     # MFA endpoints
    path('mfa/setup/', views.setup_mfa, name='setup-mfa'),
    path('mfa/verify/', views.verify_mfa_setup, name='verify-mfa'),
    path('mfa/disable/', views.disable_mfa, name='disable-mfa'),
    path('mfa/status/', views.get_mfa_status, name='mfa-status'),
    path('mfa/verify-login/', views.verify_mfa_login, name='verify-mfa-login'),
    path('mfa/send-email-code/', views.send_mfa_email_code, name='send-mfa-email-code'),
]