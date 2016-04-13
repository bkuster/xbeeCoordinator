SELECT property_ID, size
FROM sensor_property
INNER JOIN observed_property
ON property_ID = ID
WHERE sensor_id = '{0}'
AND UOM != 'deg'
ORDER BY row_order ASC;
