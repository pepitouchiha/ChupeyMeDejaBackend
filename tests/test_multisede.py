"""Pruebas de aislamiento por sede, roles y autenticación.

Correr desde backend/:  .venv\\Scripts\\python -m pytest -q
Por defecto usan una base SQLite temporal. Para probar contra PostgreSQL,
definir TEST_DATABASE_URL con una base VACÍA y desechable (se crean tablas).
"""

from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", f"sqlite:///{os.path.join(_tmp, 'test.db')}"
)
os.environ["ENVIRONMENT"] = "development"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import limitador_login  # noqa: E402
from app.main import app  # noqa: E402
from app.scripts.crear_superadmin import ejecutar as ejecutar_crear_superadmin  # noqa: E402

PASSWORD = "Clave12345"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _auth(token: str, sede_id: int | None = None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}"}
    if sede_id is not None:
        h["X-Sede-Id"] = str(sede_id)
    return h


def _login(client, email: str, password: str = PASSWORD) -> str:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def setup(client):
    # La única forma de crear el super admin: el script de línea de comandos.
    assert ejecutar_crear_superadmin(
        "super@chupe.co", PASSWORD, "Super", ["Asunción|Copacabana", "Machado|Copacabana"]
    ) == 0
    sa = _login(client, "super@chupe.co")
    sedes = {s["nombre"]: s["id"] for s in client.get("/sedes", headers=_auth(sa)).json()}
    a, m = sedes["Asunción"], sedes["Machado"]

    def crear(email: str, rol: str, sede: int | None, por: str = sa) -> str:
        r = client.post(
            "/usuarios",
            headers=_auth(por),
            json={"nombre": email, "email": email, "password": PASSWORD, "rol": rol, "sede_id": sede},
        )
        assert r.status_code == 201, r.text
        return _login(client, email)

    dueno = crear("dueno@chupe.co", "dueno", None)
    admin_a = crear("admin.a@chupe.co", "administrador", a)
    admin_m = crear("admin.m@chupe.co", "administrador", m)
    # Los cajeros los crean los administradores de cada sede.
    cajero_a = crear("cajero.a@chupe.co", "cajero", a, por=admin_a)
    return {"sa": sa, "dueno": dueno, "a": a, "m": m, "admin_a": admin_a,
            "cajero_a": cajero_a, "admin_m": admin_m}


def test_no_hay_registro_publico(client, setup):
    r = client.post(
        "/auth/registro",
        json={"nombre": "X", "email": "x@x.co", "password": PASSWORD, "sedes": [{"nombre": "Otra"}]},
    )
    assert r.status_code in (404, 405)


def _crear(client, token, rol, sede, email):
    return client.post("/usuarios", headers=_auth(token), json={
        "nombre": email, "email": email, "password": PASSWORD, "rol": rol, "sede_id": sede})


def test_solo_superadmin_crea_duenos_y_administradores(client, setup):
    for token in (setup["dueno"], setup["admin_a"], setup["cajero_a"]):
        assert _crear(client, token, "administrador", setup["a"], "x1@chupe.co").status_code == 403
        assert _crear(client, token, "dueno", None, "x2@chupe.co").status_code == 403
    # Nadie crea super admins desde la app (ni siquiera el super admin).
    assert _crear(client, setup["sa"], "superadmin", None, "x3@chupe.co").status_code == 422


def test_administrador_solo_crea_cajeros_de_su_sede(client, setup):
    assert _crear(client, setup["admin_a"], "cajero", setup["m"], "x4@chupe.co").status_code == 403
    r = _crear(client, setup["admin_a"], "cajero", None, "cajero2.a@chupe.co")
    assert r.status_code == 201 and r.json()["sede_id"] == setup["a"]
    # El dueño puede crear cajeros en cualquier sede.
    assert _crear(client, setup["dueno"], "cajero", setup["m"], "cajero.m@chupe.co").status_code == 201


