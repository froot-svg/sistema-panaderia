from django.core.management.base import BaseCommand, CommandError
from cuentas.models import Empresa, Tienda, Usuario


class Command(BaseCommand):
    help = 'Crea la empresa, la planta, dos tiendas y la primera Administradora'

    def add_arguments(self, parser):
        parser.add_argument('--ruc', required=True)
        parser.add_argument('--usuario', required=True)
        parser.add_argument('--clave', required=True)

    def handle(self, *args, ruc, usuario, clave, **opciones):
        if Empresa.objects.exists():
            raise CommandError('Ya existe una empresa registrada.')
        if len(ruc) != 11 or not ruc.isdigit():
            raise CommandError('El RUC debe tener 11 dígitos.')
        if len(clave) < 8:
            raise CommandError('La contraseña debe tener al menos 8 caracteres.')
        empresa = Empresa.objects.create(nombre='Panificadora Oh Que Bueno E.I.R.L.', ruc=ruc)
        for nombre in ('Planta', 'Tienda 1', 'Tienda 2'):
            Tienda.objects.create(empresa=empresa, nombre=nombre, es_planta=(nombre == 'Planta'))
        Usuario.objects.create_superuser(usuario, '', clave, empresa=empresa, rol='administradora')
        self.stdout.write('Listo: empresa, 3 unidades y administradora creadas.')