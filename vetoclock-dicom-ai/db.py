import pymysql
import config
from html.parser import HTMLParser


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []

    def handle_data(self, d):
        self.result.append(d)

    def get_text(self):
        return " ".join(self.result).strip()


def strip_html(html: str) -> str:
    if not html:
        return ""
    s = _HTMLStripper()
    s.feed(html)
    return s.get_text()


def get_connection():
    return pymysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        db=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def get_caso(id_caso: int) -> dict | None:
    sql = """
        SELECT
            c.id_caso, c.especie, c.raza, c.edad, c.peso,
            c.presentacion, c.evolucion, c.antecedentes, c.tratamientos,
            ct.tipotac, ct.enlacedicom,
            ct.torax, ct.abdomen, ct.craneo, ct.cuello,
            ct.toracolumbosacra, ct.cervicotoracica,
            ct.contrastetac
        FROM casos c
        JOIN casostac ct ON ct.id_caso = c.id_caso
        WHERE c.id_caso = %s
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (id_caso,))
            row = cur.fetchone()

    if not row:
        return None

    for campo in ("presentacion", "evolucion", "antecedentes", "tratamientos"):
        row[campo] = strip_html(row[campo] or "")

    return row


def get_informe(id_caso: int) -> str:
    sql = """
        SELECT area_uno FROM informes
        WHERE caso_id = %s AND activado = 1
        ORDER BY updated_at DESC LIMIT 1
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (id_caso,))
            row = cur.fetchone()

    return strip_html(row["area_uno"]) if row else ""


def get_casos_similares(especie: str, tipotac: str, region: str, excluir_id: int, limit: int = 5) -> list[dict]:
    sql = f"""
        SELECT
            c.id_caso, c.especie, c.raza, c.edad, c.peso,
            c.presentacion, c.antecedentes,
            i.area_uno
        FROM casostac ct
        JOIN casos c ON c.id_caso = ct.id_caso
        JOIN informes i ON i.caso_id = ct.id_caso
        WHERE ct.tipotac = %s
        AND ct.{region} = 1
        AND c.especie = %s
        AND ct.enlacedicom LIKE '%%amazonaws%%'
        AND i.activado = 1
        AND LENGTH(i.area_uno) > 200
        AND c.id_caso != %s
        ORDER BY RAND()
        LIMIT %s
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (tipotac, especie, excluir_id, limit))
            rows = cur.fetchall()

    for row in rows:
        for campo in ("presentacion", "antecedentes", "area_uno"):
            row[campo] = strip_html(row[campo] or "")

    return rows
