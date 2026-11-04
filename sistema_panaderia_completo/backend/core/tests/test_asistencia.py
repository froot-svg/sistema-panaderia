from datetime import time, timedelta
from decimal import Decimal
from django.utils import timezone
from personal.models import AvisoFalta, MarcadoAsistencia
from personal.servicios import registrar_faltas_pendientes
from .base import Base


class AsistenciaTests(Base):
    def marcar(self, horario, hora=10, minuto=0):
        self.v1.horario_entrada = horario
        self.v1.save()
        with self.a_las(hora, minuto):  # la hora "actual" queda fija a las 10:00
            return self.api(self.v1).post('/api/personal/mi-asistencia/')

    def test_llegada_a_tiempo_y_con_tardanza(self):
        r = self.marcar(time(10, 10))
        self.assertEqual((r.status_code, r.data['registro']['estado']), (201, 'a_tiempo'))
        MarcadoAsistencia.objects.all().delete()
        r = self.marcar(time(9, 20))
        self.assertEqual((r.data['registro']['estado'], r.data['registro']['minutos_tardanza']), ('tardanza', 40))

    def test_a_las_3_horas_exactas_ya_es_falta_y_a_las_2h59_todavia_no(self):
        r = self.marcar(time(7, 0))
        self.assertEqual((r.status_code, r.data.get('falta')), (400, True))
        self.assertEqual(MarcadoAsistencia.objects.get().estado, 'falta_sin_aviso')
        MarcadoAsistencia.objects.all().delete()
        r = self.marcar(time(7, 1))
        self.assertEqual((r.status_code, r.data['registro']['minutos_tardanza']), (201, 179))

    def test_falta_con_aviso_previo_queda_avisada(self):
        AvisoFalta.objects.create(trabajador=self.v1, fecha_falta=timezone.localdate(),
                                  motivo='Cita médica', registrado_por=self.adm)
        self.marcar(time(6, 0))
        self.assertEqual(MarcadoAsistencia.objects.get().estado, 'falta_avisada')

    def test_no_marca_dos_veces_ni_sin_horario(self):
        self.assertEqual(self.marcar(time(10, 10)).status_code, 201)
        self.assertEqual(self.marcar(time(10, 10)).status_code, 400)
        MarcadoAsistencia.objects.all().delete()
        self.assertEqual(self.marcar(None).status_code, 400)

    def test_las_faltas_vencidas_se_registran_una_sola_vez(self):
        self.v1.horario_entrada = time(6, 0)
        self.v1.save()
        self.v2.horario_entrada = time(8, 0)  # solo 2 horas de retraso: sigue en tolerancia
        self.v2.save()
        with self.a_las(10):
            self.assertEqual(len(registrar_faltas_pendientes()), 1)
            self.assertEqual(len(registrar_faltas_pendientes()), 0)
        self.assertEqual(MarcadoAsistencia.objects.get().trabajador, self.v1)


class AvisoTests(Base):
    def avisar(self, **extra):
        datos = {'trabajador': self.v1.id, 'fecha_falta': str(timezone.localdate()), 'motivo': 'Cita médica', **extra}
        return self.api(self.adm).post('/api/personal/avisos/', datos, format='json')

    def test_valida_fecha_motivo_y_duplicados(self):
        ayer = str(timezone.localdate() - timedelta(days=1))
        self.assertEqual(self.avisar(fecha_falta=ayer).status_code, 400)
        self.assertEqual(self.avisar(motivo='no').status_code, 400)
        self.assertEqual(self.avisar().status_code, 201)
        self.assertEqual(self.avisar().status_code, 400)

    def test_el_aviso_convierte_la_falta_sin_aviso_en_avisada(self):
        MarcadoAsistencia.objects.create(trabajador=self.v1, estado='falta_sin_aviso')
        self.assertEqual(self.avisar().status_code, 201)
        self.assertEqual(MarcadoAsistencia.objects.get().estado, 'falta_avisada')

    def test_no_avisa_si_el_trabajador_ya_marco_llegada(self):
        MarcadoAsistencia.objects.create(trabajador=self.v1, hora_marcado=timezone.now(), estado='a_tiempo')
        self.assertEqual(self.avisar().status_code, 400)


class PagoTests(Base):
    def setUp(self):
        self.v1.pago_diario = Decimal('40.00')
        self.v1.save()

    def asistir(self, estado):
        MarcadoAsistencia.objects.create(trabajador=self.v1, hora_marcado=timezone.now(), estado=estado)

    def pagar(self):
        return self.api(self.adm).post(f'/api/personal/pagos-hoy/{self.v1.id}/pagar/')

    def test_no_se_paga_a_quien_falto_ni_dos_veces(self):
        self.assertEqual(self.pagar().status_code, 400)  # sin asistencia registrada
        self.asistir('falta_sin_aviso')
        self.assertEqual(self.pagar().status_code, 400)
        MarcadoAsistencia.objects.all().delete()
        self.asistir('tardanza')  # la tardanza sí se paga
        self.assertEqual(self.pagar().status_code, 201)
        self.assertEqual(self.pagar().status_code, 400)  # ya se pagó hoy

    def test_exige_un_pago_diario_configurado(self):
        self.asistir('a_tiempo')
        self.v1.pago_diario = None
        self.v1.save()
        self.assertEqual(self.pagar().status_code, 400)

    def test_la_configuracion_rechaza_pago_cero_o_negativo(self):
        url = f'/api/cuentas/trabajadores/{self.v1.id}/'
        for pago in ('0', '-5'):
            r = self.api(self.adm).patch(url, {'horario_entrada': '08:00', 'pago_diario': pago}, format='json')
            self.assertEqual(r.status_code, 400)
        r = self.api(self.adm).patch(url, {'horario_entrada': '08:00', 'pago_diario': '45.50'}, format='json')
        self.assertEqual(r.status_code, 200)