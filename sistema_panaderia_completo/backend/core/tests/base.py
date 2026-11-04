from datetime import datetime, time
from unittest.mock import patch
from django.utils import timezone

def a_las(self, hora, minuto=0):
        """Congela la hora de hoy para probar tardanzas y faltas sin esperar."""
        fijo = timezone.make_aware(datetime.combine(timezone.localdate(), time(hora, minuto)))
        return patch('django.utils.timezone.now', return_value=fijo)