def test_administrador_no_ve_ni_toca_otras_sedes(client, setup):
    lista = client.get("/usuarios", headers=_auth(setup["admin_m"])).json()
    assert all(u["sede_id"] == setup["m"] for u in lista)
    cajero_a_id = next(u["id"] for u in client.get("/usuarios", headers=_auth(setup["sa"])).json()
                       if u["email"] == "cajero.a@chupe.co")
    r = client.patch(f"/usuarios/{cajero_a_id}", headers=_auth(setup["admin_m"]), json={"activo": False})
    assert r.status_code == 404
    # Un administrador no puede ascender a un cajero ni editar a otro administrador.
    r = client.patch(f"/usuarios/{cajero_a_id}", headers=_auth(setup["admin_a"]), json={"rol": "administrador"})
    assert r.status_code == 403
    admin_m_id = next(u["id"] for u in lista if u["email"] == "admin.m@chupe.co")
    r = client.post(f"/usuarios/{admin_m_id}/password", headers=_auth(setup["dueno"]), json={"password": "Otra12345"})
    assert r.status_code == 403


def test_cuenta_superadmin_intocable(client, setup):
    sa_id = next(u["id"] for u in client.get("/usuarios", headers=_auth(setup["sa"])).json()
                 if u["rol"] == "superadmin")
    assert all(u["rol"] != "superadmin" for u in client.get("/usuarios", headers=_auth(setup["dueno"])).json())
    r = client.post(f"/usuarios/{sa_id}/password", headers=_auth(setup["dueno"]), json={"password": "Otra12345"})
    assert r.status_code == 404
    r = client.delete(f"/usuarios/{sa_id}", headers=_auth(setup["sa"]))
    assert r.status_code == 403


def test_solo_superadmin_maneja_sedes(client, setup):
    assert client.post("/sedes", headers=_auth(setup["dueno"]), json={"nombre": "Nueva"}).status_code == 403
    assert client.patch(f"/sedes/{setup['a']}", headers=_auth(setup["admin_a"]), json={"activa": False}).status_code == 403
    r = client.post("/sedes", headers=_auth(setup["sa"]), json={"nombre": "Tercera", "direccion": None})
    assert r.status_code == 201


def test_superadmin_opera_cualquier_sede(client, setup):
    assert client.get("/mesas", headers=_auth(setup["sa"])).status_code == 400
    assert client.get("/mesas", headers=_auth(setup["sa"], setup["m"])).status_code == 200


def test_sin_token_401(client, setup):
    assert client.get("/mesas").status_code == 401
    assert client.get("/mesas", headers={"Authorization": "Bearer basura"}).status_code == 401


def test_dueno_debe_elegir_sede(client, setup):
    assert client.get("/mesas", headers=_auth(setup["dueno"])).status_code == 400
    assert client.get("/mesas", headers=_auth(setup["dueno"], 9999)).status_code == 404


def test_datos_aislados_por_sede(client, setup):
    r = client.post("/categorias", headers=_auth(setup["admin_a"]), json={"nombre": "Granizados", "color": "#ff007f"})
    assert r.status_code == 201, r.text
    cat_a = r.json()["id"]
    # Mismo nombre en la otra sede: permitido (cada sede tiene su menú).
    r = client.post("/categorias", headers=_auth(setup["admin_m"]), json={"nombre": "Granizados", "color": "#ff007f"})
    assert r.status_code == 201, r.text

    nombres_m = [c["id"] for c in client.get("/categorias", headers=_auth(setup["admin_m"])).json()]
    assert cat_a not in nombres_m
    # Acceso directo por id a datos de otra sede: no existe para esa sede.
    r = client.patch(f"/categorias/{cat_a}", headers=_auth(setup["admin_m"]), json={"nombre": "Robada"})
    assert r.status_code == 404
    r = client.delete(f"/categorias/{cat_a}", headers=_auth(setup["admin_m"]))
    assert r.status_code == 404
    # El dueño ve cada sede según el encabezado.
    ids_dueno_a = [c["id"] for c in client.get("/categorias", headers=_auth(setup["dueno"], setup["a"])).json()]
    assert cat_a in ids_dueno_a
    # Un producto de M no puede usar una categoría de A.
    r = client.post(
        "/productos",
        headers=_auth(setup["admin_m"]),
        json={"nombre": "Truco", "categoria_id": cat_a, "precio": 1000},
    )
    assert r.status_code == 404


