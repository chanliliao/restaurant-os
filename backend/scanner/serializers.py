from rest_framework import serializers

VALID_MODES = ("light", "normal", "heavy")

class ScanRequestSerializer(serializers.Serializer):
    image = serializers.ImageField(required=True)
    mode = serializers.ChoiceField(choices=VALID_MODES, default="normal", required=False)
