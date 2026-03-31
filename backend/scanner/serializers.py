from rest_framework import serializers

VALID_MODES = ("light", "normal", "heavy", "glm")

class ScanRequestSerializer(serializers.Serializer):
    image = serializers.ImageField(required=True)
    mode = serializers.ChoiceField(choices=VALID_MODES, default="normal", required=False)


class FieldCorrectionSerializer(serializers.Serializer):
    field = serializers.CharField(max_length=200)
    original_value = serializers.JSONField(allow_null=True)
    corrected_value = serializers.JSONField(allow_null=True)


class ConfirmRequestSerializer(serializers.Serializer):
    scan_result = serializers.DictField(required=True)
    corrections = FieldCorrectionSerializer(many=True, required=True)
    confirmed_at = serializers.DateTimeField(required=True)
