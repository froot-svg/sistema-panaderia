from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from cuentas.models import Empresa
from produccion.models import Insumo, Receta
from ventas.models import EnvioProducto, Producto
from .base import Base


class ProductoTests(Base):
    def crear(self, **extra):
        datos = {'nombre': 'Pan de Yema', 'categoria': 'pan', 'unidades_por_sol': 4, 'precio': '1.00', **extra}
        return self.api(self.adm).post('/api/ventas/productos/', datos, format='json')

    def test_crea_el_producto_en_la_empresa_del_usuario(self):
        self.assertEqual(self.crear().status_code, 201)
        self.assertEqual(Producto.objects.get(nombre='Pan de Yema').empresa, self.empresa)

    def test_rechaza_datos_invalidos(self):
        casos = [{'precio': '0'}, {'precio': '-1.00'}, {'unidades_por_sol': 0}, {'unidades_por_sol': -2},
                 {'nombre': 'ab'}, {'nombre': 'pan francés'}]  # nombre corto y nombre repetido
        for extra in casos:
            with self.subTest(extra=extra):
                self.assertEqual(self.crear(**extra).status_code, 400)

    def test_valida_las_fechas_de_la_promocion(self):
        hoy = timezone.localdate()
        dia = lambda n: str(hoy + timedelta(days=n))
        casos = [{'precio_promocional': '0.80', 'promocion_inicio': dia(-1), 'promocion_fin': dia(1)},  # empieza ayer
                 {'precio_promocional': '0.80', 'promocion_inicio': dia(2), 'promocion_fin': dia(1)},   # fin antes del inicio
                 {'precio_promocional': '0.80'}]                                                          # incompleta
        for extra in casos:
            with self.subTest(extra=extra):
                self.assertEqual(self.crear(**extra).status_code, 400)
        r = self.crear(precio_promocional='0.80', promocion_inicio=dia(0), promocion_fin=dia(1))
        self.assertEqual((r.status_code, r.data['en_promocion']), (201, True))

    def test_desactivar_no_borra_ni_revalida_una_promocion_ya_iniciada(self):
        hoy = timezone.localdate()
        p = Producto.objects.create(
            empresa=self.empresa, nombre='Rosca', categoria='pan', unidades_por_sol=1, precio=Decimal('2.00'),
            precio_promocional=Decimal('1.50'), promocion_inicio=hoy - timedelta(days=1),
            promocion_fin=hoy + timedelta(days=1))
        cliente = self.api(self.adm)
        r = cliente.patch(f'/api/ventas/productos/{p.id}/', {'activo': False}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(cliente.delete(f'/api/ventas/productos/{p.id}/').status_code, 405)
        self.assertTrue(Producto.objects.filter(pk=p.id, activo=False).exists())


class InsumoTests(Base):
    def test_insumo_nuevo_empieza_en_cero_y_el_stock_no_se_edita(self):
        url = '/api/produccion/insumos/'
        r = self.api(self.adm).post(url, {'nombre': 'Harina', 'stock_actual_kg': '999'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Insumo.objects.get().stock_actual_kg, 0)
        for nombre in ('ab', 'harina'):  # corto y repetido
            self.assertEqual(self.api(self.adm).post(url, {'nombre': nombre}, format='json').status_code, 400)

    def test_la_compra_suma_stock_y_valida_cantidades(self):
        harina = Insumo.objects.create(empresa=self.empresa, nombre='Harina')

        def comprar(**extra):
            datos = {'insumo': harina.id, 'cantidad_kg': '25.50', 'precio': '60.00', **extra}
            return self.api(self.adm).post('/api/produccion/compras/', datos, format='json')

        self.assertEqual(comprar().status_code, 201)
        self.assertEqual(comprar(cantidad_kg='10.00').status_code, 201)
        for extra in ({'cantidad_kg': '0'}, {'cantidad_kg': '-2'}, {'precio': '0'}, {'precio': '-5'}):
            with self.subTest(extra=extra):
                self.assertEqual(comprar(**extra).status_code, 400)
        harina.refresh_from_db()
        self.assertEqual(harina.stock_actual_kg, Decimal('35.50'))

    def test_no_compra_insumos_de_otra_empresa(self):
        otra = Empresa.objects.create(nombre='Otra panadería', ruc='20999999999')
        ajeno = Insumo.objects.create(empresa=otra, nombre='Harina')
        r = self.api(self.adm).post(
            '/api/produccion/compras/', {'insumo': ajeno.id, 'cantidad_kg': '5.00', 'precio': '10.00'}, format='json')
        self.assertEqual(r.status_code, 400)


class ProduccionTests(Base):
    def producir(self, cantidad=100):
        datos = {'tienda': self.planta.id, 'producto': self.pan.id, 'cantidad_producida': cantidad}
        return self.api(self.panadero).post('/api/produccion/produccion/', datos, format='json')

    def test_la_produccion_descuenta_el_insumo_segun_la_receta(self):
        harina = Insumo.objects.create(empresa=self.empresa, nombre='Harina', stock_actual_kg=Decimal('50'))
        Receta.objects.create(producto=self.pan, insumo=harina, kg_por_unidad=Decimal('0.02'))
        self.assertEqual(self.producir().status_code, 201)
        harina.refresh_from_db()
        self.assertEqual(harina.stock_actual_kg, Decimal('48'))  # 100 x 0.02 = 2 kg
        self.assertEqual(self.producir(0).status_code, 400)
        self.assertEqual(self.producir(-5).status_code, 400)

    def test_la_merma_no_puede_superar_lo_producido(self):
        produccion_id = self.producir().data['id']

        def mermar(cantidad):
            return self.api(self.panadero).post(
                '/api/produccion/mermas/', {'produccion': produccion_id, 'cantidad': cantidad}, format='json')

        self.assertEqual(mermar(101).status_code, 400)
        self.assertEqual(mermar(0).status_code, 400)
        self.assertEqual(mermar(60).status_code, 201)
        self.assertEqual(mermar(41).status_code, 400)  # 60 + 41 > 100
        self.assertEqual(mermar(40).status_code, 201)


class TrasladoPlantaTests(Base):
    def enviar(self, cantidad=50, usuario=None, **extra):
        datos = {'tipo': 'planta_tienda', 'tienda_origen': self.planta.id, 'tienda_destino': self.t1.id,
                 'producto': self.pan.id, 'cantidad': cantidad, **extra}
        return self.api(usuario or self.panadero).post('/api/produccion/traslados/', datos, format='json')

    def test_exige_turno_abierto_y_alimenta_el_envio_de_la_tienda(self):
        self.assertEqual(self.enviar().status_code, 400)  # la tienda aún no abrió turno
        caja = self.turno(self.t1, self.v1)
        self.assertEqual(self.enviar().status_code, 201)
        self.assertEqual(self.enviar(cantidad=30).status_code, 201)
        envios = EnvioProducto.objects.filter(turno=caja, producto=self.pan)
        self.assertEqual((envios.count(), envios.get().cantidad_enviada), (1, 80))

    def test_valida_origen_destino_cantidad_y_rol(self):
        self.turno(self.t1, self.v1)
        casos = [{'cantidad': 0}, {'cantidad': -1}, {'tienda_origen': self.t2.id},
                 {'tienda_destino': self.planta.id}, {'tipo': 'entre_tiendas'}]
        for extra in casos:
            with self.subTest(extra=extra):
                self.assertEqual(self.enviar(**extra).status_code, 400)
        self.assertEqual(self.enviar(usuario=self.v1).status_code, 403)