def test_empleado_no_puede_cambiar_de_sede(client, setup):
    r = client.get("/mesas", headers=_auth(setup["cajero_a"], setup["m"]))
    assert r.status_code == 403


def test_permisos_cajero(client, setup):
    h = _auth(setup["cajero_a"])
    assert client.get("/productos", headers=h).status_code == 200
    assert client.post("/categorias", headers=h, json={"nombre": "X"}).status_code == 403
    assert client.post("/mesas", headers=h, json={"nombre_o_numero": "9"}).status_code == 403
    assert client.get("/trabajadores", headers=h).status_code == 403
    assert client.get("/reportes/contabilidad", headers=h).status_code == 403
    assert client.get("/usuarios", headers=h).status_code == 403
    assert client.get("/reportes/hoy", headers=h).status_code == 200


def test_flujo_venta_y_reportes_por_sede(client, setup):
    ha = _auth(setup["admin_a"])
    cajero = _auth(setup["cajero_a"])
    cat = client.post("/categorias", headers=ha, json={"nombre": "Bebidas"}).json()["id"]
    prod = client.post(
        "/productos", headers=ha, json={"nombre": "Granizado 16oz", "categoria_id": cat, "precio": 12000, "costo": 4000}
    ).json()["id"]
    mesa = client.post("/mesas", headers=ha, json={"nombre_o_numero": "1"}).json()["id"]

    # Caja cerrada: no se puede abrir mesa ni vender.
    assert client.post("/ventas/abrir", headers=cajero, json={"mesa_id": mesa}).status_code == 409
    assert client.post("/caja/abrir", headers=cajero, json={"base_inicial": 50000}).status_code == 201

    v = client.post("/ventas/abrir", headers=cajero, json={"mesa_id": mesa}).json()
    r = client.post(f"/ventas/{v['id']}/items", headers=cajero, json={"items": [{"producto_id": prod, "cantidad": 2}]})
    assert r.status_code == 200, r.text
    r = client.post(f"/ventas/{v['id']}/cerrar", headers=cajero, json={"metodo_pago": "efectivo"})
    assert r.status_code == 200, r.text

    # La venta de A no existe para M.
    assert client.get(f"/ventas/{v['id']}", headers=_auth(setup["admin_m"])).status_code == 404

    hoy_a = client.get("/reportes/hoy", headers=ha).json()
    hoy_m = client.get("/reportes/hoy", headers=_auth(setup["admin_m"])).json()
    assert hoy_a["total"] == 24000 and hoy_a["num_ventas"] == 1
    assert hoy_m["total"] == 0 and hoy_m["num_ventas"] == 0
    assert hoy_a["margen"] == 16000

    for ruta in ("/reportes/mensual", "/reportes/diario", "/reportes/contabilidad"):
        r = client.get(ruta, headers=ha)
        assert r.status_code == 200, (ruta, r.text)
    cont = client.get("/reportes/contabilidad", headers=ha).json()
    assert cont["ventas_total"] == 24000
    diario = client.get("/reportes/diario", headers=ha).json()
    assert diario[0]["total"] == 24000

    caja_m = client.get("/caja/actual", headers=_auth(setup["admin_m"])).json()
    assert caja_m["abierta"] is False


def test_configuracion_por_sede(client, setup):
    ca = client.get("/configuracion/negocio", headers=_auth(setup["admin_a"])).json()
    cm = client.get("/configuracion/negocio", headers=_auth(setup["admin_m"])).json()
    assert ca["nombre_negocio"].endswith("Asunción")
    assert cm["nombre_negocio"].endswith("Machado")
    cats_gasto = client.get("/gastos/categorias", headers=_auth(setup["admin_m"])).json()
    assert {c["clave"] for c in cats_gasto} >= {"compra_inventario", "nomina"}


