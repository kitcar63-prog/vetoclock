UPDATE facturas f
JOIN clientes c ON f.id_cliente = c.id_cliente
SET f.nombre = CONCAT(f.nombre, ' ', c.nombre_facturacion)
WHERE f.nombre = 'ANICURA SPAIN HOLDING, S.L.U.'
AND (
(MONTH(CURDATE()) = 1 AND MONTH(f.fechaFactura) = 12 AND YEAR(f.fechaFactura) = YEAR(CURDATE()) - 1) OR
(MONTH(f.fechaFactura) = MONTH(CURDATE()) - 1 AND YEAR(f.fechaFactura) = YEAR(CURDATE()))
);

UPDATE facturas f
JOIN clientes c ON f.id_cliente = c.id_cliente
SET f.nombre = CONCAT(f.nombre, ' ', c.nombre_facturacion)
WHERE f.nombre = 'IVC EVIDENSIA ASSETS SLU'
AND (
(MONTH(CURDATE()) = 1 AND MONTH(f.fechaFactura) = 12 AND YEAR(f.fechaFactura) = YEAR(CURDATE()) - 1) OR
(MONTH(f.fechaFactura) = MONTH(CURDATE()) - 1 AND YEAR(f.fechaFactura) = YEAR(CURDATE()))
);

UPDATE facturas f
JOIN clientes c ON f.id_cliente = c.id_cliente
SET f.nombre = CONCAT(f.nombre, ' ', c.nombre_facturacion)
WHERE f.nombre = 'UNAVETS HEALTHCARE, S.L.'
AND (
(MONTH(CURDATE()) = 1 AND MONTH(f.fechaFactura) = 12 AND YEAR(f.fechaFactura) = YEAR(CURDATE()) - 1) OR
(MONTH(f.fechaFactura) = MONTH(CURDATE()) - 1 AND YEAR(f.fechaFactura) = YEAR(CURDATE()))
);

UPDATE facturas f
JOIN clientes c ON f.id_cliente = c.id_cliente
SET f.nombre = CONCAT(f.nombre, ' ', c.nombre_facturacion)
WHERE f.nombre = 'ACTIVOS MEDIVET IBERIA, SL'
AND (
(MONTH(CURDATE()) = 1 AND MONTH(f.fechaFactura) = 12 AND YEAR(f.fechaFactura) = YEAR(CURDATE()) - 1) OR
(MONTH(f.fechaFactura) = MONTH(CURDATE()) - 1 AND YEAR(f.fechaFactura) = YEAR(CURDATE()))
);
