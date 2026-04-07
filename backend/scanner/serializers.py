from rest_framework import serializers


class ScanRequestSerializer(serializers.Serializer):
    image = serializers.ImageField(required=True)


class FieldCorrectionSerializer(serializers.Serializer):
    field = serializers.CharField(max_length=200)
    original_value = serializers.JSONField(allow_null=True)
    corrected_value = serializers.JSONField(allow_null=True)


class ConfirmRequestSerializer(serializers.Serializer):
    scan_result = serializers.DictField(required=True)
    corrections = FieldCorrectionSerializer(many=True, required=True)
    confirmed_at = serializers.DateTimeField(required=True)