def test_cambiar_password_invalida_token_anterior(client, setup):
    r = client.post("/usuarios", headers=_auth(setup["sa"]), json={
        "nombre": "Temp", "email": "temp@chupe.co", "password": PASSWORD, "rol": "cajero", "sede_id": setup["a"]})
    assert r.status_code == 201
    viejo = client.post("/auth/login", json={"email": "temp@chupe.co", "password": PASSWORD}).json()["access_token"]
    r = client.post("/auth/cambiar-password", headers=_auth(viejo),
                    json={"password_actual": PASSWORD, "password_nueva": "OtraClave99"})
    assert r.status_code == 200
    nuevo = r.json()["access_token"]
    assert client.get("/mesas", headers=_auth(viejo)).status_code == 401
    assert client.get("/mesas", headers=_auth(nuevo)).status_code == 200


def test_usuario_desactivado_pierde_acceso(client, setup):
    r = client.post("/usuarios", headers=_auth(setup["sa"]), json={
        "nombre": "Ex", "email": "ex@chupe.co", "password": PASSWORD, "rol": "cajero", "sede_id": setup["m"]})
    uid = r.json()["id"]
    token = client.post("/auth/login", json={"email": "ex@chupe.co", "password": PASSWORD}).json()["access_token"]
    client.patch(f"/usuarios/{uid}", headers=_auth(setup["sa"]), json={"activo": False})
    assert client.get("/mesas", headers=_auth(token)).status_code == 401
    assert client.post("/auth/login", json={"email": "ex@chupe.co", "password": PASSWORD}).status_code == 403


def test_limite_intentos_login(client, setup):
    limitador_login._fallos.clear()
    for _ in range(5):
        assert client.post("/auth/login", json={"email": "dueno@chupe.co", "password": "mala"}).status_code == 401
    r = client.post("/auth/login", json={"email": "dueno@chupe.co", "password": PASSWORD})
    assert r.status_code == 429
    limitador_login._fallos.clear()


def test_password_debil_rechazada(client, setup):
    r = client.post("/usuarios", headers=_auth(setup["sa"]), json={
        "nombre": "D", "email": "d@chupe.co", "password": "12345678", "rol": "cajero", "sede_id": setup["a"]})
    assert r.status_code == 422


# --- Tipos de insumo administrables por sede


def test_tipos_iniciales_por_sede_y_aislados(client, setup):
    ta = client.get("/insumos/tipos", headers=_auth(setup["admin_a"])).json()
    tm = client.get("/insumos/tipos", headers=_auth(setup["admin_m"])).json()
    assert [t["clave"] for t in ta] == ["vaso", "bebida", "licor", "implemento", "otro"]
    assert {t["id"] for t in ta}.isdisjoint({t["id"] for t in tm})
    # Crear un tipo en A no lo agrega a M.
    r = client.post("/insumos/tipos", headers=_auth(setup["admin_a"]), json={"nombre": "Topping"})
    assert r.status_code == 201 and r.json()["clave"] == "topping"
    assert "topping" not in [t["clave"] for t in client.get("/insumos/tipos", headers=_auth(setup["admin_m"])).json()]
    # Nombre repetido (sin importar mayúsculas) en la misma sede: rechazado.
    assert client.post("/insumos/tipos", headers=_auth(setup["admin_a"]), json={"nombre": "topping"}).status_code == 409


