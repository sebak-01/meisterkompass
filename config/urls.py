"""
config/urls.py
"""

from django.contrib import admin
from django.urls import path

from courses.views import CourseListView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", CourseListView.as_view(), name="course-list"),
]