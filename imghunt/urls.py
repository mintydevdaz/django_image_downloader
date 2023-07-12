from django.urls import path

from . import views

app_name = "imghunt"
urlpatterns = [
    path("", views.index, name="index"),
    path("success", views.success, name="success"),
    path("download_zip", views.download_zip, name="download_zip"),
]
