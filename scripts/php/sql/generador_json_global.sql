SELECT 
    dg.nombre AS nombre_grupo,
    cl.empresa, 
    DATE_FORMAT(c.fecha, '%Y-%m') AS mes_anio,
    COUNT(c.id_caso) AS total_casos,
    COALESCE(u.nombre, 'No asignado') AS nombre_usuario,
    CASE 
        WHEN c.urgencia_abierto IS NOT NULL THEN 'URGENCIA'
        ELSE 'NORMAL'
    END AS tipo_urgencia
FROM casos c
JOIN grupos_dashboard gd ON c.cliente_id = gd.id_cliente
JOIN dashboard_grupos dg ON gd.grupo_dashboard_id = dg.id
JOIN clientes cl ON gd.id_cliente = cl.id_cliente
LEFT JOIN usuarios u ON c.asignado_a = u.id  -- Relación con usuarios
WHERE dg.id = 1  -- Anicura
AND c.fecha >= '2021-01-01'
GROUP BY cl.empresa, dg.nombre, mes_anio, u.nombre, tipo_urgencia
ORDER BY cl.empresa, mes_anio DESC;
