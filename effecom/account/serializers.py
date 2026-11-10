from django.contrib.auth import authenticate, get_user_model, password_validation
from rest_framework import serializers

from .models import Activity


User = get_user_model()


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "first_name")
        read_only_fields = ("id", "email")


class RegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=150)
    first_name = serializers.CharField(max_length=150, trim_whitespace=True)
    password = serializers.CharField(
        write_only=True, trim_whitespace=False, min_length=8
    )

    def validate_email(self, value):
        email = value.strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                "An account with this email already exists."
            )
        return email

    def validate_password(self, value):
        password_validation.validate_password(value)
        return value

    def create(self, validated_data):
        email = validated_data["email"]
        return User.objects.create_user(
            username=email,
            email=email,
            first_name=validated_data["first_name"],
            password=validated_data["password"],
        )


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True, trim_whitespace=False
    )

    def validate(self, attrs):
        email = attrs["email"].strip().lower()
        user = authenticate(
            request=self.context.get("request"),
            username=email,
            password=attrs["password"],
        )
        if user is None:
            raise serializers.ValidationError(
                {"detail": "Email or password is incorrect."}
            )
        if not user.is_active:
            raise serializers.ValidationError(
                {"detail": "This account is inactive."}
            )
        attrs["user"] = user
        return attrs


class ActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Activity
        fields = (
            "id",
            "tool",
            "text",
            "language",
            "voice",
            "source_language",
            "target_language",
            "result",
            "created_at",
        )
        read_only_fields = fields
