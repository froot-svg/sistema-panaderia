import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from personal.servicios import registrar_faltas_pendientes
from ventas.servicios import reintentar_pendientes


class Command(BaseCommand):
    help = 'Corre cada minuto las faltas automáticas y los reintentos de comprobantes'

    def handle(self, *args, **opciones):
        self.stdout.write('Tareas programadas iniciadas')
        while True:
            try:
                faltas = registrar_faltas_pendientes()
                enviados, pendientes = reintentar_pendientes()
                self.stdout.write(f'Faltas nuevas: {len(faltas)} · Comprobantes enviados: {enviados} · pendientes: {pendientes}')
            except Exception as error:  # una falla no debe detener el proceso
                self.stderr.write(f'Error en tareas programadas: {error}')
            close_old_connections()
            time.sleep(60)