def test_insumo_usa_tipos_de_su_sede(client, setup):
    ha, hm = _auth(setup["admin_a"]), _auth(setup["admin_m"])
    base = {"nombre": "Chispas", "unidad": "paquete", "stock": 3, "stock_minimo": 1}
    r = client.post("/insumos", headers=ha, json={**base, "tipo": "topping"})
    assert r.status_code == 201, r.text
    assert r.json()["tipo_nombre"] == "Topping"
    # M no tiene el tipo "topping".
    assert client.post("/insumos", headers=hm, json={**base, "tipo": "topping"}).status_code == 422
    assert client.post("/insumos", headers=ha, json={**base, "tipo": "no_existe"}).status_code == 422

    tipo = next(t for t in client.get("/insumos/tipos", headers=ha).json() if t["clave"] == "topping")
    assert tipo["num_insumos"] == 1
    # Con insumos no se puede borrar; desactivado ya no se puede elegir para insumos nuevos.
    assert client.delete(f"/insumos/tipos/{tipo['id']}", headers=ha).status_code == 409
    assert client.patch(f"/insumos/tipos/{tipo['id']}", headers=ha, json={"activo": False}).status_code == 200
    assert client.post("/insumos", headers=ha, json={**base, "nombre": "Otro", "tipo": "topping"}).status_code == 422
    # Renombrar el tipo se refleja en los insumos (la clave no cambia).
    client.patch(f"/insumos/tipos/{tipo['id']}", headers=ha, json={"nombre": "Toppings", "activo": True})
    chispas = next(i for i in client.get("/insumos", headers=ha).json() if i["nombre"] == "Chispas")
    assert chispas["tipo"] == "topping" and chispas["tipo_nombre"] == "Toppings"


def test_cajero_ve_tipos_pero_no_los_edita(client, setup):
    h = _auth(setup["cajero_a"])
    assert client.get("/insumos/tipos", headers=h).status_code == 200
    assert client.post("/insumos/tipos", headers=h, json={"nombre": "X"}).status_code == 403


def test_completar_datos_base_asigna_cada_sede():
    from app.db.session import SessionLocal
    from app.db.tenancy import fijar_sede, sin_filtro_de_sede
    from app.models.insumo import TipoInsumo
    from app.models.sede import Sede
    from app.services.sedes import completar_datos_base

    with SessionLocal() as db:
        nuevas = [Sede(nombre="Vieja 1"), Sede(nombre="Vieja 2")]
        db.add_all(nuevas)
        db.commit()
        completar_datos_base(db)
        for sede in nuevas:
            fijar_sede(db, sede.id)
            assert db.query(TipoInsumo).count() == 5
        with sin_filtro_de_sede(db):
            ids = [s.id for s in nuevas]
            assert db.query(TipoInsumo).filter(TipoInsumo.sede_id.in_(ids)).count() == 10


# --- Correcciones de la revisión de código


def test_no_se_borra_producto_con_ventas(client, setup):
    h = _auth(setup["admin_m"])
    cat = client.post("/categorias", headers=h, json={"nombre": "Revisión"}).json()["id"]
    prod = client.post("/productos", headers=h, json={"nombre": "Vendido", "categoria_id": cat, "precio": 1000}).json()["id"]
    if not client.get("/caja/actual", headers=h).json()["abierta"]:
        assert client.post("/caja/abrir", headers=h, json={"base_inicial": 0}).status_code == 201
    r = client.post("/ventas", headers=h, json={"items": [{"producto_id": prod, "cantidad": 1}], "metodo_pago": "efectivo"})
    assert r.status_code == 201, r.text
    assert client.delete(f"/productos/{prod}", headers=h).status_code == 409
    assert client.get("/ventas", headers=h).status_code == 200


def test_receta_descuenta_stock_en_cada_venta(client, setup):
    h = _auth(setup["admin_m"])
    vaso = client.post("/insumos", headers=h, json={"nombre": "Vaso prueba", "tipo": "vaso", "stock": 10}).json()
    cat = client.post("/categorias", headers=h, json={"nombre": "Con receta"}).json()["id"]
    prod = client.post("/productos", headers=h, json={"nombre": "Granizado prueba", "categoria_id": cat, "precio": 5000}).json()["id"]
    client.put(f"/productos/{prod}/insumos", headers=h, json=[{"insumo_id": vaso["id"], "cantidad": 1}])
    for _ in range(2):
        r = client.post("/ventas", headers=h, json={"items": [{"producto_id": prod, "cantidad": 2}], "metodo_pago": "efectivo"})
        assert r.status_code == 201, r.text
    assert client.get(f"/insumos/{vaso['id']}", headers=h).json()["stock"] == 6
    movs = client.get(f"/insumos/{vaso['id']}/movimientos", headers=h).json()
    assert sorted(m["stock_resultante"] for m in movs) == [6, 8, 10]


