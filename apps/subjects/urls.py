# urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Subjects
    path("",                       views.list_subjects,      name="list_subjects"),
    path("create/",               views.create_subject,     name="create_subject"),
    path("bulk-action/",                 views.bulk_subject_action, name="bulk_subject_action"),
    path("<str:id>/update/",      views.update_subject,     name="update_subject"),
    path("<str:id>/delete/",      views.delete_subject,     name="delete_subject"),

    # Courses
    path("courses/",                        views.list_courses,       name="list_courses"),
    path("courses/create/",                views.create_course,      name="create_course"),
    path("courses/bulk-action/",                  views.bulk_course_action,  name="bulk_course_action"),
    path("courses/<str:id>/",              views.course_detail,      name="course_detail"),
    path("courses/<str:id>/update/",       views.update_course,      name="update_course"),
    path("courses/<str:id>/delete/",       views.delete_course,      name="delete_course"),
    
     path("<str:id>/",             views.subject_detail,     name="subject_detail"),

]