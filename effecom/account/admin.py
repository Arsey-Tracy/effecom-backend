from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class EffecomUserAdmin(UserAdmin):
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Contact", {"fields": ("email",)}),
    )
    list_display = ("username", "email", "first_name", "last_name", "is_staff")