def test_una_sola_caja_abierta_por_sede_en_la_base():
    import pytest as _pytest
    from sqlalchemy.exc import IntegrityError
    from app.db.session import SessionLocal
    from app.db.tenancy import fijar_sede
    from app.models.caja import CajaSesion
    from app.models.sede import Sede

    with SessionLocal() as db:
        sede = Sede(nombre="Caja doble")
        db.add(sede)
        db.commit()
        fijar_sede(db, sede.id)
        db.add(CajaSesion(base_inicial=0))
        db.commit()
        db.add(CajaSesion(base_inicial=0))
        with _pytest.raises(IntegrityError):
            db.commit()


def test_ip_falsificada_no_salta_el_limite(client, setup):
    limitador_login._fallos.clear()
    for n in range(5):
        r = client.post("/auth/login", headers={"X-Forwarded-For": f"9.9.9.{n}, 5.5.5.5"},
                        json={"email": "admin.a@chupe.co", "password": "mala"})
        assert r.status_code == 401
    r = client.post("/auth/login", headers={"X-Forwarded-For": "1.1.1.1, 5.5.5.5"},
                    json={"email": "admin.a@chupe.co", "password": PASSWORD})
    assert r.status_code == 429
    limitador_login._fallos.clear()


def test_sede_desactivada_solo_la_ve_el_superadmin(client, setup):
    sede = client.post("/sedes", headers=_auth(setup["sa"]), json={"nombre": "Cerrada", "direccion": None}).json()
    client.patch(f"/sedes/{sede['id']}", headers=_auth(setup["sa"]), json={"activa": False})
    assert client.get("/mesas", headers=_auth(setup["dueno"], sede["id"])).status_code == 403
    assert client.get("/mesas", headers=_auth(setup["sa"], sede["id"])).status_code == 200
    sedes_dueno = client.post("/auth/login", json={"email": "dueno@chupe.co", "password": PASSWORD}).json()["sedes"]
    assert sede["id"] not in [s["id"] for s in sedes_dueno]


def test_contabilidad_rango_limitado(client, setup):
    r = client.get("/reportes/contabilidad?desde=2000-01-01&hasta=2026-01-01", headers=_auth(setup["admin_a"]))
    assert r.status_code == 422


def test_entrada_sin_costo_no_borra_costo_unitario(client, setup):
    h = _auth(setup["admin_a"])
    ins = client.post("/insumos", headers=h, json={"nombre": "Vodka", "tipo": "licor", "costo_unitario": 50000}).json()
    r = client.post(f"/insumos/{ins['id']}/entradas", headers=h,
                    json={"cantidad": 2, "costo_total": 0, "registrar_gasto": False})
    assert r.status_code == 200, r.text
    assert r.json()["costo_unitario"] == 50000


def test_nombre_solo_espacios_rechazado(client, setup):
    r = client.patch(f"/sedes/{setup['a']}", headers=_auth(setup["sa"]), json={"nombre": "   "})
    assert r.status_code == 422


def test_esquema_anterior_detiene_el_arranque(tmp_path):
    import pytest as _pytest
    from sqlalchemy import create_engine, text
    from app.db.esquema import EsquemaDesactualizadoError, verificar_esquema

    motor = create_engine(f"sqlite:///{tmp_path / 'vieja.db'}")
    with motor.begin() as conn:
        conn.execute(text("CREATE TABLE categorias (id INTEGER PRIMARY KEY, nombre VARCHAR(100))"))
    with _pytest.raises(EsquemaDesactualizadoError):
        verificar_esquema(motor)
